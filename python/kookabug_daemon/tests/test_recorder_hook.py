"""daemon 쪽 녹화 훅 연결 (M4 계획 2.1·2.2·2.9, T3): 연속성·생존 감시·검사 옵션·훅 프로세스 띄우기.

`HookStream`은 가짜 훅 원천(`FakeHookSource`)의 시각표를 그대로 먹여 본다. `HookClient`는 실제
프로세스·named pipe를 쓰되 훅 대신 작은 가짜 자식(이 파일이 만드는 스크립트)을 띄운다 — 전역 훅은
걸지 않는다.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from kb_testing.hook_harness import RawHook
from kookabug_core.recorder.contract import HOOK_PROTOCOL
from kookabug_daemon.app import UsageError, config_from_args
from kookabug_daemon.options import add_arguments
from kookabug_daemon.recorder_hook import (
    TESTING_ENV,
    HookClient,
    HookStop,
    HookStopIncomplete,
    HookStream,
    HookTesting,
    HookUpdate,
)
from kookabug_daemon.recorder_hook import testing_options as options_for  # test_로 시작하면 수집됨
from kookabug_platform.inputmark import KOOKABUG_INPUT_MARK
from kookabug_platform.recorder.fake import FakeHookSource
from kookabug_platform.recorder.hookproc import HookCore
from kookabug_sdk.rpc import Incoming, PeerLost

MS = 1_000_000
TEST_MARK = 0x7E57
HEADER = {
    "kind": "header",
    "format": "kookabug.recorder-script/0",
    "title": "x",
    "geometry": {
        "frame_bounds": [0, 0, 800, 600],
        "client_origin": [0, 0],
        "client_size": [800, 600],
        "dpi": 96,
    },
    "scene": "title",
}


def raw_key(kind: str = "key_down", **f: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "vk": 0x41,
        "scan": 0x1E,
        "extended": False,
        "injected": False,
        "injected_lower_il": False,
        "extra_info": 0,
        **f,
    }


def raw_move(**f: Any) -> dict[str, Any]:
    return {
        "kind": "mouse_move",
        "x": 1,
        "y": 2,
        "injected": False,
        "injected_lower_il": False,
        "extra_info": 0,
        **f,
    }


def typing(start_ms: int, count: int, step_ms: int = 50, **f: Any) -> list[dict[str, Any]]:
    lines = []
    for i in range(count):
        t = (start_ms + i * step_ms) * MS
        lines.append({"kind": "input", "t_ns": t, "input": raw_key("key_down", **f)})
        lines.append({"kind": "input", "t_ns": t + 10 * MS, "input": raw_key("key_up", **f)})
    return lines


def replay(
    lines: list[dict[str, Any]],
    *,
    testing: HookTesting | None = None,
    tail_ms: int = 600,
) -> tuple[HookStream, list[HookUpdate], int]:
    """시각표를 먹이고, 메시지 사이에 100 ms마다 생존 감시를 돈다 (`HookClient` 감시 스레드처럼).
    (stream, 업데이트, 멈춘 시각 또는 마지막 시각)."""
    source = FakeHookSource([HEADER, *lines], tail_ns=tail_ms * MS)
    stream = HookStream(mono_base_ns=0, testing=testing)
    updates: list[HookUpdate] = []
    checked = 0
    stopped_at: int | None = None
    for t, message in source.timeline():
        while stopped_at is None and checked + 100 * MS <= t:
            checked += 100 * MS
            lost = stream.liveness(checked)  # 후보 (정지는 HookClient 정지 기계가 정한다)
            if lost is not None:
                stream.stop = lost  # 여기서는 받아들인다 (읽기가 밀리지 않는 재생)
                return stream, updates, checked
        update = stream.feed(message["method"], message["params"], t)
        if update is not None:
            updates.append(update)  # 넘침이면 유실 앞 이벤트, 멈춘 뒤에는 관측·표본
        if stream.stop is not None and stopped_at is None:
            stopped_at = t
            if stream.stop.reason == "hook_lost":
                return stream, updates, t
    return stream, updates, checked if stopped_at is None else stopped_at


def kept_events(updates: list[HookUpdate]) -> list[dict[str, Any]]:
    return [e for u in updates for e in u.events]


# ── 연속성 ──────────────────────────────────────────────────


def test_fake_stream_records_without_stop() -> None:
    lines = [*typing(100, 10), {"kind": "input", "t_ns": 900 * MS, "input": raw_move()}]
    stream, updates, _ = replay(lines)
    assert stream.stop is None
    events = kept_events(updates)
    assert len([e for e in events if "crit_seq" in e]) == 20
    assert stream.checker.last_crit == 20
    assert sum(len(u.obs) for u in updates) == 20
    assert any(u.ime for u in updates)


def test_crit_seq_gap_stops_recording_input_overflow() -> None:
    lines = [
        *typing(100, 3),  # crit 1..6
        {"kind": "fault", "t_ns": 300 * MS, "fault": "overflow", "count": 1},
        *typing(320, 3),  # 7은 버려진다, 8..12는 큐에 들어간다
    ]
    stream, updates, _ = replay(lines)
    assert stream.stop is not None
    assert stream.stop.reason == "input_overflow"
    assert stream.stop.cut_crit_seq == 7
    # 유실 전 동작은 남는다
    assert [e["crit_seq"] for e in kept_events(updates) if "crit_seq" in e] == [1, 2, 3, 4, 5, 6]

    # 묶음 안 crit_seq 빈틈 (넘침 표시 없이) — 손으로 만든 묶음
    stream = HookStream(mono_base_ns=0)
    hello = FakeHookSource([HEADER]).timeline()[0][1]["params"]
    assert stream.feed("hook.hello", hello, 0) is not None
    first = [
        {**raw_key(), "event_id": 1, "crit_seq": 1, "t_ns": 1 * MS},
        {**raw_key("key_up"), "event_id": 2, "crit_seq": 3, "t_ns": 2 * MS},
    ]
    batch = {
        "batch_no": 1,
        "events": first,
        "crit_first": 1,
        "crit_last": 3,
        "dropped_marker": 0,
        "coalesced_moves": 0,
        "overflow": 0,
    }
    update = stream.feed("hook.events", batch, 3 * MS)
    assert update is not None
    assert [e["crit_seq"] for e in update.events] == [1]  # 빈틈 앞은 넘긴다
    assert stream.stop is not None
    assert (stream.stop.reason, stream.stop.cut_crit_seq) == ("input_overflow", 2)
    assert stream.feed("hook.events", {**batch, "batch_no": 2}, 4 * MS) is None  # 멈춘 뒤 무시


def _key(core: HookCore) -> None:
    core.on_key(0x100, 0x41, 30, 0, 0)


def _hello_stream() -> HookStream:
    stream = HookStream(mono_base_ns=0)
    stream.feed("hook.hello", FakeHookSource([HEADER]).timeline()[0][1]["params"], 0)
    return stream


def test_overflow_batch_delivers_valid_prefix_exactly_once() -> None:
    """검수 T3-1 지적 1: 넘침을 실은 첫 묶음의 유실 앞 이벤트(1..cut-1)도 넘긴다."""
    core = HookCore(crit_capacity=4, clock=lambda: 0)
    for _ in range(5):
        _key(core)
    batch = core.take_batch()
    assert batch is not None
    assert [e["crit_seq"] for e in batch["events"]] == [1, 2, 3, 4]
    stream = _hello_stream()
    update = stream.feed("hook.events", batch, 0)
    assert stream.stop is not None and stream.stop.cut_crit_seq == 5
    assert update is not None
    assert [e["crit_seq"] for e in update.events] == [1, 2, 3, 4]
    # 멈춘 뒤: 이벤트는 더 받지 않고, 유실 앞 이벤트의 관측·표본은 넘긴다
    assert stream.feed("hook.events", {**batch, "batch_no": 2}, 0) is None
    obs_update = stream.feed("hook.obs", {"batch": [{"cause_event_id": 4}]}, 0)
    assert obs_update is not None and obs_update.obs == [{"cause_event_id": 4}]
    ime_update = stream.feed("hook.ime", {"batch": [{"status": "ok"}]}, 0)
    assert ime_update is not None and ime_update.ime == [{"status": "ok"}]
    assert stream.feed("hook.health", {"batch_no": 1}, 0) is None


def test_overflow_with_gap_inside_batch_delivers_until_gap() -> None:
    """큐가 찬 뒤 일부를 보내 자리가 나면, 버린 번호 뒤 이벤트가 같은 묶음에 들어온다."""
    core = HookCore(crit_capacity=4, max_batch=3, clock=lambda: 0)
    for _ in range(5):  # 5는 버려진다
        _key(core)
    stream = _hello_stream()
    delivered: list[int] = []
    first = core.take_batch()  # 1, 2 — 아직 버린 이벤트 앞 큐가 남아 넘침을 싣지 않는다
    assert first is not None and first["overflow"] == 0
    update = stream.feed("hook.events", first, 0)
    assert update is not None and stream.stop is None
    delivered += [e["crit_seq"] for e in update.events]
    _key(core)  # 6 — 자리가 나서 큐에 들어간다
    while (batch := core.take_batch()) is not None and stream.stop is None:
        update = stream.feed("hook.events", batch, 0)
        if update is not None:
            delivered += [e["crit_seq"] for e in update.events]
    assert stream.stop is not None and stream.stop.cut_crit_seq == 5
    assert delivered == [1, 2, 3, 4]


def test_batch_no_gap_stops_recording() -> None:
    lines = [
        *typing(100, 2),
        {"kind": "fault", "t_ns": 200 * MS, "fault": "batch_gap"},
        *typing(220, 1),  # 이 묶음을 잃는다
        *typing(400, 1),
    ]
    stream, updates, _ = replay(lines)
    assert stream.stop is not None
    assert stream.stop.reason == "input_overflow"
    assert stream.stop.cut_crit_seq == 5
    assert [e["crit_seq"] for e in kept_events(updates) if "crit_seq" in e] == [1, 2, 3, 4]


def test_marker_and_coalesced_moves_do_not_stop() -> None:
    lines = []
    for i in range(200):
        t = (100 + i * 3) * MS
        lines.append({"kind": "input", "t_ns": t, "input": raw_move(x=i)})
        lines.append(
            {"kind": "input", "t_ns": t + MS, "input": raw_key(extra_info=KOOKABUG_INPUT_MARK)}
        )
    stream, updates, _ = replay(lines)
    assert stream.stop is None
    assert stream.checker.counters["dropped_marker"] == 200
    assert stream.checker.counters["coalesced_moves"] > 0
    assert all("crit_seq" not in e for e in kept_events(updates))


# ── 생존 감시 ───────────────────────────────────────────────


def test_hook_lost_on_health_silence() -> None:
    lines = [*typing(100, 2), {"kind": "fault", "t_ns": 1000 * MS, "fault": "health_stop"}]
    stream, _, at = replay(lines, tail_ms=4000)
    assert stream.stop is not None
    assert stream.stop.reason == "hook_lost"
    assert "hook.health" in stream.stop.detail
    # 마지막 생존 보고(500 ms) + 2초 넘게
    assert 2500 * MS < at <= 2700 * MS


def test_hook_lost_on_last_input_ahead() -> None:
    lines = [
        *typing(100, 2),
        {"kind": "fault", "t_ns": 1000 * MS, "fault": "hook_detached"},
        *typing(1100, 4),  # OS 입력은 있었는데 훅 이벤트가 없다
    ]
    stream, _, at = replay(lines, tail_ms=3000)
    assert stream.stop is not None
    assert stream.stop.reason == "hook_lost"
    assert "훅 이벤트가 없다" in stream.stop.detail
    # 입력이 처음 보인 보고(1.5 s)의 앞 보고(1.0 s)부터 1초 넘게
    assert 2000 * MS < at <= 2200 * MS


def test_idle_without_input_is_not_lost() -> None:
    stream, _, _ = replay(typing(100, 1), tail_ms=5000)
    assert stream.stop is None


def test_hello_must_match() -> None:
    hello = FakeHookSource([HEADER]).timeline()[0][1]["params"]
    stream = HookStream(mono_base_ns=0)
    assert stream.feed("hook.health", {"batch_no": 0}, 0) is None
    assert stream.stop is not None and stream.stop.reason == "hook_lost"
    stream = HookStream(mono_base_ns=0)
    stream.feed("hook.hello", {**hello, "protocol": HOOK_PROTOCOL + 1}, 0)
    assert stream.stop is not None and "프로토콜" in stream.stop.detail
    stream = HookStream(mono_base_ns=5)
    stream.feed("hook.hello", hello, 0)
    assert stream.stop is not None and "기준 시각" in stream.stop.detail


# ── 다른 프로그램의 입력·검사 표식 ─────────────────────────


def test_injected_input_filtered_unless_test_mark_accepted() -> None:
    lines = [
        *typing(100, 2, injected=True, extra_info=0),  # 다른 프로그램 (매크로 등)
        *typing(300, 2, injected=True, extra_info=TEST_MARK),  # 검사 표식
        *typing(500, 1, injected=True, injected_lower_il=True, extra_info=TEST_MARK),
        *typing(600, 1),  # 사람
        {"kind": "input", "t_ns": 700 * MS, "input": raw_move(injected=True)},
    ]
    stream, updates, _ = replay(lines)
    assert stream.stop is None
    human = [e for e in kept_events(updates) if "crit_seq" in e]
    assert len(human) == 2
    assert stream.ignored_injected == 10  # 이동은 세지 않는다

    stream, updates, _ = replay(lines, testing=HookTesting(accept_extra_info=TEST_MARK))
    kept = [e for e in kept_events(updates) if "crit_seq" in e]
    assert [e["extra_info"] for e in kept] == [TEST_MARK] * 6 + [0, 0]
    assert stream.ignored_injected == 4


def test_test_mark_option_rejected_without_testing_env() -> None:
    assert options_for({}) is None
    with pytest.raises(ValueError, match=TESTING_ENV):
        options_for({}, accept_extra_info=TEST_MARK)
    with pytest.raises(ValueError, match=TESTING_ENV):
        options_for({TESTING_ENV: "0"}, ime_query_window=123)
    got = options_for({TESTING_ENV: "1"}, accept_extra_info=TEST_MARK, ime_query_window=9)
    assert got == HookTesting(TEST_MARK, 9)


def test_test_mark_equal_to_product_mark_rejected() -> None:
    with pytest.raises(ValueError, match="제품 표식"):
        options_for({TESTING_ENV: "1"}, accept_extra_info=KOOKABUG_INPUT_MARK)


def test_daemon_args_apply_testing_rule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "kookabug.json").write_text('{"format": "kookabug.workspace/0"}', encoding="utf-8")
    parser = argparse.ArgumentParser()
    add_arguments(parser)
    argv = ["--workspace", str(tmp_path), "--recorder-accept-extra-info", str(TEST_MARK)]
    monkeypatch.delenv(TESTING_ENV, raising=False)
    with pytest.raises(UsageError, match=TESTING_ENV):
        config_from_args(parser.parse_args(argv))
    monkeypatch.setenv(TESTING_ENV, "1")
    assert config_from_args(parser.parse_args(argv)).recorder_testing == HookTesting(TEST_MARK)
    bad = ["--workspace", str(tmp_path), "--recorder-accept-extra-info", str(KOOKABUG_INPUT_MARK)]
    with pytest.raises(UsageError, match="제품 표식"):
        config_from_args(parser.parse_args(bad))
    assert (
        config_from_args(parser.parse_args(["--workspace", str(tmp_path)])).recorder_testing is None
    )


# ── 훅 프로세스 띄우기 (가짜 자식) ──────────────────────────

_CHILD = r"""
import argparse, json, sys, time
from kookabug_sdk import pipe

p = argparse.ArgumentParser()
for name in ("--pipe", "--parent-pid", "--parent-created", "--mono-base-ns", "--target-hwnd",
             "--ime-query-window", "--mode", "--argv-out", "--protocol"):
    p.add_argument(name)
args = p.parse_args()
key = bytes.fromhex(sys.stdin.readline().strip())
with open(args.argv_out, "w", encoding="utf-8") as f:
    json.dump({"argv": sys.argv, "key": key.hex()}, f)
if args.mode == "no_connect":
    time.sleep(60)
conn = pipe.connect(args.pipe, key)

def send(method, params):
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}).encode()
    conn.send_frame(body, timeout=None)

from kookabug_core.win import current
me = current()
send("hook.hello", {"pid": me.pid, "created": str(me.created), "dpi_awareness": "per_monitor_v2",
                    "hooks": {"mouse": True, "keyboard": True},
                    "mono_base_ns": args.mono_base_ns, "protocol": int(args.protocol)})
send("hook.health", {"batch_no": 0, "last_event_ns": None, "last_input_tick": 1,
                     "sent_at_ns": 0})
if args.mode == "exit":
    time.sleep(0.3)
    sys.exit(7)
if args.mode == "eof":
    time.sleep(0.3)
    conn.close()
    time.sleep(60)
if args.mode == "silent":
    time.sleep(60)

def wait_stop():
    while True:
        message = json.loads(conn.recv_frame(timeout=None))
        if message.get("method") == "hook.stop":
            return

def keys(core, n):
    for _ in range(n):
        core.on_key(0x100, 0x41, 30, 0, 0)

def obs_for(batch):
    return [{"cause_event_id": e["event_id"], "obs_at_ns": e["t_ns"], "fg": 1, "fg_thread": 2,
             "focus": 1, "hkl": "409", "table_changed_ns": 0, "zorder_rev": 0}
            for e in batch["events"] if "crit_seq" in e]

if args.mode == "stop":
    wait_stop()
    sys.exit(0)
if args.mode == "stop_flush":
    # 정상 멈춤을 받은 뒤 마지막 묶음·관측을 보내고 끝난다 (훅 프로세스의 마무리 송신)
    from kookabug_platform.recorder.hookproc import HookCore
    core = HookCore(clock=lambda: 1_000_000, max_batch=2)
    wait_stop()
    keys(core, 3)
    while (batch := core.take_batch()) is not None:
        send("hook.events", batch)
        send("hook.obs", {"batch": obs_for(batch)})
    sys.exit(0)
if args.mode == "overflow":
    # 중요 큐 4칸에 키 5개 — 5번을 잃은 묶음과 그 앞 이벤트의 관측, 정상 멈춤을 기다린 뒤 끝
    from kookabug_platform.recorder.hookproc import HookCore
    core = HookCore(clock=lambda: 1_000_000, crit_capacity=4)
    keys(core, 5)
    batch = core.take_batch()
    send("hook.events", batch)
    wait_stop()
    send("hook.obs", {"batch": obs_for(batch)})
    sys.exit(0)
if args.mode == "flood":
    # 실제 HookCore·Sender로 키를 쏟는다 (훅 없이 콜백 함수를 직접 부름). daemon이 읽지 않으면
    # 파이프 쓰기가 막히고 그동안 중요 큐(64칸)가 차서 넘친다
    import threading
    from collections import deque
    from kookabug_platform.recorder.hookproc import HookCore
    from kookabug_platform.recorder.hookwin32 import Sender

    class Api:
        def last_input_tick(self):
            return 1

    core = HookCore(base_ns=int(args.mono_base_ns), crit_capacity=64)
    broken = threading.Event()
    sender = Sender(core, Api(), conn, deque(), deque(), on_broken=broken.set)
    sender.start()
    for _ in range(4000):
        core.on_key(0x100, 0x41, 30, 0, 0)
        time.sleep(0.0002)
    wait_stop()
    sender.stop(flush=True)
    sys.exit(0)
"""


class Child:
    def __init__(
        self,
        tmp_path: Path,
        mode: str,
        protocol: int = HOOK_PROTOCOL,
        *,
        consume_s: float = 0.0,
    ) -> None:
        script = tmp_path / "fake_hook.py"
        script.write_text(_CHILD, encoding="utf-8")
        self.argv_out = tmp_path / "argv.json"
        self.stops: list[HookStop] = []
        self.stopped = threading.Event()
        self.log: list[tuple[str, Any]] = []
        """받은 차례: ("events", [crit_seq...]) / ("obs", [cause...]) / ("stop", HookStop)."""

        def on_update(update: HookUpdate) -> None:
            time.sleep(consume_s)  # 느린 소비자
            if update.events:
                self.log.append(("events", [e.get("crit_seq") for e in update.events]))
            if update.obs:
                self.log.append(("obs", [o["cause_event_id"] for o in update.obs]))

        def on_stop(stop: HookStop) -> None:
            self.log.append(("stop", stop))
            self.stops.append(stop)
            self.stopped.set()

        self.client = HookClient(
            mono_base_ns=time.monotonic_ns(),
            on_update=on_update,
            on_stop=on_stop,
            target_hwnd=4242,
            command=[
                sys.executable,
                str(script),
                "--mode",
                mode,
                "--argv-out",
                str(self.argv_out),
                "--protocol",
                str(protocol),
            ],
            logs_dir=tmp_path,
        )


@pytest.mark.process
@pytest.mark.timeout(60)
def test_hook_lost_on_child_exit(tmp_path: Path) -> None:
    child = Child(tmp_path, "exit")
    hello = child.client.start(timeout=20)
    assert hello["protocol"] == HOOK_PROTOCOL
    assert child.stopped.wait(10)
    (stop,) = child.stops
    assert stop.reason == "hook_lost"
    # 프로세스가 끝나면 파이프도 닫힌다 — 어느 쪽이 먼저 보든 hook_lost 하나
    assert "끝났다" in stop.detail or "끊겼다" in stop.detail
    # 파이프 키는 명령줄에 남기지 않는다 (stdin으로)
    seen = json.loads(child.argv_out.read_text(encoding="utf-8"))
    assert seen["key"] not in " ".join(seen["argv"])
    assert "--target-hwnd" in seen["argv"] and "4242" in seen["argv"]
    child.client.stop()


@pytest.mark.process
@pytest.mark.timeout(60)
def test_hook_lost_on_pipe_eof(tmp_path: Path) -> None:
    child = Child(tmp_path, "eof")
    child.client.start(timeout=20)
    assert child.stopped.wait(10)
    (stop,) = child.stops
    assert stop.reason == "hook_lost"
    assert "끊겼다" in stop.detail
    # 살아 있던 자식은 끝낸다 (Job)
    pid = child.client.pid
    assert pid is not None
    child.client.stop()


@pytest.mark.process
@pytest.mark.timeout(60)
def test_hook_lost_on_health_silence_real_process(tmp_path: Path) -> None:
    child = Child(tmp_path, "silent")
    child.client.start(timeout=20)
    started = time.monotonic()
    assert child.stopped.wait(10)
    assert time.monotonic() - started >= 1.5
    assert child.stops[0].reason == "hook_lost"
    assert "hook.health" in child.stops[0].detail
    child.client.stop()


@pytest.mark.process
@pytest.mark.timeout(60)
def test_normal_stop_does_not_report_loss(tmp_path: Path) -> None:
    child = Child(tmp_path, "stop")
    child.client.start(timeout=20)
    assert child.client.stop() is None
    assert not child.stopped.wait(0.5)
    assert child.stops == []


@pytest.mark.process
@pytest.mark.timeout(60)
def test_normal_stop_delivers_final_batches_before_returning(tmp_path: Path) -> None:
    """검수 T3-1 지적 2: 마무리 묶음을 느린 소비자가 다 받은 뒤에야 `stop()`이 돌아온다."""
    child = Child(tmp_path, "stop_flush", consume_s=0.2)
    child.client.start(timeout=20)
    started = time.monotonic()
    assert child.client.stop() is None
    assert time.monotonic() - started >= 0.2 * 4  # 묶음 2개 + 관측 2개
    events = [s for kind, seqs in child.log if kind == "events" for s in seqs]
    obs = [c for kind, causes in child.log if kind == "obs" for c in causes]
    assert events == [1, 2, 3]
    assert len(obs) == 3
    assert child.stops == []


@pytest.mark.process
@pytest.mark.timeout(60)
def test_overflow_reports_after_prefix_and_its_observations(tmp_path: Path) -> None:
    """넘침: 유실 앞 이벤트 → (훅을 정상으로 멈춰) 그 관측 → `on_stop` 차례로 한 번씩."""
    child = Child(tmp_path, "overflow")
    child.client.start(timeout=20)
    assert child.stopped.wait(10)
    kinds = [kind for kind, _ in child.log]
    assert kinds == ["events", "obs", "stop"]
    assert child.log[0][1] == [1, 2, 3, 4]
    assert len(child.log[1][1]) == 4
    stop = child.log[2][1]
    assert (stop.reason, stop.cut_crit_seq) == ("input_overflow", 5)
    assert child.client.result == stop
    child.client.stop()
    assert len(child.stops) == 1


def test_normal_stop_waits_for_slow_consumer_without_process() -> None:
    """지적 2의 재현과 같은 구성(대역 프로세스·큐): 첫 콜백이 처리 중일 때 멈춰도 둘 다 넘긴다."""
    delivered: list[int] = []
    stops: list[HookStop] = []
    entered = threading.Event()

    def on_update(update: HookUpdate) -> None:
        entered.set()
        time.sleep(0.3)
        delivered.extend(e["crit_seq"] for e in update.events)

    client = HookClient(mono_base_ns=0, on_update=on_update, on_stop=stops.append)
    hello = FakeHookSource([HEADER]).timeline()[0][1]["params"]
    client.stream.feed("hook.hello", hello, client.now_ns())
    incoming: queue.Queue[Any] = queue.Queue()
    alive = [True]

    def wait(timeout: float | None = None) -> bool:
        alive[0] = False
        incoming.put(PeerLost("EOF"))  # 훅 프로세스가 끝나 파이프가 닫힘
        return True

    client._peer = cast(
        Any,
        SimpleNamespace(incoming=incoming, lost=None, notify=lambda *a: None, close=lambda: None),
    )
    client._process = cast(
        Any, SimpleNamespace(wait=wait, alive=lambda: alive[0], terminate=lambda: None)
    )
    core = HookCore(clock=lambda: 0)
    for _ in range(2):
        _key(core)
        batch = core.take_batch()
        assert batch is not None
        incoming.put(Incoming("hook.events", batch, None))
    client._start_threads()
    assert entered.wait(5)
    client.stop()
    assert delivered == [1, 2]
    assert incoming.qsize() == 0
    assert stops == []


class _QueueHook:
    """대역 파이프·프로세스: `hook.stop`을 받으면(또는 끝내면) 훅이 끝나 EOF가 온다."""

    def __init__(self, client: HookClient) -> None:
        self.incoming: queue.Queue[Any] = queue.Queue()
        self._alive = True
        self.lost: PeerLost | None = None
        hello = FakeHookSource([HEADER]).timeline()[0][1]["params"]
        client.stream.feed("hook.hello", hello, client.now_ns())  # 생존 감시 기준 = 지금
        client._peer = cast(Any, self)
        client._process = cast(Any, self)

    def eof(self) -> None:
        if self.lost is None:
            self.lost = PeerLost("EOF")
            self._alive = False
            self.incoming.put(self.lost)

    def alive(self) -> bool:
        return self._alive

    def notify(self, method: str, params: Any) -> None:
        if method == "hook.stop":
            self.eof()

    def close(self) -> None:
        self.eof()

    def wait(self, timeout: float | None = None) -> int | None:
        return None if self._alive else 0

    def terminate(self) -> None:
        self.eof()

    def exit_code(self) -> int:
        return 0


def test_overflow_stop_reported_after_slow_prefix_callback_and_obs() -> None:
    """검수 T3-2 지적 1: 유실 앞 이벤트 콜백이 늦는 동안 감시 스레드가 돌아도, 차례는
    events 끝 → obs → (EOF) → on_stop 이다."""
    order: list[str] = []
    entered, release, reported = threading.Event(), threading.Event(), threading.Event()

    def on_update(update: HookUpdate) -> None:
        if update.events:
            order.append("events_enter")
            entered.set()
            assert release.wait(5)
            order.append("events_done")
        if update.obs:
            order.append("obs")

    def on_stop(stop: HookStop) -> None:
        order.append(f"stop:{stop.reason}")
        reported.set()

    client = HookClient(mono_base_ns=0, on_update=on_update, on_stop=on_stop)
    hook = _QueueHook(client)
    core = HookCore(clock=lambda: 0, crit_capacity=4)
    for _ in range(5):
        _key(core)
    hook.incoming.put(Incoming("hook.events", cast(dict[str, Any], core.take_batch()), None))
    obs = [{"cause_event_id": n} for n in range(1, 5)]
    hook.incoming.put(Incoming("hook.obs", {"batch": obs}, None))
    client._start_threads()  # 읽기 + 감시
    assert entered.wait(5)
    assert not reported.wait(0.5), "콜백이 끝나기 전에 멈춤을 알렸다"
    release.set()
    assert reported.wait(10)
    assert order == ["events_enter", "events_done", "obs", "stop:input_overflow"]
    assert client.wait_done(5)


def test_normal_stop_deadline_is_reported_as_incomplete() -> None:
    """검수 T3-2 지적 2: 넘기기 기한을 넘기면 정상 완료(None)와 구별되고, 그 뒤 콜백은 없다."""
    delivered: list[int] = []
    entered, release = threading.Event(), threading.Event()

    def on_update(update: HookUpdate) -> None:
        entered.set()
        assert release.wait(10)
        delivered.extend(e["crit_seq"] for e in update.events)

    client = HookClient(mono_base_ns=0, on_update=on_update, on_stop=lambda stop: None)
    hook = _QueueHook(client)
    core = HookCore(clock=lambda: 0)
    for _ in range(2):
        _key(core)
        hook.incoming.put(Incoming("hook.events", cast(dict[str, Any], core.take_batch()), None))
    client._start_threads()
    assert entered.wait(5)
    started = time.monotonic()
    with pytest.raises(HookStopIncomplete):
        client.stop(timeout=0.2, deliver_timeout=0.5)
    assert time.monotonic() - started < 3
    assert delivered == [] and not client.wait_done(0)
    release.set()
    assert client.wait_done(5)  # 실행 중이던 콜백 하나는 끝난다
    assert delivered == [1]  # 포기한 뒤의 콜백은 없다


def test_normal_stop_within_deadline_returns_none_after_all_delivered() -> None:
    delivered: list[int] = []

    def on_update(update: HookUpdate) -> None:
        time.sleep(0.3)
        delivered.extend(e["crit_seq"] for e in update.events)

    client = HookClient(mono_base_ns=0, on_update=on_update, on_stop=lambda stop: None)
    hook = _QueueHook(client)
    core = HookCore(clock=lambda: 0)
    for _ in range(2):
        _key(core)
        hook.incoming.put(Incoming("hook.events", cast(dict[str, Any], core.take_batch()), None))
    client._start_threads()
    assert client.stop(timeout=1, deliver_timeout=5) is None
    assert delivered == [1, 2]
    assert client.wait_done(0)


@pytest.mark.process
@pytest.mark.timeout(90)
def test_pipe_stall_backpressure_overflows_then_prefix_kept(tmp_path: Path) -> None:
    """검수 T3-1 지적 4의 CI판: 받는 쪽이 **파이프 읽기**를 멈추면 훅의 송신 쓰기가 막히고, 그동안
    중요 큐가 차서 넘친다. 읽기를 재개하면 유실 지점에서 `input_overflow`, 그 앞은 모두 한 번씩."""
    script = tmp_path / "fake_hook.py"
    script.write_text(_CHILD, encoding="utf-8")
    base = time.monotonic_ns()
    raw = RawHook(
        [
            sys.executable,
            str(script),
            "--mode",
            "flood",
            "--argv-out",
            str(tmp_path / "a.json"),
            "--protocol",
            str(HOOK_PROTOCOL),
        ],
        mono_base_ns=base,
        logs_dir=tmp_path,
    ).start()
    try:
        stream = HookStream(mono_base_ns=base)
        hello = raw.recv(timeout=20)
        assert hello is not None
        stream.feed(hello["method"], hello["params"], 0)
        time.sleep(2.0)  # 파이프를 읽지 않는다 (생존 감시는 이 검사가 돌리지 않는다)
        delivered: list[int] = []
        while stream.stop is None:
            message = raw.recv(timeout=10)
            assert message is not None, raw.stderr()
            update = stream.feed(message["method"], message["params"], 0)
            if update is not None:
                delivered += [e["crit_seq"] for e in update.events if "crit_seq" in e]
        assert stream.stop.reason == "input_overflow", stream.stop
        cut = stream.stop.cut_crit_seq
        assert cut is not None and cut > 1
        assert delivered == list(range(1, cut))  # 유실 앞은 빠짐·중복 없이
        assert stream.checker.violation is not None
        assert stream.checker.violation.reason == "overflow"
        raw.send("hook.stop", {})
    finally:
        raw.close()


@pytest.mark.process
@pytest.mark.timeout(60)
def test_start_fails_on_protocol_mismatch(tmp_path: Path) -> None:
    child = Child(tmp_path, "stop", protocol=HOOK_PROTOCOL + 1)
    with pytest.raises(RuntimeError, match="프로토콜"):
        child.client.start(timeout=20)
    assert child.stops == []
