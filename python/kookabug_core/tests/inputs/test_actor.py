"""입력 액터 (구현 계획 M0b 2.4 "입력 액터 계약")."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from kb_testing.proc import read_fake_input_log, wait_until
from kookabug_core.engine.errors import EngineError
from kookabug_core.inputs import (
    ACTOR_THREAD_NAME,
    ClientPoint,
    FakeBackend,
    GuardedOp,
    HookAction,
    HookedBackend,
    InputActor,
    NoneBackend,
    PlatformUnavailable,
    create_backend,
)
from kookabug_core.inputs.actor import _Marker  # pyright: ignore[reportPrivateUsage]
from kookabug_core.inputs.keys import KeyUnknown
from kookabug_core.record import InputKey, Journal, held_inputs, read_run
from kookabug_core.record.runfolder import EVENTS_FILE
from kookabug_sdk.context import Cancelled
from kookabug_sdk.types import Match, Point, Rect, Secret

FAST = 1.0  # 제어 쪽 호출이 "곧바로" 돌아왔다고 볼 상한 (초)


class Rig:
    """가짜 백엔드 + 이벤트 목록 + 액터. 훅은 스레드 장벽으로 넣는다."""

    def __init__(
        self,
        tmp_path: Path,
        hooks: Mapping[str, Mapping[str, HookAction]] | None = None,
        guard: Guard | None = None,
    ):
        self.log = tmp_path / "input.jsonl"
        self.events: list[dict[str, Any]] = []
        self.gate = threading.Event()
        self.fake = FakeBackend(self.log, run="r0000001")
        self.backend = HookedBackend(self.fake, hooks or {}, gate=self.gate)
        self.actor = InputActor(self.backend, emit=self.emit, gate=self.gate, guard=guard)
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
    rig.in_thread("other", lambda: rig.actor.click(ClientPoint(1, 2), button="right"))
    rig.in_thread("third", lambda: rig.actor.type_text("hi"))
    rig.join()
    assert rig.actor.stop(10)
    lines = rig.lines()
    assert len(lines) == 7  # a 누르기·떼기, 이동·버튼 누르기·떼기, 글자 둘(글자마다 하나)
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
            rig.actor.click(ClientPoint(5, 5))

    rig.in_thread("t1", keys)
    rig.in_thread("t2", clicks)
    rig.join()
    assert not rig.errors
    rig.actor.stop(10)
    ops = rig.ops()
    combo = [("down", "ctrl"), ("down", "a"), ("up", "a"), ("up", "ctrl")]
    click = [("move", ""), ("down", "left"), ("up", "left")]
    counts = {"combo": 0, "click": 0}
    i = 0
    while i < len(ops):
        if ops[i : i + 4] == combo:
            counts["combo"] += 1
            i += 4
        elif ops[i : i + 3] == click:
            counts["click"] += 1
            i += 3
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
        rig.actor.click(ClientPoint(0, 0))
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
    rig2.in_thread("click", lambda: rig2.actor.click(ClientPoint(3, 4), button="right"))
    hold2.wait_entered()
    rig2.actor.close_gate()
    hold2.release()
    rig2.join()
    assert rig2.actor.stop(10)
    lines = [line for line in rig2.lines() if line["op"] != "move"]
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
    assert "".join(received) == "hunter2plain"  # 원문은 백엔드에만 간다 (글자마다 하나씩)
    assert len(received) == len("hunter2plain")
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
        actor.click(ClientPoint(0, 0))
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


# ── M1 T5: 이동·휠, 입력 직전 확인, 요청 단위 원자성, ClientPoint ───────────────


class Guard:
    """입력 직전 확인 흉내: 부른 자리를 남기고, 화면 좌표 = 클라이언트 + (100, 200)."""

    def __init__(self, log: Path, fail: Callable[[GuardedOp, int], bool] | None = None) -> None:
        self.log = log
        self.fail = fail
        self.calls: list[tuple[GuardedOp, object | None, ClientPoint | None, str, int]] = []

    def check(self, op: GuardedOp, target: object | None, at: ClientPoint | None) -> Point | None:
        logged = len(read_fake_input_log(self.log)) if self.log.exists() else 0
        self.calls.append((op, target, at, threading.current_thread().name, logged))
        if self.fail is not None and self.fail(op, len(self.calls)):
            raise EngineError("window_not_foreground", "확인 실패 (검사)")
        return None if at is None else Point(at.x + 100, at.y + 200)


def test_move_and_wheel_not_recorded_as_held(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.actor.start()
    rig.actor.scroll(ClientPoint(3, 4), -2, step="s1")
    assert rig.events == []  # 이동·휠은 누르기 기록 대상이 아니다
    assert rig.actor.held == []
    rig.actor.drag(ClientPoint(0, 0), ClientPoint(32, 16), duration_ms=40, step="s2")
    assert rig.actor.stop(10)
    lines = rig.lines()
    assert [(line["op"], line.get("at"), line.get("amount")) for line in lines[:2]] == [
        ("move", [3, 4], None),
        ("wheel", [3, 4], -2),
    ]
    drag = [(line["op"], line.get("at")) for line in lines[2:]]
    # move(시작) → down → 보간 move 3개(40ms / 16ms) → up
    assert drag == [
        ("move", [0, 0]),
        ("down", [0, 0]),
        ("move", [11, 5]),
        ("move", [21, 11]),
        ("move", [32, 16]),
        ("up", None),
    ]
    # 드래그의 버튼만 누르기·떼기로 기록된다
    assert [(e["event"], e.get("button")) for e in rig.events] == [
        ("input.down", "left"),
        ("input.up", "left"),
    ]


def test_before_primitive_runs_on_actor_thread_before_down(tmp_path: Path) -> None:
    guard = Guard(tmp_path / "input.jsonl")
    rig = Rig(tmp_path, guard=guard)
    rig.actor.start()
    target = object()
    rig.actor.click(ClientPoint(1, 2), target=target)
    rig.actor.key("a", target=target)
    rig.actor.type_text("hi", target=target)
    assert rig.actor.stop(10)
    # down·text·move 직전마다, 그 요청의 대상과 함께, 액터 스레드에서. up에는 확인이 없다
    assert [(op, at, thread) for op, _, at, thread, _ in guard.calls] == [
        ("move", ClientPoint(1, 2), ACTOR_THREAD_NAME),
        ("down", ClientPoint(1, 2), ACTOR_THREAD_NAME),
        ("down", None, ACTOR_THREAD_NAME),
        ("text", None, ACTOR_THREAD_NAME),  # 글자마다
        ("text", None, ACTOR_THREAD_NAME),
    ]
    assert all(t is target for _, t, _, _, _ in guard.calls)
    # 확인은 그 원시 동작이 백엔드에 가기 전이다 (그때까지의 기록 줄 수)
    assert [logged for *_, logged in guard.calls] == [0, 1, 3, 5, 6]
    # 백엔드에는 확인이 돌려준 화면 좌표가 간다
    lines = rig.lines()
    assert [line.get("at") for line in lines[:2]] == [[101, 202], [101, 202]]


def test_text_checked_per_character_stops_when_focus_lost(tmp_path: Path) -> None:
    # 보내는 도중 포커스를 잃으면(셋째 글자 직전 확인 실패) 남은 글자를 보내지 않는다 — 다른 창에
    # 글자가 들어가지 않게. 보충 문자(대리 쌍)는 한 글자로 함께 간다
    received: list[str] = []

    class Recording(FakeBackend):
        def text(self, text: str) -> None:
            received.append(text)
            super().text(text)

    guard = Guard(tmp_path / "input.jsonl", fail=lambda op, n: n == 3)
    actor = InputActor(Recording(tmp_path / "input.jsonl"), guard=guard).start()
    with pytest.raises(EngineError):
        actor.type_text(Secret("한😀글자"))
    assert received == ["한", "😀"]
    guard.fail = None
    actor.type_text("")  # 빈 글자는 아무것도 보내지 않고 끝난다
    assert received == ["한", "😀"]
    assert actor.stop(10)


def test_check_failure_releases_partial_combo(tmp_path: Path) -> None:
    # ctrl+shift+a: 두 번째 down(shift) 직전 확인이 실패 → 이미 누른 ctrl만 바로 뗀다
    guard = Guard(tmp_path / "input.jsonl", fail=lambda op, n: n == 2)
    rig = Rig(tmp_path, guard=guard)
    rig.actor.start()
    with pytest.raises(EngineError) as caught:
        rig.actor.key("ctrl+shift+a")
    assert caught.value.code == "window_not_foreground"
    assert rig.ops() == [("down", "ctrl"), ("up", "ctrl")]
    assert [(e["event"], e["key"]) for e in rig.events] == [
        ("input.down", "ctrl"),
        ("input.up", "ctrl"),
    ]
    assert rig.actor.held == []

    # 드래그 중간 이동의 확인이 실패해도 그 요청이 누른 버튼을 뗀다
    guard.calls.clear()
    guard.fail = lambda op, n: n == 4  # move(시작)·down·move 하나 뒤
    with pytest.raises(EngineError):
        rig.actor.drag(ClientPoint(0, 0), ClientPoint(10, 0), duration_ms=48)
    assert rig.actor.held == []
    tail = [(line["op"], line.get("button")) for line in rig.lines()[2:]]
    assert tail == [("move", None), ("down", "left"), ("move", None), ("up", "left")]
    # 다음 요청은 정상으로 돈다 (확인 실패는 그 요청의 오류일 뿐)
    guard.fail = None
    rig.actor.key("b")
    assert rig.actor.stop(10)


def test_release_all_skips_checks(tmp_path: Path) -> None:
    guard = Guard(tmp_path / "input.jsonl")
    rig = Rig(tmp_path, guard=guard)
    rig.actor.start()
    rig.actor.press("ctrl+a")
    rig.actor.press_button(ClientPoint(5, 5), button="right")
    assert rig.actor.held == [
        InputKey("keyboard", "ctrl"),
        InputKey("keyboard", "a"),
        InputKey("mouse", "right"),
    ]
    # 이제 어떤 확인도 실패한다 (포커스를 잃음 등) — 떼기는 확인 없이 된다
    guard.fail = lambda op, n: True
    before = len(guard.calls)
    rig.actor.release("a")
    assert rig.actor.held == [InputKey("keyboard", "ctrl"), InputKey("mouse", "right")]
    rig.actor.close_gate()  # RELEASE_ALL
    assert rig.actor.stop(10)
    assert rig.actor.held == []
    assert len(guard.calls) == before  # release·RELEASE_ALL은 확인을 부르지 않았다
    downs_ups = [line for line in rig.lines() if line["op"] in ("down", "up")]
    assert [(line["op"], line.get("key") or line.get("button")) for line in downs_ups] == [
        ("down", "ctrl"),
        ("down", "a"),
        ("down", "right"),
        ("up", "a"),
        ("up", "right"),
        ("up", "ctrl"),
    ]


def test_actor_accepts_client_point_only(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.actor.start()
    rect = Rect(0, 0, 10, 10)
    for at in (Point(1, 2), rect, Match(rect, 0.9)):
        with pytest.raises(TypeError, match="ClientPoint"):
            rig.actor.click(at)  # pyright: ignore[reportArgumentType]
        with pytest.raises(TypeError, match="ClientPoint"):
            rig.actor.scroll(at, 1)  # pyright: ignore[reportArgumentType]
        with pytest.raises(TypeError, match="ClientPoint"):
            rig.actor.drag(at, ClientPoint(0, 0))  # pyright: ignore[reportArgumentType]
        with pytest.raises(TypeError, match="ClientPoint"):
            rig.actor.press_button(at)  # pyright: ignore[reportArgumentType]
    assert rig.actor.stop(10)
    assert rig.lines() == []


def test_unknown_key_and_button_are_key_unknown(tmp_path: Path) -> None:
    # 가짜 백엔드에서도 모르는 이름은 key_unknown이고 아무것도 누르지 않는다
    rig = Rig(tmp_path)
    rig.actor.start()
    for call in (
        lambda: rig.actor.key("ctrl+nosuchkey"),
        lambda: rig.actor.click(ClientPoint(0, 0), button="thumb"),
        # 잘못 쓴 조합(빈 이름)도 같은 사유 (실행기에서 node_error가 아니라 key_unknown)
        lambda: rig.actor.key(""),
        lambda: rig.actor.key("+a"),
        lambda: rig.actor.key("ctrl++a"),
        lambda: rig.actor.press("ctrl+"),
        lambda: rig.actor.release(""),
    ):
        with pytest.raises(KeyUnknown) as caught:
            call()
        assert caught.value.code == "key_unknown"
    rig.actor.key("Ctrl+Escape")  # 대소문자 무시·별칭 → 정식 이름으로 기록
    assert rig.actor.stop(10)
    assert rig.ops() == [("down", "ctrl"), ("down", "esc"), ("up", "esc"), ("up", "ctrl")]


def test_failed_request_keeps_keys_held_by_earlier_request(tmp_path: Path) -> None:
    # 누르고 있기(press ctrl) 중에 ctrl+a 요청의 a 직전 확인이 실패 → 그 요청이 새로 누른 것이
    # 없으므로 아무것도 떼지 않는다. ctrl은 앞 요청의 것이라 그대로 쥐고 있다
    guard = Guard(tmp_path / "input.jsonl", fail=lambda op, n: n == 3)
    rig = Rig(tmp_path, guard=guard)
    rig.actor.start()
    rig.actor.press("ctrl")
    with pytest.raises(EngineError):
        rig.actor.key("ctrl+a")
    assert rig.actor.held == [InputKey("keyboard", "ctrl")]
    assert rig.ops() == [("down", "ctrl"), ("down", "ctrl")]
    # 같은 상황에서 새로 누른 키는 뗀다: press(ctrl) 유지 + shift+a 중 a 확인 실패 → shift만 뗌
    guard.calls.clear()
    guard.fail = lambda op, n: n == 2
    with pytest.raises(EngineError):
        rig.actor.key("shift+a")
    assert rig.actor.held == [InputKey("keyboard", "ctrl")]
    assert rig.ops()[2:] == [("down", "shift"), ("up", "shift")]
    rig.actor.release("ctrl")
    assert rig.actor.stop(10)
    assert rig.actor.held == []


def test_repeat_down_normal_and_recovery_order_agree(tmp_path: Path) -> None:
    # 떼지 않고 같은 키를 다시 누르면 맨 뒤로 간다 — 정상 마무리(RELEASE_ALL)와 기록을 읽은
    # 복구(held_inputs의 거꾸로)가 같은 차례로 뗀다
    folder = tmp_path / "run"
    folder.mkdir()
    journal = Journal(folder / EVENTS_FILE, "aaaaaaaa")
    rig = Rig(tmp_path)
    rig.actor = InputActor(rig.backend, emit=journal.emit, gate=rig.gate).start()
    try:
        rig.actor.press("a")
        rig.actor.press("shift")
        rig.actor.press("a")
        assert rig.actor.held == [InputKey("keyboard", "shift"), InputKey("keyboard", "a")]
        recovery = [k.name for k in reversed(held_inputs(read_run(folder)))]
        assert rig.actor.stop(10)
        normal = [name for op, name in rig.ops() if op == "up"]
        assert normal == recovery == ["a", "shift"]
    finally:
        journal.close()


@pytest.mark.parametrize("end", ["request_failure", "normal_stop"])
def test_repeat_down_in_one_request_release_order_agrees(tmp_path: Path, end: str) -> None:
    # 한 요청 안에서 a를 다시 누름 (a+shift+a). 요청 실패 정리·정상 마무리가 그 순간의 기록을
    # 읽은 강제 종료 복구(held_inputs의 거꾸로)와 같은 차례로 뗀다
    folder = tmp_path / "run"
    folder.mkdir()
    journal = Journal(folder / EVENTS_FILE, "aaaaaaaa")
    recovery: list[str] = []

    def snapshot() -> None:
        recovery.extend(k.name for k in reversed(held_inputs(read_run(folder))))

    def fail_on_b(op: GuardedOp, n: int) -> bool:
        if n == 4:  # a, shift, a 다음 b 직전
            snapshot()
            return True
        return False

    guard = Guard(tmp_path / "input.jsonl", fail=fail_on_b if end == "request_failure" else None)
    rig = Rig(tmp_path, guard=guard)
    rig.actor = InputActor(rig.backend, emit=journal.emit, gate=rig.gate, guard=guard).start()
    try:
        if end == "request_failure":
            with pytest.raises(EngineError):
                rig.actor.key("a+shift+a+b")
            assert rig.actor.held == []
        else:
            rig.actor.press("a+shift+a")
            snapshot()
            assert rig.actor.stop(10)
        released = [name for op, name in rig.ops() if op == "up"]
        assert released == recovery == ["a", "shift"]
    finally:
        rig.actor.stop(10)
        journal.close()


# ── P1 D1: 실행 첫 창을 앞으로 가져오는 Alt (tap_unguarded) ─────────────────────


def test_tap_unguarded_skips_guard_but_records(tmp_path: Path) -> None:
    # 대상 창이 아직 앞에 없어 포그라운드 확인을 할 수 없다: 확인 없이, 기록·떼기는 그대로
    guard = Guard(tmp_path / "input.jsonl", fail=lambda op, n: True)
    rig = Rig(tmp_path, guard=guard)
    rig.actor.start()
    rig.actor.tap_unguarded("alt", step="s1")
    assert guard.calls == []
    assert rig.ops() == [("down", "alt"), ("up", "alt")]
    assert [(e["event"], e["step"]) for e in rig.events] == [
        ("input.down", "s1"),
        ("input.up", "s1"),
    ]
    assert rig.actor.held == []
    # 다른 요청은 여전히 확인을 거친다
    with pytest.raises(EngineError):
        rig.actor.key("alt")
    assert rig.actor.stop(10)


def test_tap_unguarded_refused_when_gate_closed(tmp_path: Path) -> None:
    # 취소·마무리로 게이트가 닫혔으면 백엔드를 부르지 않는다
    rig = Rig(tmp_path)
    rig.actor.start()
    rig.actor.close_gate()
    with pytest.raises(Cancelled):
        rig.actor.tap_unguarded("alt")
    assert rig.actor.stop(10)
    assert [op for op in rig.ops() if op[1] == "alt"] == []
    assert rig.events == []


class _CountingSend:
    """SendInput 흉내: 호출마다 `results`의 개수만큼 넣었다고 돌려준다 (0 = 하나도 못 넣음)."""

    def __init__(self, results: list[int]) -> None:
        self.results = results
        self.calls: list[int] = []

    def __call__(self, inputs: Any) -> int:
        self.calls.append(len(inputs))
        return self.results.pop(0) if self.results else len(inputs)


@pytest.mark.parametrize(
    "results",
    [
        [0],  # 누르기를 못 넣음 → 실패, 떼기를 보낸다 (눌렸을 수 있음으로 기록됐다)
        [1, 1],  # 정상
        [1, 0, 1],  # 떼기 실패 → 실패 정리가 다시 뗀다
    ],
    ids=["down_0", "ok", "up_0"],
)
def test_tap_unguarded_partial_send_never_leaves_alt_down(
    tmp_path: Path, results: list[int]
) -> None:
    sendinput = pytest.importorskip("kookabug_platform.sendinput")
    send = _CountingSend(list(results))
    events: list[dict[str, Any]] = []
    actor = InputActor(
        sendinput.SendInputBackend(send=send), emit=lambda e: events.append(dict(e))
    ).start()
    try:
        if results == [1, 1]:
            actor.tap_unguarded("alt")
        else:
            with pytest.raises(OSError):
                actor.tap_unguarded("alt")
        assert actor.held == []  # 액터 기준 눌린 키 없음
        # 기록상으로도 눌린 채 남지 않는다 (마지막 기록이 떼기)
        assert [e["event"] for e in events][-1] == "input.up"
        assert send.calls[-1] == 1  # 마지막 SendInput은 떼기 하나
    finally:
        assert actor.stop(10)
