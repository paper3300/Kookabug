"""자기 종료 감시자와 감독자 사망 감지 (구현 계획 M0b 2.6, 4차 결정 4·5).

감독자 역할은 별도 프로세스(`dummy_supervisor`)다. 그 프로세스를 끝내면 하네스는 감독자가 쥐던 Job
핸들도 닫고 더는 하드 종료·복구를 하지 않는다 (감독자가 없는 상태).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of

from kb_testing.proc import Spawned, assert_no_live, barrier, wait_until
from kookabug_core.inputs import ACTOR_THREAD_NAME
from kookabug_core.win import ProcessId, identify

pytestmark = pytest.mark.process

GRACE_MS = 2_000
FINALIZE_POINTS = (
    "runner.after_run_end",
    "runner.before_run_json_final",
    "runner.before_worker_shutdown",
    "runner.before_lease_release",
)


def key_graph(key: str = "ctrl") -> GraphBuilder:
    return (
        tk()
        .entry("n_key")
        .node("n_key", "testkit.input.hold", inputs={"key": key}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def unsupervised(tmp_path: Path, graph: GraphBuilder, **kw: Any) -> RunnerHarness:
    kw.setdefault("shutdown_grace_ms", GRACE_MS)
    return RunnerHarness.make(tmp_path, graph, dummy_supervisor=True, hard_stop=False, **kw)


def job_idents(h: RunnerHarness) -> list[ProcessId]:
    return [i for i in (identify(pid) for pid in h.job_pids()) if i is not None]


def test_supervisor_death_detected_by_process_handle(tmp_path: Path, spawned: Spawned) -> None:
    h = unsupervised(tmp_path, key_graph(), hooks={"after_down": {"ctrl": "block"}})
    h.start(spawned)
    wait_until(lambda: any(line["op"] == "down" for line in h.fake_inputs()))
    idents = job_idents(h)
    h.kill_supervisor()
    done = h.finish(recover_record=False)
    assert done.exit_code == 0, h.stderr()
    (requested,) = done.of("cancel.requested")
    assert requested["reason"] == "supervisor_lost"
    run_end = done.run_end
    assert run_end is not None
    assert run_end["finalized_by"] == "runner" and run_end["cancel_reason"] == "supervisor_lost"
    # 키는 액터가 뗐고, 임대권은 깨끗하게 놓였다
    runner_calls = [line for line in h.fake_inputs() if line["by"] == "runner"]
    assert [line["op"] for line in runner_calls] == ["down", "up"]
    assert {line["thread"] for line in runner_calls} == {ACTOR_THREAD_NAME}
    lease = h.lease_file()
    assert lease is not None and lease["clean"] is True
    # runner의 Job 핸들이 마지막으로 닫혀 남은 프로세스(워커)도 끝났다
    assert_no_live(idents)


def test_channel_eof_with_live_supervisor_is_not_cancel(tmp_path: Path, spawned: Spawned) -> None:
    signal = tmp_path / "gate.signal"
    graph = (
        tk()
        .entry("n_gate")
        .node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = RunnerHarness.make(tmp_path, graph).start(spawned)
    h.wait_log("gate")
    h.close_channel()  # 감독자 프로세스(이 테스트)는 살아 있다
    h.wait_event("control.lost")
    assert not h.has_event("cancel.requested")
    signal.touch()  # 노드는 계속 돌고 있었다: 정상으로 끝낸다
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.of("cancel.requested") == []
    assert done.run_end is not None and done.run_end["verdict"] == "pass"


def test_supervisor_dead_and_main_hung_self_terminates(tmp_path: Path, spawned: Spawned) -> None:
    h = unsupervised(tmp_path, key_graph(), hooks={"after_down": {"ctrl": "hang"}})
    h.start(spawned)
    wait_until(lambda: any(line["op"] == "down" for line in h.fake_inputs()))
    idents = job_idents(h)
    killed = time.monotonic()
    h.kill_supervisor()
    done = h.finish(recover_record=False)
    elapsed = time.monotonic() - killed
    assert done.exit_code == 4, h.stderr()
    assert GRACE_MS / 1000 - 0.5 <= elapsed < GRACE_MS / 1000 + 5
    # 이중 고장: 그 자리에서 마무리하는 주체가 없다 (run.end 없음 → 읽기가 "중단")
    assert done.run_end is None and done.view.status == "interrupted"
    lease = h.lease_file()
    assert lease is not None and lease["clean"] is False
    assert_no_live(idents)  # Job 마지막 핸들로 워커도 끝났다


def test_self_terminate_while_journal_lock_held(tmp_path: Path, spawned: Spawned) -> None:
    stuck = barrier(tmp_path / "barriers" / "partial_log")
    faults = [
        {
            "point": "journal.partial_line",
            "role": "runner",
            "when": {"event": "log", "nth": 1},
            "action": stuck.action,
        }
    ]
    graph = tk().entry("n_block").node("n_block", "testkit.block")
    h = unsupervised(tmp_path, graph, faults=faults).start(spawned)
    stuck.wait_ready()  # 주 스레드가 저널 잠금을 쥔 채 log 줄 앞 절반에서 멈췄다
    idents = job_idents(h)
    h.kill_supervisor()
    done = h.finish(recover_record=False)
    # 제어 스레드가 cancel.requested 쓰기에서 막혀도 감시자가 유예 안에 끝낸다
    assert done.exit_code == 4, h.stderr()
    view = done.view
    assert view.truncated and view.status == "interrupted"
    start, end = step_of(view.events, "n_block")
    assert end is None and view.steps[start["step"]].status == "interrupted"
    assert_no_live(idents)


@pytest.mark.parametrize("point", FINALIZE_POINTS)
def test_hang_in_finalize_self_terminates_without_supervisor(
    tmp_path: Path, spawned: Spawned, point: str
) -> None:
    stuck = barrier(tmp_path / "barriers" / "finalize")
    faults = [{"point": point, "role": "runner", "action": stuck.action}]
    h = unsupervised(tmp_path, key_graph(), faults=faults).start(spawned)
    stuck.wait_ready()  # 마무리 중 멈춤 (장벽을 열지 않는다 = 끊을 수 없는 정지)
    idents = job_idents(h)
    h.kill_supervisor()
    done = h.finish(recover_record=False)
    assert done.exit_code == 4, h.stderr()
    assert_no_live(idents)


def test_finalize_deadline_backup_self_kill_when_supervisor_alive_but_not_killing(
    tmp_path: Path, spawned: Spawned
) -> None:
    stuck = barrier(tmp_path / "barriers" / "finalize")
    faults = [{"point": "runner.before_worker_shutdown", "role": "runner", "action": stuck.action}]
    graph = tk().entry("n_pass").node("n_pass", "core.test.pass")
    h = RunnerHarness.make(
        tmp_path,
        graph,
        faults=faults,
        hard_stop=False,  # 감독자는 살아 있지만 하드 종료를 하지 않는다
        shutdown_grace_ms=1_000,
        self_kill_margin_ms=2_000,
    ).start(spawned)
    stuck.wait_ready()
    began = time.monotonic()
    code = h.wait()
    elapsed = time.monotonic() - began
    assert code == 4, h.stderr()
    # 종료 단계 진입 + 마무리 유예 + 자기 종료 여유 (장벽 대기 시작이 진입 직후)
    assert 2.0 <= elapsed < 8.0
    assert h.stopping == ["finish"]
