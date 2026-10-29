"""라이선스 감사 판정.

입력은 파이프라인(`license_pipeline.py`)이 만든 파일들이다.

- 기준 집합: `uv export`로 뽑은 제품 런타임 requirement 중, **감사 대상 venv의 마커 환경**에서
  활성인 것만. 감사 도구가 도는 Python의 환경으로 마커를 평가하지 않는다
- 스캔 결과: 대상 venv를 `pip-licenses --with-system`으로 빠짐없이 읽은 JSON
- 판정: 기준 집합과 스캔 결과를 이름·버전으로 대조하고, 라이선스를 허용 목록으로 판정한다

종료 코드 0 = 통과, 1 = 감사 실패, 2 = 입력·설정 오류.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

from packaging.markers import Marker
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import InvalidVersion, Version

from kookabug_sdk.console import utf8_stdio

# 대상 venv에서 수집해야 하는 PEP 508 마커 변수 (tools/marker_env.py가 만든다)
MARKER_ENV_KEYS = frozenset(
    {
        "implementation_name",
        "implementation_version",
        "os_name",
        "platform_machine",
        "platform_python_implementation",
        "platform_release",
        "platform_system",
        "platform_version",
        "python_full_version",
        "python_version",
        "sys_platform",
    }
)

# 오염 메시지에 "감사 도구 의존성으로 보임"을 붙이는 데만 쓴다. 판정에서 빼는 목록이 아니다
AUDIT_TOOL_PACKAGES = frozenset(
    canonicalize_name(n) for n in ("pip-licenses", "prettytable", "wcwidth", "tomli", "pip")
)

UNKNOWN = "UNKNOWN"


class AuditInputError(Exception):
    """입력 파일·설정이 잘못됐다 (종료 코드 2)."""


# ---------------------------------------------------------------- 기준 집합


@dataclass(frozen=True)
class RuntimeRequirement:
    name: NormalizedName
    display_name: str
    version: Version
    marker: Marker | None
    line: str


def parse_runtime(text: str) -> list[RuntimeRequirement]:
    """`uv export --format requirements-txt` 결과를 읽는다. 모든 항목은 `==`로 고정돼야 한다."""
    reqs: list[RuntimeRequirement] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip().rstrip("\\").strip()
        if not line:
            continue
        if line.startswith("-"):
            raise AuditInputError(f"runtime 파일에 옵션·편집 설치 줄이 있다: {raw.strip()!r}")
        try:
            req = Requirement(line)
        except InvalidRequirement as exc:
            raise AuditInputError(f"requirement를 읽을 수 없다: {line!r} ({exc})") from exc
        specs = list(req.specifier)
        if len(specs) != 1 or specs[0].operator not in ("==", "==="):
            raise AuditInputError(f"버전이 하나로 고정되지 않았다: {line!r}")
        try:
            version = Version(specs[0].version)
        except InvalidVersion as exc:
            raise AuditInputError(f"버전을 읽을 수 없다: {line!r}") from exc
        reqs.append(
            RuntimeRequirement(
                name=canonicalize_name(req.name),
                display_name=req.name,
                version=version,
                marker=req.marker,
                line=line,
            )
        )
    return reqs


def load_marker_env(data: Mapping[str, Any]) -> dict[str, str]:
    missing = MARKER_ENV_KEYS - data.keys()
    if missing:
        raise AuditInputError(f"마커 환경에 키가 없다: {', '.join(sorted(missing))}")
    return {k: str(data[k]) for k in MARKER_ENV_KEYS}


@dataclass
class Baseline:
    active: dict[NormalizedName, RuntimeRequirement]
    inactive: list[RuntimeRequirement]


def select_active(reqs: Iterable[RuntimeRequirement], marker_env: Mapping[str, str]) -> Baseline:
    """대상 환경에서 활성인 requirement만 기준 집합으로 고른다."""
    env = {**marker_env, "extra": ""}
    active: dict[NormalizedName, RuntimeRequirement] = {}
    inactive: list[RuntimeRequirement] = []
    for req in reqs:
        if req.marker is not None and not req.marker.evaluate(env):
            inactive.append(req)
            continue
        prev = active.get(req.name)
        if prev is not None and prev.version != req.version:
            raise AuditInputError(
                f"{req.display_name}: 대상 환경에서 활성인 버전이 둘이다 "
                f"({prev.version}, {req.version})"
            )
        active[req.name] = req
    return Baseline(active=active, inactive=inactive)


# ---------------------------------------------------------------- 스캔 결과


@dataclass(frozen=True)
class ScannedPackage:
    name: NormalizedName
    display_name: str
    version: str
    license: str
    license_text: str = ""
    notice_text: str = ""


def _text(value: Any) -> str:
    if not isinstance(value, str) or value == UNKNOWN:
        return ""
    return value


def parse_pip_licenses(data: Any) -> dict[NormalizedName, ScannedPackage]:
    if not isinstance(data, list):
        raise AuditInputError("pip-licenses JSON은 배열이어야 한다")
    out: dict[NormalizedName, ScannedPackage] = {}
    for item in data:
        try:
            display, version, lic = item["Name"], item["Version"], item["License"]
        except (KeyError, TypeError) as exc:
            raise AuditInputError(f"pip-licenses 항목에 필드가 없다: {item!r}") from exc
        name = canonicalize_name(display)
        if name in out:
            raise AuditInputError(f"스캔 결과에 같은 패키지가 두 번 있다: {display}")
        out[name] = ScannedPackage(
            name=name,
            display_name=display,
            version=str(version),
            license=str(lic),
            license_text=_text(item.get("LicenseText")),
            notice_text=_text(item.get("NoticeText")),
        )
    return out


def parse_pnpm_licenses(data: Any) -> list[ScannedPackage]:
    """`pnpm licenses list --json` 결과 ({라이선스: [패키지...]})를 읽는다."""
    if not isinstance(data, dict):
        raise AuditInputError("pnpm licenses JSON은 객체여야 한다")
    out: list[ScannedPackage] = []
    for group_license, items in data.items():
        for item in items:
            lic = item.get("license") or group_license
            for version in item.get("versions") or [""]:
                out.append(
                    ScannedPackage(
                        name=canonicalize_name(item["name"]),
                        display_name=item["name"],
                        version=str(version),
                        license=str(lic),
                        license_text=_read_js_license_text(item.get("paths") or []),
                    )
                )
    out.sort(key=lambda p: (p.display_name, p.version))
    return out


def _read_js_license_text(paths: Sequence[str]) -> str:
    for p in paths:
        d = Path(p)
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file() and re.match(r"(?i)^(license|licence|copying)", f.name):
                return f.read_text(encoding="utf-8", errors="replace")
    return ""


# ---------------------------------------------------------------- 라이선스 정책


class Status(IntEnum):
    """라이선스 한 개의 판정. 숫자가 클수록 나쁘다."""

    ALLOWED = 0
    NEEDS_EXCEPTION = 1  # MPL-2.0 같은 조건부 허용
    UNKNOWN = 2
    DENIED = 3


@dataclass(frozen=True)
class PackageException:
    license: str
    reason: str


@dataclass
class Policy:
    allowed: frozenset[str]
    conditional: frozenset[str]
    denied_patterns: tuple[re.Pattern[str], ...]
    aliases: dict[str, str]
    exceptions: dict[NormalizedName, PackageException] = field(default_factory=dict)
    # 검토한 "라이선스 WITH 예외" 조합. 목록 밖 조합은 미상으로 본다
    allowed_with: frozenset[str] = frozenset()


def load_policy(data: Mapping[str, Any]) -> Policy:
    try:
        allowed = frozenset(data["allowed"])
        conditional = frozenset(data.get("conditional", []))
        patterns = tuple(re.compile(p, re.IGNORECASE) for p in data["denied_patterns"])
    except (KeyError, re.error) as exc:
        raise AuditInputError(f"허용 목록 설정 오류: {exc}") from exc
    aliases = {k.casefold(): v for k, v in data.get("aliases", {}).items()}
    exceptions: dict[NormalizedName, PackageException] = {}
    for name, entry in data.get("exceptions", {}).items():
        lic = str(entry.get("license", "")).strip()
        reason = str(entry.get("reason", "")).strip()
        if not lic or not reason:
            raise AuditInputError(f"예외 {name}: license와 reason이 모두 있어야 한다")
        exceptions[canonicalize_name(name)] = PackageException(license=lic, reason=reason)
    allowed_with: set[str] = set()
    for entry in data.get("allowed_with", []):
        m = _WITH_ENTRY.match(str(entry).strip())
        if m is None:
            raise AuditInputError(
                f"allowed_with 항목은 '<라이선스> WITH <예외>' 형식이다: {entry!r}"
            )
        allowed_with.add(f"{m[1]} WITH {m[2]}")
    return Policy(allowed, conditional, patterns, aliases, exceptions, frozenset(allowed_with))


def load_policy_file(path: Path) -> Policy:
    with path.open("rb") as f:
        return load_policy(tomllib.load(f))


_TOKEN = re.compile(r"\s*(\(|\)|\bAND\b|\bOR\b|\bWITH\b|[^\s()]+)", re.IGNORECASE)
_OPERATORS = frozenset({"AND", "OR", "WITH", "(", ")"})
_SPDX_ID = re.compile(r"^[A-Za-z0-9.\-]+\+?$")
_WITH_ENTRY = re.compile(r"^([A-Za-z0-9.\-]+) WITH ([A-Za-z0-9.\-]+)$")


def _classify_id(lic_id: str, policy: Policy) -> Status:
    lic_id = lic_id.removesuffix("+")
    if any(p.search(lic_id) for p in policy.denied_patterns):
        return Status.DENIED
    if lic_id in policy.allowed:
        return Status.ALLOWED
    if lic_id in policy.conditional:
        return Status.NEEDS_EXCEPTION
    return Status.UNKNOWN


def _eval_expression(expr: str, policy: Policy) -> Status:
    """SPDX 식(AND·OR·WITH·괄호)을 판정한다. OR은 가장 나은 쪽, AND는 가장 나쁜 쪽."""
    tokens = [t for t in _TOKEN.findall(expr) if t.strip()]
    if not tokens:
        return Status.UNKNOWN
    pos = 0

    def peek() -> str | None:
        return tokens[pos].upper() if pos < len(tokens) else None

    def take() -> str:
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def parse_or() -> Status:
        result = parse_and()
        while peek() == "OR":
            take()
            result = min(result, parse_and())
        return result

    def parse_and() -> Status:
        result = parse_with()
        while peek() == "AND":
            take()
            result = max(result, parse_with())
        return result

    def take_id() -> str:
        tok = peek()
        if tok is None or tok in _OPERATORS:
            raise ValueError("식이 잘렸다")
        lic_id = take()
        if not _SPDX_ID.match(lic_id):
            raise ValueError(f"SPDX 식별자가 아니다: {lic_id}")
        return lic_id

    def parse_with() -> Status:
        if peek() == "(":
            take()
            result = parse_or()
            if peek() != ")":
                raise ValueError("괄호가 닫히지 않았다")
            take()
            return result
        lic_id = take_id()
        status = _classify_id(lic_id, policy)
        if peek() != "WITH":
            return status
        take()
        exception_id = take_id()
        # 예외가 붙으면 다른 조건이 된다. 금지 계열은 그대로 금지, 그 외는 검토한 조합만 허용
        if status is Status.DENIED:
            return Status.DENIED
        if f"{lic_id.removesuffix('+')} WITH {exception_id}" in policy.allowed_with:
            return Status.ALLOWED
        return Status.UNKNOWN

    try:
        result = parse_or()
    except ValueError:
        return Status.UNKNOWN
    return result if pos == len(tokens) else Status.UNKNOWN


def classify_license(text: str, policy: Policy) -> tuple[Status, str]:
    """스캐너가 준 라이선스 문자열을 판정한다. 돌려주는 문자열은 별칭을 푼 SPDX 식."""
    text = text.strip()
    if not text or text == UNKNOWN:
        return Status.UNKNOWN, UNKNOWN
    # pip-licenses는 분류자 여러 개를 "; "로 잇는다. 무엇이 적용되는지 모르므로 전부 만족해야 한다
    parts = [p.strip() for p in text.split(";") if p.strip()]
    resolved = [policy.aliases.get(p.casefold(), p) for p in parts]
    statuses: list[Status] = []
    for orig, res in zip(parts, resolved, strict=True):
        status = _eval_expression(res, policy)
        # SPDX 식이 아닌 긴 이름("GNU General Public License v3 ...")도 금지 계열이면 금지로 본다
        if status is Status.UNKNOWN and any(p.search(orig) for p in policy.denied_patterns):
            status = Status.DENIED
        statuses.append(status)
    expr = " AND ".join(f"({r})" if len(resolved) > 1 else r for r in resolved)
    return max(statuses), expr


@dataclass(frozen=True)
class LicenseVerdict:
    ok: bool
    license: str
    detail: str


def judge_package(name: NormalizedName, license_text: str, policy: Policy) -> LicenseVerdict:
    status, expr = classify_license(license_text, policy)
    exc = policy.exceptions.get(name)
    if status is Status.ALLOWED:
        return LicenseVerdict(True, expr, "허용")
    if status is Status.DENIED:
        note = " (예외로도 허용하지 않는다)" if exc else ""
        return LicenseVerdict(False, expr, f"금지 라이선스{note}")
    if exc is None:
        if status is Status.NEEDS_EXCEPTION:
            return LicenseVerdict(False, expr, "패키지 이름별 예외(이유 포함)가 있어야 허용")
        return LicenseVerdict(False, expr, "라이선스 미상 또는 허용 목록 밖")
    exc_status, exc_expr = classify_license(exc.license, policy)
    if exc_status in (Status.ALLOWED, Status.NEEDS_EXCEPTION):
        return LicenseVerdict(True, exc_expr, f"예외: {exc.reason}")
    return LicenseVerdict(False, exc_expr, "예외에 적은 라이선스도 허용 목록 밖")


# ---------------------------------------------------------------- 감사


@dataclass
class AuditResult:
    problems: list[str]
    notes: list[str]
    notices: str
    python_rows: list[tuple[str, str, str]]  # (이름, 버전, 라이선스)
    js_rows: list[tuple[str, str, str]]

    @property
    def ok(self) -> bool:
        return not self.problems


def compare_sets(
    baseline: Baseline, scanned: Mapping[NormalizedName, ScannedPackage]
) -> tuple[list[str], list[str]]:
    """(문제, 참고) 목록. 제품이 요구한 공통 패키지는 기준 집합에 있으므로 정상으로 남는다."""
    problems: list[str] = []
    notes: list[str] = []
    for name, req in sorted(baseline.active.items()):
        pkg = scanned.get(name)
        if pkg is None:
            problems.append(
                f"[누락] {req.display_name}=={req.version}: 기준 집합에 있는데 스캔 결과에 없다"
            )
            continue
        try:
            same = Version(pkg.version) == req.version
        except InvalidVersion:
            same = False
        if not same:
            problems.append(
                f"[버전 불일치] {req.display_name}: 잠금 {req.version}, 대상 환경 {pkg.version}"
            )
        if name in AUDIT_TOOL_PACKAGES:
            notes.append(
                f"{req.display_name}: 감사 도구도 쓰는 패키지지만 제품 의존성이라 감사한다"
            )
    for name, pkg in sorted(scanned.items()):
        if name in baseline.active:
            continue
        hint = " — 감사 도구 의존성으로 보인다" if name in AUDIT_TOOL_PACKAGES else ""
        problems.append(
            f"[오염] {pkg.display_name}=={pkg.version}: 기준 집합에 없는 패키지가 "
            f"대상 환경에 있다{hint}"
        )
    for req in baseline.inactive:
        notes.append(f"{req.line}: 대상 환경 마커에서 비활성이라 기준 집합에서 뺐다")
    return problems, notes


def render_notices(
    py: Sequence[tuple[ScannedPackage | None, RuntimeRequirement, str]],
    js: Sequence[tuple[ScannedPackage, str]],
) -> str:
    lines = [
        "THIRD-PARTY SOFTWARE NOTICES (초안)",
        "",
        "Kookabug 배포물에 포함되는 제3자 소프트웨어와 라이선스 목록이다.",
        "이 파일은 tools/license_audit.py가 만든다. 직접 고치지 않는다.",
        "",
    ]

    def section(title: str, name: str, version: str, lic: str, text: str, notice: str) -> None:
        lines.extend(["=" * 78, f"{name} {version}", f"License: {lic}", f"({title})", "-" * 78])
        lines.append(text.strip() or "(라이선스 파일을 찾지 못했다)")
        if notice.strip():
            lines.extend(["", "NOTICE:", notice.strip()])
        lines.append("")

    for pkg, req, lic in py:
        section(
            "Python",
            req.display_name,
            str(req.version),
            lic,
            pkg.license_text if pkg else "",
            pkg.notice_text if pkg else "",
        )
    for pkg, lic in js:
        section("JavaScript", pkg.display_name, pkg.version, lic, pkg.license_text, "")
    return "\n".join(lines).rstrip() + "\n"


def audit(
    runtime: Sequence[RuntimeRequirement],
    marker_env: Mapping[str, str],
    py_scan: Mapping[NormalizedName, ScannedPackage],
    js_scan: Sequence[ScannedPackage],
    policy: Policy,
) -> AuditResult:
    baseline = select_active(runtime, marker_env)
    problems, notes = compare_sets(baseline, py_scan)

    py_entries: list[tuple[ScannedPackage | None, RuntimeRequirement, str]] = []
    py_rows: list[tuple[str, str, str]] = []
    for name, req in sorted(baseline.active.items()):
        pkg = py_scan.get(name)
        if pkg is None:
            py_entries.append((None, req, UNKNOWN))
            continue
        verdict = judge_package(name, pkg.license, policy)
        if not verdict.ok:
            problems.append(
                f"[라이선스] {req.display_name}=={req.version}: {pkg.license!r} — {verdict.detail}"
            )
        py_entries.append((pkg, req, verdict.license))
        py_rows.append((req.display_name, str(req.version), verdict.license))

    js_entries: list[tuple[ScannedPackage, str]] = []
    js_rows: list[tuple[str, str, str]] = []
    for pkg in js_scan:
        verdict = judge_package(pkg.name, pkg.license, policy)
        if not verdict.ok:
            problems.append(
                f"[라이선스] (JS) {pkg.display_name}@{pkg.version}: {pkg.license!r} — "
                f"{verdict.detail}"
            )
        js_entries.append((pkg, verdict.license))
        js_rows.append((pkg.display_name, pkg.version, verdict.license))

    used = set(baseline.active) | {p.name for p in js_scan}
    for name in sorted(set(policy.exceptions) - used):
        notes.append(f"쓰이지 않는 예외: {name}")

    return AuditResult(
        problems=problems,
        notes=notes,
        notices=render_notices(py_entries, js_entries),
        python_rows=py_rows,
        js_rows=js_rows,
    )


# ---------------------------------------------------------------- 명령줄


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditInputError(f"{path}: JSON을 읽을 수 없다 ({exc})") from exc


def main(argv: Sequence[str] | None = None) -> int:
    utf8_stdio()
    parser = argparse.ArgumentParser(description="Kookabug 라이선스 감사 판정")
    parser.add_argument("--runtime", type=Path, required=True, help="uv export 결과")
    parser.add_argument("--marker-env", type=Path, required=True, help="대상 venv의 마커 환경")
    parser.add_argument("--python", type=Path, required=True, help="pip-licenses JSON")
    parser.add_argument("--js", type=Path, help="pnpm licenses JSON (없으면 JS 감사 생략)")
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--notices-out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        runtime = parse_runtime(args.runtime.read_text(encoding="utf-8"))
        marker_env = load_marker_env(_read_json(args.marker_env))
        py_scan = parse_pip_licenses(_read_json(args.python))
        js_scan = parse_pnpm_licenses(_read_json(args.js)) if args.js else []
        policy = load_policy_file(args.allowlist)
        result = audit(runtime, marker_env, py_scan, js_scan, policy)
    except AuditInputError as exc:
        print(f"라이선스 감사 입력 오류: {exc}", file=sys.stderr)
        return 2

    args.notices_out.parent.mkdir(parents=True, exist_ok=True)
    args.notices_out.write_text(result.notices, encoding="utf-8")

    print(f"Python 런타임 패키지 {len(result.python_rows)}개, JS 패키지 {len(result.js_rows)}개")
    for name, version, lic in result.python_rows:
        print(f"  {name}=={version}  {lic}")
    for name, version, lic in result.js_rows:
        print(f"  (JS) {name}@{version}  {lic}")
    for note in result.notes:
        print(f"참고: {note}")
    if result.problems:
        print(f"라이선스 감사 실패 ({len(result.problems)}건)", file=sys.stderr)
        for p in result.problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f"라이선스 감사 통과. NOTICES: {args.notices_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
