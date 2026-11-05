"""`target.capture/load_image/open/preview/save/read_text` (M2 계획 2.4·2.9 T6, M4 T11).

- 정지 화면은 daemon 프레임 캐시(`frames`)에 두고, 보일 PNG는 편집기 캐시(`image_cache`)에 쓴다
- 권한 대표 인자는 링크를 해석한 경로다: `target.open`·`target.save`는 target 파일,
  `target.load_image`는 그 PNG, `target.preview`는 `base_path`(없으면 "")
- 미리보기·저장 규칙은 `targets` 모듈 설명. 점수·배율·방법은 `Vision.find` 그대로다
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Final

from kookabug_daemon.documents import WsPath, resolve_path
from kookabug_daemon.frames import EditorFrame, FrameCache
from kookabug_daemon.methods import Call, Handler, MethodSpec
from kookabug_daemon.methods.graph import request_int
from kookabug_daemon.methods.windows import capture_window
from kookabug_daemon.protocol import InvalidParams, RequestFailed
from kookabug_daemon.targets import read_bytes, require_platform, target_path

__all__ = ["IMAGE_SUFFIX", "METHODS", "image_path", "new_frame"]

IMAGE_SUFFIX: Final = ".png"


def image_path(call: Call, key: str = "path") -> WsPath:
    """정지 화면으로 열 PNG (워크스페이스·실행 폴더). `.kookabug/`·루트 밖은 거부."""
    given = str(call.params[key])
    where = resolve_path(call.daemon.root, given)
    if not (
        given.casefold().endswith(IMAGE_SUFFIX)
        and where.path.name.casefold().endswith(IMAGE_SUFFIX)
    ):
        raise InvalidParams(f"'{given}'은(는) PNG 파일이 아니다", path=given)
    return where


def new_frame(call: Call, pixels: Any, client_size: tuple[int, int], dpi: int) -> EditorFrame:
    """정지 화면을 캐시에 넣고 PNG를 편집기 캐시에 쓴다 (막히는 호출)."""
    from kookabug_platform.frames import encode_png

    pixels.setflags(write=False)
    frame_id = FrameCache.new_id()
    frame = EditorFrame(frame_id, pixels, client_size, max(1, dpi), f"{frame_id}.png")
    call.daemon.image_cache.put(frame.cache, encode_png(pixels))
    call.daemon.frames.add(frame)
    return frame


def _capture(call: Call) -> dict[str, Any]:
    import numpy as np

    captured = capture_window(request_int(call.params["window"]))
    pixels = np.ascontiguousarray(captured.pixels)
    info = captured.info
    return new_frame(call, pixels, info.client_size, info.dpi).to_json()


def _load_image(call: Call, where: WsPath) -> dict[str, Any]:
    import numpy as np

    from kookabug_platform.frames import decode_image

    data = read_bytes(where.path)
    if data is None:
        raise RequestFailed("not_found", f"'{where.given}'이(가) 없다", path=where.given)
    try:
        pixels = np.array(decode_image(data), copy=True)
    except ValueError as exc:
        text = f"'{where.given}'을(를) 이미지로 읽을 수 없다: {exc}"
        raise RequestFailed("target_image_invalid", text, message=text) from exc
    size = (int(pixels.shape[1]), int(pixels.shape[0]))
    return new_frame(call, pixels, size, 96).to_json()


async def _capture_handler(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_capture, call)


async def _load_image_handler(call: Call) -> dict[str, Any]:
    where = image_path(call)
    return await asyncio.to_thread(_load_image, call, where)


async def _open(call: Call) -> dict[str, Any]:
    where = target_path(call.daemon.root, str(call.params["path"]))
    return await asyncio.to_thread(call.daemon.targets.open, where)


def _preview_base(call: Call) -> WsPath | None:
    base = call.params.get("base_path")
    return None if base is None else resolve_path(call.daemon.root, str(base))


async def _preview(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    return await asyncio.to_thread(
        call.daemon.targets.preview,
        str(params["frame_id"]),
        params["spec"],
        params["template"],
        _preview_base(call),
        request_int(params["seq"]),
        [float(f) for f in params.get("scales") or ()],
    )


def _read_text(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    frame_id = str(params["frame_id"])
    rect = [request_int(v) for v in params["rect"]]
    # 녹화 세션이 올린 정지 화면이면 그 프레임의 보호 영역(비밀번호 칸)과 겹치는 영역은 읽지 않는다
    recorder = getattr(call.daemon, "recorder", None)
    if recorder is not None:
        recorder.check_read_region(frame_id, rect)
    return call.daemon.targets.read_text(frame_id, rect)


async def _read_text_handler(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_read_text, call)


async def _save(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    where = target_path(call.daemon.root, str(params["path"]), save=True)
    base: Any = params["base_revision"]
    outcome = await asyncio.to_thread(
        call.daemon.targets.save,
        where,
        params["spec"],
        params.get("crop"),
        None if base is None else str(base),
    )
    return {
        "image": outcome.image,
        "revision": outcome.revision,
        "preview": outcome.preview,
        "warnings": outcome.warnings,
    }


def _target_arg(call: Call) -> str:
    return target_path(call.daemon.root, str(call.params["path"])).rel


def _save_arg(call: Call) -> str:
    return target_path(call.daemon.root, str(call.params["path"]), save=True).rel


def _image_arg(call: Call) -> str:
    return image_path(call).rel


def _preview_arg(call: Call) -> str:
    base = _preview_base(call)
    return "" if base is None else base.rel


def _needs_platform(handler: Handler) -> Handler:
    """kookabug-platform이 없으면 처리기 전에 `platform_unavailable` (선택 설치, `targets`)."""

    async def run(call: Call) -> dict[str, Any]:
        require_platform()
        return await handler(call)

    return run


METHODS: Final = {
    "target.capture": MethodSpec(_needs_platform(_capture_handler)),
    "target.load_image": MethodSpec(_needs_platform(_load_image_handler), _image_arg),
    "target.open": MethodSpec(_needs_platform(_open), _target_arg),
    "target.preview": MethodSpec(_needs_platform(_preview), _preview_arg),
    "target.read_text": MethodSpec(_needs_platform(_read_text_handler)),
    "target.save": MethodSpec(_needs_platform(_save), _save_arg),
}
