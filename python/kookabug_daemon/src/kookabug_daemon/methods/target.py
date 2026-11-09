"""`target.capture/load_image/open/preview/save/read_text` (M2 계획 2.4·2.9 T6, M4 T11).

- 정지 화면은 daemon 프레임 캐시(`frames`)에 두고, 보일 PNG는 편집기 캐시(`image_cache`)에 쓴다
- 권한 대표 인자는 링크를 해석한 경로다: `target.open`·`target.save`는 target 파일,
  `target.load_image`는 그 PNG, `target.preview`는 `base_path`(없으면 "")
- 미리보기·저장 규칙은 `targets` 모듈 설명. 점수·배율·방법은 `Vision.find` 그대로다
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Final

from kookabug_core import basis, forbidden
from kookabug_core.canonical import loads_strict, save_text
from kookabug_core.knowledge.formats import Actor, KnowledgeError
from kookabug_core.workspace import Workspace
from kookabug_daemon.documents import RUNS_NAME, WsPath, resolve_path
from kookabug_daemon.frames import EditorFrame, FrameCache
from kookabug_daemon.methods import Call, Handler, MethodSpec
from kookabug_daemon.methods.adopt import failed
from kookabug_daemon.methods.graph import request_int
from kookabug_daemon.methods.tools import agent_use_safe_api
from kookabug_daemon.methods.windows import (  # noqa: F401 — RealSource가 이 이름으로 찾는다
    capture_window,
)
from kookabug_daemon.methods.working import refuse_policy_path, working_actor
from kookabug_daemon.protocol import InvalidParams, RequestFailed
from kookabug_daemon.screen_source import Grab
from kookabug_daemon.targets import read_bytes, require_platform, target_path

__all__ = ["IMAGE_SUFFIX", "METHODS", "image_path", "new_frame"]

IMAGE_SUFFIX: Final = ".png"
SCREEN_TARGETS: Final = "targets/screens/"
"""확정 화면 지도의 target 자리 (승격이 쓴다)."""


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


def new_frame(
    call: Call,
    pixels: Any,
    client_size: tuple[int, int],
    dpi: int,
    *,
    grab: Grab | None = None,
) -> EditorFrame:
    """정지 화면을 캐시에 넣는다 (막히는 호출). 사람 연결이면 PNG를 편집기 캐시에 쓴다.

    에이전트 연결이 만든 정지 화면은 **디스크에 쓰지 않는다**(픽셀은 메모리 캐시만, M7 3.5a) —
    이미지가 나가는 출구는 보호 판정(`frame_guard`)을 거친 agent 캐시뿐이다. 창 캡처(`grab`)면 창
    바인딩과 캡처 시점 판정을 프레임에 둔다(R1)."""
    from kookabug_platform.frames import encode_png

    pixels.setflags(write=False)
    frame_id = FrameCache.new_id()
    frame = EditorFrame(
        frame_id,
        pixels,
        client_size,
        max(1, dpi),
        f"{frame_id}.png",
        owner=call.connection,
        window=grab is not None,
        binding=None if grab is None else grab.binding,
    )
    if call.principal.kind == "agent":
        frame = replace(frame, guard=call.daemon.guard.check(frame))
    else:
        call.daemon.image_cache.put(frame.cache, encode_png(pixels))
    call.daemon.frames.add(frame)
    return frame


def _capture(call: Call) -> dict[str, Any]:
    grab = call.daemon.screen_source.capture(request_int(call.params["window"]))
    frame = new_frame(call, grab.pixels, grab.client_size, grab.dpi, grab=grab)
    result = frame.to_json()
    if call.principal.kind == "agent":
        assert frame.guard is not None
        if not frame.guard.clear:
            # 보호 중: 이미지는 어디에도 쓰지 않고 사유·안내만 (탐색을 이어 가게)
            result["protected"] = frame.guard.to_json()
            return result
        # MCP 이미지 내용: 긴 변 1568·1 MiB 이하로 줄여 에이전트 캐시에 (M5 3.2, 편집기 캐시와 나눔)
        from kookabug_daemon.agent_cache import AgentCache, shrink_png
        from kookabug_platform.frames import encode_png

        png, width, height = shrink_png(encode_png(frame.pixels))
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
    actor = working_actor(call)
    if actor is not None:
        # 작업 기준 연결은 자기 작업 기준 사본을 본다 (M8 3.6, `graph.open`과 같은 규칙). revision은
        # 사본의 것이라 다음 `target.save`의 base_revision과 맞는다. 사본이 없으면 팀 파일
        _, change = await asyncio.to_thread(
            basis.view, call.daemon.root, where.rel, job=actor.job, agent=actor.id
        )
        if change is not None:
            copy_where = target_path(call.daemon.root, basis.copy_rel(change.id, where.rel))
            return await asyncio.to_thread(call.daemon.targets.open, copy_where)
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

    if call.principal.kind == "agent":
        # 사라진 창의 정지 화면은 먼저 버린다 (M7 R1 — 그 뒤 frame_expired)
        call.daemon.guard.sweep()
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
    if call.principal.kind == "agent":
        # 보호 판정 (M7 3.5a): 민감 target(sensitive_region)·비밀값을 입력한 창(frame_protected)
        call.daemon.guard.require_clear(frame)
        return call.daemon.targets.read_text(frame_id, rect)
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
    frame = _agent_frame(call, str(crop["frame_id"]))
    if call.principal.kind == "agent":
        _guard_crop(call, frame, crop["rect"])
    return crop


def _guard_crop(call: Call, frame: EditorFrame, rect: Any) -> None:
    """에이전트 crop (`kb_target_create{frame_id}`, M7 3.5a): 보호 판정이 `clear`인 프레임만, 그리고
    그 창의 알려진 비밀값 칸 상자와 겹치면 거부 (녹화기 `ProtectionSet.require_clear` — 안전 확인
    직후 경계 이중 방어)."""
    from kookabug_core.recorder.protect import SecretRegionOverlap
    from kookabug_daemon.frames import check_rect

    guard = call.daemon.guard
    guard.require_clear(frame)
    box = check_rect(frame, [request_int(v) for v in rect], what="잘라 낼 영역")
    protection = guard.protection_set(frame)
    if protection is None:
        return
    try:
        protection.require_clear((box[0], box[1], box[2], box[3]), None, frame.pixels)
    except SecretRegionOverlap as exc:
        raise RequestFailed(
            "frame_protected",
            "비밀값을 입력한 칸과 겹치는 영역은 자르지 않아요",
            reason="secret_field",
        ) from exc


async def _save(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    where = target_path(call.daemon.root, str(params["path"]), save=True)
    seen = [rel.replace("\\", "/").casefold() for rel in (where.given, where.rel)]
    with contextlib.suppress(forbidden.UnresolvablePath):
        # 정션 별칭으로 가리킨 화면 지도 자리도 같은 자리다 (풀 수 없으면 아래 경로 검사가 거부)
        seen.append(forbidden.real_key(call.daemon.root, where.rel))
    if call.principal.kind == "agent" and any(rel.startswith(SCREEN_TARGETS) for rel in seen):
        # 확정 화면 지도의 target 자리는 사람의 승격만 쓴다 (M7 3.7 — 에이전트는 탐색 세션 폴더)
        raise RequestFailed(
            "permission_denied",
            "targets/screens/는 화면 지도 승격(사람) 자리라 에이전트가 쓰지 않는다",
        )
    refuse_policy_path(call, where.given, where.rel)
    base: Any = params["base_revision"]
    crop = await asyncio.to_thread(_save_crop, call)
    actor = working_actor(call)
    if actor is not None:
        return await asyncio.to_thread(
            _save_working, call, where, actor, crop, None if base is None else str(base)
        )
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


def _view_revision(json_bytes: bytes | None, png: bytes | None) -> str | None:
    if json_bytes is None:
        return None
    image = "missing" if png is None else hashlib.sha256(png).hexdigest()
    return f"{hashlib.sha256(json_bytes).hexdigest()}:{image}"


def _save_working(
    call: Call,
    where: WsPath,
    actor: Actor,
    crop: Mapping[str, Any] | None,
    base_revision: str | None,
) -> dict[str, Any]:
    """작업 기준 target 쓰기 (E3·R4, 막히는 호출): 팀 파일은 읽기만 한다. 이미지 이름은 지금 보기의
    `image`(제자리 수리 — 같은 경로의 PNG 바이트만 바뀐다), 없으면 `<이름>.png`. 쓰기 전에 그 정지
    화면에서 바로 찾아지는지 본다(팀 저장과 같은 규칙)."""
    from kookabug_core.adopt import image_rel
    from kookabug_daemon.targets import (
        _check_spec,  # pyright: ignore[reportPrivateUsage]
        _crop_image,  # pyright: ignore[reportPrivateUsage]
        _fill_defaults,  # pyright: ignore[reportPrivateUsage]
        _fill_frame,  # pyright: ignore[reportPrivateUsage]
    )
    from kookabug_platform.frames import encode_png

    root = call.daemon.root
    params = call.params
    data, _ = basis.view(root, where.rel, job=actor.job, agent=actor.id)
    current: dict[str, Any] | None = None
    text: str | None = None
    if data is not None:
        text = data.decode("utf-8", errors="replace")
        parsed = loads_strict(text)
        current = parsed if isinstance(parsed, dict) else None
    old_image = None if current is None else image_rel(where.rel, current)
    png_now = None
    if old_image is not None:
        png_now, _ = basis.view(root, old_image, job=actor.job, agent=actor.id)
    revision = _view_revision(data, png_now)
    if base_revision is None and data is not None:
        raise RequestFailed("exists", f"'{where.given}'이(가) 이미 있다", revision=revision)
    if base_revision is not None and revision != base_revision:
        raise RequestFailed(
            "revision_conflict",
            "target이 밖에서 바뀌었다 (작업 기준 보기가 기준 revision과 다르다)",
            revision=revision,
        )
    stem = where.path.name[: -len(".target.json")]
    name = str(current["image"]) if current is not None and "image" in current else f"{stem}.png"
    # 제자리 수리는 지금 보기의 `image`(다른 target과 함께 쓰는 PNG일 수 있다)를 덮는다: 그 PNG가
    # 금지 판정이 읽는 파일이면 쓰지 않는다 (옆 경로 — target 경로 검사만으로는 안 막힌다)
    written = image_rel(where.rel, {"image": name})
    if written is None:
        raise RequestFailed("target_invalid", "target image 경로가 틀렸다", diagnostics=[])
    refuse_policy_path(call, written)
    value = _fill_defaults(params["spec"], name)
    files: dict[str, bytes] = {}
    preview: Any = None
    if crop is not None:
        frame = call.daemon.frames.get(str(crop["frame_id"]))
        pixels, _ = _crop_image(frame, crop["rect"])
        _check_spec(value, where.rel)
        _fill_frame(value, frame)
        png = bytes(encode_png(pixels))
        preview = call.daemon.targets._expected_preview(where, value, frame, png)  # pyright: ignore[reportPrivateUsage]
        image = image_rel(where.rel, value)
        if image is None:
            raise RequestFailed("target_invalid", "target image 경로가 틀렸다", diagnostics=[])
        files[image] = png
    else:
        if current is None or png_now is None:
            raise RequestFailed(
                "target_invalid", "새 target은 crop(템플릿 영역)이 있어야 한다", diagnostics=[]
            )
        if current.get("recorded") is not None:
            value["recorded"] = copy.deepcopy(current["recorded"])
        else:
            value.pop("recorded", None)
        _check_spec(value, where.rel)
        png = png_now
    out = save_text(text, value).encode("utf-8")
    files[where.rel] = out
    expect = {where.rel: None if data is None else hashlib.sha256(data).hexdigest()}
    try:
        doc = basis.write(root, files, actor=actor, kind="target", expect=expect)
    except KnowledgeError as exc:
        raise failed(exc) from exc
    image = image_rel(where.rel, value) or name
    return {
        "image": image,
        "revision": _view_revision(out, png),
        "preview": preview,
        "warnings": [],
        "basis": "working",
        "change": str(doc["id"]),
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
