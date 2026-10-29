"""취소 순서 (구현 계획 M0b 2.6 "취소 순서", 계획 검수 4차 M1).

`cancel.requested`·액터의 `input.up`·`worker.exit`·`step.end`는 서로 다른 스레드·프로세스가 쓰므로
그 사이 순서는 단정하지 않는다. 단정하는 것: 게이트가 닫힌 뒤 새 입력이 처리되지 않음, 진행 중이던
원시 동작이 누른 키는 액터가 뗌, 제어 스레드는 백엔드를 부르지 않음, `run.end`가 마지막.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of

from kb_testing.proc import Spawned, wait_until
from kookabug_core.inputs import ACTOR_THREAD_NAME

pytestmark = pytest.mark.process


def single(node_type: str, inputs: dict[str, object] | None = None) -> GraphBuilder:
    return (
        tk()
        .entry("n_work")
        .node("n_work", node_type, inputs=inputs, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def blocked_on_key(tmp_path: Path, spawned: Spawned, **kw: Any) -> RunnerHarness:
    """워커 노드가 `ctrl`을 누른 채 막힌 상태 (가짜 백엔드 after_down: block)."""
    graph = single("testkit.input.hold", {"key": "ctrl", "text": "hello"})
    h = RunnerHarness.make(tmp_path, graph, hooks={"after_down": {"ctrl": "block"}}, **kw)
    h.start(spawned)
    wait_until(lambda: any(line["op"] == "down" for line in h.fake_inputs()))
    return h


def test_cancel_order_by_seq(tmp_path: Path, spawned: Spawned) -> None:
    h = blocked_on_key(tmp_path, spawned)
    assert h.cancel() == "cancelling"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    events = done.view.events
    kinds = [e["event"] for e in events]
    seq = {k: i for i, k in reversed(list(enumerate(kinds)))}  # 처음 나온 위치
    (requested,) = done.of("cancel.requested")
    assert requested["reason"] == "cancelled"
    # 진행 중이던 down → 액터의 up (같은 키)
    assert seq["input.down"] < seq["input.up"]
    # 열린 스텝은 cancelled로 닫히고, 워커는 정상 shutdown, run.end가 마지막
    _, end = step_of(events, "n_work")
    assert end is not None and end["status"] == "cancelled"
    assert seq["worker.exit"] < seq["run.end"] and kinds[-1] == "run.end"
    run_end = done.run_end
    assert run_end is not None
    assert run_end["code"] == "cancelled" and run_end["cancel_reason"] == "cancelled"
    assert h.stopping and h.stopping[0] == "cancelled"


def test_control_thread_never_calls_backend(tmp_path: Path, spawned: Spawned) -> None:
    h = blocked_on_key(tmp_path, spawned)
    h.cancel()
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    runner_calls = [line for line in h.fake_inputs() if line["by"] == "runner"]
    assert [line["op"] for line in runner_calls] == ["down", "up"]
    # 취소를 받은 제어 스레드가 아니라 액터가 뗐다
    assert {line["thread"] for line in runner_calls} == {ACTOR_THREAD_NAME}


def test_input_rejected_after_gate(tmp_path: Path, spawned: Spawned) -> None:
    # 노드는 key 뒤에 type_text를 하려 했지만, 게이트가 닫힌 뒤라 그 입력은 백엔드에 가지 않는다
    h = blocked_on_key(tmp_path, spawned)
    h.cancel()
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    ops = [line["op"] for line in h.fake_inputs()]
    assert "text" not in ops
    assert ops.count("down") == 1
    events = done.view.events
    cancel_at = next(i for i, e in enumerate(events) if e["event"] == "cancel.requested")
    assert not [e for e in events[cancel_at:] if e["event"] == "input.down"]


def test_cancel_during_inprocess_core_delay(tmp_path: Path, spawned: Spawned) -> None:
    graph = (
        tk()
        .entry("n_delay")
        .node("n_delay", "core.flow.delay", inputs={"ms": 60_000}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = RunnerHarness.make(tmp_path, graph, plugin_modules=()).start(spawned)
    h.wait_event("step.start", node="n_delay")
    began = time.monotonic()
    h.cancel()
    code = h.wait()
    assert time.monotonic() - began < 1.0
    assert code == 0, h.stderr()
    done = h.finish()
    _, end = step_of(done.view.events, "n_delay")
    assert end is not None and end["status"] == "cancelled"
    assert done.run_end is not None and done.run_end["code"] == "cancelled"


def test_cancel_during_worker_node(tmp_path: Path, spawned: Spawned) -> None:
    h = RunnerHarness.make(tmp_path, single("testkit.block")).start(spawned)
    h.wait_log("blocking")
    h.cancel()
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    _, end = step_of(done.view.events, "n_work")
    assert end is not None and end["status"] == "cancelled"
    (exit,) = done.of("worker.exit")
    assert exit["reason"] == "shutdown"
    assert done.run_end is not None and done.run_end["code"] == "cancelled"
