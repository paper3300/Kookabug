"""경계 멈춤 (구현 계획 M0b 2.6 "멈춤", P8).

`run.pause`는 노드 실행 중이어도 받는 즉시 답하고(`pausing`), 다음 스텝 시작 확인 지점에서 멈춘다
(`debug.pause`). 멈춘 동안 취소가 바로 먹히고, 취소가 재개를 이긴다. 멈춘 시간은 기한에서 빼지
않는다(M3부터).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of

from kb_testing.proc import Spawned

pytestmark = pytest.mark.process


def gate_graph(signal: Path) -> GraphBuilder:
    return (
        tk()
        .entry("n_gate")
        .node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def paused(tmp_path: Path, spawned: Spawned, **kw: Any) -> RunnerHarness:
    """`n_gate` 실행 중 멈춤 요청 → gate를 끝내 다음 경계에서 멈춘 상태."""
    signal = tmp_path / "gate.signal"
    h = RunnerHarness.make(tmp_path, gate_graph(signal), **kw).start(spawned)
    h.wait_log("gate")
    assert h.pause() == "pausing"
    signal.touch()
    h.wait_event("debug.pause")
    return h


def test_pause_acknowledged_while_node_running(tmp_path: Path, spawned: Spawned) -> None:
    signal = tmp_path / "gate.signal"
    h = RunnerHarness.make(tmp_path, gate_graph(signal)).start(spawned)
    h.wait_log("gate")
    began = time.monotonic()
    assert h.pause() == "pausing"
    assert time.monotonic() - began < 1.0
    # 응답이 왔을 때 노드는 아직 실행 중이다 (멈춤은 경계에서)
    start, end = step_of(h.events(), "n_gate")
    assert end is None and not h.has_event("debug.pause")
    signal.touch()
    h.wait_event("debug.pause")
    assert h.resume() == "running"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "pass"
    assert start["node"] == "n_gate"


def test_pause_applied_at_next_boundary(tmp_path: Path, spawned: Spawned) -> None:
    h = paused(tmp_path, spawned)
    events = h.events()
    kinds = [e["event"] for e in events]
    at = kinds.index("debug.pause")
    _, gate_end = step_of(events, "n_gate")
    assert gate_end is not None and events.index(gate_end) < at
    # 멈춘 뒤에는 스텝이 시작하지 않는다
    assert "step.start" not in kinds[at:]
    assert h.pause() == "paused"
    h.resume()
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    pause_event = done.of("debug.pause")[0]
    start, _ = step_of(done.view.events, "n_pass")
    assert pause_event["step"] == start["step"]  # 멈춘 곳 = 다음에 시작할 스텝


def test_resume_continues(tmp_path: Path, spawned: Spawned) -> None:
    h = paused(tmp_path, spawned)
    assert h.resume() == "running"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    kinds = [e["event"] for e in done.view.events]
    assert kinds.index("debug.pause") < kinds.index("debug.resume")
    _, end = step_of(done.view.events, "n_pass")
    assert end is not None and end["status"] == "success"
    assert done.run_end is not None and done.run_end["verdict"] == "pass"
    assert done.run_json is not None and done.run_json["pause_count"] == 1


def test_cancel_while_paused(tmp_path: Path, spawned: Spawned) -> None:
    h = paused(tmp_path, spawned)
    assert h.cancel() == "cancelling"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.of("debug.resume") == []
    assert [e for e in done.view.events if e.get("node") == "n_pass"] == []
    assert done.run_end is not None and done.run_end["code"] == "cancelled"


def test_deadline_expires_while_paused(tmp_path: Path, spawned: Spawned) -> None:
    # 멈춘 시간은 기한에서 빼지 않는다: 멈춘 채 기한이 지나면 deadline_exceeded로 취소
    h = paused(tmp_path, spawned, deadline_ms=5_000)
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    run_end = done.run_end
    assert run_end is not None
    assert (
        run_end["code"] == "deadline_exceeded" and run_end["cancel_reason"] == "deadline_exceeded"
    )
    assert done.of("debug.resume") == []


def test_cancel_and_resume_race_cancel_wins(tmp_path: Path, spawned: Spawned) -> None:
    h = paused(tmp_path, spawned)
    assert h.peer is not None
    cancel = h.peer.request("run.cancel")
    resume = h.peer.request("run.resume")
    assert cancel.result(5)["state"] == "cancelling"
    assert resume.result(5)["state"] == "cancelling"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["code"] == "cancelled"
    assert done.of("debug.resume") == []
