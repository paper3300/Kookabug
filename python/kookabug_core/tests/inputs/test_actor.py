"""입력 액터 (구현 계획 M0b 2.4 "입력 액터 계약")."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from kb_testing.proc import read_fake_input_log, wait_until
from kookabug_core.inputs import (
    ACTOR_THREAD_NAME,
    FakeBackend,
    HookAction,
    InputActor,
    NoneBackend,
    PlatformUnavailable,
    create_backend,
)
from kookabug_core.inputs.actor import _Marker  # pyright: ignore[reportPrivateUsage]
from kookabug_core.record import InputKey
from kookabug_sdk.context import Cancelled
from kookabug_sdk.types import Point, Rect, Secret

FAST = 1.0  # 제어 쪽 호출이 "곧바로" 돌아왔다고 볼 상한 (초)


class Rig:
    """가짜 백엔드 + 이벤트 목록 + 액터. 훅은 스레드 장벽으로 넣는다."""

    def __init__(self, tmp_path: Path, hooks: Mapping[str, Mapping[str, HookAction]] | None = None):
        self.log = tmp_path / "input.jsonl"
        self.events: list[dict[str, Any]] = []
        self.gate = threading.Event()
        self.backend = FakeBackend(self.log, run="r0000001", hooks=hooks, gate=self.gate)
        self.actor = InputActor(self.backend, emit=self.emit, gate=self.gate)
        self.threads: list[threading.Thread] = []
        self.errors: dict[str, BaseException] = {}

    def emit(self, event: Mapping[str, Any]) -> None:
        self.events.append(dict(event))

    def lines(self) -> list[dict[str, Any]]:
        return read_fake_input_log(self.log)

    def ops(self) -> list[tuple[str, str]]:
        return [(line["op"], line.get("key") or line.get("button") or "") for line in self.lines()]

    def wait_ops(self, count: int) -> list[tuple[str, str]]:
        """요청이 Cancelled로 끝난 뒤 액터의 RELEASE_ALL까지 기다린다."""
        wait_until(lambda: len(self.lines()) >= count, message=f"원시 동작 {count}개")
        return self.ops()

    def in_thread(self, name: str, fn: Callable[[], None]) -> threading.Thread:
        def body() -> None:
            try:
                fn()
            except BaseException as exc:
                self.errors[name] = exc

        thread = threading.Thread(target=body, name=name, daemon=True)
        thread.start()
        self.threads.append(thread)
        return thread

    def join(self) -> None:
        for thread in self.threads:
            thread.join(10)
            assert not thread.is_alive()


class Latch:
    """훅 자리의 스레드 장벽: 들어오면 `entered`, `release()`까지 기다린다."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self._go = threading.Event()

    def __call__(self) -> None:
        self.entered.set()
        self._go.wait()

    def wait_entered(self) -> None:
        assert self.entered.wait(10), "훅에 들어오지 않았다"

    def release(self) -> None:
        self._go.set()


@pytest.fixture
def latches() -> Iterator[list[Latch]]:
    made: list[Latch] = []
    yield made
    for latch in made:  # 걸린 액터 스레드를 남기지 않는다
        latch.release()


def latch(made: list[Latch]) -> Latch:
    item = Latch()
    made.append(item)
    return item


def test_all_backend_calls_on_actor_thread(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.actor.start()
    rig.actor.key("a")
    rig.in_thread("other", lambda: rig.actor.click(Point(1, 2), button="right"))
    rig.in_thread("third", lambda: rig.actor.type_text("hi"))
    rig.join()
    assert rig.actor.stop(10)
    lines = rig.lines()
    assert len(lines) == 5
    assert {line["thread"] for line in lines} == {ACTOR_THREAD_NAME}


def test_down_event_before_backend_down(tmp_path: Path) -> None:
    seen: list[tuple[list[dict[str, Any]], int]] = []
    rig: Rig

    def before_down() -> None:
        seen.append((list(rig.events), len(rig.lines())))

    rig = Rig(tmp_path, hooks={"before_down": {"a": before_down}})
    rig.actor.start()
    rig.actor.key("a")
    rig.actor.stop(10)
    events, logged = seen[0]
    # 백엔드가 누르기 전에 이미 input.down이 기록돼 있다
    assert [e["event"] for e in events] == ["input.down"]
    assert events[0]["key"] == "a"
    assert logged == 0


def test_up_event_after_backend_up(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    seen: list[list[tuple[str, str]]] = []
    original = rig.emit

    def emit(event: Mapping[str, Any]) -> None:
        if event["event"] == "input.up":
            seen.append(rig.ops())
        original(event)

    rig.actor = InputActor(rig.backend, emit=emit, gate=rig.gate).start()
    rig.actor.key("a")
    rig.actor.stop(10)
    # input.up을 쓸 때 백엔드는 이미 뗐다
    assert seen == [[("down", "a"), ("up", "a")]]
    assert [e["event"] for e in rig.events] == ["input.down", "input.up"]


def test_click_key_split_into_down_up_without_interleaving(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.actor.start()
    rounds = 20

    def keys() -> None:
        for _ in range(rounds):
            rig.actor.key("ctrl+a")

    def clicks() -> None:
        for _ in range(rounds):
            rig.actor.click(Rect(0, 0, 10, 10))

    rig.in_thread("t1", keys)
    rig.in_thread("t2", clicks)
    rig.join()
    assert not rig.errors
    rig.actor.stop(10)
    ops = rig.ops()
    combo = [("down", "ctrl"), ("down", "a"), ("up", "a"), ("up", "ctrl")]
    click = [("down", "left"), ("up", "left")]
    counts = {"combo": 0, "click": 0}
    i = 0
    while i < len(ops):
        if ops[i : i + 4] == combo:
            counts["combo"] += 1
            i += 4
        elif ops[i : i + 2] == click:
            counts["click"] += 1
            i += 2
        else:
            pytest.fail(f"요청의 원시 동작이 섞였다: {ops[i : i + 4]}")
    assert counts == {"combo": rounds, "click": rounds}
    assert {
        tuple(line["at"])
        for line in rig.lines()
        if line["device"] == "mouse" and line["op"] == "down"
    } == {(5, 5)}


def test_gate_closes_immediately_queued_requests_cancelled(
    tmp_path: Path, latches: list[Latch]
) -> None:
    hold = latch(latches)
    rig = Rig(tmp_path, hooks={"after_down": {"ctrl": hold}})
    rig.actor.start()
    rig.in_thread("first", lambda: rig.actor.key("ctrl"))
    hold.wait_entered()
    rig.in_thread("second", lambda: rig.actor.key("x"))
    rig.in_thread("third", lambda: rig.actor.type_text("y"))
    wait_until(lambda: len(rig.actor._queue) == 2)  # pyright: ignore[reportPrivateUsage]

    started = time.monotonic()
    rig.actor.close_gate()
    assert time.monotonic() - started < FAST
    hold.release()
    rig.join()

    assert {name: type(exc) for name, exc in rig.errors.items()} == {
        "first": Cancelled,
        "second": Cancelled,
        "third": Cancelled,
    }
    # 대기 중이던 요청은 백엔드에 닿지 않았다. 누른 ctrl은 RELEASE_ALL이 뗐다
    assert rig.wait_ops(2) == [("down", "ctrl"), ("up", "ctrl")]
    assert rig.actor.stop(10)
    assert rig.ops() == [("down", "ctrl"), ("up", "ctrl")]


def test_release_all_runs_after_current_primitive(tmp_path: Path, latches: list[Latch]) -> None:
    hold = latch(latches)
    rig = Rig(tmp_path, hooks={"after_down": {"ctrl": hold}})
    rig.actor.start()
    rig.in_thread("main", lambda: rig.actor.key("ctrl"))
    hold.wait_entered()

    started = time.monotonic()
    rig.actor.close_gate()  # 제어 스레드(여기)는 백엔드를 부르지 않고 바로 돌아온다
    assert time.monotonic() - started < FAST
    assert rig.ops() == [("down", "ctrl")]

    hold.release()
    rig.join()
    assert isinstance(rig.errors["main"], Cancelled)
    rig.wait_ops(2)
    lines = rig.lines()
    assert [(line["op"], line["key"]) for line in lines] == [("down", "ctrl"), ("up", "ctrl")]
    # 마지막 물리 동작은 액터의 up이다
    assert lines[-1]["thread"] == ACTOR_THREAD_NAME
    assert rig.actor.stop(10)
    assert [e["event"] for e in rig.events] == ["input.down", "input.up"]


def test_release_all_placed_before_pending_requests(tmp_path: Path, latches: list[Latch]) -> None:
    hold = latch(latches)
    rig = Rig(tmp_path, hooks={"after_down": {"ctrl": hold}})
    rig.actor.start()
    rig.in_thread("first", lambda: rig.actor.key("ctrl"))
    hold.wait_entered()
    rig.in_thread("pending", lambda: rig.actor.key("x"))
    wait_until(lambda: len(rig.actor._queue) == 1)  # pyright: ignore[reportPrivateUsage]
    rig.actor.close_gate()
    # 대기 요청은 큐에서 빠져 바로 취소되고, 큐 맨 앞에는 RELEASE_ALL만 남는다
    queue = list(rig.actor._queue)  # pyright: ignore[reportPrivateUsage]
    assert queue == [_Marker.RELEASE_ALL]
    wait_until(lambda: "pending" in rig.errors)
    assert isinstance(rig.errors["pending"], Cancelled)
    hold.release()
    rig.join()
    assert rig.actor.stop(10)
    assert rig.ops() == [("down", "ctrl"), ("up", "ctrl")]


def test_requests_after_gate_closed_rejected(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.actor.start()
    rig.actor.close_gate()
    with pytest.raises(Cancelled):
        rig.actor.key("a")
    with pytest.raises(Cancelled):
        rig.actor.click(Point(0, 0))
    assert rig.lines() == []
    assert rig.actor.stop(10)


def test_stop_drains_and_joins(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.actor.start()
    for key in ("a", "b", "c"):
        rig.actor.key(key)
    assert rig.actor.stop(10) is True
    assert rig.actor.quiesced
    thread = rig.actor._thread  # pyright: ignore[reportPrivateUsage]
    assert thread is not None and not thread.is_alive()
    with pytest.raises(Cancelled):
        rig.actor.key("d")
    assert len(rig.lines()) == 6


def test_quiesced_only_after_actor_joined_and_nothing_held(
    tmp_path: Path, latches: list[Latch]
) -> None:
    # 액터가 살아 있으면 quiesced가 아니다
    rig = Rig(tmp_path)
    rig.actor.start()
    assert not rig.actor.quiesced
    assert rig.actor.stop(10)

    # 액터는 끝났지만 떼지 못한 키가 남으면 quiesced가 아니다
    hold = latch(latches)

    def refuse_up() -> None:
        raise OSError("가짜 백엔드가 떼기를 거부")

    rig2 = Rig(
        tmp_path / "2", hooks={"after_down": {"ctrl": hold}, "before_up": {"ctrl": refuse_up}}
    )
    rig2.actor.start()
    rig2.in_thread("main", lambda: rig2.actor.key("ctrl"))
    hold.wait_entered()
    rig2.actor.close_gate()
    hold.release()
    rig2.join()
    assert rig2.actor.stop(10) is False
    thread = rig2.actor._thread  # pyright: ignore[reportPrivateUsage]
    assert thread is not None and not thread.is_alive()
    assert rig2.actor.held == [InputKey("keyboard", "ctrl")]
    assert not rig2.actor.quiesced
    assert isinstance(rig2.actor.errors[0], OSError)
    # 기록에도 up이 없다 → 다음 소유자가 복구한다
    assert [e["event"] for e in rig2.events] == ["input.down"]


def test_hung_backend_blocks_actor_not_control_thread(tmp_path: Path, latches: list[Latch]) -> None:
    hang = latch(latches)  # 테스트가 끝날 때까지 풀지 않는다 (가짜 백엔드 hang 자리)
    rig = Rig(tmp_path, hooks={"after_down": {"ctrl": hang}})
    rig.actor.start()
    rig.in_thread("main", lambda: rig.actor.key("ctrl"))
    hang.wait_entered()

    started = time.monotonic()
    rig.actor.close_gate()
    assert time.monotonic() - started < FAST
    assert rig.actor.stop(0.3) is False
    assert not rig.actor.quiesced
    assert rig.ops() == [("down", "ctrl")]
    assert rig.actor.held == []  # held에 넣기 전(백엔드 안)에서 멈췄다


def test_mouse_buttons_and_multiple_keys_released(tmp_path: Path, latches: list[Latch]) -> None:
    hold = latch(latches)
    rig = Rig(tmp_path, hooks={"after_down": {"a": hold}})
    rig.actor.start()
    rig.in_thread("keys", lambda: rig.actor.key("ctrl+shift+a"))
    hold.wait_entered()
    rig.actor.close_gate()
    hold.release()
    rig.join()
    # 누른 순서의 거꾸로 뗀다
    assert rig.wait_ops(6) == [
        ("down", "ctrl"),
        ("down", "shift"),
        ("down", "a"),
        ("up", "a"),
        ("up", "shift"),
        ("up", "ctrl"),
    ]
    assert rig.actor.stop(10)

    hold2 = latch(latches)
    rig2 = Rig(tmp_path / "mouse", hooks={"after_down": {"mouse:right": hold2}})
    rig2.actor.start()
    rig2.in_thread("click", lambda: rig2.actor.click(Point(3, 4), button="right"))
    hold2.wait_entered()
    rig2.actor.close_gate()
    hold2.release()
    rig2.join()
    assert rig2.actor.stop(10)
    lines = rig2.lines()
    assert [(line["op"], line["device"], line["button"]) for line in lines] == [
        ("down", "mouse", "right"),
        ("up", "mouse", "right"),
    ]
    assert rig2.events[-1] == {"event": "input.up", "device": "mouse", "button": "right"}


def test_secret_text_not_in_events(tmp_path: Path) -> None:
    received: list[str] = []

    class Recording(FakeBackend):
        def text(self, text: str) -> None:
            received.append(text)
            super().text(text)

    events: list[Mapping[str, Any]] = []
    actor = InputActor(Recording(tmp_path / "input.jsonl"), emit=events.append).start()
    actor.type_text(Secret("hunter2"), step="s1")
    actor.type_text("plain")
    actor.stop(10)
    assert received == ["hunter2", "plain"]  # 원문은 백엔드에만 간다
    assert events == []
    assert "hunter2" not in (tmp_path / "input.jsonl").read_text(encoding="utf-8")


def test_none_backend_is_platform_unavailable(tmp_path: Path) -> None:
    events: list[Mapping[str, Any]] = []
    actor = InputActor(create_backend("none"), emit=events.append).start()
    assert isinstance(actor.backend, NoneBackend)
    with pytest.raises(PlatformUnavailable) as caught:
        actor.key("a")
    assert caught.value.code == "platform_unavailable"
    with pytest.raises(PlatformUnavailable):
        actor.click(Point(0, 0))
    assert events == []
    assert actor.stop(10)


def test_pending_requests_cancelled_while_release_blocked(
    tmp_path: Path, latches: list[Latch]
) -> None:
    down = latch(latches)
    up = latch(latches)
    rig = Rig(tmp_path, hooks={"after_down": {"ctrl": down}, "before_up": {"ctrl": up}})
    rig.actor.start()
    rig.in_thread("first", lambda: rig.actor.key("ctrl"))
    down.wait_entered()
    pending = rig.in_thread("pending", lambda: rig.actor.key("x"))
    wait_until(lambda: len(rig.actor._queue) == 1)  # pyright: ignore[reportPrivateUsage]
    rig.actor.close_gate()
    # 대기 요청은 게이트를 닫는 자리에서 끝난다 (액터가 아직 down 안에 있어도)
    pending.join(10)
    assert isinstance(rig.errors["pending"], Cancelled)

    down.release()
    up.wait_entered()  # RELEASE_ALL의 up이 멈춰 있다
    rig.join()
    assert isinstance(rig.errors["first"], Cancelled)
    assert rig.actor.stop(0.2) is False  # 떼기가 끝나지 않았으므로 quiesced가 아니다
    up.release()
    assert rig.actor.stop(10)
    assert rig.ops() == [("down", "ctrl"), ("up", "ctrl")]


def test_journal_failure_blocks_queued_and_later_input(
    tmp_path: Path, latches: list[Latch]
) -> None:
    at_up = latch(latches)
    rig = Rig(tmp_path, hooks={"before_up": {"a": at_up}})
    written: list[dict[str, Any]] = []

    def emit(event: Mapping[str, Any]) -> None:
        if event["event"] == "input.up" and event["key"] == "a":
            raise OSError("저널 쓰기 실패")
        written.append(dict(event))

    rig.actor = InputActor(rig.backend, emit=emit, gate=rig.gate).start()
    rig.in_thread("a", lambda: rig.actor.key("a"))
    at_up.wait_entered()
    rig.in_thread("b", lambda: rig.actor.key("b"))
    wait_until(lambda: len(rig.actor._queue) == 1)  # pyright: ignore[reportPrivateUsage]
    at_up.release()
    rig.join()

    assert isinstance(rig.errors["a"], OSError)
    assert isinstance(rig.errors["b"], Cancelled)
    assert isinstance(rig.actor.journal_error, OSError)
    assert rig.actor.gate_closed
    with pytest.raises(Cancelled):
        rig.actor.key("c")
    assert rig.actor.stop(10)
    # 실패 뒤에는 새 입력도 기록도 없다
    assert rig.ops() == [("down", "a"), ("up", "a")]
    assert written == [{"event": "input.down", "device": "keyboard", "key": "a"}]


def test_journal_failure_on_down_releases_held_without_recording(
    tmp_path: Path, latches: list[Latch]
) -> None:
    hold = latch(latches)
    rig = Rig(tmp_path, hooks={"after_down": {"ctrl": hold}})
    written: list[str] = []

    def emit(event: Mapping[str, Any]) -> None:
        if event["event"] == "input.down" and event["key"] == "x":
            raise OSError("저널 쓰기 실패")
        written.append(f"{event['event']}:{event['key']}")

    rig.actor = InputActor(rig.backend, emit=emit, gate=rig.gate).start()
    rig.in_thread("ctrl", lambda: rig.actor.key("ctrl+x"))
    hold.wait_entered()
    hold.release()
    rig.join()
    assert isinstance(rig.errors["ctrl"], OSError)
    assert rig.actor.stop(10)
    # x는 누르지 않았고, 이미 누른 ctrl은 뗐지만 기록하지 않았다 (기록상 눌렸을 수 있음 → 복구 대상)
    assert rig.ops() == [("down", "ctrl"), ("up", "ctrl")]
    assert written == ["input.down:ctrl"]


def test_unstarted_actor_not_quiesced_and_stop_is_final(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    assert not rig.actor.quiesced
    with pytest.raises(RuntimeError, match="시작하지 않았다"):
        rig.actor.key("a")
    assert rig.actor.stop(10) is True
    assert rig.actor.quiesced
    with pytest.raises(RuntimeError, match="다시 시작하지 않는다"):
        rig.actor.start()
    with pytest.raises(Cancelled):
        rig.actor.key("a")

    started = Rig(tmp_path / "2")
    started.actor.start()
    assert started.actor.stop(10)
    with pytest.raises(RuntimeError):
        started.actor.start()
    assert started.lines() == [] and rig.lines() == []
