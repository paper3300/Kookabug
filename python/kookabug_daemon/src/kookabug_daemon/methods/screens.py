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
from kookabug_core.workspace import Workspace
from kookabug_daemon.documents import resolve_path
from kookabug_daemon.frames import EditorFrame
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.protocol import InvalidParams, RequestFailed
from kookabug_daemon.targets import require_platform
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


# ---------------------------------------------------------------- M7 저장·식별 (3.5·3.6)


def _frame(call: Call) -> EditorFrame:
    from kookabug_daemon.methods.target import (
        _agent_frame,  # pyright: ignore[reportPrivateUsage]
    )

    return _agent_frame(call, str(call.params["frame_id"]))


def _save(call: Call) -> dict[str, Any]:
    from kookabug_daemon.screen_save import save

    if call.principal.kind != "agent":
        raise RequestFailed("agent_only", "화면 지도 저장은 에이전트 탐색 세션만 한다")
    session = call.daemon.explore.require(call.connection)
    result = save(call, _frame(call), session)
    call.daemon.explore.changed()
    return result


def _identify(call: Call) -> dict[str, Any]:
    from kookabug_daemon.screen_save import identify

    session = call.daemon.explore.get(call.connection)
    return identify(call.daemon, _frame(call), session)


async def _save_handler(call: Call) -> dict[str, Any]:
    require_platform()
    return await asyncio.to_thread(_save, call)


async def _identify_handler(call: Call) -> dict[str, Any]:
    require_platform()
    return await asyncio.to_thread(_identify, call)


# ------------------------------------------------------- M7 B4 지도·확인·승격·버리기 (3.3·3.7)

THUMB_SIDE: Final = 320
"""썸네일 긴 변 (사람 화면 카드)."""


def _thumb(call: Call) -> Any:
    """대표 스크린샷 경로 → 편집기 캐시의 썸네일 이름 (사람 연결만, C8). 에이전트는 None."""
    if call.principal.kind == "agent":
        return None
    root: Path = call.daemon.root
    cache = call.daemon.image_cache

    def make(rel: str) -> str | None:
        import hashlib

        try:
            path = resolve_path(root, rel).path
            stat = path.stat()
        except RequestFailed, InvalidParams, OSError:
            return None
        stamp = f"{rel}|{stat.st_size}|{stat.st_mtime_ns}".encode()
        name = f"map_{hashlib.sha256(stamp).hexdigest()[:24]}.png"
        if cache.path_of(name).is_file():
            return name
        try:
            cache.put(name, _shrink(path.read_bytes()))
        except Exception:  # 깨진 PNG·캐시 쓰기 실패: 썸네일 없이
            return None
        return name

    return make


def _shrink(data: bytes) -> bytes:
    import cv2
    import numpy as np

    from kookabug_platform.frames import encode_png

    pixels = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if pixels is None:
        raise ValueError("PNG가 아니다")
    height, width = pixels.shape[:2]
    side = max(width, height)
    if side > THUMB_SIDE:
        scale = THUMB_SIDE / side
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        pixels = cv2.resize(pixels, size, interpolation=cv2.INTER_AREA)
    return encode_png(np.asarray(pixels, dtype=np.uint8))


def _map(call: Call) -> dict[str, Any]:
    from kookabug_core.screen_map import build_map

    root = call.daemon.root
    sessions = call.daemon.explore.listing(Workspace.open(root))
    return build_map(root, sessions=sessions, thumb=_thumb(call))


def _request(call: Call) -> Any:
    from kookabug_core.screen_promote import PromoteRequest

    p = call.params
    return PromoteRequest(
        session=str(p["session"]),
        key=str(p["key"]),
        mode=p.get("mode", "new"),
        id=p.get("id"),
        title=p.get("title"),
        description=p.get("description"),
        folder=p.get("folder"),
        replace_shot=bool(p.get("replace_shot", False)),
        replace_detect=bool(p.get("replace_detect", False)),
        base_revisions=dict(p.get("base_revisions") or {}),
    )


def _failed(exc: Any) -> RequestFailed:
    return RequestFailed(exc.code, exc.message, **exc.fields)


def _check(call: Call) -> dict[str, Any]:
    from kookabug_core.screen_promote import PromoteError, check

    try:
        result = check(call.daemon.root, _request(call))
    except PromoteError as exc:
        raise _failed(exc) from exc
    if result["ok"]:
        _check_images(call, result)
    return result


def _check_images(call: Call, result: dict[str, Any]) -> None:
    """후보 판정 조건을 그 대표 스크린샷(기록 크기로 되돌림)에서 평가 — 맞아야 한다. 스크린샷 있는
    확정 화면에서도 평가해 맞으면 경고 (같은 화면일 수 있다)."""
    from kookabug_core.screens import ScreenDef, ScreenFileError, read_screen_file, screen_index

    root: Path = call.daemon.root
    session, key = str(call.params["session"]), str(call.params["key"])
    rel = f"{SCREENS_DIR}/{EXPLORED_DIR}/{session}/{key}{SUFFIX}"
    try:
        candidate = read_screen_file(resolve_path(root, rel).path, rel)
    except ScreenFileError, RequestFailed, InvalidParams:
        return
    if not candidate.detect():
        result["shot"] = "none"
        return
    try:
        from kookabug_daemon.screen_save import _loader, _reader  # pyright: ignore[reportPrivateUsage]

        load, reader = _loader(root), _reader(call.daemon)
    except Exception as exc:  # 플랫폼 없음: 이미지 확인 없이
        result["warnings"].append(
            f"판정 조건을 스크린샷에서 확인하지 못했다 ({type(exc).__name__})"
        )
        return

    def evaluate(screen: ScreenDef, shot_rel: str, size: tuple[int, int]) -> str | None:
        from kookabug_platform.screens import evaluate_screen
        from kookabug_platform.vision import FrameMeta, Vision

        try:
            pixels = _restore(resolve_path(root, shot_rel).path.read_bytes(), size)
            meta = FrameMeta(size, 96, backend="editor")
            return evaluate_screen(screen, load, pixels, meta, Vision(), ocr=reader).state
        except Exception:
            return None

    if candidate.shot is None:
        result["shot"] = "none"
        result["warnings"].append("대표 스크린샷이 없어 판정 조건을 확인하지 못했다")
    else:
        state = evaluate(candidate, candidate.shot.image, candidate.shot.client_size)
        result["shot"] = state or "unknown"
        if state == "not_matched":
            result["ok"] = False
            result["problems"].append("후보 판정 조건이 자기 대표 스크린샷에서 맞지 않는다")
        elif state != "matched":
            result["warnings"].append("후보 판정 조건을 자기 대표 스크린샷에서 확인하지 못했다")
    for sid, paths in sorted(screen_index(Workspace.open(root)).items()):
        if len(paths) != 1:
            continue
        try:
            other = read_screen_file(resolve_path(root, paths[0]).path, paths[0])
        except ScreenFileError, RequestFailed, InvalidParams:
            continue
        if other.shot is None or (sid == result.get("id") and call.params.get("mode") == "merge"):
            continue
        if evaluate(candidate, other.shot.image, other.shot.client_size) == "matched":
            result["warnings"].append(f"후보 판정 조건이 확정 화면 '{sid}'의 스크린샷에서도 맞는다")


def _restore(data: bytes, size: tuple[int, int]) -> Any:
    import cv2
    import numpy as np

    pixels = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if pixels is None:
        raise ValueError("PNG가 아니다")
    if (pixels.shape[1], pixels.shape[0]) != size:
        pixels = cv2.resize(pixels, size, interpolation=cv2.INTER_LINEAR)
    return np.asarray(pixels, dtype=np.uint8)


def _promote(call: Call) -> dict[str, Any]:
    from kookabug_core.screen_promote import PromoteError, promote

    try:
        result = promote(call.daemon.root, _request(call))
    except PromoteError as exc:
        raise _failed(exc) from exc
    call.daemon.explore.changed()
    call.daemon.screens_changed()
    return result


def _discard(call: Call) -> dict[str, Any]:
    from kookabug_core.screen_promote import PromoteError, discard

    key = call.params.get("key")
    try:
        removed = discard(
            call.daemon.root,
            str(call.params["session"]),
            None if key is None else str(key),
            active=call.daemon.explore.live_ids(),
        )
    except PromoteError as exc:
        raise _failed(exc) from exc
    call.daemon.explore.changed()
    call.daemon.screens_changed()
    return {"removed": removed}


# ------------------------------------------------------- M7 B5 카드 배치 (3.8, 사람만)

LAYOUT_FILE: Final = (".kookabug", "screen-map.json")
LAYOUT_FORMAT: Final = "kookabug.screen-map/0"
LAYOUT_MAX_BYTES: Final = 1024 * 1024


def _layout_revision(data: bytes | None) -> str | None:
    import hashlib

    return None if data is None else hashlib.sha256(data).hexdigest()[:16]


def _layout_read(root: Path) -> tuple[dict[str, Any], bytes | None]:
    path = root.joinpath(*LAYOUT_FILE)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return {}, None
    except OSError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
    try:
        value = loads_strict(data.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        return (
            {},
            data,
        )  # 깨진 배치는 빈 배치로 본다 (다음 저장이 덮는다 — revision은 그대로 맞춘다)
    layout = value.get("layout") if isinstance(value, dict) else None
    return (layout if isinstance(layout, dict) else {}), data


def _check_layout(layout: Any) -> dict[str, Any]:
    """카드 자리 `{positions: {노드: [x, y]}, zoom?}`만 받는다."""
    if not isinstance(layout, dict) or set(layout) - {"positions", "zoom"}:
        raise InvalidParams("layout은 {positions, zoom?}이다")
    positions = layout.get("positions", {})
    if not isinstance(positions, dict):
        raise InvalidParams("layout.positions는 노드 → [x, y]다")
    for node, xy in positions.items():
        ok = (
            isinstance(node, str)
            and 0 < len(node) <= 200
            and isinstance(xy, list)
            and len(xy) == 2
            and all(
                isinstance(v, int | float) and not isinstance(v, bool) and abs(v) < 1e6 for v in xy
            )
        )
        if not ok:
            raise InvalidParams(f"layout.positions[{node!r}]는 [x, y] 숫자다")
    zoom = layout.get("zoom")
    if zoom is not None and (
        isinstance(zoom, bool) or not isinstance(zoom, int | float) or not 0.1 <= zoom <= 4
    ):
        raise InvalidParams("layout.zoom은 0.1~4다")
    return {"positions": positions, **({"zoom": zoom} if zoom is not None else {})}


def _layout_get(call: Call) -> dict[str, Any]:
    layout, data = _layout_read(call.daemon.root)
    return {"layout": layout, "revision": _layout_revision(data)}


def _layout_set(call: Call) -> dict[str, Any]:
    import json

    from kookabug_core.documents import DocumentError, write_atomic

    root: Path = call.daemon.root
    layout = _check_layout(call.params["layout"])
    body = json.dumps({"format": LAYOUT_FORMAT, "layout": layout}, ensure_ascii=False).encode(
        "utf-8"
    )
    if len(body) > LAYOUT_MAX_BYTES:
        raise InvalidParams("화면 지도 배치가 너무 크다")
    path = root.joinpath(*LAYOUT_FILE)
    _, current = _layout_read(root)
    base = call.params.get("base_revision")
    if base != _layout_revision(current):
        raise RequestFailed(
            "revision_conflict",
            "화면 지도 배치가 다른 곳에서 바뀌었다",
            revision=_layout_revision(current),
        )
    path.parent.mkdir(parents=True, exist_ok=True)

    def unchanged() -> None:
        now = path.read_bytes() if path.exists() else None
        if _layout_revision(now) != _layout_revision(current):
            raise RequestFailed("revision_conflict", "화면 지도 배치가 다른 곳에서 바뀌었다")

    try:
        write_atomic(path, body, before_replace=unchanged)
    except DocumentError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
    return {"layout": layout, "revision": _layout_revision(body)}


def _threaded(fn: Any) -> Any:
    async def handler(call: Call) -> dict[str, Any]:
        return await asyncio.to_thread(fn, call)

    return handler


METHODS: Final = {
    "screens.list": MethodSpec(_list_handler, _list_arg),
    "screens.get": MethodSpec(_get_handler, _path_arg),
    "screens.save": MethodSpec(_save_handler),
    "screens.identify": MethodSpec(_identify_handler),
    "screens.map": MethodSpec(_threaded(_map)),
    "screens.check": MethodSpec(_threaded(_check)),
    "screens.promote": MethodSpec(_threaded(_promote)),
    "screens.discard": MethodSpec(_threaded(_discard)),
    "screens.layout_get": MethodSpec(_threaded(_layout_get)),
    "screens.layout_set": MethodSpec(_threaded(_layout_set)),
}
