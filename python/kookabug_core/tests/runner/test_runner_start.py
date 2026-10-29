"""runner 시작 순서 (구현 계획 M0b 2.6 "시작 순서").

스냅샷 → 워커 hello·원격 등록 → 의미 검증 → 입력 임대권 → 실행. 시작 중에도 취소가 먹힌다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers.graphs import GraphBuilder
from helpers.lease import LeaseEnv
from helpers.run import tk
from helpers.runner import RunnerHarness, events_of, step_of

from kb_testing.proc import Spawned, barrier

pytestmark = pytest.mark.process


def passing(node_type: str = "testkit.read_text") -> GraphBuilder:
    return (
        tk()
        .entry("n_work")
        .node("n_work", node_type, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def test_start_order_events(tmp_path: Path, spawned: Spawned) -> None:
    h = RunnerHarness.make(tmp_path, passing()).start(spawned)
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    kinds = [e["event"] for e in done.view.events]
    # run.start → (스냅샷: 파일) → worker.start → (검증) → 첫 step.start → … → run.end
    assert kinds[0] == "run.start"
    assert kinds.index("worker.start") < kinds.index("step.start")
    assert kinds[-1] == "run.end"
    assert (h.run_dir / "snapshot" / "tests" / "t.graph.json").is_file()
    snapshot_mtime = (h.run_dir / "snapshot" / "tests" / "t.graph.json").stat().st_mtime_ns
    worker_log = h.run_dir / "logs" / "worker.stderr.log"
    assert worker_log.exists() and worker_log.stat().st_mtime_ns >= snapshot_mtime
    run_end = done.run_end
    assert run_end is not None
    assert run_end["verdict"] == "pass" and run_end["finalized_by"] == "runner"
    assert done.run_json is not None
    assert done.run_json["status"] == "finished" and done.run_json["verdict"] == "pass"
    assert {"id": "testkit", "version": "0+dev"} in done.run_json["plugins"]
    assert done.recovered is not None and done.recovered.finalize.appended == []


def test_external_plugin_only_graph_passes(tmp_path: Path, spawned: Spawned) -> None:
    # 코어 노드 없이 플러그인 노드만으로 끝나는 그래프 (검증이 원격 선언으로 통과해야 한다)
    graph = tk().entry("n_work").node("n_work", "testkit.read_text")
    h = RunnerHarness.make(tmp_path, graph).start(spawned)
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None
    # 검증 노드 없이 끝났으므로 no_assertion fail (원격 선언으로 검증을 통과해 실행까지 갔다)
    assert done.run_end["code"] == "no_assertion"
    _, end = step_of(done.view.events, "n_work")
    assert end is not None and end["status"] == "success"


def test_graph_invalid_recorded_with_diagnostics(tmp_path: Path, spawned: Spawned) -> None:
    graph = tk().entry("n_work").node("n_work", "testkit.no_such_node")
    h = RunnerHarness.make(tmp_path, graph).start(spawned)
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None
    assert done.run_end["verdict"] == "error" and done.run_end["code"] == "graph_invalid"
    assert done.of("step.start") == []
    assert done.run_json is not None
    codes = {d["code"] for d in done.run_json["diagnostics"]}
    assert "node_type_unknown" in codes or any("unknown" in c for c in codes), codes


def test_input_lease_busy_is_error_with_owner(tmp_path: Path, spawned: Spawned) -> None:
    env = LeaseEnv.make(tmp_path / "lease")
    holder = env.lease("other")  # 이 프로세스가 같은 이름의 임대권을 쥔다
    holder.lease.acquire(0)
    try:
        graph = (
            tk()
            .entry("n_key")
            .node("n_key", "testkit.input.hold", next={"done": "n_pass"})
            .node("n_pass", "core.test.pass")
        )
        h = RunnerHarness.make(
            tmp_path,
            graph,
            lease_name=env.env["KOOKABUG_INPUT_LEASE_NAME"],
            state_dir=Path(env.env["KOOKABUG_STATE_DIR"]),
        ).start(spawned)
        done = h.finish()
    finally:
        holder.lease.release(None)
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None
    assert done.run_end["code"] == "input_lease_busy"
    assert "other" in done.run_end["reason"]
    assert done.of("step.start") == []
    assert h.fake_inputs() == []


def test_no_input_effect_no_lease(tmp_path: Path, spawned: Spawned) -> None:
    h = RunnerHarness.make(tmp_path, passing()).start(spawned)
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    # 입력 노드가 없으면 임대권을 얻지 않는다 (옆 파일이 생기지 않음)
    assert h.lease_file() is None
    assert events_of(done.view.events, "input.recovered") == []


def test_cancel_during_startup(tmp_path: Path, spawned: Spawned) -> None:
    gate = barrier(tmp_path / "barriers" / "after_hello")
    faults = [{"point": "runner.after_hello", "role": "runner", "action": gate.action}]
    h = RunnerHarness.make(tmp_path, passing(), faults=faults).start(spawned)
    gate.wait_ready()
    assert h.cancel() == "cancelling"
    h.wait_event("cancel.requested", reason="cancelled")
    gate.go()
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None
    assert done.run_end["code"] == "cancelled" and done.run_end["cancel_reason"] == "cancelled"
    # 스냅샷·워커·실행 전에 끝났다
    assert done.of("worker.start") == [] and done.of("step.start") == []
