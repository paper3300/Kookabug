"""`--press-feedback`: 왼쪽 버튼 down에서 단추를 눌린 색으로, up에서 되돌림 (M4 T4, 창 없이).

그리기 명령을 기록하는 가짜 Canvas로 본다. 옵션이 없으면 그리기 명령이 옵션 도입 전과 같다(눌림
상태를 아예 만들지 않음) — 화면 PNG 신선도는 `test_frames_fresh`가 따로 본다.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sample_game.app import App, EventLog
from sample_game.flow import Scene, scene_state
from sample_game.layout import BUTTONS
from sample_game.options import parse_args
from sample_game.render import ACCENT, PRESSED, draw

START = BUTTONS[Scene.TITLE][0]


class RecordingCanvas:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        def record(*args: Any, **kwargs: Any) -> None:
            self.calls.append((name, args, kwargs))

        return record


def fills(canvas: RecordingCanvas) -> list[str]:
    return [kw.get("fill", "") for name, _a, kw in canvas.calls if name == "create_rectangle"]


def make_app(tmp_path: Path, *extra: str) -> tuple[App, RecordingCanvas]:
    options = parse_args(["--start-scene", Scene.TITLE.value, *extra])
    app = App(options, scene_state(Scene.TITLE), EventLog(tmp_path / "events.jsonl"))
    app._held["main"] = set()
    canvas = RecordingCanvas()
    app.canvas = canvas  # pyright: ignore[reportAttributeAccessIssue]
    return app, canvas


def mouse(app: App, kind: str, x: int, y: int, num: int = 1) -> None:
    app._mouse(SimpleNamespace(num=num, x=x, y=y), "main", kind)  # pyright: ignore[reportArgumentType]


def center(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    return rect[0] + rect[2] // 2, rect[1] + rect[3] // 2


def test_draw_without_pressed_is_unchanged() -> None:
    game = scene_state(Scene.TITLE)
    plain, explicit = RecordingCanvas(), RecordingCanvas()
    draw(plain, game, (1024, 640), "f")  # pyright: ignore[reportArgumentType]
    draw(explicit, game, (1024, 640), "f", None)  # pyright: ignore[reportArgumentType]
    assert plain.calls == explicit.calls
    assert ACCENT in fills(plain) and PRESSED not in fills(plain)


def test_press_feedback_on_down_colors_button_and_up_restores(tmp_path: Path) -> None:
    app, canvas = make_app(tmp_path, "--press-feedback")
    x, y = center(START.rect)
    mouse(app, "mouse_down", x, y)
    assert app.pressed == START.id
    assert PRESSED in fills(canvas)
    canvas.calls.clear()
    mouse(app, "mouse_up", x, y)
    assert app.pressed is None
    assert PRESSED not in fills(canvas)
    assert app.game.scene is Scene.LOGIN  # 클릭 판정은 그대로 (뗄 때)


def test_press_outside_button_or_right_button_draws_nothing_new(tmp_path: Path) -> None:
    app, canvas = make_app(tmp_path, "--press-feedback")
    mouse(app, "mouse_down", 5, 5)
    assert app.pressed is None and canvas.calls == []
    x, y = center(START.rect)
    mouse(app, "mouse_down", x, y, num=3)  # 오른쪽 버튼
    assert app.pressed is None and canvas.calls == []


def test_without_option_down_does_not_redraw(tmp_path: Path) -> None:
    app, canvas = make_app(tmp_path)
    x, y = center(START.rect)
    mouse(app, "mouse_down", x, y)
    assert app.pressed is None
    assert canvas.calls == []  # 옵션 없이는 down에서 다시 그리지도 않는다
