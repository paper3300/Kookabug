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

from kookabug_core.workspace import Workspace
from kookabug_daemon.documents import RUNS_NAME, WsPath, resolve_path
from kookabug_daemon.frames import EditorFrame, FrameCache
from kookabug_daemon.methods import Call, Handler, MethodSpec
from kookabug_daemon.methods.graph import request_int
from kookabug_daemon.methods.tools import agent_use_safe_api
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
    frame = EditorFrame(
        frame_id, pixels, client_size, max(1, dpi), f"{frame_id}.png", owner=call.connection
    )
    call.daemon.image_cache.put(frame.cache, encode_png(pixels))
    call.daemon.frames.add(frame)
    return frame


def _capture(call: Call) -> dict[str, Any]:
    import numpy as np

    captured = capture_window(request_int(call.params["window"]))
    pixels = np.ascontiguousarray(captured.pixels)
    info = captured.info
    frame = new_frame(call, pixels, info.client_size, info.dpi)
    result = frame.to_json()
    if call.principal.kind == "agent":
        # MCP 이미지 내용: 긴 변 1568·1 MiB 이하로 줄여 에이전트 캐시에 (M5 3.2, 편집기 캐시와 나눔)
        from kookabug_daemon.agent_cache import AgentCache, shrink_png
        from kookabug_platform.frames import encode_png

        png, width, height = shrink_png(encode_png(pixels))
        name = AgentCache(call.daemon.root).put(call.connection, png)
        result["agent_image"] = {"cache": name, "width": width, "height": height}
    return result


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


def _deny_agent_runs(call: Call, where: WsPath) -> None:
    """에이전트 연결은 `runs/` 아래 이미지를 정지 화면으로 열지 못한다 — 실행 증거는 비밀값 분류를
    지나는 `run.artifact{as_frame}`로만 (M5 3.5 H2)."""
    if call.principal.kind != "agent":
        return
    for rel in (where.given, where.rel):
        first = rel.replace("\\", "/").split("/", 1)[0].casefold()
        if first == RUNS_NAME.casefold():
            raise agent_use_safe_api(f"{call.method}의 runs/ 경로")


async def _load_image_handler(call: Call) -> dict[str, Any]:
    where = image_path(call)
    _deny_agent_runs(call, where)
    return await asyncio.to_thread(_load_image, call, where)


async def _open(call: Call) -> dict[str, Any]:
    where = target_path(call.daemon.root, str(call.params["path"]))
    return await asyncio.to_thread(call.daemon.targets.open, where)


def _preview_base(call: Call) -> WsPath | None:
    base = call.params.get("base_path")
    return None if base is None else resolve_path(call.daemon.root, str(base))


async def _preview(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    _agent_frame(call, str(params["frame_id"]))
    template: Any = params["template"]
    crop: Any = template.get("crop")
    if crop is not None:
        _agent_frame(call, str(crop["frame_id"]))
    elif call.principal.kind == "agent":
        base = _preview_base(call)
        rel = Workspace.resolve_from(base.rel if base is not None else "", str(template["image"]))
        if rel is not None:
            _deny_agent_runs(call, resolve_path(call.daemon.root, rel))
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
    result = call.daemon.targets.read_text(frame_id, rect)
    if recorder is not None:
        # 보호 영역 밖에 다시 보인 비밀값 원문도 응답으로 내보내지 않는다 (B5 검수 2차 High)
        recorder.check_read_result(result)
    return result


async def _read_text_handler(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_read_text, call)


def _agent_frame(call: Call, frame_id: str) -> EditorFrame:
    """정지 화면. 에이전트 연결이면 (M5 3.8, B2 검수 H2):
    녹화 세션 프레임(비밀번호가 찍힐 수 있는 임시 화면)은 `recorder_frame`, 다른 연결(UI 등)이
    만든 프레임은 `frame_not_owned`, 실행 증거에서 연 프레임은 그 파일의 분류를 다시 본다."""
    from kookabug_daemon.methods.run_agent import recheck_source

    frame = call.daemon.frames.get(frame_id)
    if call.principal.kind != "agent":
        return frame
    if frame.origin == "recorder":
        raise RequestFailed("recorder_frame", "녹화 세션의 화면은 에이전트가 쓸 수 없다")
    if frame.owner != call.connection:
        raise RequestFailed(
            "frame_not_owned",
            f"정지 화면 {frame_id}은(는) 이 연결이 만든 것이 아니다 "
            "(kb_screen_capture로 다시 얻는다)",
        )
    recheck_source(call, frame)
    return frame


def _screen_read_text(call: Call) -> dict[str, Any]:
    """`screen.read_text` (`kb_ocr_read`, M5 3.3·3.8): 지금 정지 화면의 글자. 녹화 프레임은 받지
    않고(사람용 `target.read_text`와 다름), `sensitive: true` target이 그 화면 어디에든 보이면
    `sensitive_region`으로 거부한다(B2 검수 H3 — 영역과 상관없이). 민감 target을 확인하지
    못해도(읽기·판정 실패) 거부한다(H5, fail closed). 에이전트는 자기 연결이 만든
    정지 화면만 쓴다(H2). 지금 화면은 기록이 아니라 가리지 않는다."""
    params: Mapping[str, Any] = call.params
    frame_id = str(params["frame_id"])
    frame = _agent_frame(call, frame_id)
    if frame.origin == "recorder":
        raise RequestFailed("recorder_frame", "녹화 세션의 화면은 이 메서드로 읽지 않는다")
    given = params.get("rect")
    rect = (
        [request_int(v) for v in given] if given is not None else [0, 0, frame.width, frame.height]
    )
    hit = call.daemon.targets.sensitive_visible(frame)
    if hit is not None:
        text = (
            f"민감 target을 확인하지 못함 ('{hit.path}'을(를) 읽거나 판정할 수 없다) — 읽지 않는다"
            if hit.failed
            else f"민감 target '{hit.path}'이(가) 보이는 화면이라 읽지 않는다"
        )
        raise RequestFailed("sensitive_region", text, path=hit.path)
    return call.daemon.targets.read_text(frame_id, rect)


async def _screen_read_text_handler(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_screen_read_text, call)


def _save_crop(call: Call) -> Mapping[str, Any] | None:
    """`crop`의 정지 화면. 실행 증거 출처(`{run_id, file, rect}`)면 에이전트용 분류를 지난 이미지만
    정지 화면으로 열어 `{frame_id, rect}`로 바꾼다 (`kb_target_create{run, file}`, M5 3.3)."""
    from kookabug_daemon.methods.run_agent import artifact_frame

    crop: Any = call.params.get("crop")
    if crop is None:
        return None
    if "run_id" in crop:
        frame = artifact_frame(call, str(crop["run_id"]), str(crop["file"]))
        return {"frame_id": frame.frame_id, "rect": list(crop["rect"])}
    _agent_frame(call, str(crop["frame_id"]))
    return crop


async def _save(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    where = target_path(call.daemon.root, str(params["path"]), save=True)
    base: Any = params["base_revision"]
    crop = await asyncio.to_thread(_save_crop, call)
    outcome = await asyncio.to_thread(
        call.daemon.targets.save,
        where,
        params["spec"],
        crop,
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
    "screen.read_text": MethodSpec(_needs_platform(_screen_read_text_handler)),
}
