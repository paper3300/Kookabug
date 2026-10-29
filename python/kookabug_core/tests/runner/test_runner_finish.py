"""runner 정상 마무리 (구현 계획 M0b 2.6 "정상 마무리 순서").

주 스레드만 마무리한다: 워커 shutdown → 액터 STOP·join → run.end → run.json → (quiesced면) 임대권
깨끗하게 놓기 → 종료 코드 0.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers.graphs import GraphBuilder
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of

from kb_testing.proc import Spawned, barrier, wait_until
from kookabug_core.inputs import ACTOR_THREAD_NAME

pytestmark = pytest.mark.process


def key_graph(key: str = "a") -> GraphBuilder:
    return (
        tk()
        .entry("n_key")
        .node("n_key", "testkit.input.hold", inputs={"key": key}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def test_normal_finish_order(tmp_path: Path, spawned: Spawned) -> None:
    h = RunnerHarness.make(tmp_path, key_graph()).start(spawned)
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    kinds = [e["event"] for e in done.view.events]
    last_step_end = max(i for i, k in enumerate(kinds) if k == "step.end")
    # 워커 shutdown → run.end. run.end가 runner의 마지막 줄이다
    assert last_step_end < kinds.index("worker.exit") < kinds.index("run.end") == len(kinds) - 1
    (exit,) = done.of("worker.exit")
    assert exit["reason"] == "shutdown" and exit["exit_code"] == 0
    # 입력은 액터가 눌렀다 뗐다 (down 기록 → up 기록)
    assert [e["event"] for e in done.view.events if e["event"].startswith("input.")] == [
        "input.down",
        "input.up",
    ]
    assert h.stopping == ["finish"]
    assert done.run_json is not None and done.run_json["status"] == "finished"
    assert done.run_json["pause_count"] == 0
    lease = h.lease_file()
    assert lease is not None and lease["clean"] is True and lease["owner"] is None


def test_exit_code_zero_after_main_finalize(tmp_path: Path, spawned: Spawned) -> None:
    graph = tk().entry("n_pass").node("n_pass", "core.test.pass")
    h = RunnerHarness.make(tmp_path, graph, plugin_modules=()).start(spawned)
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["finalized_by"] == "runner"
    # 복구 경로는 확인만 한다 (덧붙인 것 없음, run.json 그대로)
    assert done.recovered is not None
    assert done.recovered.finalize.appended == []
    assert done.recovered.finalize.run_json_repaired is False
    assert done.run_json is not None and "run_json_repaired" not in done.run_json
    assert done.view.outcome == "finalized_by_runner"


def test_lease_released_clean_only_after_actor_joined(tmp_path: Path, spawned: Spawned) -> None:
    # 액터가 up 직전에 멈춘 동안 임대권은 dirty(이 실행이 소유)다. 액터가 끝난 뒤에만 clean
    stall = barrier(tmp_path / "barriers" / "before_up")
    faults = [
        {
            "point": "actor.before_backend",
            "role": "runner",
            "when": {"event": "up"},
            "action": stall.action,
        }
    ]
    h = RunnerHarness.make(tmp_path, key_graph(), faults=faults).start(spawned)
    stall.wait_ready()
    lease = h.lease_file()
    assert lease is not None and lease["clean"] is False
    assert lease["owner"]["run_id"] == h.run_dir.name.rsplit("_", 1)[1]
    assert not h.has_event("run.end")
    stall.go()
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    lease = h.lease_file()
    assert lease is not None and lease["clean"] is True
    assert lease["last_owner"]["run_id"] == lease_run_id(h)
    runner_calls = [line for line in h.fake_inputs() if line["by"] == "runner"]
    assert [line["op"] for line in runner_calls] == ["down", "up"]
    assert {line["thread"] for line in runner_calls} == {ACTOR_THREAD_NAME}


def test_key_left_down_by_node_released_by_actor_at_finish(
    tmp_path: Path, spawned: Spawned
) -> None:
    # 노드의 입력 요청이 키를 누른 채 막혀 있다(after_down: block) → 취소로 게이트가 닫히면 요청은
    # 취소되고 키는 눌린 채 남는다 → 마무리 전에 액터가 그 키를 뗀다 (RELEASE_ALL, 액터 스레드)
    h = RunnerHarness.make(
        tmp_path, key_graph("ctrl"), hooks={"after_down": {"ctrl": "block"}}
    ).start(spawned)
    wait_until(lambda: any(line["op"] == "down" for line in h.fake_inputs()))
    h.cancel()
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    _, end = step_of(done.view.events, "n_key")
    assert end is not None and end["status"] == "cancelled"
    inputs = [e for e in done.view.events if e["event"].startswith("input.")]
    assert [(e["event"], e["key"]) for e in inputs] == [
        ("input.down", "ctrl"),
        ("input.up", "ctrl"),
    ]
    kinds = [e["event"] for e in done.view.events]
    assert kinds.index("input.up") < kinds.index("run.end")
    runner_calls = [line for line in h.fake_inputs() if line["by"] == "runner"]
    assert [(line["op"], line["key"]) for line in runner_calls] == [
        ("down", "ctrl"),
        ("up", "ctrl"),
    ]
    assert {line["thread"] for line in runner_calls} == {ACTOR_THREAD_NAME}
    lease = h.lease_file()
    assert lease is not None and lease["clean"] is True


def test_journal_write_failure_exits_3_and_supervisor_finalizes(
    tmp_path: Path, spawned: Spawned
) -> None:
    # 저널 쓰기가 줄 중간에 실패하면 runner는 기록 없이 노드를 더 돌리지 않고, run.end를 쓰지 못한
    # 채 종료 코드 3으로 끝난다 → 감독자 복구 경로가 잘린 줄을 자르고 runner_died로 마무리한다
    faults = [
        {
            "point": "journal.partial_line",
            "role": "runner",
            "when": {"event": "step.start", "nth": 2},
            "action": "raise",
        }
    ]
    graph = tk().entry("n_pass").node("n_pass", "core.test.pass")
    h = RunnerHarness.make(tmp_path, graph, plugin_modules=(), faults=faults).start(spawned)
    done = h.finish()
    assert done.exit_code == 3, h.stderr()
    assert done.recovered is not None and done.recovered.finalize.truncated_bytes > 0
    run_end = done.run_end
    assert run_end is not None
    assert run_end["code"] == "runner_died" and run_end["runner_exit_code"] == 3
    assert [e for e in done.view.events if e.get("node") == "n_pass"] == []
    assert not done.view.truncated  # 복구 경로가 잘린 줄을 잘라 냈다


def lease_run_id(h: RunnerHarness) -> str:
    return h.run_dir.name.rsplit("_", 1)[1]
