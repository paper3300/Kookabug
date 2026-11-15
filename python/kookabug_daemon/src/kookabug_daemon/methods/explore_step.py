"""`explore.step` (`kb_explore_step`, UX7 C): 탐색 한 걸음.

입력 하나(점·target 클릭, 키, 글자·비밀값, 또는 없음) → 화면이 바뀌고 멈추기를 기다림 → 캡처 →
화면 판별 → 탐색 세션이 열려 있으면 이동 자동 기록. 입력은 `kb_input_*`와 **같은 제어 실행 경로**
(`control.send_input` — 권한·금지 동작·입력 임대권·비밀값 보호 기록·탐색 스텝 예산)다. 캡처는
`kb_screen_capture`와 같은 보호 판정을 지난 축소 이미지만, 판별은 `kb_screen_identify`와 같다.

- 기다림: 입력 직전 프레임과 비교해 바뀐 뒤 0.5초 동안 차이가 작으면 끝. 바뀐 뒤 3초가 지나도 계속
  움직이면(배경 애니메이션 등) 그때 끝. 상한 `wait_ms`(입력이 있으면 기본 10초, 없으면 0, 최대
  60초). 안 바뀌면 그대로 캡처하고 `changed: false`
- 이동 기록: 출발 = 세션의 지금 화면(직전 판별·저장), 도착 = 이번 판별의 첫 화면. 점 클릭·키 입력만
  기록한다(target 클릭·글자 입력은 via가 없다). 도착이 처음 보는 화면이면 대기 이동으로 두고
  `new_screen: true` — 에이전트가 `kb_screen_save`(key)로 저장하면 그 키로 `to`를 채운다
- 창은 정확히 하나로 정해져야 한다(제목 또는 `@game`). 결과의 `window`는 준 이름(`@game`이면
  `@game`만 — 실제 제목은 권한 판정에만 쓴다)
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Final

from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods.control import (
    graph_for,
    refuse_if_denied,
    remember_target,
    resolve_target,
    send_input,
)
from kookabug_daemon.protocol import InvalidParams, RequestFailed
from kookabug_daemon.screen_source import Grab
from kookabug_daemon.targets import require_platform

__all__ = ["METHODS", "frame_change"]

DEFAULT_WAIT_MS: Final = 10_000
MAX_WAIT_MS: Final = 60_000
POLL_S: Final = 0.15
STABLE_S: Final = 0.5
SETTLE_CAP_S: Final = 3.0
"""바뀐 뒤 이만큼 지나도 멈추지 않으면(계속 움직이는 배경) 그대로 끝낸다."""
CHANGED: Final = 0.002
"""입력 직전 프레임과 다른 픽셀 비율이 이보다 크면 바뀌었다."""
STILL: Final = 0.003
"""연달은 두 프레임의 다른 픽셀 비율이 이보다 작으면 멈췄다."""
PIXEL_DELTA: Final = 24


def frame_change(a: Any, b: Any) -> float:
    """두 프레임의 다른 픽셀 비율 (0~1, 크기가 다르면 1). 4픽셀마다 하나만 본다."""
    import numpy as np

    if a.shape != b.shape:
        return 1.0
    x = np.asarray(a[::4, ::4], dtype=np.int16)
    y = np.asarray(b[::4, ::4], dtype=np.int16)
    diff = np.abs(x - y)
    moved = diff.max(axis=-1) > PIXEL_DELTA if diff.ndim == 3 else diff > PIXEL_DELTA
    return float(np.mean(moved)) if moved.size else 0.0


def _input_of(params: Mapping[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """입력 종류(`control.*`)와 그 인자. 둘 이상이면 `invalid_params`."""
    kinds: list[tuple[str, dict[str, Any]]] = []
    if "point" in params or "target" in params:
        kinds.append(
            (
                "control.click",
                {k: params[k] for k in ("point", "target", "button", "count") if k in params},
            )
        )
    if "keys" in params:
        kinds.append(("control.key", {"keys": params["keys"]}))
    if "text" in params or "secret" in params:
        kinds.append(("control.type", {k: params[k] for k in ("text", "secret") if k in params}))
    if len(kinds) > 1:
        raise InvalidParams("입력은 하나만 준다 (point·target 클릭, keys, text·secret 중 하나)")
    if not kinds:
        if "button" in params or "count" in params:
            raise InvalidParams("button·count는 point·target 클릭과 함께 준다")
        return None, {}
    return kinds[0]


def _via(
    method: str | None, params: Mapping[str, Any], size: tuple[int, int]
) -> dict[str, Any] | None:
    """이동 기록의 via (점 클릭·키만). 점은 프레임 비율로."""
    if method == "control.key":
        return {"key": str(params["keys"])}
    if method == "control.click" and params.get("point") is not None:
        x, y = (int(v) for v in params["point"])
        width, height = size
        if not (0 <= x < width and 0 <= y < height):
            return None
        return {"click": {"point": [round(x / width, 4), round(y / height, 4)]}}
    return None


async def _wait(call: Call, hwnd: int, before: Grab, wait_ms: int) -> tuple[Grab, bool, int]:
    """바뀌고 멈출 때까지 (또는 기한). (마지막 프레임, 바뀌었나, 기다린 ms)."""
    source = call.daemon.screen_source
    loop = asyncio.get_running_loop()
    start = loop.time()
    deadline = start + wait_ms / 1000
    last = before
    changed = False
    changed_at = 0.0
    still_since = 0.0
    while True:
        if loop.time() >= deadline:
            break
        await asyncio.sleep(POLL_S)
        grab = await asyncio.to_thread(source.capture, hwnd)
        now = loop.time()
        if not changed:
            if frame_change(before.pixels, grab.pixels) > CHANGED:
                changed, changed_at, still_since = True, now, now
        elif frame_change(last.pixels, grab.pixels) > STILL:
            still_since = now
        last = grab
        if changed and (now - still_since >= STABLE_S or now - changed_at >= SETTLE_CAP_S):
            break
    return last, changed, int((loop.time() - start) * 1000)


async def _step(call: Call) -> dict[str, Any]:
    from kookabug_daemon.methods.target import frame_result, new_frame
    from kookabug_daemon.screen_save import add_moves, identify

    if call.principal.kind != "agent":
        raise RequestFailed("agent_only", "탐색 한 걸음은 에이전트 연결만 쓴다")
    require_platform()
    params = call.params
    window = str(params["window"])
    method, given = _input_of(params)
    # 인자가 틀리면 판정 전에 거부 (아무것도 묻지 않음)
    value = None if method is None else graph_for(call.daemon.root, method, given, window)
    wait_ms = min(int(params.get("wait_ms", DEFAULT_WAIT_MS if method else 0)), MAX_WAIT_MS)
    target = await resolve_target(call, window)
    bindings = target.bindings or []
    if len(bindings) != 1:
        # 판정이 먼저다 (거부 정책이면 창 유무와 관계없이 permission_denied)
        await refuse_if_denied(call, target.title)
        raise RequestFailed(
            "window_not_found",
            f"창 {window!r}이(가) 없거나 여럿이다 (정확히 같은 제목의 창 하나, 또는 @game)",
        )
    hwnd = bindings[0].hwnd
    source = call.daemon.screen_source
    before = await asyncio.to_thread(source.capture, hwnd)
    done: dict[str, Any] | None = None
    if method is not None and value is not None:
        done = await send_input(call, method, given, target, value)
    else:
        # 입력 없이 기다림·캡처만도 이 도구의 판정을 지난다 (거부 정책이면 화면도 보지 않는다).
        # 판정이 허용된 뒤에만 이 창을 이 주체의 게임으로 기억한다 (입력이 있으면 send_input이)
        await call.daemon.approvals.authorize(call, target.title)
        remember_target(call, target)
    session = call.daemon.explore.get(call.connection)
    if done is not None and done.get("verdict") != "pass":
        # 입력이 들어가지 않았다: 화면은 지금 그대로, 이동은 기록하지 않는다
        last, changed, waited = before, False, 0
    elif wait_ms > 0:
        last, changed, waited = await _wait(call, hwnd, before, wait_ms)
    else:
        last = await asyncio.to_thread(source.capture, hwnd)
        changed, waited = frame_change(before.pixels, last.pixels) > CHANGED, 0
    frame = await asyncio.to_thread(
        new_frame, call, last.pixels, last.client_size, last.dpi, grab=last
    )
    shown = await asyncio.to_thread(frame_result, call, frame)
    found = await asyncio.to_thread(identify, call.daemon, frame, session)
    matches = found["matches"]
    new_screen = not matches and not found["unknown"]
    move: dict[str, Any] | None = None
    if session is not None and (done is None or done.get("verdict") == "pass"):
        via = _via(method, given, (frame.width, frame.height))
        origin = session.where()
        arrived: tuple[str, str] | None = None
        if matches:
            first = matches[0]
            state = "confirmed" if first["state"] == "confirmed" else "explored"
            arrived = (state, str(first.get("id") or first.get("key")))
        if method is not None:
            session.wait_for([])  # 새 걸음: 지난 대기 이동은 버린다
        if via is not None and origin is not None:
            if arrived is not None and arrived != origin:
                card = await asyncio.to_thread(
                    add_moves, call.daemon, session, origin, [{"via": via, "to": arrived[1]}]
                )
                if card is not None:
                    move = {"from": origin[1], "to": arrived[1], "status": "recorded", "card": card}
            elif arrived is None and new_screen and changed:
                session.wait_for([(origin, {"via": via, "status": "tried"})])
                move = {"from": origin[1], "to": None, "status": "pending"}
        if arrived is not None:
            session.move_to(arrived)
        elif changed or new_screen:
            session.move_to(None)  # 처음 보는(또는 확인 못 한) 화면 — 저장하면 그 키가 된다
    return {
        "frame": shown,
        "changed": changed,
        "waited_ms": waited,
        "window": target.label,
        "input": done,
        "identify": found,
        "new_screen": new_screen,
        "move": move,
    }


def _window_arg(call: Call) -> str:
    return str(call.params["window"])


METHODS: Final = {"explore.step": MethodSpec(_step, _window_arg, self_authorized=True)}
