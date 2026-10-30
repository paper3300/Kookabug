"""창 껍데기의 키 처리 (창 없이 처리기만)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sample_game.app import App, EventLog, printable_chars
from sample_game.flow import Scene, scene_state
from sample_game.options import parse_args


def make_app(tmp_path: Path, scene: Scene) -> tuple[App, Path]:
    path = tmp_path / "events.jsonl"
    app = App(parse_args(["--start-scene", scene.value]), scene_state(scene), EventLog(path))
    app._held["main"] = set()
    return app, path


def key_event(keysym: str, char: str, keycode: int = 0x41) -> SimpleNamespace:
    return SimpleNamespace(keysym=keysym, char=char, keycode=keycode)


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


def test_control_chars_not_typed(tmp_path: Path) -> None:
    app, path = make_app(tmp_path, Scene.LOGIN)
    app._key_down(key_event("Tab", "\t", 0x09), "main")  # pyright: ignore[reportArgumentType]
    assert (app.game.account, app.game.focus) == ("", "password")
    assert not any(e["event"] == "char" for e in records(app, path))
