"""화면 판정 파일 `*.screen.json` (구현 계획 M1 2.10, 스키마 v0 4장 "화면 판정 파일").

- 화면 ID = 파일 이름 줄기(`screens/lobby/server_list.screen.json` → `server_list`). `screens/`
  아래 어디에 둬도 되고, `screens/_explored/`(Agent 탐색 결과, 사람 확인 전)는 보지 않는다
- 같은 ID의 파일이 둘 이상이면 그 ID는 모호하다(`screen_ambiguous`)
- `detect.all`(전부 보임)·`detect.none`(하나도 안 보임). 값은 `$target`만(M1)

여기는 파일 찾기·형식만 다룬다. 판정(이미지 매칭)은 `kookabug_platform.screens`가 한다. 실행 중
화면 판정으로 실행을 바꾸지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from kookabug_core.canonical import loads_strict
from kookabug_core.schema import check_shape
from kookabug_core.workspace import Workspace

__all__ = [
    "EXPLORED_DIR",
    "SCREENS_DIR",
    "SUFFIX",
    "ScreenDef",
    "ScreenFileError",
    "parse_screen",
    "read_screen_file",
    "screen_id",
    "screen_index",
]

SCREENS_DIR: Final = "screens"
EXPLORED_DIR: Final = "_explored"
SUFFIX: Final = ".screen.json"


class ScreenFileError(Exception):
    """화면 파일을 읽을 수 없거나 형식이 틀렸다."""


@dataclass(frozen=True, slots=True)
class ScreenDef:
    """화면 하나. `all`·`none`은 target 경로(워크스페이스 루트 기준)."""

    id: str
    path: str
    title: str | None
    all: tuple[str, ...]
    none: tuple[str, ...]

    @property
    def targets(self) -> tuple[str, ...]:
        return (*self.all, *self.none)


def screen_id(path: str | Path) -> str:
    """파일 경로 → 화면 ID (파일 이름에서 `.screen.json`을 뺀 것)."""
    name = Path(path).name if isinstance(path, Path) else path.rsplit("/", 1)[-1]
    if not name.endswith(SUFFIX):
        raise ValueError(f"{name}은(는) {SUFFIX} 파일이 아니다")
    return name[: -len(SUFFIX)]


def screen_index(workspace: Workspace) -> dict[str, list[str]]:
    """워크스페이스의 화면 ID → 파일 경로들(루트 기준, 정렬). `_explored/`는 뺀다."""
    base = workspace.root / SCREENS_DIR
    index: dict[str, list[str]] = {}
    if not base.is_dir():
        return index
    for path in base.rglob(f"*{SUFFIX}"):
        rel_parts = path.relative_to(base).parts
        if rel_parts[0] == EXPLORED_DIR or not path.is_file():
            continue
        rel = "/".join((SCREENS_DIR, *rel_parts))
        index.setdefault(screen_id(path), []).append(rel)
    for paths in index.values():
        paths.sort()
    return index


def parse_screen(data: Any, rel: str) -> ScreenDef:
    """형식 검사 → `ScreenDef`. 틀리면 `ScreenFileError`."""
    problems = check_shape(data, "screen", file=rel)
    if problems:
        detail = "; ".join(f"{d.pointer or '/'} {d.message}" for d in problems[:3])
        raise ScreenFileError(f"화면 파일 '{rel}'의 형식이 틀렸다: {detail}")
    detect: Mapping[str, Any] = data["detect"]

    def refs(key: str) -> tuple[str, ...]:
        return tuple(item["$target"] for item in detect.get(key, ()))

    return ScreenDef(screen_id(rel), rel, data.get("title"), refs("all"), refs("none"))


def read_screen_file(path: Path, rel: str) -> ScreenDef:
    """파일 하나를 읽는다. `rel`은 진단·ID용 이름(워크스페이스 기준 경로 또는 파일 이름)."""
    try:
        data = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ScreenFileError(f"화면 파일 '{rel}'을(를) 읽을 수 없다: {exc}") from exc
    return parse_screen(data, rel)
