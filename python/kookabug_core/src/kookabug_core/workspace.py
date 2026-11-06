"""워크스페이스: 루트·경로, `kookabug.json`·`.kookabug/local.json`, `$setting` 탐색, 비밀값 제공자.

`$setting` 탐색 순서 (워크스페이스 구조 "설정"):
실행 옵션 → `.kookabug/local.json` → 선택한 프로필 → `kookabug.json` 기본값.
처음으로 그 키를 가진 계층의 값을 쓴다 (병합이 아니다). 그 값이 `null`이면 오류다.
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final, Literal, Protocol, cast

from kookabug_core.canonical import loads_strict
from kookabug_core.codes import diag
from kookabug_core.diagnostics import Diagnostic
from kookabug_core.schema import check_shape

__all__ = [
    "AGENTS_BEGIN",
    "AGENTS_END",
    "AGENTS_FILE",
    "AGENTS_SECTION",
    "LOCAL_FILE",
    "RETENTION_DEFAULTS",
    "SECRET_ENV_PREFIX",
    "WORKSPACE_FILE",
    "EnvSecrets",
    "MemorySecrets",
    "RunConditions",
    "RunOptions",
    "SecretChain",
    "SecretProvider",
    "SettingLookup",
    "Workspace",
    "WorkspaceError",
    "agents_md_section",
    "default_secrets",
    "ensure_workspace_id",
    "secret_env_name",
    "workspace_id",
    "write_agents_md",
]

WORKSPACE_FILE: Final = "kookabug.json"
LOCAL_FILE: Final = ".kookabug/local.json"
SECRET_ENV_PREFIX: Final = "KOOKABUG_SECRET_"
RETENTION_DEFAULTS: Final[Mapping[str, int]] = {
    "passed_days": 14,
    "failed_days": 60,
    "keep_last": 50,
}
"""실행 기록 보관 기본값 (워크스페이스 구조 \"실행 기록 보관\"). 정리는 보류 H1."""

Layer = Literal["options", "local", "profile", "workspace"]
_LAYER_NAMES: Final[dict[Layer, str]] = {
    "options": "실행 옵션",
    "local": LOCAL_FILE,
    "profile": "프로필",
    "workspace": f"{WORKSPACE_FILE} 기본값",
}


class WorkspaceError(Exception):
    """워크스페이스를 열 수 없다 (`kookabug.json`이 없음 등)."""


@dataclass(frozen=True, slots=True)
class RunOptions:
    """실행 옵션. `settings`는 M0b CLI `--set`, `profile`은 선택한 프로필 이름."""

    settings: Mapping[str, Any] = field(default_factory=dict[str, Any])
    profile: str | None = None


@dataclass(frozen=True, slots=True)
class RunConditions:
    """`kookabug.json`의 `run`: 실행 조건 기본값(시간은 밀리초). 없는 값은 None (감독자 기본값을
    쓴다)."""

    deadline_ms: int | None = None
    worker_cancel_grace_ms: int | None = None
    worker_start_timeout_ms: int | None = None
    shutdown_grace_ms: int | None = None
    capture_timeout_ms: int | None = None
    frame_budget_mib: int | None = None
    frame_output_refs: int | None = None


@dataclass(frozen=True, slots=True)
class SettingLookup:
    """`$setting` 탐색 결과. `layer`가 None이면 어느 계층에도 키가 없다."""

    key: str
    layer: Layer | None
    value: Any = None

    @property
    def found(self) -> bool:
        return self.layer is not None


@dataclass
class Workspace:
    root: Path
    config: dict[str, Any]
    local: dict[str, Any] | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list[Diagnostic])

    @classmethod
    def open(cls, root: str | Path) -> Workspace:
        """`root/kookabug.json`이 있는 워크스페이스를 연다.

        두 설정 파일의 읽기·형식 오류는 `diagnostics`에 담는다 (형식이 틀린 파일은 빈 설정으로
        본다).
        """
        root = Path(root).resolve()
        path = root / WORKSPACE_FILE
        if not path.is_file():
            raise WorkspaceError(f"{path}이(가) 없다. 워크스페이스 루트가 아니다")
        diags: list[Diagnostic] = []
        config = _read_settings_file(path, WORKSPACE_FILE, "workspace", diags)
        local_path = root / LOCAL_FILE
        local = (
            _read_settings_file(local_path, LOCAL_FILE, "local", diags)
            if local_path.is_file()
            else None
        )
        return cls(root, config or {"format": "kookabug.workspace/0"}, local, diags)

    @classmethod
    def find(cls, start: str | Path) -> Workspace:
        """`start`(파일 또는 폴더)에서 위로 올라가며 `kookabug.json`이 있는 폴더를 찾는다."""
        here = Path(start).resolve()
        for folder in (here, *here.parents):
            if (folder / WORKSPACE_FILE).is_file():
                return cls.open(folder)
        raise WorkspaceError(f"{here}와(과) 그 위 폴더에 {WORKSPACE_FILE}이(가) 없다")

    # ------------------------------------------------------------ 경로

    @property
    def local_path(self) -> Path:
        return self.root.joinpath(*LOCAL_FILE.split("/"))

    def resolve(self, rel: str) -> Path | None:
        """워크스페이스 루트 기준 경로('/' 구분) → 절대 경로. 루트 밖이거나 형식이 틀리면 None."""
        parts = _rel_parts(rel)
        return None if parts is None else self.root.joinpath(*parts)

    @staticmethod
    def resolve_from(base: str, rel: str) -> str | None:
        """`base`(루트 기준 파일 경로)가 있는 폴더 기준 상대 경로 → 루트 기준 경로.

        `..`은 쓸 수 있지만 루트 밖으로 나가면 None. target의 `image`가 이 규칙이다. 경로 계산만
        하므로(루트를 쓰지 않음) 워크스페이스 없이도 부를 수 있다(daemon target 편집).
        """
        if not isinstance(rel, str) or not rel or "\\" in rel or rel.startswith("/") or ":" in rel:
            return None
        parts = list(PurePosixPath(base).parent.parts)
        for part in rel.split("/"):
            if part == "":
                return None
            if part == ".":
                continue
            if part == "..":
                if not parts:
                    return None
                parts.pop()
            else:
                parts.append(part)
        return "/".join(parts) if parts else None

    def relative(self, path: Path) -> str | None:
        """절대 경로 → 루트 기준 경로. 루트 밖이면 None."""
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return None

    # ------------------------------------------------------------ 설정

    def run_conditions(self) -> RunConditions:
        """`kookabug.json`의 `run` 블록. 형식이 틀린 파일은 빈 설정으로 읽었으므로 모두 None이다."""
        run = self.config.get("run")
        if not isinstance(run, dict):
            return RunConditions()
        return RunConditions(
            deadline_ms=run.get("deadline_ms"),
            worker_cancel_grace_ms=run.get("worker_cancel_grace_ms"),
            worker_start_timeout_ms=run.get("worker_start_timeout_ms"),
            shutdown_grace_ms=run.get("shutdown_grace_ms"),
            capture_timeout_ms=run.get("capture_timeout_ms"),
            frame_budget_mib=run.get("frame_budget_mib"),
            frame_output_refs=run.get("frame_output_refs"),
        )

    def retention(self) -> dict[str, int]:
        """`kookabug.json`의 `retention`, 없는 값은 기본값 (워크스페이스 구조 "실행 기록 보관")."""
        out = dict(RETENTION_DEFAULTS)
        raw = self.config.get("retention")
        if isinstance(raw, dict):
            for key in out:
                value = cast(dict[str, Any], raw).get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    out[key] = value
        return out

    def profile_names(self) -> list[str]:
        profiles = self.config.get("profiles")
        return sorted(profiles) if isinstance(profiles, dict) else []

    def check_options(self, options: RunOptions) -> list[Diagnostic]:
        if options.profile is not None and options.profile not in self.profile_names():
            names = ", ".join(self.profile_names()) or "없음"
            return [
                diag(
                    "profile_missing",
                    f"프로필 '{options.profile}'이(가) {WORKSPACE_FILE}에 없다 "
                    f"(있는 프로필: {names})",
                    file=WORKSPACE_FILE,
                    pointer="/profiles",
                )
            ]
        return []

    def setting_layers(self, options: RunOptions) -> list[tuple[Layer, Mapping[str, Any]]]:
        """탐색 순서대로 (계층, 설정)."""
        layers: list[tuple[Layer, Mapping[str, Any]]] = [("options", options.settings)]
        if self.local is not None:
            layers.append(("local", _settings_of(self.local)))
        if options.profile is not None:
            profiles = self.config.get("profiles")
            profile = profiles.get(options.profile) if isinstance(profiles, dict) else None
            if isinstance(profile, dict):
                layers.append(("profile", _settings_of(profile)))
        layers.append(("workspace", _settings_of(self.config)))
        return layers

    def lookup_setting(self, key: str, options: RunOptions | None = None) -> SettingLookup:
        for layer, settings in self.setting_layers(options or RunOptions()):
            if key in settings:
                return SettingLookup(key, layer, settings[key])
        return SettingLookup(key, None)

    def setting_problem(
        self, lookup: SettingLookup, options: RunOptions | None = None
    ) -> tuple[str, str] | None:
        """탐색 결과의 문제 (진단 코드, 메시지). 쓸 수 있는 값이면 None."""
        key = lookup.key
        local = str(self.local_path)
        hint = f'{local}의 "settings"에 "{key}" 값을 넣는다'
        if not lookup.found:
            return "setting_missing", f"설정 '{key}'이(가) 어디에도 없다. {hint}"
        if lookup.value is not None:
            return None
        assert lookup.layer is not None
        where = _LAYER_NAMES[lookup.layer]
        if lookup.layer == "profile" and options is not None:
            where = f"프로필 '{options.profile}'"
        if lookup.layer == "local":
            return "setting_null", f"설정 '{key}'이(가) {local}에 null로 적혀 있다. 값을 넣는다"
        return (
            "setting_null",
            f"설정 '{key}'이(가) null이다({where}). 사람마다 다른 값이므로 {hint}",
        )


def _settings_of(data: Mapping[str, Any]) -> Mapping[str, Any]:
    settings = data.get("settings")
    return settings if isinstance(settings, dict) else {}


def _read_settings_file(
    path: Path, rel: str, kind: Literal["workspace", "local"], diags: list[Diagnostic]
) -> dict[str, Any] | None:
    try:
        data = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        diags.append(diag("json_invalid", f"{rel}을(를) 읽을 수 없다: {exc}", file=rel))
        return None
    problems = check_shape(data, kind, file=rel)
    diags.extend(problems)
    return None if problems else data


def _rel_parts(rel: object) -> list[str] | None:
    if not isinstance(rel, str) or not rel or "\\" in rel or rel.startswith("/") or ":" in rel:
        return None
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    return parts


# ---------------------------------------------------------------- 비밀값


def secret_env_name(key: str) -> str:
    """비밀 키 → 환경 변수 이름 (`.`은 `_`, 대문자).

    `accounts.qa_tester_01` → `KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01`
    """
    return SECRET_ENV_PREFIX + key.replace(".", "_").upper()


class SecretProvider(Protocol):
    def get(self, key: str) -> str | None:
        """비밀 키의 값. 없으면 None."""
        ...


class EnvSecrets:
    """환경 변수 `KOOKABUG_SECRET_<키>` (CI·무인 실행)."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ

    def get(self, key: str) -> str | None:
        return self._environ.get(secret_env_name(key))


class MemorySecrets:
    """메모리에 둔 비밀값 (테스트·에이전트용)."""

    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self._values = dict(values or {})

    def get(self, key: str) -> str | None:
        return self._values.get(key)


class SecretChain:
    """앞의 제공자부터 찾는다."""

    def __init__(self, *providers: SecretProvider) -> None:
        self._providers = providers

    def get(self, key: str) -> str | None:
        for provider in self._providers:
            value = provider.get(key)
            if value is not None:
                return value
        return None


_WORKSPACE_ID: Final = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def workspace_id(workspace: Workspace) -> str | None:
    """`kookabug.json` `id` (자격 증명 관리자 이름의 접두). 없거나 형식이 틀리면 None."""
    value = workspace.config.get("id")
    return value if isinstance(value, str) and _WORKSPACE_ID.fullmatch(value) else None


def ensure_workspace_id(root: Path) -> str:
    """`kookabug.json`에 `id`가 없으면 만들어 넣고 돌려준다 (M4 계획 Q10: 처음 비밀값을 만들 때).

    원문을 다시 읽어 `id` 하나만 더한 텍스트(`save_text` — 나머지 원문 바이트·순서는 그대로)를 같은
    폴더 임시 파일 → `os.replace`로 쓴다. JSON이 틀린 파일이면 건드리지 않고 `WorkspaceError`."""
    from kookabug_core.canonical import save_text
    from kookabug_core.documents import write_atomic

    path = root / WORKSPACE_FILE
    try:
        text = path.read_bytes().decode("utf-8")
        value = loads_strict(text)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise WorkspaceError(
            f"{path}을(를) 읽을 수 없어 워크스페이스 ID를 넣지 않는다: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise WorkspaceError(f"{path}이(가) JSON 객체가 아니다")
    data = cast(dict[str, Any], value)
    current = data.get("id")
    if isinstance(current, str) and _WORKSPACE_ID.fullmatch(current):
        return current
    new_id = str(uuid.uuid4())
    data["id"] = new_id
    write_atomic(path, save_text(text, data).encode("utf-8"))
    return new_id


AGENTS_FILE: Final = "AGENTS.md"
AGENTS_BEGIN: Final = "<!-- kookabug:begin -->"
AGENTS_END: Final = "<!-- kookabug:end -->"
AGENTS_SECTION: Final = """\
## Kookabug 워크스페이스 규칙 (자동 관리 구간 — 이 표시 사이는 Kookabug가 다시 쓴다)

- 폴더: `tests/` 테스트 그래프, `subgraphs/` 서브그래프, `targets/` 찾기 대상(`*.target.json` +
  PNG), `screens/` 화면 지도, `runs/` 실행 기록(읽기 전용), `.kookabug/` 개인 설정·캐시(Git 제외)
- 파일 형식은 Kookabug 저장소의 `Docs/Design/그래프 JSON 스키마 v0.md`·`워크스페이스 구조.md`
- 그래프는 Kookabug MCP 도구(`kb_graph_create`·`kb_graph_patch`)로 고친다. 노드 ID를 바꾸지 않는다
- 도구는 `kb_toolset_enable`로 툴셋(graph_edit·run·observe·control·screens)을 켠 뒤 쓴다
- 실패 분석은 `kb_run_status`(실패 요약)·`kb_run_events`부터 본다. 그다음 `kb_run_artifact_get`
  (스크린샷)·`kb_run_compare`(지난 성공과 비교)
- 비밀값(비밀번호·토큰)을 파일·그래프에 쓰지 않는다. 그래프에서는 `{"$secret": "키"}`로 가리킨다
"""
"""예제·새 워크스페이스 `AGENTS.md`의 관리 구간 본문 (M5 3.12)."""


def agents_md_section(root: Path) -> str | None:
    """`AGENTS.md`의 관리 구간 본문 (표시 사이). 파일·표시가 없거나 읽을 수 없으면 None."""
    try:
        text = (root / AGENTS_FILE).read_text(encoding="utf-8-sig")
    except OSError, UnicodeDecodeError:
        return None
    begin = text.find(AGENTS_BEGIN)
    end = text.find(AGENTS_END, begin + len(AGENTS_BEGIN)) if begin >= 0 else -1
    if begin < 0 or end < 0:
        return None
    return text[begin + len(AGENTS_BEGIN) : end].strip("\r\n")


def write_agents_md(root: Path, section: str = AGENTS_SECTION) -> None:
    """`AGENTS.md`의 관리 구간만 `section`으로 쓴다 (워크스페이스 구조 "`AGENTS.md`"). 사용자가 쓴
    구간 밖 글은 그대로 둔다. 파일이 없으면 만들고, 표시가 없으면 끝에 구간을 붙인다. 같은 폴더
    임시 파일 → `os.replace`."""
    from kookabug_core.documents import write_atomic

    path = root / AGENTS_FILE
    block = f"{AGENTS_BEGIN}\n{section.strip(chr(10))}\n{AGENTS_END}"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        text = None
    except (OSError, UnicodeDecodeError) as exc:
        raise WorkspaceError(f"{path}을(를) 읽을 수 없어 고치지 않는다: {exc}") from exc
    if text is None:
        new = f"# 에이전트 안내\n\n{block}\n"
    else:
        begin = text.find(AGENTS_BEGIN)
        end = text.find(AGENTS_END, begin + len(AGENTS_BEGIN)) if begin >= 0 else -1
        if begin >= 0 and end >= 0:
            new = text[:begin] + block + text[end + len(AGENTS_END) :]
        else:
            new = text + ("" if text.endswith("\n") or not text else "\n") + f"\n{block}\n"
        if new == text:
            return
    write_atomic(path, new.encode("utf-8"))


def default_secrets(workspace: Workspace | None = None) -> SecretProvider:
    """기본 제공자: 환경 변수 → (Windows이고 워크스페이스 ID가 있으면) 자격 증명 관리자."""
    from kookabug_core.win.credentials import CredentialSecrets, available

    env = EnvSecrets()
    wid = None if workspace is None else workspace_id(workspace)
    if wid is None or not available():
        return env
    return SecretChain(env, CredentialSecrets(wid))
