"""`screens.list`·`screens.get` (M5 계획 3.3·3.5 H4): 화면 지도(`screens/**/*.screen.json`) 조회.

화면 지도는 screens 툴셋 도구(`kb_screen_list`·`kb_screen_get`)로만 판정한다. 에이전트 연결은
`workspace.tree`·`workspace.read`(kb_project_info로 판정)에서 `screens/`를 보지 못한다 —
screens를 막은 정책을 그 길로 돌아가지 않게. `screens/_explored/`(사람 확인 전 탐색 결과)도 목록에
넣는다(`explored: true`).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Final

from kookabug_core.canonical import loads_strict
from kookabug_core.screens import EXPLORED_DIR, SCREENS_DIR, SUFFIX, ScreenFileError, parse_screen
from kookabug_daemon.documents import resolve_path
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.protocol import InvalidParams, RequestFailed
from kookabug_daemon.watch import walk

__all__ = ["METHODS", "in_screens"]


def in_screens(rel: str) -> bool:
    """워크스페이스 기준 경로가 `screens/` 폴더이거나 그 아래인가 (대소문자 무시)."""
    first = rel.replace("\\", "/").strip("/").split("/", 1)[0]
    return first.casefold() == SCREENS_DIR


def _under(call: Call) -> str:
    under = call.params.get("under")
    if under is None:
        return SCREENS_DIR
    text = str(under).replace("\\", "/").strip("/")
    if not text:
        return SCREENS_DIR
    if not in_screens(text):
        text = f"{SCREENS_DIR}/{text}"
    return resolve_path(call.daemon.root, text).rel


def _entry(root: Path, rel: str) -> dict[str, Any]:
    parts = rel.split("/")
    entry: dict[str, Any] = {"path": rel, "id": parts[-1][: -len(SUFFIX)]}
    if len(parts) > 2 and parts[1] == EXPLORED_DIR:
        entry["explored"] = True
    try:
        data = loads_strict((root / rel).read_text(encoding="utf-8"))
        screen = parse_screen(data, rel)
    except (OSError, UnicodeDecodeError, ValueError, ScreenFileError) as exc:
        entry["problem"] = str(exc)
        return entry
    if screen.title is not None:
        entry["title"] = screen.title
    return entry


def _list(call: Call) -> dict[str, Any]:
    root = call.daemon.root
    under = _under(call).casefold().rstrip("/") + "/"
    screens = [
        _entry(root, item.rel)
        for item in walk(root)
        if not item.is_dir
        and in_screens(item.rel)
        and item.rel.casefold().endswith(SUFFIX)
        and item.rel.casefold().startswith(under)
    ]
    screens.sort(key=lambda e: e["path"])
    return {"screens": screens}


def _path_arg(call: Call) -> str:
    return resolve_path(call.daemon.root, str(call.params["path"])).rel


def _get(call: Call) -> dict[str, Any]:
    given = str(call.params["path"])
    where = resolve_path(call.daemon.root, given)
    if not (in_screens(where.given) and in_screens(where.rel) and where.rel.endswith(SUFFIX)):
        raise InvalidParams(f"'{given}'은(는) screens/ 아래 화면 지도 파일이 아니다", path=given)
    try:
        text = where.path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise RequestFailed("not_found", f"'{given}'이(가) 없다", path=given) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
    result: dict[str, Any] = {"path": where.rel}
    try:
        value = loads_strict(text)
    except ValueError as exc:
        result["problem"] = str(exc)
        return result
    result["value"] = value
    try:
        parse_screen(value, where.rel)
    except ScreenFileError as exc:
        result["problem"] = str(exc)
    return result


async def _list_handler(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_list, call)


async def _get_handler(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_get, call)


def _list_arg(call: Call) -> str:
    return _under(call)


METHODS: Final = {
    "screens.list": MethodSpec(_list_handler, _list_arg),
    "screens.get": MethodSpec(_get_handler, _path_arg),
}
