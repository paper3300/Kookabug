"""네이티브 파일·OCR 모델·최종 설치 트리 감사 (구현 계획 M1 2.12).

패키지 메타데이터 감사(`license_audit`)가 보지 못하는 것을 본다.

- wheel·Python 배포본 안의 DLL·pyd·exe: 한 파일에 여러 구성요소가 정적으로 들어 있으므로
  `native-licenses.toml`에 파일 glob마다 **구성요소별 라이선스 식**을 적고 그 식 전체를 판정한다.
  식의 모든 구성요소에 원문(배포물 안 파일 또는 `third_party_licenses/`)이 연결돼 있어야 하고
  원문은 NOTICES에 실린다. Rust 확장은 동봉 SBOM의 크레이트마다 원문 절이 있어야 한다
- 읽을 수 없는 폴더는 감사 문제다 (그 안의 파일을 판정하지 못했으므로)
- 제거 목록(설치본에서 빼는 파일·폴더): 빌드 입력에서는 금지 라이선스 파일이 "제거 목록에 있음"일
  때만 허용하고, glob이 아무것도 못 맞히면 실패한다(버전이 바뀌어 이름이 달라진 것). 최종 트리에는
  제거 목록과 무관하게 금지 라이선스 파일·제거 대상이 하나라도 남으면 실패한다
- 최종 트리의 `*.dist-info/RECORD`와 실제 파일 대조
- OCR 모델 표(`models.toml`)의 라이선스와, 모델 폴더가 있으면 크기·SHA256. 모델 경로는 모델
  폴더 안의 상대 경로만 받는다. 모델의 라이선스 근거 원문(`[[text]]`, 모델과 같은 폴더에 받음)도
  모델 폴더가 있으면 크기·SHA256을 확인하고 원문을 NOTICES에 싣는다

단계는 둘이다. `audit_build_input`은 빌드 입력(감사 venv의 site-packages, 설치 전 스테이징 트리),
`audit_final_tree`는 최종 설치 트리(설치본 폴더, CI에서는 무인 설치 결과)다.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import posixpath
import re
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from packaging.utils import canonicalize_name

from license_audit import (
    LICENSE_REF_PREFIX,
    AuditInputError,
    PinnedBinary,
    Policy,
    Status,
    classify_license,
    expression_satisfied,
)

SITE_PACKAGES = "site-packages"
INSTALL = "install"
SCOPES = (SITE_PACKAGES, INSTALL)
NATIVE_SUFFIXES = (".dll", ".pyd", ".exe")
# 설치 폴더(install scope)에서는 Electron 배포물의 바이너리 자원(Chromium 자원 묶음·ICU 데이터·V8
# 스냅숏·앱 번들)도 표에 있어야 한다 (구현 계획 M2 2.14). site-packages에는 적용하지 않는다
INSTALL_RESOURCE_SUFFIXES = (".pak", ".dat", ".bin", ".asar")
ORIGINS = ("wheel", "pbs")
TOOLS_DIR = Path(__file__).resolve().parent
# SBOM에서 빌드에 쓰이지 않은 것으로 표시된 크레이트
SBOM_EXCLUDED_SCOPE = "excluded"
# 설치 폴더 구조 (2.12)
SITE_PACKAGES_IN_INSTALL = "python/Lib/site-packages"
MODELS_IN_INSTALL = "ocr-models"


# ---------------------------------------------------------------- 표


@dataclass(frozen=True)
class LicenseText:
    """구성요소 라이선스 원문 하나. 배포물 안 파일(`path`, 항목 scope 기준 glob) 또는 레포에 둔
    원문(`file`, 표 폴더 기준). `covers`는 이 원문이 덮는 식의 잎(`ID` 또는 `ID WITH 예외`),
    `expect`는 원문에 반드시 있어야 하는 글귀 (엉뚱한 파일을 가리키지 않았는지 확인)."""

    covers: tuple[str, ...]
    expect: tuple[str, ...]
    path: str = ""
    file: str = ""
    # False면 NOTICES에 원문을 옮겨 싣지 않고 위치만 적는다. 원문 파일이 배포물에 그대로 있을 때만
    # 쓴다 (path, 예: 20 MB인 Electron의 LICENSES.chromium.html)
    embed: bool = True

    @property
    def label(self) -> str:
        return self.path or self.file


@dataclass(frozen=True)
class NativeEntry:
    """파일 glob 하나와 그 파일에 들어 있는 구성요소 전부의 라이선스 식과 원문."""

    glob: str
    scope: str
    package: str
    license: str
    reason: str
    components: str = ""
    texts: tuple[LicenseText, ...] = ()
    # Rust 확장의 동봉 SBOM glob (항목 scope 기준). 주면 SBOM의 크레이트마다 라이선스를 판정하고
    # texts에 그 크레이트의 원문 절(`이름 버전` 줄)이 있어야 한다
    sbom: str = ""
    # 배포물에 SBOM이 없을 때 레포에 둔 SBOM (표 폴더 기준, 예: uv 실행기의 Cargo.lock에서 만든 것).
    # 판정은 sbom과 같다
    sbom_file: str = ""


@dataclass(frozen=True)
class StripRule:
    """설치본에서 빼는 파일·폴더. 폴더를 맞히면 그 아래 전부."""

    glob: str
    scope: str
    reason: str
    # 이 파일이 오는 빌드 입력: wheel(감사 venv에도 있음) 또는 pbs(Python 배포본, T13 스테이징에만)
    origin: str = "wheel"


@dataclass(frozen=True)
class LicenseRefDef:
    """SPDX 밖 배포물(VC++ 재배포 파일·Inno Setup·sqlite blessing 등)의 원문 위치와 처리 근거."""

    id: str
    name: str
    source: str
    reason: str
    notice: str = ""


@dataclass
class NativeTable:
    entries: list[NativeEntry]
    strip: list[StripRule]
    license_refs: dict[str, LicenseRefDef]
    # LicenseText.file의 기준 폴더 (표 파일이 있는 폴더)
    base_dir: Path = TOOLS_DIR

    @property
    def ref_ids(self) -> frozenset[str]:
        return frozenset(self.license_refs)


@dataclass(frozen=True)
class ModelText:
    """모델 라이선스 근거 원문 파일 (모델 폴더 안)."""

    file: str
    label: str
    sha256: str
    size: int
    url: str = ""


@dataclass(frozen=True)
class ModelEntry:
    file: str
    sha256: str
    size: int
    license: str
    source: str
    url: str = ""
    texts: tuple[ModelText, ...] = ()


def _required(item: Mapping[str, Any], key: str, where: str) -> str:
    value = str(item.get(key, "")).strip()
    if not value:
        raise AuditInputError(f"{where}: {key}가 있어야 한다")
    return value


def _scope(item: Mapping[str, Any], where: str) -> str:
    scope = str(item.get("scope", SITE_PACKAGES))
    if scope not in SCOPES:
        raise AuditInputError(f"{where}: scope는 {', '.join(SCOPES)} 중 하나다 ({scope!r})")
    return scope


def _str_list(item: Mapping[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = item.get(key, [])
    if isinstance(value, str):
        value = [value]
    out = tuple(str(v).strip() for v in value if str(v).strip())
    if not out:
        raise AuditInputError(f"{where}: {key}가 있어야 한다")
    return out


def _load_text(item: Mapping[str, Any], where: str) -> LicenseText:
    path = str(item.get("path", "")).strip()
    file = str(item.get("file", "")).strip()
    if bool(path) == bool(file):
        raise AuditInputError(f"{where}: path(배포물 안)와 file(레포) 중 하나만 있어야 한다")
    embed = item.get("embed", True)
    if not isinstance(embed, bool) or (not embed and not path):
        raise AuditInputError(f"{where}: embed = false는 배포물 안 원문(path)에만 쓴다")
    return LicenseText(
        covers=_str_list(item, "covers", where),
        expect=_str_list(item, "expect", where),
        path=path,
        file=file,
        embed=embed,
    )


def load_native_table(data: Mapping[str, Any], base_dir: Path = TOOLS_DIR) -> NativeTable:
    entries: list[NativeEntry] = []
    for i, item in enumerate(data.get("native", [])):
        where = f"native[{i}]"
        if "evidence" in item or "notice" in item:
            raise AuditInputError(f"{where}: evidence·notice 대신 texts를 쓴다")
        if item.get("sbom") and item.get("sbom_file"):
            raise AuditInputError(f"{where}: sbom(배포물 안)과 sbom_file(레포) 중 하나만 쓴다")
        entries.append(
            NativeEntry(
                glob=_required(item, "glob", where),
                scope=_scope(item, where),
                package=_required(item, "package", where),
                license=_required(item, "license", where),
                reason=_required(item, "reason", where),
                components=str(item.get("components", "")).strip(),
                texts=tuple(
                    _load_text(t, f"{where}.texts[{j}]")
                    for j, t in enumerate(item.get("texts", []))
                ),
                sbom=str(item.get("sbom", "")).strip(),
                sbom_file=str(item.get("sbom_file", "")).strip(),
            )
        )
    strip: list[StripRule] = []
    for i, item in enumerate(data.get("strip", [])):
        where = f"strip[{i}]"
        origin = str(item.get("origin", "wheel"))
        if origin not in ORIGINS:
            raise AuditInputError(f"{where}: origin은 {', '.join(ORIGINS)} 중 하나다 ({origin!r})")
        strip.append(
            StripRule(
                glob=_required(item, "glob", where),
                scope=_scope(item, where),
                reason=_required(item, "reason", where),
                origin=origin,
            )
        )
    refs: dict[str, LicenseRefDef] = {}
    for ref_id, item in data.get("licenseref", {}).items():
        where = f"licenseref.{ref_id}"
        if not ref_id.startswith(LICENSE_REF_PREFIX):
            raise AuditInputError(f"{where}: 이름은 {LICENSE_REF_PREFIX}로 시작해야 한다")
        refs[ref_id] = LicenseRefDef(
            id=ref_id,
            name=_required(item, "name", where),
            source=_required(item, "source", where),
            reason=_required(item, "reason", where),
            notice=str(item.get("notice", "")).strip(),
        )
    return NativeTable(entries, strip, refs, base_dir)


def load_native_table_file(path: Path) -> NativeTable:
    try:
        with path.open("rb") as f:
            return load_native_table(tomllib.load(f), path.resolve().parent)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AuditInputError(f"{path}: 네이티브 표를 읽을 수 없다 ({exc})") from exc


def _model_file(item: Mapping[str, Any], where: str) -> tuple[str, str, int]:
    """모델 폴더 안 파일의 (경로, sha256, 크기)."""
    try:
        size = int(item["size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuditInputError(f"{where}: size는 정수여야 한다") from exc
    sha256 = _required(item, "sha256", where).lower()
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise AuditInputError(f"{where}: sha256은 16진수 64자다")
    file = _required(item, "file", where)
    # 모델은 모델 폴더 안에 있어야 한다: 절대 경로·드라이브·상위 폴더 이탈 금지
    win = PureWindowsPath(file)
    if win.drive or win.root or PurePosixPath(file).is_absolute() or ".." in win.parts:
        raise AuditInputError(f"{where}: file은 모델 폴더 안의 상대 경로여야 한다 ({file!r})")
    return file, sha256, size


def load_model_table(data: Mapping[str, Any]) -> list[ModelEntry]:
    """`[[model]]`과, 모델의 `license_texts`가 가리키는 `[[text]]`(근거 원문)."""
    texts: dict[str, ModelText] = {}
    for i, item in enumerate(data.get("text", [])):
        where = f"text[{i}]"
        file, sha256, size = _model_file(item, where)
        texts[file] = ModelText(
            file=file,
            label=_required(item, "label", where),
            sha256=sha256,
            size=size,
            url=str(item.get("url", "")),
        )
    models: list[ModelEntry] = []
    for i, item in enumerate(data.get("model", [])):
        where = f"model[{i}]"
        file, sha256, size = _model_file(item, where)
        refs = item.get("license_texts", [])
        if not isinstance(refs, list) or any(ref not in texts for ref in refs):
            raise AuditInputError(f"{where}: license_texts는 [[text]]의 file 목록이다")
        models.append(
            ModelEntry(
                file=file,
                sha256=sha256,
                size=size,
                license=_required(item, "license", where),
                source=_required(item, "source", where),
                url=str(item.get("url", "")),
                texts=tuple(texts[ref] for ref in refs),
            )
        )
    return models


def load_model_table_file(path: Path) -> list[ModelEntry]:
    try:
        with path.open("rb") as f:
            return load_model_table(tomllib.load(f))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AuditInputError(f"{path}: 모델 표를 읽을 수 없다 ({exc})") from exc


# ---------------------------------------------------------------- 트리


@dataclass(frozen=True)
class Layout:
    """감사할 폴더들. scope → 그 scope의 glob이 기준으로 삼는 폴더."""

    roots: Mapping[str, Path]

    @classmethod
    def site_packages(cls, path: Path) -> Layout:
        return cls({SITE_PACKAGES: path})

    @classmethod
    def install(cls, root: Path) -> Layout:
        return cls({INSTALL: root, SITE_PACKAGES: root / SITE_PACKAGES_IN_INSTALL})


def expand_braces(pattern: str) -> list[str]:
    """`a/{b,c}.dll` → `a/b.dll`, `a/c.dll`. 중첩은 지원하지 않는다."""
    start = pattern.find("{")
    if start < 0:
        return [pattern]
    end = pattern.find("}", start)
    if end < 0:
        raise AuditInputError(f"glob의 중괄호가 닫히지 않았다: {pattern!r}")
    head, tail = pattern[:start], pattern[end + 1 :]
    return [
        expanded
        for alt in pattern[start + 1 : end].split(",")
        for expanded in expand_braces(head + alt + tail)
    ]


def glob_match(rel: str, pattern: str) -> bool:
    """`rel`(scope 기준 posix 상대 경로)이 glob에 맞는가. Windows 파일 이름처럼 대소문자 무시."""
    path = PurePosixPath(rel.casefold())
    return any(path.full_match(p) for p in expand_braces(pattern.casefold()))


def iter_files(layout: Layout, errors: list[str] | None = None) -> Iterator[tuple[str, str, Path]]:
    """(scope, 상대 경로, 실제 경로). install 아래 site-packages는 site-packages scope로만 준다.

    읽을 수 없는 폴더는 그 아래를 검사하지 못한 것이므로 `errors`에 감사 문제로 남긴다
    (`errors`가 없으면 예외). 조용히 건너뛰면 그 안의 DLL이 판정 없이 통과한다.
    """
    site = layout.roots.get(SITE_PACKAGES)

    def onerror(exc: OSError) -> None:
        if errors is None:
            raise exc
        errors.append(f"[읽을 수 없는 폴더] {exc.filename}: {exc.strerror or exc}")

    for scope, root in layout.roots.items():
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root, onerror=onerror):
            here = Path(dirpath)
            if scope != SITE_PACKAGES and site is not None:
                dirnames[:] = [d for d in dirnames if (here / d) != site]
            dirnames.sort()
            for name in sorted(filenames):
                path = here / name
                yield scope, path.relative_to(root).as_posix(), path


def is_native(rel: str, scope: str = SITE_PACKAGES) -> bool:
    """표에 있어야 하는 파일인가: DLL·pyd·exe, 설치 폴더에서는 Electron 바이너리 자원도."""
    name = rel.casefold()
    if name.endswith(NATIVE_SUFFIXES):
        return True
    return scope == INSTALL and name.endswith(INSTALL_RESOURCE_SUFFIXES)


def find_entry(table: NativeTable, scope: str, rel: str) -> NativeEntry | None:
    """먼저 적은 항목이 이긴다."""
    for entry in table.entries:
        if entry.scope == scope and glob_match(rel, entry.glob):
            return entry
    return None


def find_strip(table: NativeTable, scope: str, rel: str) -> StripRule | None:
    """파일 자신이나 그 위 폴더를 맞히는 제거 규칙."""
    parts = rel.split("/")
    candidates = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    for rule in table.strip:
        if rule.scope == scope and any(glob_match(c, rule.glob) for c in candidates):
            return rule
    return None


@dataclass(frozen=True)
class NativeFile:
    scope: str
    rel: str
    path: Path
    entry: NativeEntry | None


# ---------------------------------------------------------------- 판정


def judge_entry(
    entry: NativeEntry,
    table: NativeTable,
    policy: Policy,
    pinned_ok: frozenset[str] = frozenset(),
) -> tuple[Status, str]:
    """구성요소별 식 전체를 판정한다. AND의 어느 한 부분이라도 허용 밖이면 허용 밖이다.

    네이티브 항목은 파일마다 이유를 적으므로 조건부(MPL-2.0 등)는 그 이유로 허용한다.
    `pinned_ok`는 고정 바이너리 한정 예외가 정확히 맞은 파일에서만 준다 (`match_pinned`).
    """
    status, expr = classify_license(
        entry.license,
        policy,
        package=canonicalize_name(entry.package),
        license_refs=table.ref_ids,
        pinned_ok=pinned_ok,
    )
    if status is Status.NEEDS_EXCEPTION:
        status = Status.ALLOWED
    return status, expr


def _status_text(status: Status) -> str:
    return {
        Status.ALLOWED: "허용",
        Status.NEEDS_EXCEPTION: "조건부",
        Status.UNKNOWN: "라이선스 미상·허용 목록 밖·정의 안 된 LicenseRef",
        Status.DENIED: "금지 라이선스",
    }[status]


def _where(scope: str, rel: str) -> str:
    return f"{scope}:{rel}"


def sbom_components(sbom: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """CycloneDX SBOM의 (이름, 버전, 라이선스 식). 빌드에 쓰이지 않은(excluded) 것은 뺀다."""
    out: set[tuple[str, str, str]] = set()
    for comp in sbom.get("components", []):
        if comp.get("scope") == SBOM_EXCLUDED_SCOPE:
            continue
        parts = [
            str(lic.get("expression") or lic.get("license", {}).get("id") or "")
            for lic in comp.get("licenses", [])
        ]
        parts = [p for p in parts if p]
        if not parts:
            lic = "UNKNOWN"
        else:
            lic = parts[0] if len(parts) == 1 else " AND ".join(f"({p})" for p in parts)
        out.add((str(comp["name"]), str(comp["version"]), lic))
    return sorted(out)


# NOTICES에 실을 원문: (표시 이름, 내용)
Collected = list[tuple[str, str]]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").strip()


def check_texts(
    entry: NativeEntry,
    table: NativeTable,
    policy: Policy,
    layout: Layout,
    files_by_scope: Mapping[str, Sequence[str]],
    *,
    pinned_ok: frozenset[str] = frozenset(),
    references: list[str] | None = None,
) -> tuple[list[str], Collected]:
    """구성요소 원문 확인. 식의 모든 잎(OR는 하나)이 texts(또는 고지문 있는 LicenseRef)로 덮여야
    하고, 각 원문이 실제로 있고 `expect` 글귀를 담아야 한다. SBOM을 주면 크레이트마다도 본다.

    OR는 **허용이면서 원문도 있는** 선택지로만 채운다. 허용 판정은 원문과 같은 OR 쪽을 골라야
    한다 — 허용된 MIT 원문 없이 금지된 GPL 원문으로 식을 채우는 것을 막는다.

    `embed = false`인 원문은 확인만 하고 돌려주는 원문 목록 대신 `references`에 위치를 남긴다.
    """
    head = f"{entry.package} {entry.glob}"
    problems: list[str] = []
    collected: Collected = []
    covered = {c for t in entry.texts for c in t.covers}

    def leaf_allowed(leaf: str) -> bool:
        # judge_entry와 같은 문맥: 패키지별 WITH 예외, 표의 LicenseRef, 조건부는 항목 reason,
        # 고정 바이너리 한정 예외가 맞은 파일이면 그 잎
        status, _ = classify_license(
            leaf,
            policy,
            package=canonicalize_name(entry.package),
            license_refs=table.ref_ids,
            pinned_ok=pinned_ok,
        )
        return status in (Status.ALLOWED, Status.NEEDS_EXCEPTION)

    def leaf_has_text(leaf: str) -> bool:
        ref = table.license_refs.get(leaf)
        return leaf in covered or (ref is not None and bool(ref.notice))

    ok, missing = expression_satisfied(
        entry.license, lambda leaf: leaf_allowed(leaf) and leaf_has_text(leaf)
    )
    if not ok:
        reasons = [
            leaf if leaf_allowed(leaf) else f"{leaf}(허용 밖이라 선택지가 될 수 없음)"
            for leaf in missing
        ]
        problems.append(f"[구성요소 원문 없음] {head}: {', '.join(reasons)}의 원문이 texts에 없다")

    joined_all: list[str] = []
    rels = files_by_scope.get(entry.scope, ())
    for text in entry.texts:
        found: Collected = []
        if text.path:
            for rel in rels:
                if glob_match(rel, text.path):
                    found.append((_where(entry.scope, rel), _read(layout.roots[entry.scope] / rel)))
        else:
            repo_file = table.base_dir / text.file
            if repo_file.is_file():
                found.append((f"tools:{text.file}", _read(repo_file)))
        if not found:
            problems.append(f"[근거 원문 없음] {head}: {text.label}에 맞는 파일이 없다")
            continue
        joined = "\n".join(body for _, body in found)
        # 원문의 줄바꿈 위치와 무관하게 글귀를 찾는다
        flat = " ".join(joined.split()).casefold()
        for phrase in text.expect:
            if " ".join(phrase.split()).casefold() not in flat:
                problems.append(f"[근거 원문 불일치] {head}: {text.label}에 '{phrase}'가 없다")
        joined_all.append(joined)
        if text.embed:
            collected.extend(found)
        elif references is not None:
            for label, _ in found:
                rel = label.split(":", 1)[1]
                size = (layout.roots[entry.scope] / rel).stat().st_size
                ref = f"{label} ({size} bytes, 배포물에 그대로 있다)"
                if ref not in references:
                    references.append(ref)

    sboms: list[tuple[str, Path]] = []
    if entry.sbom:
        sboms = [
            (_where(entry.scope, r), layout.roots[entry.scope] / r)
            for r in rels
            if glob_match(r, entry.sbom)
        ]
        if not sboms:
            problems.append(f"[SBOM 없음] {head}: {entry.scope}:{entry.sbom}")
    elif entry.sbom_file:
        sboms = [(f"tools:{entry.sbom_file}", table.base_dir / entry.sbom_file)]
        if not sboms[0][1].is_file():
            problems.append(f"[SBOM 없음] {head}: tools:{entry.sbom_file}")
            sboms = []
    if sboms:
        corpus = "\n" + "\n".join(joined_all) + "\n"
        for label, sbom_path in sboms:
            try:
                data = json.loads(sbom_path.read_text(encoding="utf-8"))
                comps = sbom_components(data)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                problems.append(f"[SBOM 읽기 실패] {label}: {exc}")
                continue
            for name, version, lic in comps:
                status, expr = classify_license(lic, policy)
                if status not in (Status.ALLOWED, Status.NEEDS_EXCEPTION):
                    problems.append(
                        f"[SBOM 구성요소 라이선스] {head}: {name} {version} {expr} — "
                        f"{_status_text(status)}"
                    )
                if f"\n{name} {version}\n" not in corpus:
                    problems.append(
                        f"[SBOM 구성요소 원문 없음] {head}: {name} {version} "
                        "(tools/fetch_crate_licenses.py로 다시 모은다)"
                    )
    return problems, collected


@dataclass
class NativeReport:
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    files: list[NativeFile] = field(default_factory=list)
    notice_sections: list[str] = field(default_factory=list)
    # 고정 바이너리 한정 예외로 허용한 파일
    pinned: list[tuple[NativeFile, PinnedBinary]] = field(default_factory=list)
    # NOTICES에 옮겨 싣지 않고 위치만 적은 원문 (embed = false)
    references: list[str] = field(default_factory=list)


# 빌드 입력 감사와 최종 트리 감사는 같은 보고 형식을 쓴다
InputAudit = NativeReport
TreeAudit = NativeReport


def _scan(
    layout: Layout, table: NativeTable, errors: list[str]
) -> tuple[list[NativeFile], dict[str, list[str]], list[tuple[str, str]]]:
    natives: list[NativeFile] = []
    files_by_scope: dict[str, list[str]] = {s: [] for s in layout.roots}
    all_files: list[tuple[str, str]] = []
    for scope, rel, path in iter_files(layout, errors):
        files_by_scope[scope].append(rel)
        all_files.append((scope, rel))
        if is_native(rel, scope):
            natives.append(NativeFile(scope, rel, path, find_entry(table, scope, rel)))
    return natives, files_by_scope, all_files


def match_pinned(
    policy: Policy, entry: NativeEntry, nf: NativeFile, versions: Mapping[str, str]
) -> PinnedBinary | None:
    """이 파일에 정확히 맞는 고정 바이너리 한정 예외. 배포물(package)·판(versions의 실제 판)·
    설치 폴더 안 상대 경로·sha256이 **모두** 같아야 한다. 하나라도 다르면 None(예외 없음 = 금지
    그대로)."""
    for pin in policy.pinned:
        name = canonicalize_name(pin.package)
        if name != canonicalize_name(entry.package) or nf.scope != INSTALL:
            continue
        if nf.rel.casefold() != pin.path.casefold() or versions.get(name) != pin.version:
            continue
        if nf.path.is_file() and _sha256(nf.path) == pin.sha256:
            return pin
    return None


def _judge_natives(
    report: NativeReport,
    table: NativeTable,
    policy: Policy,
    layout: Layout,
    files_by_scope: Mapping[str, Sequence[str]],
    *,
    allow_stripped_denied: bool,
    versions: Mapping[str, str] | None = None,
) -> Collected:
    """네이티브 파일마다 표 항목과 판정. 돌려주는 값은 NOTICES에 실을 구성요소 원문.

    항목의 식이 허용이 아니면 파일마다 고정 바이너리 한정 예외(`match_pinned`)를 먼저 본다. 맞는
    파일만 그 예외의 잎을 허용해 다시 판정하고, 예외의 대응 소스 산출물이 설치 트리에 있어야 한다.
    맞지 않는 파일은 예외가 없는 것과 같다."""
    versions = versions or {}
    evidence: Collected = []
    by_entry: dict[NativeEntry, list[NativeFile]] = {}
    for nf in report.files:
        if nf.entry is None:
            # 빌드 입력에서 제거 목록 안의 파일(PBS pip의 distlib 실행기 등)은 판정 대신 뺀다
            if allow_stripped_denied and find_strip(table, nf.scope, nf.rel) is not None:
                report.notes.append(
                    f"[제거 대상] {_where(nf.scope, nf.rel)} (표 없음): 제거 목록에 있어 "
                    "설치본에서 뺀다"
                )
                continue
            report.problems.append(
                f"[네이티브 표 없음] {_where(nf.scope, nf.rel)}: tools/native-licenses.toml에 "
                "구성요소별 라이선스를 적어야 한다"
            )
            continue
        by_entry.setdefault(nf.entry, []).append(nf)

    for entry, nfs in by_entry.items():
        status, expr = judge_entry(entry, table, policy)
        if status is Status.ALLOWED:
            problems, found = check_texts(
                entry, table, policy, layout, files_by_scope, references=report.references
            )
            report.problems.extend(problems)
            evidence.extend(found)
            continue
        rest: list[NativeFile] = []
        for nf in nfs:
            pin = match_pinned(policy, entry, nf, versions)
            if (
                pin is None
                or judge_entry(entry, table, policy, pin.leaves)[0] is not Status.ALLOWED
            ):
                rest.append(nf)
                continue
            report.pinned.append((nf, pin))
            if not (layout.roots[INSTALL] / pin.source).is_file():
                report.problems.append(
                    f"[예외 근거 산출물 없음] {_where(nf.scope, nf.rel)}: 고정 바이너리 예외의 "
                    f"대응 소스 정보 {pin.source}가 설치 트리에 없다"
                )
            problems, found = check_texts(
                entry,
                table,
                policy,
                layout,
                files_by_scope,
                pinned_ok=pin.leaves,
                references=report.references,
            )
            report.problems.extend(problems)
            evidence.extend(found)
        if not rest:
            continue
        stripped = [find_strip(table, nf.scope, nf.rel) for nf in rest]
        if allow_stripped_denied and status is Status.DENIED and all(stripped):
            for nf in rest:
                report.notes.append(
                    f"[제거 대상] {_where(nf.scope, nf.rel)} ({expr}): 제거 목록에 있어 "
                    "설치본에서 뺀다"
                )
            continue
        for nf in rest:
            report.problems.append(
                f"[네이티브 라이선스] {_where(nf.scope, nf.rel)}: {expr} — "
                f"{_status_text(status)} ({entry.package})"
            )

    for entry in table.entries:
        if entry.scope in files_by_scope and entry not in by_entry:
            report.notes.append(f"쓰이지 않는 네이티브 항목: {entry.scope}:{entry.glob}")
    return evidence


def audit_build_input(
    layout: Layout,
    table: NativeTable,
    policy: Policy,
    *,
    models: Sequence[ModelEntry] | None = None,
    models_dir: Path | None = None,
    origins: Sequence[str] = ("wheel",),
    versions: Mapping[str, str] | None = None,
) -> NativeReport:
    """빌드 입력 감사. 금지 라이선스 파일은 제거 목록에 있을 때만 허용하고 그 사실을 남긴다.

    `origins`는 이 입력에 들어 있는 빌드 입력 종류다. 그 종류의 제거 규칙은 반드시 무언가를
    맞혀야 한다 (감사 venv에는 wheel만 있으므로 pbs 규칙은 보지 않는다). `versions`는 고정 바이너리
    한정 예외가 비교하는 배포물의 실제 판(정규화한 이름 → 판)이다.
    """
    report = NativeReport()
    natives, files_by_scope, all_files = _scan(layout, table, report.problems)
    report.files = natives
    evidence = _judge_natives(
        report,
        table,
        policy,
        layout,
        files_by_scope,
        allow_stripped_denied=True,
        versions=versions,
    )

    hit: set[StripRule] = set()
    for scope, rel in all_files:
        rule = find_strip(table, scope, rel)
        if rule is not None:
            hit.add(rule)
    for rule in table.strip:
        if rule.origin in origins and rule.scope in files_by_scope and rule not in hit:
            report.problems.append(
                f"[제거 목록 빗나감] {rule.scope}:{rule.glob}: 빌드 입력에 맞는 파일이 없다 "
                "(버전이 바뀌어 이름이 달라졌는지 확인)"
            )

    if models is not None:
        report.problems.extend(audit_models(models, models_dir, policy))
    report.notice_sections = render_notice_sections(
        report.files,
        table,
        policy,
        evidence,
        models,
        models_dir,
        pinned=report.pinned,
        references=report.references,
    )
    return report


ELECTRON = canonicalize_name("electron")
_ELECTRON_MARK = re.compile(rb"Electron/(\d+\.\d+\.\d+)")


def electron_version(root: Path) -> str | None:
    """설치 폴더 맨 위 실행 파일에 든 Electron 판 (`Electron/<판>` 사용자 에이전트 글귀). 고정
    바이너리 예외의 판 비교는 레포의 고정판이 아니라 실제로 배포되는 실행 파일에서 읽은 판으로
    한다."""
    if not root.is_dir():
        return None
    for exe in sorted(root.glob("*.exe")):
        tail = b""
        with exe.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                found = _ELECTRON_MARK.search(tail + chunk)
                if found:
                    return found[1].decode("ascii")
                tail = chunk[-64:]
    return None


def detect_versions(root: Path) -> dict[str, str]:
    """고정 바이너리 예외가 비교하는 배포물 판 (설치 트리에서 읽은 것)."""
    found = electron_version(root)
    return {ELECTRON: found} if found else {}


def audit_final_tree(
    root: Path,
    table: NativeTable,
    policy: Policy,
    *,
    models: Sequence[ModelEntry] | None = None,
    installer_files: Sequence[str] = (),
    versions: Mapping[str, str] | None = None,
) -> NativeReport:
    """최종 설치 트리 감사. 제거 목록에 있어도 남아 있으면 실패다.

    `installer_files`는 설치 프로그램이 설치 때 더하는 네이티브 파일(설치 폴더 기준, 예: NSIS
    제거 프로그램)이다. 설치 전 트리에는 없으므로 있는 것으로 보고 판정·NOTICES에 넣는다(설치된
    트리에 실제로 있으면 그 파일을 그대로 본다). `versions`를 주지 않으면 트리에서 읽는다
    (`detect_versions`)."""
    layout = Layout.install(root)
    report = NativeReport()
    if versions is None:
        versions = detect_versions(root)
    if not root.is_dir():
        report.problems.append(f"[설치 폴더 없음] {root}")
    natives, files_by_scope, all_files = _scan(layout, table, report.problems)
    present = {nf.rel.casefold() for nf in natives if nf.scope == INSTALL}
    for rel in installer_files:
        if rel.casefold() not in present:
            natives.append(NativeFile(INSTALL, rel, root / rel, find_entry(table, INSTALL, rel)))
    report.files = natives

    for scope, rel in all_files:
        rule = find_strip(table, scope, rel)
        if rule is not None:
            report.problems.append(
                f"[제거 대상 남음] {_where(scope, rel)}: 최종 트리에 있으면 안 된다 ({rule.reason})"
            )
    evidence = _judge_natives(
        report,
        table,
        policy,
        layout,
        files_by_scope,
        allow_stripped_denied=False,
        versions=versions,
    )

    site = layout.roots[SITE_PACKAGES]
    if site.is_dir():
        # 폴더 읽기 오류는 위 스캔이 이미 남겼다
        report.problems.extend(audit_records(site, table, errors=[]))
    else:
        report.problems.append(f"[site-packages 없음] {SITE_PACKAGES_IN_INSTALL}")

    models_dir: Path | None = None
    if models is not None:
        models_dir = root / MODELS_IN_INSTALL
        if not models_dir.is_dir():
            report.problems.append(f"[모델 폴더 없음] {MODELS_IN_INSTALL}")
            models_dir = None
        else:
            report.problems.extend(audit_models(models, models_dir, policy))
    report.notice_sections = render_notice_sections(
        report.files,
        table,
        policy,
        evidence,
        models,
        models_dir,
        pinned=report.pinned,
        references=report.references,
    )
    return report


def _pyc_source(rel: str) -> str | None:
    """`a/__pycache__/m.cpython-314.pyc` → `a/m.py` (compileall이 만든 파일은 RECORD에 없다)."""
    p = PurePosixPath(rel)
    if p.suffix != ".pyc" or p.parent.name != "__pycache__":
        return None
    return (p.parent.parent / (p.name.split(".", 1)[0] + ".py")).as_posix()


def audit_records(site: Path, table: NativeTable, errors: list[str] | None = None) -> list[str]:
    """`*.dist-info/RECORD`의 경로와 실제 파일이 서로 맞아야 한다.

    읽을 수 없는 폴더는 문제로 남긴다 (`errors`를 주면 그쪽에 모은다 — 같은 트리를 이미 스캔해
    오류를 남긴 호출자가 중복을 피할 때).
    """
    problems: list[str] = []
    walk_errors = problems if errors is None else errors
    recorded: set[str] = set()
    for record in sorted(site.glob("*.dist-info/RECORD")):
        dist = record.parent.name
        try:
            rows = list(csv.reader(record.read_text(encoding="utf-8").splitlines()))
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            problems.append(f"[RECORD 읽기 실패] {dist}: {exc}")
            continue
        for row in rows:
            if not row or not row[0].strip():
                continue
            rel = posixpath.normpath(row[0].replace("\\", "/"))
            recorded.add(rel.casefold())
            rule = find_strip(table, SITE_PACKAGES, rel)
            if rule is not None:
                problems.append(
                    f"[RECORD에 제거한 파일] {dist}: {row[0]} — 제거한 파일의 줄도 RECORD에서 "
                    "지워야 한다"
                )
            elif not (site / rel).is_file():
                problems.append(f"[RECORD에 있는데 없음] {dist}: {row[0]}")
    for _, rel, _ in iter_files(Layout.site_packages(site), walk_errors):
        if rel.casefold() in recorded:
            continue
        source = _pyc_source(rel)
        if source is not None and source.casefold() in recorded:
            continue
        problems.append(f"[RECORD에 없는 파일] {SITE_PACKAGES}:{rel}")
    return problems


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def audit_models(
    models: Sequence[ModelEntry], models_dir: Path | None, policy: Policy
) -> list[str]:
    """모델 라이선스는 허용이어야 한다. 폴더를 주면 모델마다 크기·SHA256을 확인한다."""
    problems: list[str] = []
    for m in models:
        status, expr = classify_license(m.license, policy)
        if status is not Status.ALLOWED:
            problems.append(f"[모델 라이선스] {m.file}: {expr} — {_status_text(status)}")
        if models_dir is None:
            continue
        path = models_dir / m.file
        # 표를 손으로 만든 경우도 막는다: 링크 등으로 폴더 밖을 가리키면 실패
        if not path.resolve().is_relative_to(models_dir.resolve()):
            problems.append(f"[모델 경로 이탈] {m.file}: {models_dir} 밖을 가리킨다")
            continue
        if not path.is_file():
            problems.append(f"[모델 없음] {m.file}: {models_dir}에 없다")
            continue
        size = path.stat().st_size
        if size != m.size or _sha256(path) != m.sha256:
            problems.append(f"[모델 해시 불일치] {m.file}: 표와 크기·SHA256이 다르다")
    if models_dir is not None:
        for t in _model_texts(models):
            path = models_dir / t.file
            if not path.resolve().is_relative_to(models_dir.resolve()):
                problems.append(f"[모델 경로 이탈] {t.file}: {models_dir} 밖을 가리킨다")
            elif not path.is_file():
                problems.append(f"[모델 근거 원문 없음] {t.file}: {models_dir}에 없다")
            elif path.stat().st_size != t.size or _sha256(path) != t.sha256:
                problems.append(f"[모델 근거 원문 해시 불일치] {t.file}: 표와 크기·SHA256이 다르다")
    return problems


def _model_texts(models: Sequence[ModelEntry]) -> list[ModelText]:
    out: list[ModelText] = []
    for m in models:
        out += [t for t in m.texts if t not in out]
    return out


# ---------------------------------------------------------------- NOTICES


def _rule(title: str) -> list[str]:
    return ["#" * 78, f"# {title}", "#" * 78, ""]


def render_notice_sections(
    files: Sequence[NativeFile],
    table: NativeTable,
    policy: Policy,
    evidence: Collected,
    models: Sequence[ModelEntry] | None,
    models_dir: Path | None = None,
    *,
    pinned: Sequence[tuple[NativeFile, PinnedBinary]] = (),
    references: Sequence[str] = (),
) -> list[str]:
    """NOTICES 뒤에 붙일 절: 네이티브 파일, 패키지별 라이선스 예외, 고정 바이너리 한정 예외,
    LicenseRef, 근거 원문(옮겨 싣지 않은 원문은 위치), 모델.

    모델 근거 원문은 `models_dir`에서 읽어 싣는다(없으면 받을 주소만 적는다 — 감사는 그 경우
    원문을 확인하지 않았으므로 배포용 NOTICES는 모델 폴더를 주고 만든다)."""
    sections: list[str] = []
    entries: dict[NativeEntry, list[NativeFile]] = {}
    for nf in files:
        if nf.entry is not None:
            entries.setdefault(nf.entry, []).append(nf)

    if entries:
        lines = _rule("네이티브 파일 (DLL·pyd·exe)과 그 안의 구성요소")
        for entry, nfs in entries.items():
            lines += ["=" * 78, f"{entry.package}: {entry.glob}", f"License: {entry.license}"]
            if entry.components:
                lines.append(f"구성요소: {entry.components}")
            lines.append(f"근거: {entry.reason}")
            lines += [f"원문: {t.label} ({', '.join(t.covers)})" for t in entry.texts]
            lines += [f"  {_where(nf.scope, nf.rel)}" for nf in nfs]
            lines.append("")
        sections.append("\n".join(lines))

    used_with: list[tuple[str, str, str]] = []
    for entry in entries:
        for combo, reason in policy.package_with.get(canonicalize_name(entry.package), {}).items():
            row = (entry.package, combo, reason)
            if combo in entry.license and row not in used_with:
                used_with.append(row)
    if used_with:
        lines = _rule("패키지별 라이선스 예외")
        for package, combo, reason in used_with:
            lines += [f"{package}: {combo}", f"  이유: {reason}", ""]
        sections.append("\n".join(lines))

    if pinned:
        lines = _rule("고정 바이너리 한정 라이선스 예외")
        for nf, pin in pinned:
            lines += [
                f"{_where(nf.scope, nf.rel)}: {pin.license}",
                f"  배포물: {pin.package} {pin.version}",
                f"  SHA256: {pin.sha256}",
                f"  이유: {pin.reason}",
                f"  대응 소스·패치·빌드 정보: {pin.source}",
                "",
            ]
        sections.append("\n".join(lines))

    refs = [
        ref
        for ref_id, ref in table.license_refs.items()
        if any(ref_id in entry.license for entry in entries)
    ]
    if refs:
        lines = _rule("SPDX 밖 배포 조건 (LicenseRef)")
        for ref in refs:
            lines += [
                f"{ref.id}: {ref.name}",
                f"  원문: {ref.source}",
                f"  처리 근거: {ref.reason}",
            ]
            if ref.notice:
                lines += ["", ref.notice]
            lines.append("")
        sections.append("\n".join(lines))

    seen: set[str] = set()
    texts: list[str] = []
    for label, text in evidence:
        if label in seen:
            continue
        seen.add(label)
        texts += ["=" * 78, label, "-" * 78, text, ""]
    if references:
        texts += ["=" * 78, "옮겨 싣지 않은 원문 (설치 폴더의 그 파일이 원문이다)", "-" * 78]
        texts += [f"  {ref}" for ref in references]
        texts.append("")
    if texts:
        sections.append("\n".join(_rule("네이티브 파일 근거 원문") + texts))

    if models:
        lines = _rule("OCR 모델")
        for m in models:
            lines += [
                f"{m.file}",
                f"License: {m.license}",
                f"출처: {m.source}",
                f"SHA256: {m.sha256} ({m.size} bytes)",
            ]
            lines += [f"근거 원문: {t.label} ({t.file})" for t in m.texts]
            lines.append("")
        for t in _model_texts(models):
            body: str | None = None
            if models_dir is not None:
                try:
                    body = (models_dir / t.file).read_text(encoding="utf-8-sig")
                except OSError, UnicodeDecodeError:
                    body = None  # audit_models가 문제로 남긴다
            lines += ["=" * 78, f"{t.label} ({t.file})", "-" * 78]
            lines += [body if body is not None else f"원문: {t.url}", ""]
        sections.append("\n".join(lines))
    return sections


# ---------------------------------------------------------------- 명령줄


def main(argv: Sequence[str] | None = None) -> int:
    """최종 설치 트리 감사. 종료 코드 0 = 통과, 1 = 실패, 2 = 입력·설정 오류."""
    import argparse
    import sys

    from kookabug_sdk.console import utf8_stdio
    from license_audit import load_policy_file

    utf8_stdio()
    tools = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Kookabug 최종 설치 트리 감사")
    parser.add_argument("root", type=Path, help="설치 폴더")
    parser.add_argument("--native-table", type=Path, default=tools / "native-licenses.toml")
    parser.add_argument("--allowlist", type=Path, default=tools / "license-allowlist.toml")
    parser.add_argument("--models-table", type=Path, help="OCR 모델 표 (주면 ocr-models 해시 확인)")
    args = parser.parse_args(argv)
    try:
        report = audit_final_tree(
            args.root,
            load_native_table_file(args.native_table),
            load_policy_file(args.allowlist),
            models=load_model_table_file(args.models_table) if args.models_table else None,
        )
    except AuditInputError as exc:
        print(f"최종 트리 감사 입력 오류: {exc}", file=sys.stderr)
        return 2
    print(f"네이티브 파일 {len(report.files)}개")
    for note in report.notes:
        print(f"참고: {note}")
    if report.problems:
        print(f"최종 트리 감사 실패 ({len(report.problems)}건)", file=sys.stderr)
        for p in report.problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print("최종 트리 감사 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
