"""경로 끝 규칙과 `while` 한도 (스키마 v0 2장 "실행 전 검증", G15)."""

from pathlib import Path

from helpers.graphs import GraphBuilder, check, make_workspace, subgraph_interface
from testkit import registry_with_testkit

from kookabug_core.codes import CODES
from kookabug_core.diagnostics import Diagnostic

GRAPH = "tests/t.graph.json"
SUB = "subgraphs/s.graph.json"


def run(tmp_path: Path, g: GraphBuilder, rel: str = GRAPH) -> list[Diagnostic]:
    ws = make_workspace(tmp_path)
    return check(ws, g.write(ws, rel), registry=registry_with_testkit())


def where(diags: list[Diagnostic]) -> list[tuple[str, str, str | None, str | None]]:
    return [(d.code, d.severity, d.node, d.pointer) for d in diags]


def tk(kind: str = "test") -> GraphBuilder:
    iface = subgraph_interface() if kind == "subgraph" else None
    return GraphBuilder(kind, interface=iface, plugins={"testkit": "0"})


def test_flow_codes_in_table() -> None:
    flow = {c: info.severity for c, info in CODES.items() if info.group == "flow"}
    assert flow == {
        "exec_cycle": "error",
        "pure_cycle": "error",
        "link_not_dominated": "error",
        "loop_scope_entry": "error",
        "link_out_of_scope": "error",
        "unconnected_ok_exit": "warning",
        "subgraph_path_open": "error",
        "while_requires_limit": "error",
    }


def test_unconnected_ok_exit_warning(tmp_path: Path) -> None:
    g = tk().entry("n_tap").node("n_tap", "testkit.input.tap", inputs={"x": 1, "y": 1})
    diags = run(tmp_path, g)
    assert where(diags) == [("unconnected_ok_exit", "warning", "n_tap", "/nodes/n_tap/next")]
    assert "'done'" in diags[0].message


def test_assertion_node_end_no_warning(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_check")
        .node("n_check", "core.assert.compare", inputs={"a": 1, "op": "==", "b": 1})
    )
    assert run(tmp_path, g) == []


def test_assertion_then_click_then_end_warns(tmp_path: Path) -> None:
    # `검증 → 클릭 → 끝`은 경고 (마지막 노드가 검증 노드가 아님)
    g = (
        tk()
        .entry("n_check")
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": 1, "op": "==", "b": 1},
            next={"ok": "n_tap"},
        )
        .node("n_tap", "testkit.input.tap", inputs={"x": 1, "y": 1})
    )
    assert where(run(tmp_path, g)) == [
        ("unconnected_ok_exit", "warning", "n_tap", "/nodes/n_tap/next")
    ]


def test_unconnected_fail_exit_is_not_a_path_end_warning(tmp_path: Path) -> None:
    # 연결 안 된 fail 출구는 실행 때 처리되지 않은 실패(판정 2행)이지 검증 대상이 아니다
    g = (
        tk()
        .entry("n_wait")
        .node("n_wait", "testkit.observe.wait", inputs={"expect": "t"}, next={"found": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    assert run(tmp_path, g) == []


def test_unreachable_node_is_not_a_path_end(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_pass")
        .node("n_pass", "core.test.pass")
        .node("n_orphan", "testkit.input.tap", inputs={"x": 1, "y": 1})
    )
    assert run(tmp_path, g) == []


def test_subgraph_path_open_is_error(tmp_path: Path) -> None:
    # 서브그래프의 연결 안 된 ok 출구는 오류. 검증 노드로 끝나도 마찬가지
    # (호출한 쪽이 어느 출구로 나왔는지 모른다)
    g = (
        tk("subgraph")
        .entry("n_choose")
        .node(
            "n_choose",
            "testkit.flow.choose",
            config={"exits": ["left", "right"]},
            next={"left": "n_exit", "right": "n_check"},
        )
        .node("n_check", "core.assert.compare", inputs={"a": 1, "op": "==", "b": 1})
        .exit("n_exit", "done")
    )
    diags = run(tmp_path, g, SUB)
    assert where(diags) == [("subgraph_path_open", "error", "n_check", "/nodes/n_check/next")]
    assert "'ok'" in diags[0].message


def test_subgraph_loop_body_end_not_open(tmp_path: Path) -> None:
    g = (
        tk("subgraph")
        .entry("n_loop")
        .node(
            "n_loop",
            "core.flow.repeat",
            inputs={"times": 2},
            next={"body": "n_tap", "done": "n_exit"},
        )
        .node("n_tap", "testkit.input.tap", inputs={"x": 1, "y": 1})
        .exit("n_exit", "done")
    )
    assert run(tmp_path, g, SUB) == []

    # 반복이 끝난 뒤(done) 경로는 반복 범위 밖이라 열려 있으면 오류
    g.nodes["n_loop"]["next"] = {"body": "n_tap"}
    g.node("n_tap", "testkit.input.tap", inputs={"x": 1, "y": 1}, next={"done": "n_exit"})
    diags = run(tmp_path / "2", g, SUB)
    assert where(diags) == [("subgraph_path_open", "error", "n_loop", "/nodes/n_loop/next")]
    assert "'done'" in diags[0].message


def test_while_requires_limit(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_while")
        .node(
            "n_while",
            "core.flow.while",
            inputs={"condition": True},
            next={"body": "n_tap", "done": "n_pass"},
        )
        .node("n_tap", "testkit.input.tap", inputs={"x": 1, "y": 1})
        .node("n_pass", "core.test.pass")
    )
    diags = run(tmp_path, g)
    # 필수 입력 누락(missing_required_input)을 따로 내지 않고 한도 오류 하나로 안내한다
    assert where(diags) == [("while_requires_limit", "error", "n_while", "/nodes/n_while/in")]

    g.nodes["n_while"]["in"]["max_iterations"] = 3
    assert run(tmp_path / "2", g) == []
