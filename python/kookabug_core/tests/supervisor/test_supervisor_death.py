"""감독자 프로세스가 죽은 실행 (구현 계획 M0b 2.6 자기 종료 감시자·2.7 종료 보장 표, 4차 결정 3).

감독자는 별도 프로세스(`procs/supervisor_host.py`)의 실제 `Supervisor`다. 테스트가 그 프로세스를
`TerminateProcess`로 끝낸다 — 감독자의 Job 핸들도 OS가 닫는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers.graphs import GraphBuilder
from helpers.run import tk
from helpers.runner import step_of
from helpers.supervisor import SupervisorHost, events, start_run

from kb_testing.proc import Spawned, assert_no_live, barrier, read_fake_input_log, wait_until
from kookabug_core.inputs import ACTOR_THREAD_NAME
from kookabug_core.record import read_run
from kookabug_core.win import Process, ProcessId, identify

pytestmark = pytest.mark.process


def key_graph(key: str = "ctrl") -> GraphBuilder:
    return (
        tk()
        .entry("n_key")
        .node("n_key", "testkit.input.hold", inputs={"key": key}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def block_graph() -> GraphBuilder:
    return tk().entry("n_block").node("n_block", "testkit.block")


def worker_ident(host: SupervisorHost) -> ProcessId:
    (start,) = [e for e in host.view().events if e["event"] == "worker.start"]
    ident = identify(start["pid"])
    assert ident is not None
    return ident


def test_supervisor_killed_runner_cancels_itself(tmp_path: Path, spawned: Spawned) -> None:
    # 노드가 ctrl을 누른 채 게이트가 닫힐 때까지 기다린다(block). 감독자 프로세스를 죽이면 runner가
    # 감독자 프로세스 핸들로 사망을 알고 스스로 취소한다 → 액터가 ctrl을 떼고 정상 마무리
    host = SupervisorHost.make(tmp_path, key_graph(), hooks={"after_down": {"ctrl": "block"}})
    host.start(spawned)
    wait_until(lambda: any(ln["op"] == "down" for ln in host.fake_inputs()), message=host.stderr)
    worker = worker_ident(host)
    with Process.open(host.runner_ident) as runner:
        host.kill()
        code = runner.wait(30)
    assert code == 0, host.stderr()
    view = host.view()
    (requested,) = [e for e in view.events if e["event"] == "cancel.requested"]
    assert requested["reason"] == "supervisor_lost"
    run_end = view.run_end
    assert run_end is not None
    assert run_end["finalized_by"] == "runner" and run_end["cancel_reason"] == "supervisor_lost"
    run_json = host.run_json()
    assert run_json is not None and run_json["status"] == "finished"
    # 키는 runner의 액터가 뗐고, 임대권은 깨끗하게 놓였다
    runner_calls = [ln for ln in host.fake_inputs() if ln["by"] == "runner"]
    assert [ln["op"] for ln in runner_calls] == ["down", "up"]
    assert {ln["thread"] for ln in runner_calls} == {ACTOR_THREAD_NAME}
    lease = host.lease_file()
    assert lease is not None and lease["clean"] is True
    # runner의 Job 핸들이 마지막으로 닫혀 워커도 끝났다. 감독자는 마무리하지 못했다
    assert_no_live([worker])
    assert not (host.out / "done.json").exists()


def test_both_killed_reader_shows_interrupted(tmp_path: Path, spawned: Spawned) -> None:
    partial = barrier(tmp_path / "barriers" / "partial")
    finalize = barrier(tmp_path / "barriers" / "before_finalize")
    faults = [
        {
            "point": "journal.partial_line",
            "role": "runner",
            "when": {"event": "log", "nth": 1},
            "action": partial.action,
        },
        {"point": "recovery.before_finalize", "role": "supervisor", "action": finalize.action},
    ]
    host = SupervisorHost.make(tmp_path, block_graph(), faults=faults).start(spawned)
    partial.wait_ready()  # runner가 log 줄의 앞 절반을 쓰고 멈췄다
    worker = worker_ident(host)
    host.kill_runner()
    finalize.wait_ready()  # 감독자는 runner 종료를 확인했고 마무리 직전이다
    host.kill()
    # 아무도 마무리하지 않은 실행: 읽기만으로 "중단"
    view = read_run(host.run_dir)
    assert view.truncated and view.truncated_bytes > 0
    assert view.run_start is not None and view.run_end is None
    assert view.status == "interrupted"
    start, end = step_of(view.events, "n_block")
    assert end is None and view.steps[start["step"]].status == "interrupted"
    assert not [e for e in view.events if e["event"] == "log"]
    run_json = host.run_json()
    assert run_json is not None and run_json["status"] == "running"
    assert_no_live([worker])  # 두 Job 핸들이 모두 닫혀 OS가 워커를 끝냈다


def test_both_dead_next_lease_owner_recovers_keys(tmp_path: Path, spawned: Spawned) -> None:
    # 실행 A: ctrl을 누른 채 액터가 멈춤 → runner kill → 감독자도 마무리 직전에 kill (이중 고장)
    finalize = barrier(tmp_path / "barriers" / "before_finalize")
    faults = [
        {"point": "recovery.before_finalize", "role": "supervisor", "action": finalize.action}
    ]
    host = SupervisorHost.make(
        tmp_path, key_graph(), faults=faults, hooks={"after_down": {"ctrl": "hang"}}
    ).start(spawned)
    wait_until(lambda: any(ln["op"] == "down" for ln in host.fake_inputs()), message=host.stderr)
    a_run = host.started()["run_id"]
    host.kill_runner()
    finalize.wait_ready()
    host.kill()
    a_dir = host.run_dir
    assert read_run(a_dir).run_end is None
    assert not (a_dir / "input-recovery.json").exists()
    lease = host.lease_file()
    assert lease is not None and lease["clean"] is False  # 그 자리에서 뗀 주체가 없다

    # 실행 B: 같은 임대권·같은 입력 장치. 임대권을 얻으면 입력 전에 A의 ctrl을 뗀다
    env = {k: v for k, v in host.env.items() if k != "KOOKABUG_FAULTS"}
    handle = start_run(tmp_path, spawned, key_graph(), env=env)
    outcome = handle.wait(30)
    assert outcome.exit_code == 0 and outcome.verdict == "pass"
    lines = read_fake_input_log(host.input_log)
    assert [ln["op"] for ln in lines if ln["run"] == a_run] == ["down"]
    b_lines = [ln for ln in lines if ln["run"] == handle.run_id]
    assert [(ln["op"], ln["key"]) for ln in b_lines] == [
        ("up", "ctrl"),  # A의 키 복구 (B가 입력하기 전)
        ("down", "ctrl"),
        ("up", "ctrl"),
    ]
    marker = json.loads((a_dir / "input-recovery.json").read_text(encoding="utf-8"))
    assert marker["recovered_by"] == {"kind": "runner", "run_id": handle.run_id}
    (recovered,) = [e for e in events(handle) if e["event"] == "input.recovered"]
    assert recovered["from_run"] == a_run
    assert recovered["inputs"] == [{"device": "keyboard", "key": "ctrl"}]
    # A의 기록은 여전히 아무도 마무리하지 않은 "중단"이다
    assert read_run(a_dir).status == "interrupted"
