"""지배 검사: exec 출력은 그 출력을 주는 출구를 모든 경로가 지나야 읽는다 (스키마 v0 7장)."""

from pathlib import Path

from helpers.graphs import GraphBuilder, check, link, make_workspace
from testkit import registry_with_testkit

from kookabug_core.diagnostics import Diagnostic

GRAPH = "tests/d.graph.json"


def run(tmp_path: Path, g: GraphBuilder) -> list[Diagnostic]:
    ws = make_workspace(tmp_path)
    return check(ws, g.write(ws, GRAPH), registry=registry_with_testkit())


def where(diags: list[Diagnostic]) -> list[tuple[str, str | None, str | None]]:
    return [(d.code, d.node, d.pointer) for d in diags]


def check_reads(ref: str, node_id: str = "n_check", next: str = "n_pass") -> GraphBuilder:
    """`ref`를 읽는 검증 노드를 붙일 그래프 (`n_pass`로 끝남)."""
    return (
        GraphBuilder(plugins={"testkit": "0"})
        .node(
            node_id,
            "core.assert.compare",
            inputs={"a": link(ref), "op": "!=", "b": None},
            next={"ok": next},
        )
        .node("n_pass", "core.test.pass")
    )


def wait_any(g: GraphBuilder, next: dict[str, str]) -> GraphBuilder:
    return g.node(
        "n_wait",
        "testkit.observe.wait_any",
        config={"exits": ["error", "lobby"]},
        inputs={"targets": {"error": "error_popup", "lobby": "server_list"}},
        next=next,
    )


def test_wait_any_output_read_after_merge_allowed(tmp_path: Path) -> None:
    # 설계 7장 허용 예: wait_any → 분기 → 합류한 노드가 wait_any.match를 읽음 (모든 경로가 지남)
    g = check_reads("n_wait.match").entry("n_wait")
    wait_any(g, {"error": "n_tap_error", "lobby": "n_tap_lobby"})
    g.node("n_tap_error", "testkit.input.tap", inputs={"x": 1, "y": 1}, next={"done": "n_check"})
    g.node("n_tap_lobby", "testkit.input.tap", inputs={"x": 2, "y": 2}, next={"done": "n_check"})
    assert run(tmp_path, g) == []


def test_one_branch_output_read_after_merge_rejected(tmp_path: Path) -> None:
    # 설계 7장 거부 예: 합류한 노드가 한쪽 분기에서만 실행되는 노드의 출력을 읽음
    g = check_reads("n_read.text").entry("n_wait")
    wait_any(g, {"error": "n_read", "lobby": "n_check"})
    g.node("n_read", "testkit.read_text", next={"done": "n_check"})
    diags = run(tmp_path, g)
    assert where(diags) == [("link_not_dominated", "n_check", "/nodes/n_check/in/a")]
    assert "'n_read.text'" in diags[0].message and "(done)" in diags[0].message


def test_one_branch_output_read_inside_branch_allowed(tmp_path: Path) -> None:
    # 같은 출력을 그 분기 안에서 읽는 것은 된다
    g = check_reads("n_read.text").entry("n_wait")
    wait_any(g, {"error": "n_read", "lobby": "n_pass"})
    g.node("n_read", "testkit.read_text", next={"done": "n_check"})
    assert run(tmp_path, g) == []


def test_output_after_timeout_exit_rejected(tmp_path: Path) -> None:
    # 생산 노드가 지배하더라도 그 경로에서 나간 출구가 출력을 줘야 한다 (timeout 뒤에는 match 없음)
    g = (
        check_reads("n_wait.match")
        .entry("n_wait")
        .node(
            "n_wait",
            "testkit.observe.wait",
            inputs={"expect": "title"},
            next={"found": "n_check", "timeout": "n_check"},
        )
    )
    diags = run(tmp_path, g)
    assert where(diags) == [("link_not_dominated", "n_check", "/nodes/n_check/in/a")]
    assert "(found)" in diags[0].message


def test_fail_exit_without_outputs_rejected_even_alone(tmp_path: Path) -> None:
    # 출력을 주지 않는 출구로만 오는 노드는 읽을 수 없다
    g = (
        check_reads("n_read.text")
        .entry("n_read")
        .node("n_read", "testkit.read_text", next={"done": "n_pass", "unreadable": "n_check"})
    )
    assert where(run(tmp_path, g)) == [("link_not_dominated", "n_check", "/nodes/n_check/in/a")]


def test_pure_node_transitive_dominance_checked_at_consumer(tmp_path: Path) -> None:
    # 순수 노드가 읽는 exec 출력은 그 순수 노드를 소비하는 exec 노드 기준으로 검사한다.
    # 같은 순수 노드를 분기 안(n_check_inside)에서 읽으면 되고, 합류 뒤(n_check)에서 읽으면 안 된다
    g = check_reads("n_cmp.result").entry("n_wait")
    wait_any(g, {"error": "n_read", "lobby": "n_check"})
    g.node("n_read", "testkit.read_text", next={"done": "n_check_inside"})
    g.node(
        "n_check_inside",
        "core.assert.compare",
        inputs={"a": link("n_cmp.result"), "op": "==", "b": True},
        next={"ok": "n_check"},
    )
    g.node("n_cmp", "core.logic.compare", inputs={"a": link("n_read.text"), "op": "==", "b": "x"})
    diags = run(tmp_path, g)
    assert where(diags) == [("link_not_dominated", "n_check", "/nodes/n_check/in/a")]
    assert "'n_cmp' ← 'n_read.text'" in diags[0].message


def test_pure_node_reading_dominating_output_allowed(tmp_path: Path) -> None:
    g = (
        check_reads("n_fmt.text")
        .entry("n_read")
        .node("n_read", "testkit.read_text", next={"done": "n_check"})
        .node(
            "n_fmt",
            "core.text.format",
            inputs={"template": "{t}", "values": {"t": link("n_read.text")}},
        )
    )
    assert run(tmp_path, g) == []


def test_entry_outputs_dominate_everything(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    iface = {"exits": {"done": {"kind": "ok"}}, "inputs": {"n": {"type": "int"}}}
    g = (
        GraphBuilder("subgraph", interface=iface)
        .entry("n_check")
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": link("n_entry.n"), "op": ">", "b": 0},
            next={"ok": "n_exit", "fail": "n_exit"},
        )
        .exit("n_exit", "done")
    )
    assert check(ws, g.write(ws, "subgraphs/s.graph.json")) == []


def test_link_to_later_body_node_rejected(tmp_path: Path) -> None:
    # 지난 반복 출력 참조 거부(정적): 본문 앞쪽 노드가 뒤쪽 노드의 출력을 읽으면, 첫 회차에는
    # 값이 없고 다음 회차에는 지난 회차 값이 된다. 암묵적 귀환은 간선에 넣지 않으므로
    # 지배 검사가 막는다
    g = (
        GraphBuilder(plugins={"testkit": "0"})
        .entry("n_loop")
        .node(
            "n_loop",
            "core.flow.repeat",
            inputs={"times": 3},
            next={"body": "n_first", "done": "n_pass"},
        )
        .node(
            "n_first",
            "core.assert.compare",
            inputs={"a": link("n_later.value"), "op": "==", "b": 1},
            next={"ok": "n_later"},
        )
        .node("n_later", "testkit.fail_once", inputs={"exit": "ok"})
        .node("n_pass", "core.test.pass")
    )
    assert where(run(tmp_path, g)) == [("link_not_dominated", "n_first", "/nodes/n_first/in/a")]


def test_exec_node_reading_own_output_rejected(tmp_path: Path) -> None:
    g = (
        GraphBuilder(plugins={"testkit": "0"})
        .entry("n_read")
        .node(
            "n_read",
            "testkit.read_text",
            inputs={"text": link("n_read.text")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    diags = run(tmp_path, g)
    assert where(diags) == [("link_not_dominated", "n_read", "/nodes/n_read/in/text")]
    assert "자기 출력" in diags[0].message


def test_unreachable_consumer_not_checked(tmp_path: Path) -> None:
    # entry에서 닿지 않는 노드는 실행되지 않으므로 지배 검사 대상이 아니다
    g = check_reads("n_read.text").entry("n_pass")
    g.node("n_read", "testkit.read_text")
    assert run(tmp_path, g) == []
