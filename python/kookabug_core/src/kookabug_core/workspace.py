"""워크스페이스: 루트·경로, `kookabug.json`·`.kookabug/local.json`, `$setting` 탐색, 비밀값 제공자.

`$setting` 탐색 순서 (워크스페이스 구조 "설정"):
실행 옵션 → `.kookabug/local.json` → 선택한 프로필 → `kookabug.json` 기본값.
처음으로 그 키를 가진 계층의 값을 쓴다 (병합이 아니다). 그 값이 `null`이면 오류다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final, Literal, Protocol

from kookabug_core.canonical import loads_strict
from kookabug_core.codes import diag
from kookabug_core.diagnostics import Diagnostic
from kookabug_core.schema import check_shape

__all__ = [
    "LOCAL_FILE",
    "SECRET_ENV_PREFIX",
    "WORKSPACE_FILE",
    "EnvSecrets",
    "MemorySecrets",
    "RunOptions",
    "SecretChain",
    "SecretProvider",
    "SettingLookup",
    "Workspace",
    "WorkspaceError",
    "default_secrets",
    "secret_env_name",
]

WORKSPACE_FILE: Final = "kookabug.json"
LOCAL_FILE: Final = ".kookabug/local.json"
SECRET_ENV_PREFIX: Final = "KOOKABUG_SECRET_"

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

    def resolve_from(self, base: str, rel: str) -> str | None:
        """`base`(루트 기준 파일 경로)가 있는 폴더 기준 상대 경로 → 루트 기준 경로.

        `..`은 쓸 수 있지만 루트 밖으로 나가면 None. target의 `image`가 이 규칙이다.
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


def default_secrets() -> SecretProvider:
    """기본 제공자: 환경 변수. Windows 자격 증명 관리자는 M1에서 뒤에 붙인다."""
    return EnvSecrets()
