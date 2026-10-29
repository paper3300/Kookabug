"""감독자 `kookabug_core.supervisor` (구현 계획 M0b 2.7): 시작·hello 기한·제어 전달·하드 종료
타이머·채널 상실·복구 경로 호출. 감독자는 이 테스트 프로세스 안의 실제 `Supervisor`다."""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from typing import Any, ClassVar

import pytest
from helpers.graphs import GraphBuilder
from helpers.run import tk
from helpers.supervisor import GRACE_MS, job_idents, runner_stderr, start_run, wait_log

import kookabug_core.supervisor as supervisor_module
from kb_testing.proc import Spawned, assert_no_live, python_cmd, read_fake_input_log, wait_until
from kookabug_core.record import read_run

pytestmark = pytest.mark.process

TEST = "tests/t.graph.json"
start = start_run
stderr = runner_stderr


class _ProcessEntry(ctypes.Structure):
    _fields_: ClassVar = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def parent_pids() -> dict[int, int]:
    """지금 모든 프로세스의 PID → 부모 PID (Toolhelp 스냅샷)."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    entry = _ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    result: dict[int, int] = {}
    try:
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            result[entry.th32ProcessID] = entry.th32ParentProcessID
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return result


def is_descendant(pid: int, ancestor: int, parents: dict[int, int]) -> bool:
    seen: set[int] = set()
    while pid not in seen:
        if pid == ancestor:
            return True
        seen.add(pid)
        if pid not in parents:
            return False
        pid = parents[pid]
    return False


def block_graph() -> GraphBuilder:
    return tk().entry("n_block").node("n_block", "testkit.block")


def hung_key_graph() -> GraphBuilder:
    return (
        tk()
        .entry("n_key")
        .node("n_key", "testkit.input.hold", inputs={"key": "ctrl"}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def test_normal_run_finalized_by_runner(tmp_path: Path, spawned: Spawned) -> None:
    # 제품 기본값: venv의 sys.executable(런처)로 띄워도 hello의 식별로 runner를 잡는다
    graph = (
        tk()
        .entry("n_tap")
        .node("n_tap", "testkit.input.tap", inputs={"x": 1, "y": 2}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    handle = start(tmp_path, spawned, graph, runner_cmd=[], env_direct=False)
    assert handle.start_error is None, stderr(handle)
    assert handle.runner is not None and handle.launcher is not None
    assert handle.job is not None and handle.job.contains(handle.runner.pid)
    outcome = handle.wait(30)
    assert outcome.exit_code == 0 and not outcome.hard_stopped, stderr(handle)
    assert outcome.verdict == "pass" and outcome.recover_error is None
    assert outcome.run_end is not None and outcome.run_end["finalized_by"] == "runner"
    assert outcome.run_json is not None and outcome.run_json["status"] == "finished"
    assert "run_json_repaired" not in outcome.run_json
    # 복구 경로는 확인만 했다 (덧붙인 이벤트 없음)
    assert outcome.recovered is not None and outcome.recovered.finalize.appended == []
    assert outcome.recovered.job_terminated
    assert handle.stopping == ["finish"]
    # 두 번째 wait()는 같은 결과
    assert handle.wait() is outcome


def test_runner_never_says_hello_killed_and_finalized(tmp_path: Path, spawned: Spawned) -> None:
    # 제어 채널에 붙지 않는 "runner": hello 기한에 하드 종료 → 복구 경로가 기록을 마무리한다
    never = python_cmd("-c", "import time; time.sleep(600)")
    began = time.monotonic()
    handle = start(tmp_path, spawned, block_graph(), runner_cmd=never, hello_timeout=1.0)
    assert time.monotonic() - began < 10
    assert handle.start_error is not None and "기한" in handle.start_error
    outcome = handle.wait(30)
    assert outcome.exit_code == 4 and outcome.hard_stopped
    run_end = outcome.run_end
    assert run_end is not None
    assert run_end["code"] == "runner_died" and run_end["finalized_by"] == "supervisor"
    assert run_end["verdict"] == "error"
    assert outcome.run_json is not None and outcome.run_json["status"] == "finished"
    assert outcome.run_json["graph"] == TEST
    assert outcome.recovered is not None and outcome.recovered.job_terminated


def test_runner_exits_before_hello_detected_without_waiting(
    tmp_path: Path, spawned: Spawned
) -> None:
    began = time.monotonic()
    handle = start(
        tmp_path, spawned, block_graph(), runner_cmd=python_cmd("-c", "raise SystemExit(7)")
    )
    assert time.monotonic() - began < 10  # hello 기한(30초)을 기다리지 않는다
    assert handle.start_error is not None and "종료 코드 7" in handle.start_error
    outcome = handle.wait(30)
    assert outcome.exit_code == 7 and not outcome.hard_stopped
    assert outcome.run_end is not None and outcome.run_end["runner_exit_code"] == 7


def test_cancel_pause_resume_forwarded(tmp_path: Path, spawned: Spawned) -> None:
    signal = tmp_path / "gate.signal"
    graph = (
        tk()
        .entry("n_gate")
        .node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_block"})
        .node("n_block", "testkit.block")
    )
    handle = start(tmp_path, spawned, graph)
    wait_log(handle, "gate")
    assert handle.pause() == "pausing"  # 노드 실행 중에도 바로 답한다
    signal.touch()
    wait_until(lambda: any(e["event"] == "debug.pause" for e in read_run(handle.run_dir).events))
    assert handle.resume() == "running"
    wait_log(handle, "blocking")
    assert handle.cancel() == "cancelling"
    outcome = handle.wait(30)
    assert outcome.exit_code == 0 and not outcome.hard_stopped, stderr(handle)
    events = read_run(handle.run_dir).events
    kinds = [e["event"] for e in events]
    assert kinds.count("debug.pause") == 1 and kinds.count("debug.resume") == 1
    (requested,) = [e for e in events if e["event"] == "cancel.requested"]
    assert requested["reason"] == "cancelled"
    assert outcome.run_end is not None and outcome.run_end["finalized_by"] == "runner"
    assert outcome.run_end["cancel_reason"] == "cancelled"
    assert outcome.run_json is not None and outcome.run_json["pause_count"] == 1


@pytest.mark.parametrize("trigger", ["cancel", "deadline"])
def test_supervisor_hard_stops_runner_after_shutdown_grace(
    tmp_path: Path, spawned: Spawned, trigger: str
) -> None:
    # 노드가 ctrl을 누른 채 액터가 백엔드에서 멈춤 → 주 스레드 마무리가 끝나지 않는다.
    # 감독자 하드 종료 타이머: cancel() 또는 runner.stopping(기한 초과)부터 shutdown_grace_ms
    opts: dict[str, Any] = {"deadline_ms": 4_000} if trigger == "deadline" else {}
    handle = start(
        tmp_path, spawned, hung_key_graph(), hooks={"after_down": {"ctrl": "hang"}}, **opts
    )
    log = tmp_path / "input.jsonl"
    wait_until(lambda: any(line["op"] == "down" for line in read_fake_input_log(log)))
    idents = job_idents(handle)
    if trigger == "cancel":
        armed = time.monotonic()
        assert handle.cancel() == "cancelling"
    else:
        wait_until(lambda: handle.stopping, message="runner.stopping 없음")
        armed = time.monotonic()
    code = handle.wait_exit(30)
    elapsed = time.monotonic() - armed
    assert code == 4 and handle.hard_stopped
    # 자기 종료 감시자(유예 + 10초 여유)보다 먼저 감독자가 끝냈다
    assert elapsed < (GRACE_MS + 10_000) / 1000
    outcome = handle.wait(30)
    reason = "cancelled" if trigger == "cancel" else "deadline_exceeded"
    run_end = outcome.run_end
    assert run_end is not None
    assert run_end["code"] == "runner_died" and run_end["finalized_by"] == "supervisor"
    assert run_end["cancel_reason"] == reason and run_end["runner_exit_code"] == 4
    # 감독자 복구 경로가 임대권 안에서 ctrl을 뗐다 (마지막 물리 동작 up)
    ctrl = [line for line in read_fake_input_log(log) if line.get("key") == "ctrl"]
    assert ctrl[-1]["op"] == "up" and ctrl[-1]["by"] == "supervisor"
    assert run_end["input_recovery"] == "recovered"
    assert_no_live(idents)


def test_supervisor_hard_stops_on_channel_loss(tmp_path: Path, spawned: Spawned) -> None:
    handle = start(tmp_path, spawned, block_graph())
    wait_log(handle, "blocking")
    idents = job_idents(handle)
    assert handle.peer is not None
    handle.peer.close()  # 감독자 쪽 연결이 끊겼다 (송신 실패·EOF와 같은 PeerLost)
    outcome = handle.wait(30)
    assert outcome.channel_lost and outcome.hard_stopped and outcome.exit_code == 4
    assert handle.stopping == []  # runner.stopping 전의 상실: 곧바로 하드 종료
    assert outcome.run_end is not None and outcome.run_end["code"] == "runner_died"
    assert outcome.run_end.get("cancel_reason") is None
    assert_no_live(idents)


def test_channel_eof_after_stopping_is_not_hard_stop(tmp_path: Path, spawned: Spawned) -> None:
    # 정상 마무리 끝에 runner가 채널을 닫는다 → 감독자는 하드 종료하지 않는다 (종료 코드 0 유지)
    handle = start(tmp_path, spawned, tk().entry("n_pass").node("n_pass", "core.test.pass"))
    outcome = handle.wait(30)
    assert outcome.exit_code == 0 and not outcome.hard_stopped, stderr(handle)
    assert handle.stopping == ["finish"]


def test_force_stop_kills_and_finalizes(tmp_path: Path, spawned: Spawned) -> None:
    handle = start(tmp_path, spawned, block_graph())
    wait_log(handle, "blocking")
    idents = job_idents(handle)
    outcome = handle.force_stop(30)
    assert outcome.exit_code == 4 and outcome.hard_stopped
    assert outcome.run_end is not None and outcome.run_end["finalized_by"] == "supervisor"
    assert_no_live(idents)


def test_only_supervisor_writes_recovery(tmp_path: Path, spawned: Spawned) -> None:
    # 실행 Job 안에는 runner와 워커뿐이다 (runner 쪽 복구 도우미 프로세스가 없다).
    # runner를 죽인 뒤 기록을 마무리한 것은 감독자다
    handle = start(tmp_path, spawned, block_graph())
    wait_log(handle, "blocking")
    events = read_run(handle.run_dir).events
    (worker,) = [e for e in events if e["event"] == "worker.start"]
    assert handle.runner is not None and handle.job is not None
    before = set(handle.job.process_ids())
    others = before - {handle.runner.pid}
    # runner가 띄운 것은 워커 하나다. 나머지는 그 워커의 자손(venv 런처를 거치면 실제 워커와
    # 런처의 콘솔 호스트)뿐이다
    parents = parent_pids()
    assert handle.runner.pid in before
    assert [p for p in others if parents.get(p) == handle.runner.pid] == [worker["pid"]]
    assert all(is_descendant(p, worker["pid"], parents) for p in others)
    handle.runner.terminate(1)
    assert handle.wait_exit(10) == 1
    # runner가 죽은 뒤 Job에 새로 생긴 프로세스가 없다 (runner 쪽 복구 프로세스 없음)
    assert set(handle.job.process_ids()) <= others
    outcome = handle.wait(30)
    run_end = outcome.run_end
    assert run_end is not None and run_end["finalized_by"] == "supervisor"
    assert outcome.recovered is not None and outcome.recovered.finalize.appended == ["run.end"]
    # 복구 경로의 run.end가 마지막 줄이고, 그 뒤 runner가 쓴 것이 없다
    assert read_run(handle.run_dir).events[-1] == run_end


def test_spec_send_stalled_start_deadline_still_applies(tmp_path: Path, spawned: Spawned) -> None:
    # 검수 T10-1 High 1: stdin을 읽지 않는 자식 + 파이프 버퍼보다 큰 사양. 사양 쓰기가 막혀도
    # 시작 기한(띄우기 전부터 하나)이 지나면 자식을 끝내고 핸들을 돌려준다
    never = python_cmd("-c", "import time; time.sleep(600)")
    began = time.monotonic()
    handle = start(
        tmp_path,
        spawned,
        block_graph(),
        runner_cmd=never,
        hello_timeout=0.5,
        settings={"large": "x" * (1 << 20)},
    )
    assert time.monotonic() - began < 10
    assert handle.start_error is not None and "기한" in handle.start_error
    assert handle.launcher is not None and handle.launcher.poll() is not None  # 자식은 끝났다
    outcome = handle.wait(30)
    assert outcome.exit_code == 4 and outcome.hard_stopped
    assert outcome.run_end is not None and outcome.run_end["code"] == "runner_died"
    assert outcome.run_json is not None and outcome.run_json["status"] == "finished"


def blocked_in_finishing(thread: threading.Thread) -> bool:
    """그 스레드가 마무리 구간의 잠금을 기다리는 중이다."""
    frame = sys._current_frames().get(thread.ident or 0)
    while frame is not None:
        if frame.f_code.co_name == "_finishing":
            return True
        frame = frame.f_back
    return False


def test_concurrent_wait_force_stop_recover_finalize_once(
    tmp_path: Path, spawned: Spawned, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 검수 T10-1 High 2: 같은 핸들에 wait·force_stop·recover가 겹쳐도 복구 작성자는 하나다
    never = python_cmd("-c", "import time; time.sleep(600)")
    handle = start(tmp_path, spawned, block_graph(), runner_cmd=never, hello_timeout=0.5)
    assert handle.start_error is not None
    handle.wait_exit(10)

    real = supervisor_module.recover
    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    calls: list[int] = []
    active = [0, 0]  # 지금, 최대
    nested: list[BaseException] = []

    def slow_recover(*args: Any, **kwargs: Any) -> Any:
        with lock:
            calls.append(threading.get_ident())
            active[0] += 1
            active[1] = max(active)
        try:
            if len(calls) == 1:
                # 마무리 중 같은 스레드의 재진입(신호 처리기 흉내)은 거부된다
                try:
                    handle.force_stop(1)
                except RuntimeError as exc:
                    nested.append(exc)
                entered.set()
                assert release.wait(30)
            return real(*args, **kwargs)
        finally:
            with lock:
                active[0] -= 1

    monkeypatch.setattr(supervisor_module, "recover", slow_recover)
    results: dict[str, Any] = {}

    def run(name: str, fn: Callable[[], Any]) -> threading.Thread:
        thread = threading.Thread(target=lambda: results.__setitem__(name, fn()), daemon=True)
        thread.start()
        return thread

    first = run("wait", lambda: handle.wait(30))
    assert entered.wait(30)
    others = [run("force", lambda: handle.force_stop(30)), run("recover", handle.recover)]
    wait_until(lambda: all(blocked_in_finishing(t) for t in others))
    release.set()
    for thread in (first, *others):
        thread.join(30)
        assert not thread.is_alive()

    assert len(nested) == 1
    assert active[1] == 1  # 복구 경로에 동시에 들어간 스레드가 없다
    assert results["wait"] is results["force"]  # 나머지 대기자는 같은 결과를 받는다
    assert results["wait"].recovered.finalize.appended == ["run.end"]
    assert results["recover"].finalize.appended == []
    view = read_run(handle.run_dir)
    assert [e["event"] for e in view.events].count("run.end") == 1
    assert [e["seq"] for e in view.events] == list(range(1, len(view.events) + 1))
    assert not view.warnings
