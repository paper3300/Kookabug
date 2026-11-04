"""`HookClient` 정지 순서 (M4 T3 4라운드): 정지 결정의 유일한 주체 `StopMachine`과 스레드 경합.

넘침·정상 멈춤·프로세스 종료·생존 감시 시간 초과·파이프 EOF가 서로 앞뒤로 오는 순서마다 최종 정지
사유와 `on_stop`(한 번)이 정해진다. 아래 `ORDERS` 표가 기대 결과다(보고서 표와 같다). 스레드 검사는
실제 `HookClient._read`·`_monitor`를 장벽으로 순서를 고정해 돌린다 (대역 파이프·프로세스,
훅·입력 없음).
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, cast

import pytest

from kookabug_daemon.recorder_hook import (
    HookClient,
    HookStop,
    HookUpdate,
    StopEvent,
    StopMachine,
)
from kookabug_platform.recorder.fake import FakeHookSource
from kookabug_platform.recorder.hookproc import HookCore
from kookabug_sdk.rpc import Incoming, PeerLost

OVERFLOW = HookStop("input_overflow", "넘침", 5)
LIVENESS = HookStop("hook_lost", "hook.health가 2초 넘게 오지 않았다")
PROTOCOL = HookStop("hook_lost", "훅 프로토콜이 다르다")
EXIT = "훅 프로세스가 끝났다 (종료 코드 0)"

# (이름, 사건 차례, on_stop으로 알릴 것(사유, 상세 일부) 또는 None, 알리는 사건 번호)
# 사건: ("overflow"|"protocol_lost"|"eof"|"process_exited"|"liveness_lost"|"liveness_busy"
#        |"stop_requested"|"tick", now)
ORDERS: list[tuple[str, list[str], tuple[str, str] | None, int | None]] = [
    ("넘침→EOF", ["overflow", "eof"], ("input_overflow", "넘침"), 1),
    (
        "넘침→프로세스 종료→EOF",
        ["overflow", "process_exited", "eof"],
        ("input_overflow", "넘침"),
        2,
    ),
    # 검수 T3-3: 감시가 넘침 전 상태로 프로세스 검사에 들어가 있다가 종료를 알림
    (
        "프로세스 종료→넘침→EOF",
        ["process_exited", "overflow", "eof"],
        ("input_overflow", "넘침"),
        2,
    ),
    (
        "넘침→생존 시간 초과→EOF",
        ["overflow", "liveness_lost", "eof"],
        ("input_overflow", "넘침"),
        2,
    ),
    ("생존 시간 초과→넘침", ["liveness_lost", "overflow", "eof"], ("hook_lost", "hook.health"), 0),
    ("프로세스 종료→EOF", ["process_exited", "eof"], ("hook_lost", "종료 코드 0"), 1),
    ("EOF→프로세스 종료", ["eof", "process_exited"], ("hook_lost", "파이프가 끊겼다"), 0),
    (
        "프로세스 종료→생존 시간 초과→EOF",
        ["process_exited", "liveness_lost", "eof"],
        ("hook_lost", "종료 코드 0"),
        2,
    ),
    ("생존 시간 초과(읽기 놂)", ["liveness_lost"], ("hook_lost", "hook.health"), 0),
    (
        "생존 시간 초과(읽기 밀림)→EOF",
        ["liveness_busy", "eof"],
        ("hook_lost", "파이프가 끊겼다"),
        1,
    ),
    ("프로토콜 위반", ["protocol_lost", "eof"], ("hook_lost", "프로토콜"), 0),
    ("정상 멈춤→EOF", ["stop_requested", "eof"], None, None),
    (
        "정상 멈춤→프로세스 종료→생존 시간 초과→EOF",
        ["stop_requested", "process_exited", "liveness_lost", "eof"],
        None,
        None,
    ),
    ("넘침→정상 멈춤→EOF", ["overflow", "stop_requested", "eof"], None, None),
    ("정상 멈춤→넘침(마무리 묶음)→EOF", ["stop_requested", "overflow", "eof"], None, None),
    ("프로세스 종료→정상 멈춤→EOF", ["process_exited", "stop_requested", "eof"], None, None),
    ("EOF→정상 멈춤", ["eof", "stop_requested"], ("hook_lost", "파이프가 끊겼다"), 0),
    ("넘침→넘침→EOF", ["overflow", "overflow", "eof"], ("input_overflow", "넘침"), 2),
]


def run_order(events: list[str]) -> tuple[StopMachine, list[tuple[int, Any]]]:
    busy = [False]
    machine = StopMachine(pending=lambda: 1 if busy[0] else 0)
    out: list[tuple[int, Any]] = []
    for index, name in enumerate(events):
        busy[0] = name == "liveness_busy"
        event = cast(StopEvent, "liveness_lost" if name == "liveness_busy" else name)
        stop = {"overflow": OVERFLOW, "liveness_lost": LIVENESS, "protocol_lost": PROTOCOL}.get(
            event
        )
        actions = machine.on(
            event, stop=stop, detail=EXIT if name == "process_exited" else "x", now=float(index)
        )
        out.append((index, actions))
    return machine, out


@pytest.mark.parametrize(("name", "events", "expected", "at"), ORDERS, ids=[o[0] for o in ORDERS])
def test_stop_order_table(
    name: str, events: list[str], expected: tuple[str, str] | None, at: int | None
) -> None:
    machine, out = run_order(events)
    reports = [(i, a.report) for i, a in out if a.report is not None]
    if expected is None:
        assert reports == []
        assert machine.reported is None
        assert machine.state == "ended"
        return
    assert len(reports) == 1, reports  # on_stop은 한 번
    index, report = reports[0]
    assert index == at
    assert (report.reason, expected[1] in report.detail) == (expected[0], True)
    assert machine.reported == report
    # 알리는 결정에는 끝내기가 따른다 (잠금 밖에서 on_stop 다음)
    assert out[index][1].kill


def test_overflow_notifies_hook_once_and_deadlines_kill_once() -> None:
    machine = StopMachine(drain_wait_s=3.0, exit_wait_s=1.0)
    first = machine.on("overflow", stop=OVERFLOW, now=0.0)
    assert first.notify_stop and first.report is None and not first.kill
    assert not machine.on("overflow", stop=OVERFLOW, now=0.1).notify_stop
    assert not machine.on("tick", now=2.9).kill
    assert machine.on("tick", now=3.1).kill  # 마무리 기한 — 파이프가 닫혀 EOF가 온다
    assert not machine.on("tick", now=9.0).kill  # 한 번만
    assert machine.on("eof", now=9.1).report == OVERFLOW

    machine = StopMachine(exit_wait_s=1.0)
    assert machine.on("process_exited", detail=EXIT, now=0.0).report is None
    assert machine.on("tick", now=1.5).kill  # 종료 뒤 EOF가 늦으면 파이프를 닫는다
    report = machine.on("eof", now=1.6).report
    assert report is not None and report.detail == EXIT


def test_stop_requested_notifies_only_while_running() -> None:
    assert StopMachine().on("stop_requested").notify_stop
    machine = StopMachine()
    machine.on("overflow", stop=OVERFLOW)
    assert not machine.on("stop_requested").notify_stop  # 이미 보냈다
    assert machine.state == "stopping" and machine.overflow == OVERFLOW


# ── 실제 HookClient 스레드 ──────────────────────────────────


class FakeHook:
    """대역 파이프·프로세스. `hook.stop`을 받으면 훅이 정상으로 끝나 EOF가 온다."""

    def __init__(self, client: HookClient, *, exit_on_stop: bool = True) -> None:
        self.incoming: queue.Queue[Any] = queue.Queue()
        self.running = True
        self.lost: PeerLost | None = None
        self.exit_on_stop = exit_on_stop
        self.alive_hook: Any = None
        """`alive()`에 끼울 장벽 (감시 스레드가 프로세스 검사에 들어간 순간)."""
        hello = FakeHookSource([{**HEADER}]).timeline()[0][1]["params"]
        client.stream.feed("hook.hello", hello, client.now_ns())  # 생존 감시 기준 = 지금
        client._peer = cast(Any, self)
        client._process = cast(Any, self)

    def end(self) -> None:
        self.running = False
        if self.lost is None:
            self.lost = PeerLost("EOF")
            self.incoming.put(self.lost)

    def notify(self, method: str, params: Any) -> None:
        if method == "hook.stop" and self.exit_on_stop:
            self.end()

    def close(self) -> None:
        self.end()

    def alive(self) -> bool:
        if self.alive_hook is not None:
            self.alive_hook()
        return self.running

    def terminate(self) -> None:
        self.end()

    def wait(self, timeout: float | None = None) -> int | None:
        return None if self.running else 0

    def exit_code(self) -> int:
        return 0


HEADER = {
    "kind": "header",
    "format": "kookabug.recorder-script/0",
    "title": "x",
    "geometry": {
        "frame_bounds": [0, 0, 8, 6],
        "client_origin": [0, 0],
        "client_size": [8, 6],
        "dpi": 96,
    },
    "scene": "s",
}


def overflow_batch() -> dict[str, Any]:
    core = HookCore(clock=lambda: 0, crit_capacity=4)
    for _ in range(5):
        core.on_key(0x100, 0x41, 30, 0, 0)
    batch = core.take_batch()
    assert batch is not None
    return batch


class Recorder:
    def __init__(self, *, hold_events: threading.Event | None = None) -> None:
        self.order: list[str] = []
        self.entered = threading.Event()
        self.reported = threading.Event()
        self.hold = hold_events

    def on_update(self, update: HookUpdate) -> None:
        if update.events:
            self.order.append("events_enter")
            self.entered.set()
            if self.hold is not None:
                assert self.hold.wait(10)
            self.order.append("events_done")
        if update.obs:
            self.order.append("obs")

    def on_stop(self, stop: HookStop) -> None:
        self.order.append(f"stop:{stop.reason}")
        self.reported.set()


def test_overflow_while_monitor_already_checking_process() -> None:
    """검수 T3-3 반례: 감시가 넘침 전 상태로 프로세스 검사에 들어가 있는 동안 읽기가 넘침을 찾고
    훅이 정상으로 끝난다 → 그래도 events 끝 → obs → EOF → on_stop(input_overflow)."""
    release_callback = threading.Event()
    rec = Recorder(hold_events=release_callback)
    client = HookClient(mono_base_ns=0, on_update=rec.on_update, on_stop=rec.on_stop)
    hook = FakeHook(client)
    checking, resume_check = threading.Event(), threading.Event()
    first = [True]

    def barrier() -> None:
        if threading.current_thread().name == "hook-monitor" and first[0]:
            first[0] = False
            checking.set()
            assert resume_check.wait(10)

    hook.alive_hook = barrier
    hook.incoming.put(Incoming("hook.events", overflow_batch(), None))
    hook.incoming.put(
        Incoming("hook.obs", {"batch": [{"cause_event_id": n} for n in range(1, 5)]}, None)
    )
    monitor = threading.Thread(target=client._monitor, name="hook-monitor", daemon=True)
    monitor.start()
    assert checking.wait(5)  # 감시가 프로세스 검사 안에 있다 (넘침 전 상태를 읽은 뒤)
    client._reader = threading.Thread(target=client._read, name="hook-read", daemon=True)
    client._reader.start()
    assert rec.entered.wait(5)  # 읽기가 넘침을 찾아 훅을 멈췄고(→ EOF 대기), 콜백 안이다
    assert not hook.running
    resume_check.set()  # 감시가 "프로세스 끝남"을 알린다
    assert not rec.reported.wait(0.5), "콜백이 끝나기 전에 멈춤을 알렸다"
    release_callback.set()
    assert rec.reported.wait(10)
    monitor.join(5)
    assert rec.order == ["events_enter", "events_done", "obs", "stop:input_overflow"]
    assert client.result == client.stream.stop
    assert client.wait_done(5)


def test_process_exit_with_unread_overflow_batch_reports_overflow() -> None:
    """훅이 넘침 묶음·관측을 보내고 끝났는데 감시가 읽기보다 먼저 종료를 봄 → 넘침으로 알린다."""
    rec = Recorder()
    client = HookClient(mono_base_ns=0, on_update=rec.on_update, on_stop=rec.on_stop)
    hook = FakeHook(client)
    hook.incoming.put(Incoming("hook.events", overflow_batch(), None))
    hook.incoming.put(Incoming("hook.obs", {"batch": [{"cause_event_id": 1}]}, None))
    hook.end()  # 프로세스 끝 + EOF가 큐 끝에
    client._event("process_exited", detail=EXIT)  # 감시가 먼저 봄
    assert not rec.reported.is_set()
    client._reader = threading.Thread(target=client._read, daemon=True)
    client._reader.start()
    assert rec.reported.wait(5)
    assert rec.order == ["events_enter", "events_done", "obs", "stop:input_overflow"]


def test_process_exit_without_overflow_reports_hook_lost_after_queue() -> None:
    rec = Recorder()
    client = HookClient(mono_base_ns=0, on_update=rec.on_update, on_stop=rec.on_stop)
    hook = FakeHook(client)
    core = HookCore(clock=lambda: 0)
    core.on_key(0x100, 0x41, 30, 0, 0)
    batch = core.take_batch()
    assert batch is not None
    hook.incoming.put(Incoming("hook.events", batch, None))
    hook.end()
    client._event("process_exited", detail=EXIT)
    client._reader = threading.Thread(target=client._read, daemon=True)
    client._reader.start()
    assert rec.reported.wait(5)
    assert rec.order == ["events_enter", "events_done", "stop:hook_lost"]
    assert client.result is not None and "종료 코드 0" in client.result.detail


def test_liveness_ignored_while_consumer_is_behind() -> None:
    """소비자 콜백이 늦어 생존 보고가 큐에 쌓인 동안 생존 감시 시간 초과는 알리지 않는다."""
    release = threading.Event()
    rec = Recorder(hold_events=release)
    client = HookClient(mono_base_ns=0, on_update=rec.on_update, on_stop=rec.on_stop)
    hook = FakeHook(client)
    core = HookCore(clock=lambda: 0)
    core.on_key(0x100, 0x41, 30, 0, 0)
    batch = core.take_batch()
    assert batch is not None
    hook.incoming.put(Incoming("hook.events", batch, None))
    health = {"batch_no": 1, "last_event_ns": 0, "last_input_tick": 1, "sent_at_ns": 0}
    hook.incoming.put(Incoming("hook.health", health, None))
    client._reader = threading.Thread(target=client._read, daemon=True)
    client._reader.start()
    assert rec.entered.wait(5)
    # 읽기는 콜백 안(밀림), 큐에 생존 보고가 있다 → 시간 초과 사건은 무시
    client._event("liveness_lost", stop=LIVENESS)
    assert not rec.reported.is_set() and client.machine.state == "running"
    release.set()
    deadline = time.monotonic() + 5
    while client._pending() and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)
    client._event("liveness_lost", stop=LIVENESS)  # 이제 읽기가 놀고 큐도 비었다
    assert rec.reported.wait(5)
    assert rec.order[-1] == "stop:hook_lost"
    hook.end()
    assert client.wait_done(5)


def _key_batch(core: HookCore) -> dict[str, Any]:
    core.on_key(0x100, 0x41, 30, 0, 0)
    batch = core.take_batch()
    assert batch is not None
    return batch


def test_slow_callback_with_regular_health_keeps_recording() -> None:
    """검수 T3-4 반례: 실제 `_read`·`_monitor`, 생존 보고는 0.5 s마다 정상으로 오는데 첫 이벤트
    콜백이 2.4 s 걸린다 → 멈추지 않고, 두 이벤트·생존 보고를 모두 처리하고 녹화가 이어진다."""
    delivered: list[int] = []
    stops: list[HookStop] = []

    def on_update(update: HookUpdate) -> None:
        if update.events and not delivered:
            time.sleep(2.4)  # 디스크 작업 등으로 늦은 소비자
        delivered.extend(e["crit_seq"] for e in update.events)

    client = HookClient(mono_base_ns=0, on_update=on_update, on_stop=stops.append)
    hook = FakeHook(client)
    core = HookCore(clock=lambda: 0)
    hook.incoming.put(Incoming("hook.events", _key_batch(core), None))
    hook.incoming.put(Incoming("hook.events", _key_batch(core), None))
    stop_sender = threading.Event()

    def sender() -> None:  # 훅의 송신 스레드처럼 0.5 s마다 생존 보고
        while not stop_sender.wait(0.5):
            health = {
                "batch_no": core.batch_no,
                "last_event_ns": 0,
                "last_input_tick": 1,
                "sent_at_ns": client.now_ns(),
            }
            hook.incoming.put(Incoming("hook.health", health, None))

    threading.Thread(target=sender, daemon=True).start()
    client._start_threads()  # 실제 읽기 + 감시
    try:
        time.sleep(3.5)
        assert stops == [], stops
        assert delivered == [1, 2]
        assert client.stream.stop is None and client.machine.state == "running"
        assert client.stream.health_count >= 5  # 밀렸던 생존 보고까지 처리
        hook.incoming.put(Incoming("hook.events", _key_batch(core), None))
        deadline = time.monotonic() + 2
        while delivered != [1, 2, 3] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert delivered == [1, 2, 3]  # 녹화가 이어진다
    finally:
        stop_sender.set()
        assert client.stop(timeout=1) is None
    assert stops == []


def test_real_health_silence_is_still_detected_by_idle_reader() -> None:
    """생존 보고가 정말 끊기면(읽기는 놀고 큐는 빔) 약 2 s 뒤 `hook_lost` — 감시는 그대로
    동작한다."""
    rec = Recorder()
    client = HookClient(mono_base_ns=0, on_update=rec.on_update, on_stop=rec.on_stop)
    FakeHook(client)
    started = time.monotonic()
    client._start_threads()
    assert rec.reported.wait(5)
    assert 2.0 <= time.monotonic() - started < 3.0
    assert rec.order == ["stop:hook_lost"]
    assert client.result is not None and "hook.health" in client.result.detail
    assert client.stream.stop is None  # 스트림은 후보만 냈다 — 결정은 정지 기계
    assert client.wait_done(5)


def test_normal_stop_during_overflow_drain_returns_overflow_without_on_stop() -> None:
    release = threading.Event()
    rec = Recorder(hold_events=release)
    client = HookClient(mono_base_ns=0, on_update=rec.on_update, on_stop=rec.on_stop)
    hook = FakeHook(client, exit_on_stop=False)
    hook.incoming.put(Incoming("hook.events", overflow_batch(), None))
    client._reader = threading.Thread(target=client._read, daemon=True)
    client._reader.start()
    assert rec.entered.wait(5)
    result: list[HookStop | None] = []
    stopper = threading.Thread(target=lambda: result.append(client.stop(timeout=0.2)))
    stopper.start()
    time.sleep(0.3)  # stop()이 프로세스 기한을 넘겨 끝낸다 → EOF
    release.set()
    stopper.join(10)
    assert result and result[0] is not None and result[0].reason == "input_overflow"
    assert "stop:input_overflow" not in rec.order  # 정상 멈춤 중이라 on_stop 없음
