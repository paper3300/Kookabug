"""플러그인 wheel 정적 읽기·검사 (M6 계획 3.1, 거래 ②). 코드를 실행하지 않는다 — zip만 읽는다.

- 파일명은 유효한 wheel 이름 (uv가 받는 그대로 보관하므로)
- `*.dist-info/METADATA`의 Name·Version·Requires-Dist
- 스키마 파일 `<modules[0]의 최상위 패키지>/kookabug.schema.json` 하나: node-schema 모양, 머리 판 =
  METADATA 판, ID 규칙·예약, 노드 타입 앞부분 = ID, `effects` ⊆ `permissions`, `modules` 있음,
  `kookabug-sdk` 의존 선언, `ui` 폴더(`index.js`)가 wheel 안에 있음
- 결과의 `schema_sha256` = `schema_digest(파일)` — 실행 때 hello digest와 대조한다
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from email.parser import HeaderParser
from pathlib import Path
from typing import Any, Final

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

from kookabug_core.plugins.errors import PluginError
from kookabug_core.schema import check_shape
from kookabug_sdk.schema import FORMAT, SCHEMA_FILE, schema_digest, schema_package

__all__ = [
    "RESERVED_IDS",
    "SDK_DIST",
    "Manifest",
    "ProjectManifest",
    "min_core_satisfied",
    "normalize_name",
    "read_project_manifest",
    "read_wheel",
    "requirement_name",
    "same_requirements",
]

RESERVED_IDS: Final = frozenset({"core", "kookabug", "testkit"})
SDK_DIST: Final = "kookabug-sdk"
_ID = re.compile(r"^[a-z][a-z0-9_]*$")
# {배포판}-{판}(-{빌드})?-{python}-{abi}-{플랫폼}.whl
_WHEEL_NAME = re.compile(
    r"^(?P<dist>[A-Za-z0-9](?:[A-Za-z0-9._]*[A-Za-z0-9])?)-(?P<version>[^-]+)"
    r"(?:-\d[^-]*)?-[^-]+-[^-]+-[^-]+\.whl$"
)
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")
_HEADER_KEYS: Final = ("title", "modules", "permissions", "min_core", "isolation", "ui")


def normalize_name(name: str) -> str:
    """PEP 503 이름 정규화."""
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(requirement: str) -> str:
    match = _REQ_NAME.match(requirement)
    return normalize_name(match.group(1)) if match else ""


def min_core_satisfied(app_version: str, min_core: str) -> bool:
    """앱 판이 `min_core`(PEP 440 하한)를 만족하는가.

    PEP 440 순서 그대로다 (`0.1.0 < 0.1.0.post1`, `0.1.0rc1 < 0.1.0rc2`). 예외 하나: 앱이 개발
    빌드 `X.devN`(X는 정식 판)이고 `min_core`가 정식 판 `X`와 정확히 같으면 허용한다 — 다음 정식
    판을 준비하는 앱이 그 판을 요구하는 플러그인을 받는다 (조율자 승인 규칙)."""
    app, need = Version(app_version), Version(min_core)
    if app >= need:
        return True
    dev_build = app.dev is not None and app.pre is None and app.post is None and app.local is None
    formal = need.pre is None and need.post is None and need.dev is None and need.local is None
    return dev_build and formal and Version(app.base_version) == need


@dataclass(frozen=True, slots=True)
class Manifest:
    """wheel 하나의 정적 정보."""

    id: str
    dist: str
    version: str
    wheel_name: str
    header: dict[str, Any]
    requires: tuple[str, ...]
    """METADATA의 Requires-Dist (extra 조건이 붙은 것은 뺀다)."""
    schema: dict[str, Any]
    schema_sha256: str

    @property
    def sdk_requires(self) -> tuple[str, ...]:
        return tuple(r for r in self.requires if requirement_name(r) == SDK_DIST)

    @property
    def dependencies(self) -> tuple[str, ...]:
        """SDK를 뺀 의존성 (SDK는 앱 것을 `--no-deps`로 따로 깐다)."""
        return tuple(r for r in self.requires if requirement_name(r) != SDK_DIST)

    @property
    def modules(self) -> list[str]:
        return list(self.header["modules"])

    @property
    def permissions(self) -> list[str]:
        return list(self.header.get("permissions", []))

    @property
    def isolation(self) -> str:
        return str(self.header.get("isolation", "auto"))

    def lock_manifest(self) -> dict[str, Any]:
        """잠금 `manifest` (머리에서 id·version을 뺀 것)."""
        return {k: self.header[k] for k in _HEADER_KEYS if k in self.header}


def _invalid(message: str) -> PluginError:
    return PluginError("manifest_invalid", message, stage="manifest")


def read_wheel(path: Path, *, allow_direct: bool = False) -> Manifest:
    """wheel을 읽고 정적 검사한다. 문제가 있으면 `manifest_invalid`. 의존성의 직접 URL 참조도
    거부한다 — `allow_direct`(⑥ 빌드 wheel 확정)면 받아 두고 원천과의 대조(`build_failed`)에
    맡긴다."""
    match = _WHEEL_NAME.match(path.name)
    if match is None:
        raise _invalid(f"{path.name}은(는) 유효한 wheel 파일 이름이 아니다")
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            metadata = _metadata(zf, names)
            schemas = [n for n in names if re.fullmatch(rf"[^/]+/{re.escape(SCHEMA_FILE)}", n)]
            if len(schemas) != 1:
                raise _invalid(
                    f"wheel에 노드 스키마 파일(<패키지>/{SCHEMA_FILE})이 {len(schemas)}개다 "
                    "(하나여야 한다. kookabug-sdk build로 만든다)"
                )
            try:
                document = json.loads(zf.read(schemas[0]).decode("utf-8"))
            except ValueError as exc:
                raise _invalid(f"{schemas[0]}을(를) 읽을 수 없다: {exc}") from exc
    except (OSError, zipfile.BadZipFile) as exc:
        raise _invalid(f"{path.name}을(를) zip으로 읽을 수 없다: {exc}") from exc

    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise _invalid(f"{schemas[0]}의 format이 {FORMAT}이(가) 아니다")
    if problems := check_shape(document, "node-schema"):
        raise _invalid(f"{schemas[0]}: {problems[0].message}")
    schema: dict[str, Any] = document
    header: dict[str, Any] = schema["plugin"]
    plugin_id = str(header["id"])
    problems_: list[str] = []
    if not _ID.match(plugin_id):
        problems_.append(f"플러그인 ID {plugin_id!r}이(가) 규칙에 맞지 않는다")
    if plugin_id in RESERVED_IDS:
        problems_.append(f"플러그인 ID {plugin_id!r}은(는) 예약돼 있다")
    modules = header.get("modules")
    if not modules:
        problems_.append("머리에 modules가 없다 (kookabug-sdk build로 다시 만든다)")
    elif schema_package(modules) != schemas[0].split("/", 1)[0]:
        problems_.append(
            f"스키마 파일이 modules 첫 항목의 패키지({schema_package(modules)})에 있지 않다"
        )
    if "permissions" not in header:
        problems_.append("머리에 permissions가 없다 (kookabug-sdk build로 다시 만든다)")
    permissions = set(header.get("permissions", []))
    for node in schema["nodes"]:
        node_type = str(node.get("type"))
        if not node_type.startswith(plugin_id + "."):
            problems_.append(f"노드 타입 {node_type}이(가) '{plugin_id}.'로 시작하지 않는다")
        if missing := sorted(set(node.get("effects", [])) - permissions):
            problems_.append(f"{node_type}: effects {missing}이(가) permissions에 없다")
    if not schema["nodes"]:
        problems_.append("노드가 없다")
    if str(header["version"]) != metadata["version"]:
        problems_.append(
            f"스키마 머리 판 {header['version']}이(가) 배포판 판 {metadata['version']}과 다르다"
        )
    requires = tuple(metadata["requires"])
    if not allow_direct:
        problems_ += _requirement_problems(requires)
    if not any(requirement_name(r) == SDK_DIST for r in requires):
        problems_.append(f"{SDK_DIST} 의존 선언이 없다 (예: kookabug-sdk>=0.1,<0.2)")
    min_core = header.get("min_core")
    if min_core is not None:
        try:
            Version(str(min_core))
        except InvalidVersion:
            problems_.append(f"min_core {min_core!r}이(가) PEP 440 판이 아니다")
    ui = header.get("ui")
    if ui is not None and modules:
        entry = f"{schema_package(modules)}/{ui}/index.js"
        if entry not in names:
            problems_.append(f"ui 진입 파일 {entry}이(가) wheel에 없다")
    if problems_:
        raise _invalid("; ".join(problems_))
    return Manifest(
        id=plugin_id,
        dist=metadata["name"],
        version=metadata["version"],
        wheel_name=path.name,
        header=dict(header),
        requires=requires,
        schema=schema,
        schema_sha256=schema_digest(schema),
    )


@dataclass(frozen=True, slots=True)
class ProjectManifest:
    """git·path 원천의 정적 정보 (`pyproject.toml`만 읽는다 — 빌드·import 없음, 거래 ②).
    노드·스키마는 승인 뒤 빌드한 wheel에서 다시 읽는다 (⑥, `read_wheel`)."""

    id: str
    dist: str
    version: str
    header: dict[str, Any]
    requires: tuple[str, ...]

    @property
    def sdk_requires(self) -> tuple[str, ...]:
        return tuple(r for r in self.requires if requirement_name(r) == SDK_DIST)

    @property
    def dependencies(self) -> tuple[str, ...]:
        return tuple(r for r in self.requires if requirement_name(r) != SDK_DIST)

    @property
    def permissions(self) -> list[str]:
        return list(self.header.get("permissions", []))

    @property
    def isolation(self) -> str:
        return str(self.header.get("isolation", "auto"))

    def lock_manifest(self) -> dict[str, Any]:
        return {k: self.header[k] for k in _HEADER_KEYS if k in self.header}


def read_project_manifest(root: Path) -> ProjectManifest:
    """`pyproject.toml` 정적 검사: `[tool.kookabug]`(SDK `read_project`와 같은 규칙), ID 예약,
    `[project].name`, 정적 `version`·`dependencies`(`dynamic`이면 `manifest_invalid`), SDK 의존
    선언, `min_core` PEP 440."""
    import tomllib

    from kookabug_sdk.build import BuildError, plugin_header, read_project

    try:
        project = read_project(root)
    except BuildError as exc:
        raise _invalid("; ".join(exc.problems)) from exc
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    meta = data.get("project", {})
    problems: list[str] = []
    dynamic = meta.get("dynamic", [])
    if isinstance(dynamic, list) and {"dependencies", "version"} & set(dynamic):
        problems.append(
            "[project].dynamic에 dependencies·version이 있다 (설치 전 정적으로 읽어야 한다)"
        )
    name = meta.get("name")
    if not isinstance(name, str) or not name:
        problems.append("[project].name이 없다")
    raw = meta.get("dependencies", [])
    if not isinstance(raw, list) or not all(isinstance(r, str) for r in raw):
        problems.append("[project].dependencies는 문자열 목록이다")
        raw = []
    requires = tuple(str(r).strip() for r in raw)
    problems += _requirement_problems(requires)
    if project.id in RESERVED_IDS:
        problems.append(f"플러그인 ID {project.id!r}은(는) 예약돼 있다")
    if not any(requirement_name(r) == SDK_DIST for r in requires):
        problems.append(f"{SDK_DIST} 의존 선언이 없다 (예: kookabug-sdk>=0.1,<0.2)")
    if project.min_core is not None:
        try:
            Version(project.min_core)
        except InvalidVersion:
            problems.append(f"min_core {project.min_core!r}이(가) PEP 440 판이 아니다")
    if problems:
        raise _invalid("; ".join(problems))
    return ProjectManifest(
        id=project.id,
        dist=str(name),
        version=project.version,
        header=plugin_header(project),
        requires=requires,
    )


def _requirement_problems(requires: tuple[str, ...]) -> list[str]:
    """읽을 수 없는 요구·직접 URL 참조(`이름 @ URL`). 직접 참조는 인덱스 해석·해시 잠금과 맞지
    않아 받지 않는다 (의존성은 인덱스의 wheel만, D5)."""
    problems: list[str] = []
    # 메시지에는 배포판 이름과 이유만 (요구 원문·파서 예외 문구에는 URL·인증 정보가 있을 수 있다)
    for number, requirement in enumerate(requires, start=1):
        try:
            parsed = Requirement(requirement)
        except InvalidRequirement:
            name = requirement_name(requirement) or "?"
            problems.append(f"{number}번째 의존성({name})을 읽을 수 없다 (PEP 508 요구가 아니다)")
            continue
        if parsed.url:
            problems.append(
                f"의존성 {normalize_name(parsed.name)}이(가) 직접 URL 참조다 "
                "(인덱스의 판 요구만 쓴다)"
            )
    return problems


def _requirement_key(text: str) -> tuple[str, frozenset[str], frozenset[str], str, str]:
    req = Requirement(text)
    return (
        normalize_name(req.name),
        frozenset(req.extras),
        frozenset(str(s) for s in req.specifier),
        str(req.marker or ""),
        req.url or "",  # 직접 참조 없음/있음·주소 차이도 다른 요구
    )


def same_requirements(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """두 의존성 목록이 같은 요구인가 (표기 순서·공백·이름 정규화 차이는 무시)."""
    try:
        return sorted(map(_requirement_key, a)) == sorted(map(_requirement_key, b))
    except InvalidRequirement:
        return False


def _metadata(zf: zipfile.ZipFile, names: list[str]) -> dict[str, Any]:
    found = [n for n in names if re.fullmatch(r"[^/]+\.dist-info/METADATA", n)]
    if len(found) != 1:
        raise _invalid(f"wheel의 *.dist-info/METADATA가 {len(found)}개다")
    text = zf.read(found[0]).decode("utf-8")
    message = HeaderParser().parsestr(text)
    name, version = message.get("Name"), message.get("Version")
    if not name or not version:
        raise _invalid("METADATA에 Name·Version이 없다")
    requires = [
        str(r).strip()
        for r in message.get_all("Requires-Dist") or []
        if "extra ==" not in str(r).replace("extra==", "extra ==")
    ]
    return {"name": str(name).strip(), "version": str(version).strip(), "requires": requires}
