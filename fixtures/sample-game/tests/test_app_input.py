"""창 껍데기의 키 처리 (창 없이 처리기만)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sample_game.app import CONTROL_MASK, App, EventLog, printable_chars
from sample_game.flow import Scene, scene_state
from sample_game.options import parse_args


def make_app(tmp_path: Path, scene: Scene) -> tuple[App, Path]:
    path = tmp_path / "events.jsonl"
    app = App(parse_args(["--start-scene", scene.value]), scene_state(scene), EventLog(path))
    app._held["main"] = set()
    return app, path


CTRL = CONTROL_MASK


def key_event(keysym: str, char: str, keycode: int = 0x41, state: int | str = 0) -> SimpleNamespace:
    return SimpleNamespace(keysym=keysym, char=char, keycode=keycode, state=state)


def switch_focus(app: App, old: str, new: str) -> None:
    """`old` 창이 포커스를 잃고 `new` 창이 얻는다 (Tk FocusOut/FocusIn 처리기)."""
    top_old, top_new = object(), object()
    app._focus(SimpleNamespace(widget=top_old), top_old, old, False)  # pyright: ignore[reportArgumentType]
    app._focus(SimpleNamespace(widget=top_new), top_new, new, True)  # pyright: ignore[reportArgumentType]


def records(app: App, path: Path) -> list[dict]:
    app.log.close()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(
    ("raw", "expected"), [("a", "a"), ("aba", "aba"), ("가나", "가나"), ("\t", ""), ("a\rb", "ab")]
)
def test_printable_chars(raw: str, expected: str) -> None:
    assert printable_chars(raw) == expected


def test_one_tk_event_with_several_chars_types_and_acks_every_char(tmp_path: Path) -> None:
    """검수 반례: Tk가 WM_CHAR 여러 개를 한 KeyPress 문자열로 합쳐 줘도 글자를 버리지 않는다."""
    app, path = make_app(tmp_path, Scene.LOGIN)
    assert app._key_down(key_event("a", "aba"), "main") == "break"  # pyright: ignore[reportArgumentType]
    assert app.game.account == "aba"
    events = records(app, path)
    assert [e["text"] for e in events if e["event"] == "char"] == ["a", "b", "a"]
    assert sum(e["event"] == "key_down" for e in events) == 1


def test_key_action_runs_once_per_event_not_per_char(tmp_path: Path) -> None:
    app, path = make_app(tmp_path, Scene.WORLD)
    app._key_down(key_event("i", "ii", 0x49), "main")  # pyright: ignore[reportArgumentType]
    # I는 인벤토리 열기/닫기 토글 — 글자 수만큼 돌면 다시 닫힌다
    assert app.game.scene is Scene.INVENTORY
    assert [e["text"] for e in records(app, path) if e["event"] == "char"] == ["i", "i"]


def test_ctrl_a_selects_field_then_backspace_clears(tmp_path: Path) -> None:
    """Ctrl을 누른 채 A는 게임에 `ctrl+a`(전체 고르기)로 간다. 글자(\\x01)는 들어가지 않는다."""
    app, path = make_app(tmp_path, Scene.LOGIN)
    app._key_down(key_event("a", "abc"), "main")  # pyright: ignore[reportArgumentType]
    app._key_up(key_event("a", ""), "main")  # pyright: ignore[reportArgumentType]
    app._key_down(key_event("Control_L", "", 0x11), "main")  # pyright: ignore[reportArgumentType]
    app._key_down(key_event("a", "\x01", state=CTRL), "main")  # pyright: ignore[reportArgumentType]
    assert app.game.selected and app.game.account == "abc"
    app._key_up(key_event("a", "", state=CTRL), "main")  # pyright: ignore[reportArgumentType]
    app._key_up(key_event("Control_L", "", 0x11, CTRL), "main")  # pyright: ignore[reportArgumentType]
    app._key_down(key_event("BackSpace", "\b", 0x08), "main")  # pyright: ignore[reportArgumentType]
    assert (app.game.account, app.game.selected) == ("", False)
    events = records(app, path)
    # 기록에는 키 이름 그대로 (조합 이름은 게임 안에서만)
    assert [e["key"] for e in events if e["event"] == "key_down"] == [
        "a",
        "lctrl",
        "a",
        "backspace",
    ]
    assert [e["text"] for e in events if e["event"] == "char"] == ["a", "b", "c"]


def two_window_login_app(tmp_path: Path) -> App:
    app, _ = make_app(tmp_path, Scene.LOGIN)
    app._held = {"main": set(), "second": set()}
    app.game.account = "abc"
    return app


@pytest.mark.parametrize("release_window", ["main", "second"])
def test_plain_key_after_ctrl_released_in_other_window(tmp_path: Path, release_window: str) -> None:
    """검수 반례: 메인에서 누른 Ctrl을 다른 창에서 떼고 돌아와도 메인의 누른 키 기록에 Ctrl이
    남는다. 조합은 이벤트의 modifier 상태로 정하므로 평범한 Backspace는 한 글자만 지운다."""
    app = two_window_login_app(tmp_path)
    app._key_down(key_event("Control_L", "", 0x11), "main")  # pyright: ignore[reportArgumentType]
    if release_window == "second":
        switch_focus(app, "main", "second")
    app._key_up(key_event("Control_L", "", 0x11, CTRL), release_window)  # pyright: ignore[reportArgumentType]
    if release_window == "second":
        switch_focus(app, "second", "main")
        assert "lctrl" in app._held["main"]  # 기록은 남지만 조합 판정에 쓰지 않는다
    app._key_down(key_event("BackSpace", "\b", 0x08), "main")  # pyright: ignore[reportArgumentType]
    assert (app.game.account, app.game.selected) == ("ab", False)


@pytest.mark.parametrize("press_window", ["main", "second"])
def test_ctrl_a_with_ctrl_pressed_in_other_window(tmp_path: Path, press_window: str) -> None:
    """검수 반례: 다른 창에서 Ctrl을 누른 채 메인으로 오면 메인 기록에는 Ctrl이 없지만, A 이벤트의
    modifier 상태에 Ctrl이 있으므로 전체 고르기다."""
    app = two_window_login_app(tmp_path)
    app._key_down(key_event("Control_L", "", 0x11), press_window)  # pyright: ignore[reportArgumentType]
    if press_window == "second":
        switch_focus(app, "second", "main")
        assert not app._held["main"]
    app._key_down(key_event("a", "\x01", state=CTRL), "main")  # pyright: ignore[reportArgumentType]
    assert app.game.selected and app.game.account == "abc"


def test_string_event_state_is_no_modifier(tmp_path: Path) -> None:
    """Tk가 state를 수로 못 바꾸면 문자열로 준다: 조합 없는 키로 본다."""
    app = two_window_login_app(tmp_path)
    app._key_down(key_event("BackSpace", "\b", 0x08, "??"), "main")  # pyright: ignore[reportArgumentType]
    assert app.game.account == "ab"


def test_control_chars_not_typed(tmp_path: Path) -> None:
    app, path = make_app(tmp_path, Scene.LOGIN)
    app._key_down(key_event("Tab", "\t", 0x09), "main")  # pyright: ignore[reportArgumentType]
    assert (app.game.account, app.game.focus) == ("", "password")
    assert not any(e["event"] == "char" for e in records(app, path))
