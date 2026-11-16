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
- `@game` (UX8 A): 창이 아직 없으면 `wait_ms` 안에서 생기기를 기다린다(0.5초마다). 기다리는 중
  잡은 창이 사라지면 같은 프로세스에서 주 창을 다시 골라 남은 시간 동안 이어 기다린다 — 프로세스가
  끝났을 때만 실패. 쓴 창이 바뀌었으면 `window_changed: true`
- 클릭+입력 한 걸음 (UX8 C): `point`·`target` 클릭과 `text`·`secret`을 함께 주면 클릭 → (선택
  `select_all`이면 ctrl+a) → 입력을 한 요청에서 한다(사람 확인 한 번). 클릭 위치가 칸 상자 근거다
  (비밀값은 point 클릭만)
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Final

from kookabug_daemon.game_window import GAME, is_game
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods.control import (
    InputTarget,
    click_then_type,
    game_target,
    graph_for,
    refuse_if_denied,
    remember_target,
    resolve_target,
    send_input,
    split_click_type,
)
from kookabug_daemon.protocol import InvalidParams, RequestFailed
from kookabug_daemon.screen_source import Grab, WindowBinding
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
WINDOW_POLL_S: Final = 0.5
"""`@game` 창이 없을 때 다시 찾는 간격 (UX8 A)."""


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
    """입력 종류(`control.*`)와 그 인자. 둘 이상이면 `invalid_params` — 클릭+입력(UX8 C)은
    `split_click_type`이 먼저 본다."""
    if params.get("select_all") is True and "text" not in params and "secret" not in params:
        raise InvalidParams("select_all은 text·secret과 함께 준다")
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
        raise InvalidParams(
            "입력은 하나만 준다 (point·target 클릭, keys, text·secret 중 하나 — 클릭과 "
            "text·secret을 함께 주는 클릭+입력 한 걸음만 예외)"
        )
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


GAME_GONE: Final = "@game: 게임 프로세스가 끝났다 — kb_app_launch로 다시 띄운다"
NO_GAME_WINDOW: Final = "@game: 실행한 게임의 창이 없다 (닫혔거나 아직 뜨지 않았다)"


class _Watch:
    """기다리며 캡처할 창. `@game`이면 잡은 창이 사라졌을 때 같은 프로세스에서 주 창을 다시
    고른다 (UX8 A — 로딩 중 시작 화면 창을 닫고 본 창을 새로 만드는 게임). 프로세스까지 끝났을 때만
    실패한다. 제목으로 준 창은 지금 그대로(사라지면 캡처 오류)."""

    def __init__(self, call: Call, binding: WindowBinding, game: bool) -> None:
        self.call = call
        self.binding = binding
        self.title = ""
        """바뀐 창의 지금 제목 (판정 인자로만 — 결과·기록에는 `@game`)."""
        self.game = game
        self.changed = False

    async def capture_as(self, binding: WindowBinding) -> Grab | None:
        """그 바인딩의 창 한 장 — 캡처한 창의 바인딩(HWND·PID·프로세스 생성 시각)이 기대와 같을
        때만 (UX8 검수 1 High 1: 그 사이 HWND가 다른 프로세스에 재사용됐거나 식별할 수 없으면 그
        픽셀은 버린다 — 비교·판별·캐시·결과에 넘기지 않는다). 창이 없으면 캡처 오류 그대로."""
        grab = await asyncio.to_thread(self.call.daemon.screen_source.capture, binding.hwnd)
        return grab if grab.binding == binding else None

    async def grab(self) -> Grab | None:
        """지금 창 한 장. `@game`에서 창이 사라졌거나(또는 다른 프로세스의 창이 됐거나) 새 창이
        아직 없으면 None."""
        source = self.call.daemon.screen_source
        if not self.game:
            return await asyncio.to_thread(source.capture, self.binding.hwnd)
        try:
            found = await self.capture_as(self.binding)
        except RequestFailed:
            if await asyncio.to_thread(source.alive, self.binding):
                raise
            found = None
        return found if found is not None else await self.follow()

    async def follow(self) -> Grab | None:
        """같은 게임 프로세스에서 주 창을 다시 골라 한 장. 바인딩이 맞는 프레임을 얻은 뒤에만 그
        창으로 바꾼다. 프로세스가 끝났으면 `window_not_found`."""
        game = self.call.daemon.game
        found = await asyncio.to_thread(game.find, self.call.principal)
        if found is None:
            if not await asyncio.to_thread(game.alive, self.call.principal):
                raise RequestFailed("window_not_found", GAME_GONE)
            return None
        binding, title = found
        if binding != self.binding:
            # 새 창의 제목으로도 거부 정책이면 보지 않는다 (사람에게 묻지는 않는다)
            await refuse_if_denied(self.call, title)
        try:
            grab = await self.capture_as(binding)
        except RequestFailed:
            return None  # 막 사라진 창 — 다음 회차에 다시 고른다
        if grab is None:
            return None  # 다른 프로세스·식별 불능 프레임은 버린다
        if binding != self.binding:
            self.binding, self.title, self.changed = binding, title, True
        return grab


async def _first_frame(watch: _Watch, deadline: float) -> Grab:
    """첫 유효 프레임 (UX8 검수 1 Mid 3): 고른 창이 첫 캡처 전에 닫혀도 같은 재탐색을 기한까지
    한다. 프로세스가 끝나면(`follow`) 또는 기한이 지나면 `window_not_found`."""
    loop = asyncio.get_running_loop()
    while True:
        found = await watch.grab()
        if found is not None:
            return found
        left = deadline - loop.time()
        if left <= 0:
            raise RequestFailed("window_not_found", NO_GAME_WINDOW)
        await asyncio.sleep(min(WINDOW_POLL_S, left))


async def _game_target(call: Call, deadline: float) -> InputTarget:
    """`@game` 창 (UX8 A): 아직 창이 없으면 기한까지 0.5초마다 다시 찾는다. 기억이 없으면 바로,
    프로세스가 끝났으면 `window_not_found`. 실패는 판정을 먼저 본다(거부 정책이면
    `permission_denied`)."""
    game = call.daemon.game
    loop = asyncio.get_running_loop()
    while True:
        try:
            found = await asyncio.to_thread(game.find, call.principal)
        except RequestFailed:
            await refuse_if_denied(call, GAME)
            raise
        if found is not None:
            return game_target(*found)
        text = None
        if not await asyncio.to_thread(game.alive, call.principal):
            text = GAME_GONE
        elif loop.time() >= deadline:
            text = NO_GAME_WINDOW
        if text is not None:
            await refuse_if_denied(call, GAME)
            raise RequestFailed("window_not_found", text)
        await asyncio.sleep(min(WINDOW_POLL_S, max(0.0, deadline - loop.time())))


async def _wait(watch: _Watch, before: Grab, deadline: float) -> tuple[Grab, bool]:
    """바뀌고 멈출 때까지 (또는 기한). (마지막 프레임, 바뀌었나). `@game` 창이 바뀌면 바뀐 것으로
    보고 새 창에서 이어 기다린다. 기한까지 지금 창의 유효 프레임(바인딩 일치)을 못 얻으면
    `window_not_found` — 옛 프레임은 판별·이동·저장·결과에 넘기지 않는다 (UX8 검수 2 High: 닫힌 창의
    보호 기록은 지워지므로 옛 픽셀을 나중에 프레임으로 만들면 보호 없이 나간다)."""
    loop = asyncio.get_running_loop()
    last = before
    changed = False
    changed_at = 0.0
    still_since = 0.0
    missing = False
    while True:
        if loop.time() >= deadline:
            if missing:
                raise RequestFailed("window_not_found", NO_GAME_WINDOW)
            break
        await asyncio.sleep(POLL_S)
        found = await watch.grab()
        if found is None:
            # 잡은 창이 닫혔거나 다른 프로세스 창이 됐고 새 창이 아직 없다: 남은 시간 동안 다시
            # 찾는다
            missing = True
            await asyncio.sleep(max(0.0, min(WINDOW_POLL_S - POLL_S, deadline - loop.time())))
            continue
        missing = False
        grab = found
        now = loop.time()
        if not changed:
            if watch.changed or frame_change(before.pixels, grab.pixels) > CHANGED:
                changed, changed_at, still_since = True, now, now
        elif frame_change(last.pixels, grab.pixels) > STILL:
            still_since = now
        last = grab
        if changed and (now - still_since >= STABLE_S or now - changed_at >= SETTLE_CAP_S):
            break
    return last, changed


async def _step(call: Call) -> dict[str, Any]:
    from kookabug_daemon.methods.target import frame_result, new_frame
    from kookabug_daemon.screen_save import add_moves, identify

    if call.principal.kind != "agent":
        raise RequestFailed("agent_only", "탐색 한 걸음은 에이전트 연결만 쓴다")
    require_platform()
    params = call.params
    window = str(params["window"])
    root = call.daemon.root
    # 인자가 틀리면 판정 전에 거부 (아무것도 묻지 않음)
    both = split_click_type(params)
    typed: tuple[dict[str, Any], dict[str, Any]] | None = None
    if both is not None:
        # 클릭+입력 한 걸음 (UX8 C): 클릭 위치가 곧 칸 상자 근거
        method, given = "control.click", both[0]
        typed = (both[1], graph_for(root, "control.type", both[1], window))
    else:
        method, given = _input_of(params)
    value = None if method is None else graph_for(root, method, given, window)
    wait_ms = min(int(params.get("wait_ms", DEFAULT_WAIT_MS if method else 0)), MAX_WAIT_MS)
    loop = asyncio.get_running_loop()
    started = loop.time()
    game = is_game(window)
    # `@game`은 창이 아직 없으면 wait_ms 안에서 생기기를 기다린다 (UX8 A)
    target = (
        await _game_target(call, started + wait_ms / 1000)
        if game
        else await resolve_target(call, window)
    )
    bindings = target.bindings or []
    if len(bindings) != 1:
        # 판정이 먼저다 (거부 정책이면 창 유무와 관계없이 permission_denied)
        await refuse_if_denied(call, target.title)
        raise RequestFailed(
            "window_not_found",
            f"창 {window!r}이(가) 없거나 여럿이다 (정확히 같은 제목의 창 하나, 또는 @game)",
        )
    watch = _Watch(call, bindings[0], game)
    # 고른 창이 첫 캡처 전에 닫혀도 같은 재탐색을 요청 기한까지 (UX8 검수 1 Mid 3)
    before = await _first_frame(watch, started + wait_ms / 1000)
    if watch.changed:
        target = game_target(watch.binding, watch.title)
    # 창을 기다리고 남은 기다림 (입력 뒤 바뀌고 멈추기를 기다리는 상한)
    left_s = max(0.0, wait_ms / 1000 - (loop.time() - started)) if game else wait_ms / 1000
    done: dict[str, Any] | None = None
    if typed is not None and value is not None:
        done = await click_then_type(call, target, (given, value), typed)
    elif method is not None and value is not None:
        done = await send_input(call, method, given, target, value)
    else:
        # 입력 없이 기다림·캡처만도 이 도구의 판정을 지난다 (거부 정책이면 화면도 보지 않는다).
        # 판정이 허용된 뒤에만 이 창을 이 주체의 게임으로 기억한다 (입력이 있으면 send_input이)
        await call.daemon.approvals.authorize(call, target.title)
        remember_target(call, target)
    session = call.daemon.explore.get(call.connection)
    waited_s = wait_ms / 1000 - left_s  # 창을 기다린 시간
    settle_from = loop.time()
    if done is not None and done.get("verdict") != "pass":
        # 입력이 들어가지 않았다: 이동은 기록하지 않는다. 화면은 지금 한 장(옛 프레임을 쓰지
        # 않는다 — 그 사이 창이 닫혔으면 window_not_found)
        last, changed = await _first_frame(watch, loop.time()), False
    elif left_s > 0:
        last, changed = await _wait(watch, before, settle_from + left_s)
        waited_s += loop.time() - settle_from
    else:
        # 지금 창의 유효 프레임이 없으면(창이 막 닫힘·다른 프로세스 창) window_not_found
        last = await _first_frame(watch, loop.time())
        changed = watch.changed or frame_change(before.pixels, last.pixels) > CHANGED
    waited = int(waited_s * 1000)
    frame = await asyncio.to_thread(
        new_frame, call, last.pixels, last.client_size, last.dpi, grab=last
    )
    shown = await asyncio.to_thread(frame_result, call, frame)
    found = await asyncio.to_thread(identify, call.daemon, frame, session)
    matches = found["matches"]
    new_screen = not matches and not found["unknown"]
    move: dict[str, Any] | None = None
    if session is not None and (done is None or done.get("verdict") == "pass"):
        # 클릭+입력 한 걸음은 화면 카드 via 형식이 없다 (글자 입력과 같다)
        via = None if typed is not None else _via(method, given, (frame.width, frame.height))
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
    out: dict[str, Any] = {
        "frame": shown,
        "changed": changed,
        "waited_ms": waited,
        "window": target.label,
        "input": done,
        "identify": found,
        "new_screen": new_screen,
        "move": move,
    }
    if watch.changed:
        out["window_changed"] = True  # 실제로 쓴 창이 바뀌었다 (`@game` 시작 화면 → 본 창)
    return out


def _window_arg(call: Call) -> str:
    return str(call.params["window"])


METHODS: Final = {"explore.step": MethodSpec(_step, _window_arg, self_authorized=True)}
