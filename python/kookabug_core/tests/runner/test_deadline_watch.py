"""전체 기한 감시 (구현 계획 M0b 2.6, G11): 제어 스레드가 기한 시각에 취소 순서를
`deadline_exceeded`로 시작한다. 워커 노드도 끊긴다. 판정은 `error`."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of

from kb_testing.proc import Spawned

pytestmark = pytest.mark.process


def test_deadline_kills_hung_worker_node(tmp_path: Path, spawned: Spawned) -> None:
    graph = tk().entry("n_hang").node("n_hang", "testkit.hang", inputs={"label": "hanging"})
    h = RunnerHarness.make(tmp_path, graph, deadline_ms=3_000, worker_cancel_grace_ms=500).start(
        spawned
    )
    h.wait_log("hanging")
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    _, end = step_of(done.view.events, "n_hang")
    assert end is not None and end["status"] == "error"
    assert end["error"]["code"] == "deadline_exceeded"
    (exit,) = done.of("worker.exit")
    assert exit["reason"] == "killed_after_grace"
    run_end = done.run_end
    assert run_end is not None
    assert run_end["verdict"] == "error" and run_end["code"] == "deadline_exceeded"
    assert run_end["cancel_reason"] == "deadline_exceeded"
    assert [e["reason"] for e in done.of("cancel.requested")] == ["deadline_exceeded"]
    assert h.stopping == ["deadline_exceeded"]


@pytest.mark.parametrize("trial", range(3))
def test_deadline_during_core_delay(tmp_path: Path, spawned: Spawned, trial: int) -> None:
    # 실행기가 제어 스레드보다 먼저 기한을 봐도 같은 취소 경로로 모인다 (검수 T9-1 R3): 경쟁이라
    # 여러 번 돌린다
    graph = (
        tk()
        .entry("n_delay")
        .node("n_delay", "core.flow.delay", inputs={"ms": 60_000}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = RunnerHarness.make(tmp_path, graph, plugin_modules=(), deadline_ms=2_000)
    began = time.monotonic()
    h.start(spawned)
    done = h.finish()
    assert time.monotonic() - began < 10
    assert done.exit_code == 0, h.stderr()
    _, end = step_of(done.view.events, "n_delay")
    assert end is not None and end["status"] == "error"
    assert end["error"]["code"] == "deadline_exceeded"
    run_end = done.run_end
    assert run_end is not None and run_end["code"] == "deadline_exceeded"
    assert run_end["cancel_reason"] == "deadline_exceeded"
    (requested,) = done.of("cancel.requested")
    assert requested["reason"] == "deadline_exceeded"
    kinds = [e["event"] for e in done.view.events]
    assert kinds.index("cancel.requested") < kinds.index("run.end") == len(kinds) - 1
    assert h.stopping == ["deadline_exceeded"]
