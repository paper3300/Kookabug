"""실제 SendInput이 예제 게임에 닿는가, 입력 직전 확인이 입력 전에 막는가 (구현 계획 M1 2.4).

`desktop_input`: 실제 마우스·키보드를 쓴다. 게임은 테스트 세션 Job에서 띄우고, 입력은 이
프로세스의 입력 액터(`SendInputBackend` + `WindowInputGuard`)로 보낸다. 증거는 게임의 입력 수신
기록이다. 시작 전에 눌린 키가 없는지 보고, 끝에 눌린 것을 뗀다(`kb_testing.keys`).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from kb_testing.display import pair_layout, shift_within
from kb_testing.keys import assert_no_keys_held, cursor_pos, held, release_all_for_test
from kb_testing.proc import wait_until
from kb_testing.sample_game import SampleGame, launch_sample_game
from kookabug_core.inputs import ClientPoint, InputActor
from kookabug_platform.dpi import client_to_screen, per_monitor_v2_thread
from kookabug_platform.errors import POINT_OBSCURED, WINDOW_NOT_FOREGROUND, PlatformError
from kookabug_platform.sendinput import SendInputBackend, WindowInputGuard
from kookabug_platform.tracker import WindowBinding, WindowTracker
from kookabug_platform.win32 import user32
from kookabug_platform.windows import activate, window_info

pytestmark = pytest.mark.desktop_input

INPUT_EVENTS = ("key_down", "key_up", "char", "mouse_down", "mouse_up", "wheel")


@dataclass
class Live:
    actor: InputActor
    tracker: WindowTracker
    tmp_path: Path

    def launch(self, *options: str) -> SampleGame:
        title = f"KBT5 {uuid.uuid4().hex[:8]}"
        return launch_sample_game(("--title", title, *options), workdir=self.tmp_path)

    def bind(self, hwnd: int) -> WindowBinding:
        return self.tracker.bind(hwnd)


@pytest.fixture
def live(tmp_path: Path) -> Iterator[Live]:
    assert_no_keys_held()
    tracker = WindowTracker().start()
    actor = InputActor(SendInputBackend(), guard=WindowInputGuard(tracker)).start()
    try:
        yield Live(actor, tracker, tmp_path)
    finally:
        # 이 검사가 누른 것이 남았는지는 액터가 안다(멈춘 뒤 held가 비어야 quiesced). OS의 비동기
        # 상태로 보지 않는다 — 사람이 PC를 쓰는 중이면 그 사람의 버튼이 잡힌다. 남은 것은 뗀다
        quiesced = actor.stop(10)
        tracker.stop()
        release_all_for_test()
        assert quiesced, f"검사가 키·버튼을 눌린 채 남겼다: {actor.held}"


def bring_front(hwnd: int) -> None:
    wait_until(lambda: activate(hwnd), timeout=5, message=lambda: f"{hwnd:#x}를 앞으로 못 가져옴")


def move_window(hwnd: int, dx: int, dy: int) -> None:
    """창을 옮긴다. 검사 창 모니터(`KOOKABUG_TEST_DISPLAY`)가 있으면 그 작업 영역 안에 남게 이동
    방향을 뒤집을 수 있다 (`kb_testing.display.shift_within`)."""
    rect = window_info(hwnd).window_rect
    with per_monitor_v2_thread():
        dx, dy = shift_within(rect, dx, dy)
    move_to(hwnd, rect[0] + dx, rect[1] + dy)


def move_to(hwnd: int, x: int, y: int) -> None:
    flags = user32.SWP_NOSIZE | user32.SWP_NOZORDER | user32.SWP_NOACTIVATE
    with per_monitor_v2_thread():
        assert user32.SetWindowPos(hwnd, None, x, y, 0, 0, flags)
    wait_until(lambda: window_info(hwnd).window_rect[:2] == (x, y), timeout=5)


def side_by_side(first: int, other: int) -> None:
    """두 창이 겹치지 않게: 기본은 `other`를 `first` 오른쪽 20px 옆으로. 검사 창 모니터가 있으면 그
    작업 영역 안에 가로(안 들어가면 세로)로 나란히 (`kb_testing.display.pair_layout`)."""
    a, b = window_info(first).window_rect, window_info(other).window_rect
    with per_monitor_v2_thread():
        layout = pair_layout(a, b)
    if layout is None:
        move_window(other, (a[2] - a[0]) + 20, 0)
        return
    move_to(first, *layout[0])
    move_to(other, *layout[1])


def inputs_after(game: SampleGame, seq: int) -> list[dict[str, Any]]:
    return [e for e in game.events() if e["seq"] > seq and e["event"] in INPUT_EVENTS]


def assert_cursor_not_sent(hwnd: int, point: tuple[int, int]) -> None:
    """거부된 마우스 요청은 이동도 보내지 않았다: 커서가 그 클릭 지점에 있지 않다. (전과 같은
    자리인지로 보지 않는다 — 사람이 마우스를 쓰는 PC에서는 그사이 1픽셀씩 움직인다)"""
    with per_monitor_v2_thread():
        assert cursor_pos() != client_to_screen(hwnd, point)


def refused(code: str, fn: Any) -> None:
    with pytest.raises(PlatformError) as caught:
        fn()
    assert caught.value.code == code, caught.value.message


def test_key_reaches_game_with_scancode(live: Live) -> None:
    with live.launch() as game:
        bring_front(game.hwnd)
        target = live.bind(game.hwnd)
        mark = game.last_seq()
        live.actor.key("a", target=target)
        live.actor.key("up", target=target)  # 확장 스캔 코드 E0 48 — 빠지면 숫자패드 8이 된다
        live.actor.key("shift+b", target=target)
        game.wait_event("key_up", key="b", after=mark)
        keys = [(e["event"], e["key"]) for e in inputs_after(game, mark) if e["event"] != "char"]
        assert keys == [
            ("key_down", "a"),
            ("key_up", "a"),
            ("key_down", "up"),
            ("key_up", "up"),
            ("key_down", "lshift"),
            ("key_down", "b"),
            ("key_up", "b"),
            ("key_up", "lshift"),
        ]
        assert {e["window"] for e in inputs_after(game, mark)} == {"main"}
        assert held() == []


def test_type_text_korean_reaches_game_as_char(live: Live) -> None:
    text = "한글 입력 OK1"
    with live.launch() as game:
        bring_front(game.hwnd)
        mark = game.last_seq()
        live.actor.type_text(text, target=live.bind(game.hwnd))

        def chars() -> str:
            return "".join(e["text"] for e in inputs_after(game, mark) if e["event"] == "char")

        wait_until(lambda: len(chars()) >= len(text), timeout=10, message=chars)
        assert chars() == text


def test_click_lands_on_client_point_after_window_move(live: Live) -> None:
    with live.launch() as game:
        bring_front(game.hwnd)
        target = live.bind(game.hwnd)
        move_window(game.hwnd, 60, 40)
        mark = game.last_seq()
        live.actor.click(ClientPoint(123, 77), target=target)
        up = game.wait_event("mouse_up", after=mark)
        down = game.wait_event("mouse_down", after=mark)
        assert (down["button"], down["x"], down["y"]) == ("left", 123, 77)
        assert (up["button"], up["x"], up["y"]) == ("left", 123, 77)
        # 오른쪽 버튼·이중 클릭도 같은 자리
        mark = game.last_seq()
        live.actor.click(ClientPoint(300, 210), button="right", count=2, target=target)
        wait_until(lambda: len(inputs_after(game, mark)) >= 4, timeout=5)
        assert [(e["event"], e["button"], e["x"], e["y"]) for e in inputs_after(game, mark)] == [
            ("mouse_down", "right", 300, 210),
            ("mouse_up", "right", 300, 210),
            ("mouse_down", "right", 300, 210),
            ("mouse_up", "right", 300, 210),
        ]


def test_drag_and_wheel(live: Live) -> None:
    with live.launch() as game:
        bring_front(game.hwnd)
        target = live.bind(game.hwnd)
        mark = game.last_seq()
        live.actor.drag(
            ClientPoint(200, 200), ClientPoint(320, 260), duration_ms=120, target=target
        )
        up = game.wait_event("mouse_up", after=mark)
        down = game.wait_event("mouse_down", after=mark)
        assert (down["x"], down["y"]) == (200, 200)
        assert (up["x"], up["y"]) == (320, 260)
        mark = game.last_seq()
        live.actor.scroll(ClientPoint(250, 250), 2, target=target)
        live.actor.scroll(ClientPoint(250, 250), -1, target=target)
        wait_until(
            lambda: sum(e["event"] == "wheel" for e in inputs_after(game, mark)) >= 2, timeout=5
        )
        wheels = [e["delta"] for e in inputs_after(game, mark) if e["event"] == "wheel"]
        assert wheels == [240, -120]


def test_not_foreground_refused_before_any_input(live: Live) -> None:
    with live.launch() as game, live.launch() as other:
        target = live.bind(game.hwnd)
        # 두 창이 겹치지 않게 다른 창을 옆으로 옮기고 앞으로
        side_by_side(game.hwnd, other.hwnd)
        bring_front(other.hwnd)
        marks = game.last_seq(), other.last_seq()
        refused(WINDOW_NOT_FOREGROUND, lambda: live.actor.key("a", target=target))
        refused(WINDOW_NOT_FOREGROUND, lambda: live.actor.type_text("x", target=target))
        # 마우스: 점 아래는 대상 창이지만 포그라운드가 아니다 → 커서도 옮기지 않는다
        refused(WINDOW_NOT_FOREGROUND, lambda: live.actor.click(ClientPoint(50, 50), target=target))
        assert_cursor_not_sent(game.hwnd, (50, 50))
        assert inputs_after(game, marks[0]) == [] and inputs_after(other, marks[1]) == []
        assert held() == [] and live.actor.held == []


def test_independent_second_window_foreground_refused_no_input(live: Live) -> None:
    with live.launch("--second-window") as game:
        second = game.ready["windows"]["second"]
        target = live.bind(game.hwnd)
        bring_front(second)  # 같은 프로세스의 독립 최상위 창
        mark = game.last_seq()
        refused(WINDOW_NOT_FOREGROUND, lambda: live.actor.key("a", target=target))
        refused(WINDOW_NOT_FOREGROUND, lambda: live.actor.type_text("x", target=target))
        assert inputs_after(game, mark) == []  # main·second 어느 창에도 입력 없음
        assert held() == []


def test_owned_popup_foreground_keyboard_allowed(live: Live) -> None:
    with live.launch("--owned-popup") as game:
        popup = game.ready["windows"]["popup"]
        main = live.bind(game.hwnd)
        bring_front(popup)
        mark = game.last_seq()
        live.actor.key("a", target=main)  # 대상이 소유한 팝업이 포그라운드 → 통과
        game.wait_event("key_up", key="a", after=mark)
        assert {e["window"] for e in inputs_after(game, mark)} == {"popup"}

        # 팝업 자체를 대상으로 붙이면 키보드·마우스 모두 그 팝업에 (계획 2차 검수 N1)
        target = live.bind(popup)
        mark = game.last_seq()
        live.actor.click(ClientPoint(20, 30), target=target)
        bring_front(popup)  # 클릭 직후 포그라운드가 잠깐 비는 일이 있었다 (검수 2차 실행)
        live.actor.key("b", target=target)
        game.wait_event("key_up", key="b", after=mark)
        events = inputs_after(game, mark)
        assert {e["window"] for e in events} == {"popup"}
        down = next(e for e in events if e["event"] == "mouse_down")
        assert (down["x"], down["y"]) == (20, 30)


def test_click_point_covered_by_popup_is_point_obscured(live: Live) -> None:
    with live.launch("--owned-popup") as game:
        target = live.bind(game.hwnd)
        bring_front(game.hwnd)  # 소유 팝업은 그래도 메인 위에 있다 (클라이언트 (40, 40)부터)
        mark = game.last_seq()
        refused(POINT_OBSCURED, lambda: live.actor.click(ClientPoint(100, 100), target=target))
        refused(POINT_OBSCURED, lambda: live.actor.scroll(ClientPoint(100, 100), 1, target=target))
        assert_cursor_not_sent(game.hwnd, (100, 100))
        assert inputs_after(game, mark) == []
        # 팝업 밖은 그대로 된다
        live.actor.click(ClientPoint(600, 500), target=target)
        down = game.wait_event("mouse_down", after=mark)
        assert (down["window"], down["x"], down["y"]) == ("main", 600, 500)
