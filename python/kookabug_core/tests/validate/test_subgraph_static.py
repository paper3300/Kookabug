"""서브그래프 검사: 호출 대상·순환·깊이, 종료 노드 위치(G15), 공개 출구와 출력(G16)."""

from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import (
    GraphBuilder,
    check,
    check_program,
    link,
    make_workspace,
    subgraph_interface,
)

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.validate.subgraph import MAX_CALL_DEPTH
from kookabug_core.workspace import Workspace

TEST = "tests/t.graph.json"
SUB = "subgraphs/s.graph.json"


def where(diags: list[Diagnostic]) -> list[tuple[str, str | None, str | None, str | None]]:
    return [(d.code, d.file, d.node, d.pointer) for d in diags]


def simple_sub(ws: Workspace, rel: str = SUB, iface: dict[str, Any] | None = None) -> str:
    """entry → exit(done) 서브그래프."""
    g = GraphBuilder("subgraph", interface=iface or subgraph_interface())
    return g.entry("n_exit").exit("n_exit", "done").write(ws, rel)


def caller(callee: str, *, next: dict[str, str] | None = None, **kw: Any) -> GraphBuilder:
    return (
        GraphBuilder()
        .entry("n_call")
        .call("n_call", callee, next=next if next is not None else {"done": "n_pass"}, **kw)
        .node("n_pass", "core.test.pass")
    )


def test_valid_call(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    simple_sub(ws)
    assert check(ws, caller(SUB).write(ws, TEST)) == []


@pytest.mark.parametrize("path", ["subgraphs/none.graph.json", "../outside.graph.json", "a\\b"])
def test_call_target_missing(tmp_path: Path, path: str) -> None:
    ws = make_workspace(tmp_path)
    diags = check(ws, caller(path).write(ws, TEST))
    assert where(diags) == [("call_target_missing", TEST, "n_call", "/nodes/n_call/config/graph")]


def test_call_target_broken_reports_file_problem_only(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    (tmp_path / "subgraphs").mkdir()
    (tmp_path / "subgraphs" / "s.graph.json").write_text("{", "utf-8")
    diags = check(ws, caller(SUB).write(ws, TEST))
    assert [(d.code, d.file) for d in diags] == [("json_invalid", SUB)]


def test_call_target_not_subgraph(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    GraphBuilder().entry("n_pass").node("n_pass", "core.test.pass").write(
        ws, "tests/other.graph.json"
    )
    diags = check(ws, caller("tests/other.graph.json", next={}).write(ws, TEST))
    assert where(diags) == [
        ("call_target_not_subgraph", TEST, "n_call", "/nodes/n_call/config/graph")
    ]


def sub_calling(ws: Workspace, rel: str, callee: str) -> str:
    g = GraphBuilder("subgraph", interface=subgraph_interface())
    g.entry("n_call").call("n_call", callee, next={"done": "n_exit"}).exit("n_exit", "done")
    return g.write(ws, rel)


def test_call_cycle(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    sub_calling(ws, "subgraphs/a.graph.json", "subgraphs/b.graph.json")
    sub_calling(ws, "subgraphs/b.graph.json", "subgraphs/a.graph.json")
    diags = check(ws, caller("subgraphs/a.graph.json").write(ws, TEST))
    assert where(diags) == [
        ("call_cycle", "subgraphs/b.graph.json", "n_call", "/nodes/n_call/config/graph")
    ]
    assert "subgraphs/a.graph.json → subgraphs/b.graph.json → subgraphs/a.graph.json" in (
        diags[0].message
    )


def test_call_self_cycle(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    sub_calling(ws, SUB, SUB)
    diags = check(ws, caller(SUB).write(ws, TEST))
    assert where(diags) == [("call_cycle", SUB, "n_call", "/nodes/n_call/config/graph")]


def chain(ws: Workspace, length: int) -> None:
    """subgraphs/c1 → c2 → … → c<length> (마지막은 호출 없음)."""
    for i in range(1, length):
        sub_calling(ws, f"subgraphs/c{i}.graph.json", f"subgraphs/c{i + 1}.graph.json")
    simple_sub(ws, f"subgraphs/c{length}.graph.json")


def test_call_depth(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    chain(ws, MAX_CALL_DEPTH)  # 테스트 → c1 … c16 = 프레임 16개 깊이: 허용
    assert check(ws, caller("subgraphs/c1.graph.json").write(ws, TEST)) == []

    ws2 = make_workspace(tmp_path / "deeper")
    chain(ws2, MAX_CALL_DEPTH + 1)  # c17은 17단계
    diags = check(ws2, caller("subgraphs/c1.graph.json").write(ws2, TEST))
    assert where(diags) == [
        (
            "call_depth",
            f"subgraphs/c{MAX_CALL_DEPTH}.graph.json",
            "n_call",
            "/nodes/n_call/config/graph",
        )
    ]


def test_deep_call_chain_stops_loading_and_reports_call_depth(tmp_path: Path) -> None:
    # 수백 단계 사슬도 예외(RecursionError) 없이 call_depth 하나로 끝나고, 한도 너머는 읽지 않는다
    ws = make_workspace(tmp_path)
    chain(ws, 400)
    program, diags = check_program(ws, caller("subgraphs/c1.graph.json").write(ws, TEST))
    assert where(diags) == [
        (
            "call_depth",
            f"subgraphs/c{MAX_CALL_DEPTH}.graph.json",
            "n_call",
            "/nodes/n_call/config/graph",
        )
    ]
    # 테스트 + 깊이 1~17 (17번째는 종류 확인용으로 읽고 그 호출은 따라가지 않음)
    assert len(program.graphs) == MAX_CALL_DEPTH + 2
    last = f"subgraphs/c{MAX_CALL_DEPTH + 1}.graph.json"
    assert program.calls[(last, "n_call")].status == "unloaded"


def test_cycle_after_prefix_is_call_cycle(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    for i in range(1, 5):
        sub_calling(ws, f"subgraphs/c{i}.graph.json", f"subgraphs/c{i + 1}.graph.json")
    sub_calling(ws, "subgraphs/c5.graph.json", "subgraphs/c3.graph.json")
    diags = check(ws, caller("subgraphs/c1.graph.json").write(ws, TEST))
    assert where(diags) == [
        ("call_cycle", "subgraphs/c5.graph.json", "n_call", "/nodes/n_call/config/graph")
    ]
    assert "c3.graph.json → subgraphs/c4.graph.json → subgraphs/c5.graph.json → " in (
        diags[0].message
    )


def test_cycle_beyond_depth_limit_reports_call_depth(tmp_path: Path) -> None:
    # 한도 너머의 순환은 읽지 않으므로 call_depth만 난다 (끝없이 돌지 않는다)
    ws = make_workspace(tmp_path)
    n = MAX_CALL_DEPTH + 5
    for i in range(1, n):
        sub_calling(ws, f"subgraphs/c{i}.graph.json", f"subgraphs/c{i + 1}.graph.json")
    sub_calling(ws, f"subgraphs/c{n}.graph.json", "subgraphs/c1.graph.json")
    diags = check(ws, caller("subgraphs/c1.graph.json").write(ws, TEST))
    assert [d.code for d in diags] == ["call_depth"]


def test_call_depth_counts_longest_path(tmp_path: Path) -> None:
    # 짧은 경로로도 닿는 그래프가 긴 경로에서는 너무 깊어진다
    ws = make_workspace(tmp_path)
    chain(ws, MAX_CALL_DEPTH)
    sub_calling(ws, f"subgraphs/c{MAX_CALL_DEPTH}.graph.json", "subgraphs/leaf.graph.json")
    simple_sub(ws, "subgraphs/leaf.graph.json")
    g = (
        GraphBuilder()
        .entry("n_leaf")
        .call("n_leaf", "subgraphs/leaf.graph.json", next={"done": "n_call"})
        .call("n_call", "subgraphs/c1.graph.json", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    diags = check(ws, g.write(ws, TEST))
    assert [d.code for d in diags] == ["call_depth"]


def test_terminal_in_subgraph(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    g = GraphBuilder("subgraph", interface=subgraph_interface())
    g.entry("n_pass").node("n_pass", "core.test.pass").exit("n_exit", "done")
    diags = check(ws, g.write(ws, SUB))
    assert where(diags) == [("terminal_in_subgraph", SUB, "n_pass", "/nodes/n_pass/type")]


def test_graph_exit_in_test(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    g = GraphBuilder().entry("n_exit").exit("n_exit", "done")
    diags = check(ws, g.write(ws, TEST))
    assert where(diags) == [("graph_exit_in_test", TEST, "n_exit", "/nodes/n_exit/type")]


def test_exit_name_unknown(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    g = GraphBuilder("subgraph", interface=subgraph_interface())
    g.entry("n_exit").exit("n_exit", "done").exit("n_bad", "finished")
    diags = check(ws, g.write(ws, SUB))
    assert where(diags) == [("exit_name_unknown", SUB, "n_bad", "/nodes/n_bad/config/exit")]


def test_interface_exit_unused(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    iface = subgraph_interface(exits={"done": "ok", "failed": "fail"})
    g = GraphBuilder("subgraph", interface=iface).entry("n_exit").exit("n_exit", "done")
    diags = check(ws, g.write(ws, SUB))
    assert [(d.code, d.severity, d.pointer) for d in diags] == [
        ("interface_exit_unused", "warning", "/interface/exits/failed")
    ]


OUTPUTS = {"gold": "int", "message": {"nullable": True, "type": "string"}}


def two_exit_sub(ws: Workspace, ok_in: dict[str, Any], fail_in: dict[str, Any]) -> str:
    iface = subgraph_interface(
        exits={"done": "ok", "failed": "fail"}, inputs={"n": "int"}, outputs=OUTPUTS
    )
    g = (
        GraphBuilder("subgraph", interface=iface)
        .entry("n_branch")
        .node(
            "n_branch",
            "core.flow.branch",
            inputs={"condition": True},
            next={"true": "n_ok", "false": "n_fail"},
        )
        .exit("n_ok", "done", inputs=ok_in)
        .exit("n_fail", "failed", inputs=fail_in)
    )
    return g.write(ws, SUB)


def test_exit_missing_required_output(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    two_exit_sub(ws, {"message": "m"}, {"gold": link("n_entry.n")})
    diags = check(ws, SUB)
    assert where(diags) == [("exit_missing_required_output", SUB, "n_ok", "/nodes/n_ok/in")]
    assert "'gold'" in diags[0].message


def test_non_nullable_output_required_on_every_exit_node(tmp_path: Path) -> None:
    # fail 종류 출구로 나가는 exit 노드도 nullable 아닌 출력을 줘야 한다 (G16)
    ws = make_workspace(tmp_path)
    two_exit_sub(ws, {"gold": 1}, {"message": "실패"})
    diags = check(ws, SUB)
    assert where(diags) == [("exit_missing_required_output", SUB, "n_fail", "/nodes/n_fail/in")]


def test_nullable_output_may_be_omitted(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    two_exit_sub(ws, {"gold": 1}, {"gold": link("n_entry.n")})
    assert check(ws, SUB) == []


def test_exit_unknown_output_is_unknown_input(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    two_exit_sub(ws, {"gold": 1, "bonus": 2}, {"gold": 0})
    assert where(check(ws, SUB)) == [("unknown_input", SUB, "n_ok", "/nodes/n_ok/in/bonus")]


def test_call_pins_from_interface(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    iface = subgraph_interface(
        exits={"done": "ok", "failed": "fail"},
        inputs={"n": "int", "server": {"default": "Server 1", "type": "string"}},
        outputs=OUTPUTS,
    )
    (
        GraphBuilder("subgraph", interface=iface)
        .entry("n_exit")
        .exit("n_exit", "done", inputs={"gold": link("n_entry.n")})
        .exit("n_failed", "failed", inputs={"gold": 0})
        .write(ws, SUB)
    )

    # 입력: n(필수)·server(기본값). 출구: done·failed. 출력: gold·message (모든 출구가 준다)
    good = (
        caller(SUB, inputs={"n": 3}, next={"done": "n_check", "failed": "n_log"})
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": link("n_call.gold"), "op": ">", "b": 0},
            next={"ok": "n_pass"},
        )
        .node("n_log", "core.log.message", inputs={"text": link("n_call.message")})
    )
    assert check(ws, good.write(ws, TEST)) == []

    bad = caller(
        SUB,
        inputs={"server": 1, "extra": True},
        next={"done": "n_check", "timeout": "n_pass"},
    ).node("n_check", "core.flow.branch", inputs={"condition": link("n_call.gold")})
    bad.node("n_get", "core.logic.compare", inputs={"a": link("n_call.nope"), "op": "==", "b": 1})
    assert [(d.code, d.pointer) for d in check(ws, bad.write(ws, TEST))] == [
        ("missing_required_input", "/nodes/n_call/in"),
        ("unknown_input", "/nodes/n_call/in/extra"),
        ("type_mismatch", "/nodes/n_call/in/server"),
        ("unknown_exit", "/nodes/n_call/next/timeout"),
        ("type_mismatch", "/nodes/n_check/in/condition"),
        ("link_bad_output", "/nodes/n_get/in/a"),
    ]


def test_subgraph_entry_outputs_are_interface_inputs(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    iface = subgraph_interface(inputs={"n": "int"}, outputs={"gold": "int"})
    g = (
        GraphBuilder("subgraph", interface=iface)
        .entry("n_exit")
        .exit("n_exit", "done", inputs={"gold": link("n_entry.m")})
    )
    assert [d.code for d in check(ws, g.write(ws, SUB))] == ["link_bad_output"]
