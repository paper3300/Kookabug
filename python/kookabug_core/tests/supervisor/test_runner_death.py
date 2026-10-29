"""runner가 죽은 실행을 감독자가 마무리한다 (구현 계획 M0b 2.7 복구 경로, 완료 기준 3·4·5).

감독자는 이 테스트 프로세스 안의 `Supervisor`(고장 역할 없음) 또는, 감독자 역할 고장 지점을 쓰는
검사에서는 별도 감독자 프로세스(`SupervisorHost`)다. runner를 죽이는 것은 `TerminateProcess`뿐이다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder
from helpers.run import tk
from helpers.runner import step_of
from helpers.supervisor import (
    SupervisorHost,
    events,
    job_idents,
    runner_stderr,
    start_run,
    wait_log,
)

from kb_testing.proc import Spawned, assert_no_live, barrier, read_fake_input_log, wait_until
from kookabug_core.record import read_run
from kookabug_core.supervisor import RunHandle
from kookabug_core.win import identify, is_alive

pytestmark = pytest.mark.process


def block_graph() -> GraphBuilder:
    return (
        tk()
        .entry("n_block")
        .node("n_block", "testkit.block", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def key_graph(key: str) -> GraphBuilder:
    return (
        tk()
        .entry("n_key")
        .node("n_key", "testkit.input.hold", inputs={"key": key}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def tap_graph(button: str = "left") -> GraphBuilder:
    return (
        tk()
        .entry("n_tap")
        .node("n_tap", "testkit.input.tap", inputs={"x": 3, "y": 4}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def kill_runner(handle: RunHandle) -> None:
    assert handle.runner is not None
    handle.runner.terminate(1)
    assert handle.wait_exit(10) == 1


def assert_runner_died(outcome_run_end: dict[str, Any] | None, exit_code: int = 1) -> None:
    assert outcome_run_end is not None
    assert outcome_run_end["verdict"] == "error"
    assert outcome_run_end["code"] == "runner_died"
    assert outcome_run_end["finalized_by"] == "supervisor"
    assert outcome_run_end["runner_exit_code"] == exit_code


def test_runner_killed_mid_node_supervisor_finalizes(tmp_path: Path, spawned: Spawned) -> None:
    handle = start_run(tmp_path, spawned, block_graph())
    wait_log(handle, "blocking")
    idents = job_idents(handle)
    kill_runner(handle)
    outcome = handle.wait(30)
    assert_runner_died(outcome.run_end)
    view = read_run(handle.run_dir)
    start, end = step_of(view.events, "n_block")
    assert end is None  # 열린 스텝에는 step.end를 쓰지 않는다
    assert view.steps[start["step"]].status == "interrupted"
    assert outcome.run_json is not None and outcome.run_json["status"] == "finished"
    assert outcome.run_json["code"] == "runner_died" and outcome.run_json["run_json_repaired"]
    assert_no_live(idents)  # Job 정리로 워커도 끝났다


def assert_inputs_recovered(
    handle: RunHandle, log: Path, inputs: list[dict[str, str]], run_end: dict[str, Any] | None
) -> None:
    (recovered,) = [e for e in events(handle) if e["event"] == "input.recovered"]
    assert sorted(recovered["inputs"], key=json.dumps) == sorted(inputs, key=json.dumps)
    assert recovered["by"]["kind"] == "supervisor"
    assert run_end is not None and run_end["input_recovery"] == "recovered"
    marker = json.loads((handle.run_dir / "input-recovery.json").read_text(encoding="utf-8"))
    assert marker["recovered_by"]["kind"] == "supervisor"
    # 키·버튼마다 마지막 물리 동작은 감독자의 up이다
    lines = read_fake_input_log(log)
    for item in inputs:
        name_field = "key" if item["device"] == "keyboard" else "button"
        mine = [ln for ln in lines if ln["device"] == item["device"]]
        mine = [ln for ln in mine if ln.get(name_field) == item.get(name_field)]
        assert mine[-1]["op"] == "up" and mine[-1]["by"] == "supervisor", mine


def test_runner_killed_with_key_down_supervisor_releases(tmp_path: Path, spawned: Spawned) -> None:
    handle = start_run(tmp_path, spawned, key_graph("ctrl"), hooks={"after_down": {"ctrl": "hang"}})
    log = tmp_path / "input.jsonl"
    wait_until(lambda: any(ln["op"] == "down" for ln in read_fake_input_log(log)))
    kill_runner(handle)
    outcome = handle.wait(30)
    assert_runner_died(outcome.run_end)
    assert_inputs_recovered(handle, log, [{"device": "keyboard", "key": "ctrl"}], outcome.run_end)


@pytest.mark.parametrize(
    ("graph", "hooks", "held"),
    [
        pytest.param(
            key_graph("ctrl+shift"),
            {"after_down": {"shift": "hang"}},
            [{"device": "keyboard", "key": "ctrl"}, {"device": "keyboard", "key": "shift"}],
            id="two-keys",
        ),
        pytest.param(
            tap_graph(),
            {"after_down": {"mouse:left": "hang"}},
            [{"device": "mouse", "button": "left"}],
            id="mouse",
        ),
    ],
)
def test_runner_killed_with_mouse_and_two_keys_down(
    tmp_path: Path,
    spawned: Spawned,
    graph: GraphBuilder,
    hooks: dict[str, dict[str, str]],
    held: list[dict[str, str]],
) -> None:
    # 입력 액터는 원시 동작을 하나씩 하므로 한 runner가 동시에 누를 수 있는 것은 조합 키의 앞부분
    # 또는 마우스 버튼 하나다. 두 경우 모두 감독자가 눌린 것 전부를 뗀다
    handle = start_run(tmp_path, spawned, graph, hooks=hooks)
    log = tmp_path / "input.jsonl"
    want_downs = len(held)
    wait_until(lambda: sum(ln["op"] == "down" for ln in read_fake_input_log(log)) == want_downs)
    kill_runner(handle)
    outcome = handle.wait(30)
    assert_runner_died(outcome.run_end)
    assert_inputs_recovered(handle, log, held, outcome.run_end)


def test_runner_killed_after_run_end_before_run_json(tmp_path: Path, spawned: Spawned) -> None:
    gate = barrier(tmp_path / "barriers" / "after_run_end")
    faults = [{"point": "runner.after_run_end", "role": "runner", "action": gate.action}]
    handle = start_run(
        tmp_path, spawned, tk().entry("n").node("n", "core.test.pass"), faults=faults
    )
    gate.wait_ready()
    kill_runner(handle)
    outcome = handle.wait(30)
    run_end = outcome.run_end
    # runner가 쓴 run.end를 runner_died로 덮지 않는다. run.json만 run.end에서 다시 만든다
    assert run_end is not None and run_end["verdict"] == "pass"
    assert run_end["finalized_by"] == "runner"
    assert outcome.recovered is not None and outcome.recovered.finalize.appended == []
    assert outcome.run_json is not None and outcome.run_json["status"] == "finished"
    assert outcome.run_json["verdict"] == "pass" and outcome.run_json["run_json_repaired"] is True
    assert read_run(handle.run_dir).events[-1] == run_end


def test_runner_killed_before_worker_shutdown_job_cleans_worker(
    tmp_path: Path, spawned: Spawned
) -> None:
    # 워커 노드가 끝나고 마무리에 들어간 runner를 워커 shutdown 전에 죽인다 → 워커는 Job 정리로 끝남
    gate = barrier(tmp_path / "barriers" / "before_worker_shutdown")
    faults = [{"point": "runner.before_worker_shutdown", "role": "runner", "action": gate.action}]
    graph = (
        tk()
        .entry("n_value")
        .node("n_value", "testkit.config_value", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    handle = start_run(tmp_path, spawned, graph, faults=faults)
    gate.wait_ready()
    (worker,) = [e for e in events(handle) if e["event"] == "worker.start"]
    worker_ident = identify(worker["pid"])
    assert worker_ident is not None and is_alive(worker_ident)
    idents = job_idents(handle)
    kill_runner(handle)
    assert is_alive(worker_ident)  # runner가 죽어도 감독자의 Job 핸들이 있어 워커는 아직 산다
    outcome = handle.wait(30)
    assert_runner_died(outcome.run_end)
    assert outcome.recovered is not None and outcome.recovered.job_terminated
    assert_no_live(idents)
    assert not [e for e in events(handle) if e["event"] == "worker.exit"]


def test_runner_killed_mid_line_truncated_then_finalized(tmp_path: Path, spawned: Spawned) -> None:
    gate = barrier(tmp_path / "barriers" / "partial")
    faults = [
        {
            "point": "journal.partial_line",
            "role": "runner",
            "when": {"event": "log", "nth": 1},
            "action": gate.action,
        }
    ]
    handle = start_run(tmp_path, spawned, block_graph(), faults=faults)
    gate.wait_ready()
    raw = (handle.run_dir / "events.jsonl").read_bytes()
    assert not raw.endswith(b"\n")  # log 줄의 앞 절반에서 멈췄다
    kill_runner(handle)
    outcome = handle.wait(30)  # 이 프로세스의 감독자에는 고장 규칙이 없다
    assert outcome.recovered is not None
    assert outcome.recovered.finalize.truncated_bytes > 0
    data = (handle.run_dir / "events.jsonl").read_bytes()
    assert data.endswith(b"\n")
    lines = [json.loads(line) for line in data.splitlines()]  # 파일 전체가 유효한 JSONL
    assert [e["seq"] for e in lines] == list(range(1, len(lines) + 1))
    assert not [e for e in lines if e["event"] == "log"]
    view = read_run(handle.run_dir)
    assert not view.truncated
    start, end = step_of(view.events, "n_block")
    assert end is None and view.steps[start["step"]].status == "interrupted"
    assert_runner_died(outcome.run_end)


def test_supervisor_writes_only_after_runner_exit_observed(
    tmp_path: Path, spawned: Spawned
) -> None:
    gate = barrier(tmp_path / "barriers" / "exit_observed")
    faults = [
        {"point": "recovery.runner_exit_observed", "role": "supervisor", "action": gate.action}
    ]
    host = SupervisorHost.make(tmp_path, block_graph(), faults=faults).start(spawned)
    wait_until(lambda: host.has_log("blocking"), message=host.stderr)
    runner = host.runner_ident
    journal = host.run_dir / "events.jsonl"
    host.kill_runner()
    before = journal.read_bytes()
    gate.wait_ready()
    # 지점에 닿았을 때 runner는 식별상 끝났고, 감독자는 아직 아무것도 쓰지 않았다
    assert not is_alive(runner)
    assert journal.read_bytes() == before
    run_json = host.run_json()
    assert run_json is not None and run_json["status"] == "running"
    gate.go()
    done = host.done()
    assert done["recover_error"] is None and done["appended"] == ["run.end"]
    assert_runner_died(done["run_end"])
    assert host.view().events[-1] == done["run_end"]


def test_runner_hard_stopped_supervisor_recovers(tmp_path: Path, spawned: Spawned) -> None:
    # 취소 + 액터가 백엔드에서 멈춤 → 감독자 하드 종료(코드 4) → 감독자 복구 경로
    handle = start_run(tmp_path, spawned, key_graph("ctrl"), hooks={"after_down": {"ctrl": "hang"}})
    log = tmp_path / "input.jsonl"
    wait_until(lambda: any(ln["op"] == "down" for ln in read_fake_input_log(log)))
    idents = job_idents(handle)
    assert handle.cancel() == "cancelling"
    outcome = handle.wait(30)
    assert outcome.exit_code == 4 and outcome.hard_stopped, runner_stderr(handle)
    assert_runner_died(outcome.run_end, exit_code=4)
    assert outcome.run_end is not None and outcome.run_end["cancel_reason"] == "cancelled"
    assert_inputs_recovered(handle, log, [{"device": "keyboard", "key": "ctrl"}], outcome.run_end)
    assert_no_live(idents)


def test_finalize_called_twice_no_duplicates(tmp_path: Path, spawned: Spawned) -> None:
    handle = start_run(tmp_path, spawned, key_graph("ctrl"), hooks={"after_down": {"ctrl": "hang"}})
    log = tmp_path / "input.jsonl"
    wait_until(lambda: any(ln["op"] == "down" for ln in read_fake_input_log(log)))
    kill_runner(handle)
    outcome = handle.wait(30)
    data = (handle.run_dir / "events.jsonl").read_bytes()
    run_json = (handle.run_dir / "run.json").read_bytes()
    log_lines = read_fake_input_log(log)
    again = handle.recover()  # 같은 실행을 다시 복구해도
    assert again.finalize.appended == []
    assert again.finalize.run_end == outcome.run_end
    assert (handle.run_dir / "events.jsonl").read_bytes() == data
    assert (handle.run_dir / "run.json").read_bytes() == run_json
    assert read_fake_input_log(log) == log_lines  # 키를 다시 떼지 않는다 (복구 표시 파일)
    assert handle.wait() is outcome


def test_seq_continues_after_runner_lines(tmp_path: Path, spawned: Spawned) -> None:
    handle = start_run(tmp_path, spawned, block_graph())
    wait_log(handle, "blocking")
    last_runner_seq = read_run(handle.run_dir).last_seq
    kill_runner(handle)
    outcome = handle.wait(30)
    view = read_run(handle.run_dir)
    assert [e["seq"] for e in view.events] == list(range(1, len(view.events) + 1))
    assert outcome.run_end is not None and outcome.run_end["seq"] == last_runner_seq + 1
    assert not view.warnings
