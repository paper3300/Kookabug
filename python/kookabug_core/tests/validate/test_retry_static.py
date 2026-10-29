"""재시도 설정 검사: `config.retry`는 노드 타입의 retry 선언 범위 안에서만 (스키마 v0 6장)."""

from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder, check, make_workspace
from testkit import registry_with_testkit

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.loader import Program, graph_from_data
from kookabug_core.validate import validate
from kookabug_core.workspace import RunOptions

GRAPH = "tests/r.graph.json"


def graph(node_type: str, retry: Any, inputs: dict[str, Any] | None = None) -> GraphBuilder:
    return (
        GraphBuilder(plugins={"testkit": "0"})
        .entry("n_x")
        .node("n_x", node_type, inputs=inputs or {}, config={"retry": retry})
    )


def run(tmp_path: Path, g: GraphBuilder) -> list[Diagnostic]:
    ws = make_workspace(tmp_path)
    return check(ws, g.write(ws, GRAPH), registry=registry_with_testkit())


WAIT = ("testkit.observe.wait", {"expect": "title"})


@pytest.mark.parametrize(
    "retry", [{"max_attempts": 2}, {"max_attempts": 3, "on": ["timeout"]}, {"max_attempts": 1}]
)
def test_retry_valid_config(tmp_path: Path, retry: dict[str, Any]) -> None:
    assert run(tmp_path, graph(WAIT[0], retry, WAIT[1])) == []


@pytest.mark.parametrize(
    ("node_type", "inputs"),
    [
        ("core.assert.compare", {"a": 1, "op": "==", "b": 1}),  # G2: never
        ("testkit.input.tap", {"x": 1, "y": 2}),  # 입력 노드
        ("testkit.fail_once", {}),  # 재시도 선언 없음 = never
        ("core.graph.call", None),  # 엔진 노드
    ],
)
def test_retry_not_allowed_on_never_node(
    tmp_path: Path, node_type: str, inputs: dict[str, Any] | None
) -> None:
    diags = [d for d in run(tmp_path, graph(node_type, {"max_attempts": 2}, inputs))]
    retry = [(d.code, d.node, d.pointer) for d in diags if d.code.startswith("retry_")]
    assert retry == [("retry_not_allowed", "n_x", "/nodes/n_x/config/retry")]


def test_retry_on_outside_declared(tmp_path: Path) -> None:
    g = graph(WAIT[0], {"max_attempts": 2, "on": ["timeout", "found"]}, WAIT[1])
    diags = run(tmp_path, g)
    assert [(d.code, d.pointer) for d in diags] == [
        ("retry_exit_not_allowed", "/nodes/n_x/config/retry/on/1")
    ]


def test_retry_max_attempts_shape_and_semantic(tmp_path: Path) -> None:
    # 파일에서 읽으면 형식 검사(메타스키마 minimum 1)가 먼저 막는다
    diags = run(tmp_path, graph(WAIT[0], {"max_attempts": 0}, WAIT[1]))
    assert [(d.code, d.pointer) for d in diags] == [
        ("out_of_range", "/nodes/n_x/config/retry/max_attempts")
    ]
    # 형식 검사를 거치지 않은 IR(에디터·에이전트가 만든 dict)도 의미 검사가 막는다
    ws = make_workspace(tmp_path / "ir")
    data = graph(WAIT[0], {"max_attempts": 0}, WAIT[1]).build()
    ir, load_diags = graph_from_data(data, GRAPH, ws)
    assert load_diags == []
    program = Program(ws, GRAPH, RunOptions(), graphs={GRAPH: ir})
    diags = validate(program, registry_with_testkit())
    assert [(d.code, d.pointer) for d in diags] == [
        ("retry_max_attempts", "/nodes/n_x/config/retry/max_attempts")
    ]
