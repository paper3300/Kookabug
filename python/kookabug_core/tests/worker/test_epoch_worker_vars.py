"""워커의 SDK `ctx.vars`와 관측 세대 (구현 계획 M3 2.4 "변수", 계획 검수 M6, T4).

워커는 입력 핀 밖에서 `ctx.vars.get`으로 관측값을 가져올 수 있다. runner는 변수에 값과 세대를 같이
저장하고, 워커 RPC로 오는 읽기도 코어 노드와 같이 다룬다: 재개 전 관측값은 돌려주지 않고
`StaleObservation`(처리되지 않은 fail), 읽은 세대는 그 스텝의 관측 바닥(= 출력 출처)에 합친다.
워커가 `ctx.vars.set`으로 쓰는 값에는 그 스텝의 바닥이 붙는다(관측을 가공해 다시 써도 옛 값이다).

한계: 워커가 자기 파이썬 상태에 따로 보관한 값은 추적하지 않는다 (노드 계약 위반, 문서화된 한계).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers.epoch import Debugger, SceneEngines, platform_with
from helpers.graphs import GraphBuilder, link, make_workspace
from helpers.run import tk
from helpers.worker import WorkerHarness

from kookabug_core.engine import RunResult

pytestmark = pytest.mark.process


def head(after_set: str) -> GraphBuilder:
    """띄우기(워커) → `n_read`(코어 OCR, "START") → `n_set`(var.set t) → `after_set`."""
    return (
        tk()
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_read"})
        .node("n_read", "core.ocr.read", next={"done": "n_set"})
        .node(
            "n_set",
            "core.var.set",
            inputs={"name": "t", "value": link("n_read.text")},
            next={"done": after_set},
        )
    )


def branch(node: str, source: str, then: str) -> GraphBuilder:
    cmp = f"{node}_cmp"
    return (
        GraphBuilder()
        .node(cmp, "core.logic.compare", inputs={"a": link(source), "op": "==", "b": "START"})
        .node(
            node,
            "core.flow.branch",
            inputs={"condition": link(f"{cmp}.result")},
            next={"true": then},
        )
    )


def joined(*parts: GraphBuilder) -> GraphBuilder:
    first = parts[0]
    for part in parts[1:]:
        first.nodes.update(part.nodes)
    return first


def run(tmp_path: Path, graph: GraphBuilder, dbg: Debugger) -> tuple[RunResult, WorkerHarness]:
    ws = make_workspace(tmp_path / "ws")
    graph.write(ws, "tests/t.graph.json")
    platform = platform_with(SceneEngines(texts={"title": "START"}))
    h = WorkerHarness(ws, "tests/t.graph.json", tmp_path, platform=platform, debugger=dbg)
    return h.run_all(), h


def step_end(h: WorkerHarness, node: str) -> dict[str, object]:
    (start,) = [e for e in h.events.of("step.start") if e["node"] == node]
    (end,) = [e for e in h.events.of("step.end") if e["step"] == start["step"]]
    return end


def started(h: WorkerHarness) -> list[str]:
    return [str(e["node"]) for e in h.events.of("step.start")]


def test_worker_vars_get_stale_ocr_after_resume_is_stale(tmp_path: Path) -> None:
    """OCR → var.set → 경계 멈춤·재개 → 관측 입력이 없는 워커 노드가 `ctx.vars.get`으로 읽음 →
    `StaleObservation`, 출력·뒤 분기 없음."""
    g = joined(
        head("n_w").node(
            "n_w", "testkit.epoch.vars_read", inputs={"name": "t"}, next={"done": "n_br"}
        ),
        branch("n_br", "n_w.value", "n_pass"),
        GraphBuilder().node("n_pass", "core.test.pass"),
    )
    result, h = run(tmp_path, g, Debugger(at={"n_w"}))
    assert (result.verdict, result.code, result.failure_path) == (
        "fail",
        "unhandled_fail",
        ("n_w",),
    ), result.reason
    end = step_end(h, "n_w")
    assert (end["status"], end["exit"], end["outputs"]) == ("fail", None, {})
    message = str(end["message"])
    assert message.startswith("stale_observation:") and "변수 't'" in message, message
    assert "n_br" not in started(h)


def test_worker_vars_set_roundtrip_keeps_floor(tmp_path: Path) -> None:
    """멈춤 전 같은 세대 안에서 워커가 변수의 관측을 가공해 `ctx.vars.set` → 재개 뒤 그 변수로 분기
    → `stale_observation` (가공한 값도 옛 관측이다)."""
    g = joined(
        head("n_w").node(
            "n_w",
            "testkit.epoch.vars_write",
            inputs={"src": "t", "dst": "u"},
            next={"done": "n_br"},
        ),
        GraphBuilder().node("n_get", "core.var.get", inputs={"name": "u"}),
        branch("n_br", "n_get.value", "n_pass"),
        GraphBuilder().node("n_pass", "core.test.pass"),
    )
    result, h = run(tmp_path, g, Debugger(at={"n_br"}))
    assert (result.verdict, result.failure_path) == ("fail", ("n_br",)), result.reason
    message = str(step_end(h, "n_br")["message"])
    assert message.startswith("stale_observation:") and "'n_read'" in message, message
    assert step_end(h, "n_w")["status"] == "success"


def test_worker_output_floor_includes_vars_read(tmp_path: Path) -> None:
    """입력 핀이 없는 워커 노드라도 `ctx.vars.get`으로 읽은 관측의 세대가 출력에 붙는다: 같은 세대
    분기는 통과, 재개 뒤 분기는 실패."""
    g = joined(
        head("n_w").node(
            "n_w", "testkit.epoch.vars_read", inputs={"name": "t"}, next={"done": "n_br1"}
        ),
        branch("n_br1", "n_w.value", "n_br2"),
        branch("n_br2", "n_w.value", "n_pass"),
        GraphBuilder().node("n_pass", "core.test.pass"),
    )
    result, h = run(tmp_path, g, Debugger(at={"n_br2"}))
    assert step_end(h, "n_br1")["exit"] == "true"
    assert (result.verdict, result.failure_path) == ("fail", ("n_br2",)), result.reason
    assert "'n_read'" in str(step_end(h, "n_br2")["message"])
