"""예제 게임 창 검사 (대화형 데스크톱 필요). 게임은 테스트 세션 Job 안에서 뜬다."""

from __future__ import annotations

import ctypes
import json
from ctypes import wintypes
from pathlib import Path
from typing import Any

import pytest

from kb_testing.proc import wait_until
from kb_testing.sample_game import (
    SampleGame,
    client_rect,
    is_window,
    launch_sample_game,
    window_owner,
    window_pid,
    window_root_owner,
    window_title,
    window_visible,
)
from sample_game import EXIT_FONT_MISSING
from sample_game.app import App, EventLog
from sample_game.flow import Scene, scene_state
from sample_game.layout import BUTTONS, Viewport
from sample_game.options import parse_args

pytestmark = pytest.mark.desktop

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetWindow.restype = wintypes.HWND
_user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
_user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_user32.PostMessageW.restype = wintypes.BOOL
GW_CHILD = 5
WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x0100, 0x0101, 0x0102
VK_I = 0x49


def post_key(game: SampleGame, vk: int) -> None:
    """Tk가 키 이벤트를 받는 안쪽 창에 키 메시지를 넣는다 (실제 입력 없이 기록 경로만 확인)."""
    inner = _user32.GetWindow(game.hwnd, GW_CHILD)
    assert inner, "Tk 안쪽 창이 없다"
    _user32.PostMessageW(inner, WM_KEYDOWN, vk, 1)
    _user32.PostMessageW(inner, WM_KEYUP, vk, 1 | (3 << 30))


@pytest.mark.parametrize(
    ("options", "size", "title"),
    [
        ((), (1024, 640), "SampleRPG"),
        (("--size", "800x500", "--title", "예제 RPG"), (800, 500), "예제 RPG"),
    ],
)
def test_starts_with_title_and_client_size(
    tmp_path: Path, options: tuple[str, ...], size: tuple[int, int], title: str
) -> None:
    with launch_sample_game(options, workdir=tmp_path) as game:
        ready = game.ready
        assert ready["pid"] == game.pid == window_pid(game.hwnd)
        assert ready["client_size"] == list(size)
        assert ready["dpi_awareness"] == "pmv2"
        assert ready["font"] in ("Malgun Gothic", "맑은 고딕")
        assert client_rect(game.hwnd)[2:] == size
        assert window_title(game.hwnd) == title
        assert window_visible(game.hwnd)
        screens = [e for e in game.events() if e["event"] == "screen"]
        assert screens[0]["scene"] == "title"
        assert screens[0]["seq"] > ready["seq"]


def test_event_log_screen_and_input_events_flushed(tmp_path: Path) -> None:
    with launch_sample_game(("--start-scene", "world"), workdir=tmp_path) as game:
        # 게임이 살아 있는 동안 파일에서 바로 읽힌다 (줄마다 flush)
        assert game.events()[-1]["event"] == "screen"
        assert game.events()[-1]["scene"] == "world"
        before = game.last_seq()
        post_key(game, VK_I)
        down = game.wait_event("key_down", after=before, key="i", window="main")
        assert (down["vk"], down["repeat"]) == (VK_I, False)
        game.wait_event("key_up", after=down["seq"], key="i")
        opened = game.wait_screen("inventory", after=before)
        assert opened["popup"] == "inventory"
        post_key(game, VK_I)
        game.wait_screen("world", after=opened["seq"])
        assert game.proc.poll() is None
        records = game.events()
        assert [r["seq"] for r in records] == list(range(1, len(records) + 1))
        assert game.close() == 0
    assert game.events()[-1]["event"] == "exit"


def test_exits_3_when_font_missing(tmp_path: Path) -> None:
    game = launch_sample_game(
        ("--font", "kookabug-missing-font"), workdir=tmp_path, wait_ready=False
    )
    with game:
        assert game.proc.wait(30) == EXIT_FONT_MISSING
        fatal = game.wait_event("fatal")
        assert fatal["reason"] == "font_missing"
        assert not any(e["event"] == "ready" for e in game.events())


@pytest.mark.parametrize("mode", ["unaware", "system", "pmv2"])
def test_dpi_awareness_modes_reported(tmp_path: Path, mode: str) -> None:
    with launch_sample_game(("--dpi-awareness", mode), workdir=tmp_path) as game:
        assert game.ready["dpi_awareness"] == mode
        # 게임은 자기 좌표로 요청한 크기를 본다 (unaware면 DPI 배율만큼 물리 크기가 다르다)
        assert game.ready["client_size"] == [1024, 640]
        assert game.ready["dpi"] >= 96


def test_second_window_is_independent_toplevel_same_pid(tmp_path: Path) -> None:
    with launch_sample_game(("--second-window",), workdir=tmp_path) as game:
        second = int(game.ready["windows"]["second"])
        assert second != game.hwnd
        assert window_pid(second) == window_pid(game.hwnd) == game.pid
        assert window_owner(second) == 0
        assert window_root_owner(second) == second
        assert window_owner(game.hwnd) == 0
        assert window_visible(second)
        assert window_title(second) == "SampleRPG Chat"


def test_owned_popup_has_owner(tmp_path: Path) -> None:
    with launch_sample_game(("--owned-popup",), workdir=tmp_path) as game:
        popup = int(game.ready["windows"]["popup"])
        assert window_owner(popup) == game.hwnd
        assert window_root_owner(popup) == game.hwnd
        assert window_pid(popup) == game.pid
        assert window_visible(popup)
        assert window_title(popup) == "SampleRPG Notice"
        # 메인 클라이언트 왼쪽 위 (40, 40)에 겹친다
        mx, my, _w, _h = client_rect(game.hwnd)
        px, py, _pw, _ph = client_rect(popup)
        assert mx + 40 <= px < mx + 200 and my + 40 <= py < my + 200


def test_recreate_after_new_window_same_title(tmp_path: Path) -> None:
    options = ("--recreate-after", "300", "--start-scene", "login")
    with launch_sample_game(options, workdir=tmp_path) as game:
        old = game.hwnd
        recreate = game.wait_event("recreate", after=game.ready["seq"])
        assert recreate["old_hwnd"] == old
        ready = game.wait_ready(after=recreate["seq"])
        assert ready["recreated"] is True
        new = game.hwnd
        assert new != old
        wait_until(lambda: not is_window(old), timeout=5, message="옛 창이 남아 있다")
        assert window_title(new) == "SampleRPG"
        assert window_pid(new) == game.pid
        # 게임 상태는 이어진다 (새 창이 같은 장면을 다시 그린다)
        assert game.wait_screen("login", after=ready["seq"])["scene"] == "login"
        assert sum(e["event"] == "recreate" for e in game.events()) == 1


def test_mouse_wheel_char_handlers_logged_via_tk_events(tmp_path: Path) -> None:
    """마우스·휠·글자 기록 경로.

    밖에서 넣은 마우스 메시지는 Tk가 실제 버튼 상태를 읽어 버린다(실제 입력은 T5 `desktop_input`
    검사). 그래서 게임의 Tk 처리기를 이 프로세스 안에서 Tk 이벤트로 돌린다.
    """
    log_path = tmp_path / "events.jsonl"
    options = parse_args(["--event-log", str(log_path), "--start-scene", "login"])
    log = EventLog(log_path)
    app = App(options, scene_state(Scene.LOGIN), log)
    assert app._build() is None
    root, canvas = app.root, app.canvas
    assert root is not None and canvas is not None
    try:
        root.focus_force()
        root.update()
        x, y, w, h = Viewport(*options.size).rect(BUTTONS[Scene.LOGIN][0].rect)
        cx, cy = x + w // 2, y + h // 2
        canvas.event_generate("<ButtonPress-1>", x=cx, y=cy)
        canvas.event_generate("<ButtonRelease-1>", x=cx, y=cy)
        canvas.event_generate("<ButtonPress-3>", x=5, y=6)
        canvas.event_generate("<ButtonRelease-3>", x=5, y=6)
        canvas.event_generate("<MouseWheel>", delta=-120, x=10, y=20)
        for keysym in ("a", "b"):
            root.event_generate("<KeyPress>", keysym=keysym)
            root.event_generate("<KeyRelease>", keysym=keysym)
        root.update()
    finally:
        root.destroy()
        log.close()
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    kinds = [(r["event"], r.get("button")) for r in records]
    assert ("mouse_down", "left") in kinds and ("mouse_up", "left") in kinds
    assert ("mouse_down", "right") in kinds and ("mouse_up", "right") in kinds
    down = next(r for r in records if r["event"] == "mouse_down" and r["button"] == "left")
    assert (down["x"], down["y"], down["window"]) == (cx, cy, "main")
    wheel = next(r for r in records if r["event"] == "wheel")
    assert wheel["delta"] == -120
    chars = "".join(r["text"] for r in records if r["event"] == "char")
    assert chars == "ab"
    # 계정 칸 클릭은 장면을 바꾸지 않고, 글자는 그 칸에 들어간다
    assert app.game.account == "ab"
    assert [r["scene"] for r in records if r["event"] == "screen"] == ["login"]


def test_batched_wm_char_in_one_tk_event_all_recorded(tmp_path: Path) -> None:
    """검수 반례 재현: WM_KEYDOWN 뒤 대기 중인 WM_CHAR 여러 개를 Tk가 KeyPress 하나의 문자열로
    합친다. 이 테스트가 만든 창의 메시지 큐에만 넣는다(실제 입력 없음)."""
    log_path = tmp_path / "events.jsonl"
    log = EventLog(log_path)
    app = App(parse_args(["--start-scene", "login"]), scene_state(Scene.LOGIN), log)
    assert app._build() is None
    root, canvas = app.root, app.canvas
    assert root is not None and canvas is not None
    observed: list[str] = []
    original = app._key_down

    def spy(event: Any, window: str) -> str:
        observed.append(event.char)
        return original(event, window)

    app._key_down = spy  # type: ignore[method-assign]
    hwnd = canvas.winfo_id()
    try:
        # Tk는 자기 창에 포커스가 없으면 키 이벤트를 버린다 (앞선 검사의 창이 가졌을 수 있다)
        root.focus_force()
        root.update()
        assert _user32.PostMessageW(hwnd, WM_KEYDOWN, 0x41, 1)
        assert _user32.PostMessageW(hwnd, WM_CHAR, ord("a"), 1)
        assert _user32.PostMessageW(hwnd, WM_CHAR, ord("b"), 1)
        assert _user32.PostMessageW(hwnd, WM_KEYUP, 0x41, 1 | (3 << 30))
        root.update()
        account = app.game.account
    finally:
        root.destroy()
        log.close()
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(observed) == 1 and "ab" in observed[0], observed
    chars = [r["text"] for r in records if r["event"] == "char"]
    assert "".join(chars) == observed[0] == account
    assert all(len(c) == 1 for c in chars)
    assert sum(r["event"] == "key_down" for r in records) == 1
