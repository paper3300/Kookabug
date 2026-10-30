"""키별 훅 래퍼 `HookedBackend` (구현 계획 M1 2.4 "훅 래퍼").

M0b 가짜 백엔드 안에 있던 훅 검사를 래퍼 위에서 그대로 돌린다. 안쪽 백엔드는 가짜 기록 백엔드와,
가짜가 아닌 백엔드 자리를 흉내 내는 호출 기록 백엔드 둘 다다(`kind: windows`에서도 훅이 먹는다).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from kb_testing.proc import barrier, read_fake_input_log
from kookabug_core.inputs import FakeBackend, HookAction, HookedBackend, InputBackend
from kookabug_sdk.types import Point


class Recorder:
    """호출만 남기는 백엔드 (가짜 기록 파일이 없는 실제 백엔드 자리)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    @property
    def available(self) -> bool:
        return True

    def down(self, key: str) -> None:
        self.calls.append(("down", key))

    def up(self, key: str) -> None:
        self.calls.append(("up", key))

    def mouse_down(self, button: str, at: Point | None = None) -> None:
        self.calls.append(("down", f"mouse:{button}"))

    def mouse_up(self, button: str) -> None:
        self.calls.append(("up", f"mouse:{button}"))

    def move(self, at: Point) -> None:
        self.calls.append(("move", f"{at.x},{at.y}"))

    def wheel(self, amount: int, at: Point | None = None) -> None:
        self.calls.append(("wheel", str(amount)))

    def text(self, text: str) -> None:
        self.calls.append(("text", text))


class Inner:
    """안쪽 백엔드와 "지금까지 몇 번 불렸나" (훅 자리 확인용)."""

    def __init__(self, kind: str, tmp_path: Path) -> None:
        self.kind = kind
        if kind == "fake":
            self.log = tmp_path / "input.jsonl"
            self.backend: InputBackend = FakeBackend(self.log)
            self.recorder: Recorder | None = None
        else:
            self.recorder = Recorder()
            self.backend = self.recorder

    def ops(self) -> list[str]:
        if self.recorder is not None:
            return [op for op, _ in self.recorder.calls]
        return [line["op"] for line in read_fake_input_log(self.log)] if self.log.exists() else []


@pytest.fixture(params=["fake", "recorder"])
def inner(request: pytest.FixtureRequest, tmp_path: Path) -> Inner:
    return Inner(request.param, tmp_path)


def wrap(
    inner: Inner,
    hooks: dict[str, dict[str, HookAction]],
    gate: threading.Event | None = None,
) -> HookedBackend:
    return HookedBackend(inner.backend, hooks, gate=gate)


def test_hooks_before_after_down_before_up(inner: Inner) -> None:
    seen: list[tuple[str, int]] = []

    def at(name: str) -> Callable[[], None]:
        return lambda: seen.append((name, len(inner.ops())))

    backend = wrap(
        inner,
        {
            "before_down": {"a": at("before_down"), "mouse:left": at("mouse.before_down")},
            "after_down": {"a": at("after_down")},
            "before_up": {"a": at("before_up")},
        },
    )
    backend.down("a")
    backend.up("a")
    backend.down("b")  # 훅이 없는 키
    backend.mouse_down("left")
    # 훅은 안쪽 호출 앞뒤 정해진 자리에서 돈다
    assert seen == [
        ("before_down", 0),
        ("after_down", 1),
        ("before_up", 1),
        ("mouse.before_down", 3),
    ]


def test_hook_actions_block_and_wait(inner: Inner, tmp_path: Path) -> None:
    gate = threading.Event()
    wall = barrier(tmp_path / "wall")
    backend = wrap(
        inner,
        {"after_down": {"a": "block"}, "before_up": {"a": f"wait:{wall.path}"}},
        gate=gate,
    )
    done = threading.Event()

    def press() -> None:
        backend.down("a")
        backend.up("a")
        done.set()

    thread = threading.Thread(target=press, daemon=True)
    thread.start()
    # block: 게이트가 닫힐 때까지 down 안에서 기다린다
    assert not done.wait(0.2)
    assert inner.ops() == ["down"]
    gate.set()
    # wait:<경로>: 파일 장벽에서 up 전에 기다린다
    wall.wait_ready()
    assert inner.ops() == ["down"]
    wall.go()
    assert done.wait(10)
    assert inner.ops() == ["down", "up"]


def test_move_wheel_text_pass_through(inner: Inner) -> None:
    calls: list[str] = []
    backend = wrap(inner, {"before_down": {"mouse:left": lambda: calls.append("hook")}})
    backend.move(Point(1, 2))
    backend.wheel(3, Point(1, 2))
    backend.text("가")
    assert calls == []
    assert inner.ops() == ["move", "wheel", "text"]
    assert backend.available


def test_bad_hooks_rejected(inner: Inner) -> None:
    with pytest.raises(ValueError, match="gate"):
        wrap(inner, {"after_down": {"a": "block"}})
    with pytest.raises(ValueError, match="훅 동작"):
        wrap(inner, {"after_down": {"a": "explode"}})
    with pytest.raises(ValueError, match="모르는 훅"):
        wrap(inner, {"after_up": {"a": "hang"}})
