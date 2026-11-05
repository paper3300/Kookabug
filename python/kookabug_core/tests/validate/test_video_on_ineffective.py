"""실행 전 검증 경고 `video_on_ineffective` (M4 T12, STATE ⑦): 하위 층 `record.video: "on"`이
위 층의 더 센 실효값에 져서 효과가 없을 때. 메시지에 이긴 층을 쓴다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder, check, make_workspace, subgraph_interface

from kookabug_core.diagnostics import Diagnostic

TEST = "tests/t.graph.json"
SUB = "subgraphs/s.graph.json"
ON = {"video": "on"}


def warnings(diags: list[Diagnostic]) -> list[tuple[str | None, str | None, str | None, str]]:
    return [
        (d.file, d.node, d.pointer, d.message) for d in diags if d.code == "video_on_ineffective"
    ]


def simple_test(**kw: Any) -> GraphBuilder:
    node_record = kw.pop("node_record", None)
    return GraphBuilder(**kw).entry("n").node("n", "core.test.pass", record=node_record)


@pytest.mark.parametrize(
    ("ws_record", "winner", "mode"),
    [(None, "워크스페이스 기본값", "failed_only"), ({"video": "off"}, "kookabug.json", "off")],
    ids=["기본 failed_only", "워크스페이스 off"],
)
def test_test_layer_on_warns(
    tmp_path: Path, ws_record: dict[str, Any] | None, winner: str, mode: str
) -> None:
    ws = make_workspace(tmp_path, record=ws_record)
    simple_test(record=ON).write(ws, TEST)
    found = warnings(check(ws, TEST))
    assert len(found) == 1, found
    file, node, pointer, message = found[0]
    assert (file, node, pointer) == (TEST, None, "/record/video")
    assert winner in message and f"'{mode}'" in message
    diag = next(d for d in check(ws, TEST) if d.code == "video_on_ineffective")
    assert diag.severity == "warning"


def test_node_layer_on_warns_names_test_graph(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path, record={"video": "on"})
    simple_test(record={"video": "failed_only"}, node_record=ON).write(ws, TEST)
    found = warnings(check(ws, TEST))
    assert [(f, n, p) for f, n, p, _ in found] == [(TEST, "n", "/nodes/n/record/video")]
    assert TEST in found[0][3] and "'failed_only'" in found[0][3]


def test_subgraph_layer_on_warns(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)  # 기본 failed_only
    sub = GraphBuilder("subgraph", interface=subgraph_interface(), record=ON)
    sub.entry("n_exit").exit("n_exit", "done").write(ws, SUB)
    (
        GraphBuilder()
        .entry("n_call")
        .call("n_call", SUB, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
        .write(ws, TEST)
    )
    found = warnings(check(ws, TEST))
    assert [(f, n, p) for f, n, p, _ in found] == [(SUB, None, "/record/video")]
    assert "워크스페이스 기본값" in found[0][3]


def test_call_node_off_beats_subgraph_on(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path, record={"video": "on"})
    sub = GraphBuilder("subgraph", interface=subgraph_interface())
    sub.entry("n_exit").exit("n_exit", "done", inputs=None)
    sub.nodes["n_exit"]["record"] = ON
    sub.write(ws, SUB)
    (
        GraphBuilder()
        .entry("n_call")
        .call("n_call", SUB, next={"done": "n_pass"}, record={"video": "off"})
        .node("n_pass", "core.test.pass")
        .write(ws, TEST)
    )
    found = warnings(check(ws, TEST))
    assert [(f, n, p) for f, n, p, _ in found] == [(SUB, "n_exit", "/nodes/n_exit/record/video")]
    assert TEST in found[0][3] and "'off'" in found[0][3]


def test_workspace_on_no_warning(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path, record={"video": "on"})
    simple_test(record=ON, node_record=ON).write(ws, TEST)
    assert warnings(check(ws, TEST)) == []


def test_no_on_no_warning(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    simple_test(record={"video": "off"}, node_record={"video": "failed_only"}).write(ws, TEST)
    assert warnings(check(ws, TEST)) == []
