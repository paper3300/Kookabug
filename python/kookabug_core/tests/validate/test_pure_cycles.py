"""순수 노드 data 순환 (G20).

순수 → 순수 `$link`만으로 순환하면 `pure_cycle`. exec 출력은 대상이 아니다.
"""

from pathlib import Path
from typing import Any

from helpers.graphs import GraphBuilder, check, link, make_workspace
from testkit import registry_with_testkit

from kookabug_core.diagnostics import Diagnostic

GRAPH = "tests/p.graph.json"


def run(tmp_path: Path, g: GraphBuilder) -> list[Diagnostic]:
    ws = make_workspace(tmp_path)
    return check(ws, g.write(ws, GRAPH), registry=registry_with_testkit())


def where(diags: list[Diagnostic]) -> list[tuple[str, str | None, str | None]]:
    return [(d.code, d.node, d.pointer) for d in diags]


def consuming(ref: str) -> GraphBuilder:
    """entry → `ref`를 읽는 검증 노드 → pass."""
    return (
        GraphBuilder(plugins={"testkit": "0"})
        .entry("n_check")
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": link(ref), "op": "==", "b": True},
            next={"ok": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


def cmp(g: GraphBuilder, node_id: str, a: Any, b: Any = True) -> GraphBuilder:
    return g.node(node_id, "core.logic.compare", inputs={"a": a, "op": "==", "b": b})


def test_pure_self_cycle_rejected(tmp_path: Path) -> None:
    # 순수 A가 자기 출력을 읽는다. exec 순환은 없다
    g = cmp(consuming("n_a.result"), "n_a", link("n_a.result"))
    diags = run(tmp_path, g)
    assert where(diags) == [("pure_cycle", "n_a", "/nodes/n_a/in/a")]
    assert "'n_a' → 'n_a'" in diags[0].message


def test_pure_mutual_cycle_rejected(tmp_path: Path) -> None:
    g = consuming("n_a.result")
    cmp(g, "n_a", link("n_b.result"))
    cmp(g, "n_b", link("n_a.result"))
    diags = run(tmp_path, g)
    # 순환 하나에 진단 하나 (ID가 가장 앞선 노드에서)
    assert where(diags) == [("pure_cycle", "n_a", "/nodes/n_a/in/a")]
    assert "'n_a' → 'n_b' → 'n_a'" in diags[0].message


def test_pure_three_node_cycle_rejected(tmp_path: Path) -> None:
    g = consuming("n_b.result")
    cmp(g, "n_a", link("n_b.result"))
    cmp(g, "n_b", link("n_c.result"), b=link("n_x.result"))
    cmp(g, "n_c", link("n_a.result"))
    cmp(g, "n_x", 1, b=1)  # 순환에 매달린 순수 노드는 순환이 아니다
    diags = run(tmp_path, g)
    assert where(diags) == [("pure_cycle", "n_a", "/nodes/n_a/in/a")]
    assert "'n_a' → 'n_b' → 'n_c' → 'n_a'" in diags[0].message


def test_two_separate_cycles_reported_separately(tmp_path: Path) -> None:
    g = consuming("n_a.result")
    cmp(g, "n_a", link("n_b.result"), b=link("n_c.result"))
    cmp(g, "n_b", link("n_a.result"))
    cmp(g, "n_c", link("n_d.result"))
    cmp(g, "n_d", link("n_c.result"))
    assert where(run(tmp_path, g)) == [
        ("pure_cycle", "n_a", "/nodes/n_a/in/a"),
        ("pure_cycle", "n_c", "/nodes/n_c/in/a"),
    ]


def test_pure_diamond_allowed(tmp_path: Path) -> None:
    # A·B가 C를 읽고 D가 A·B를 읽는다: 같은 노드를 두 번 읽어도 순환은 아니다
    g = consuming("n_d.result")
    cmp(g, "n_c", 1, b=1)
    cmp(g, "n_a", link("n_c.result"))
    cmp(g, "n_b", link("n_c.result"))
    cmp(g, "n_d", link("n_a.result"), b=link("n_b.result"))
    assert run(tmp_path, g) == []


def test_pure_cycle_check_ignores_exec_outputs(tmp_path: Path) -> None:
    # 순수 P가 exec E의 출력을 읽고, E 뒤의 노드가 P를 읽는다 → 순환 아님 (E의 출력은 저장된 값)
    g = (
        GraphBuilder(plugins={"testkit": "0"})
        .entry("n_e")
        .node("n_e", "testkit.fail_once", inputs={"exit": "ok"}, next={"ok": "n_check"})
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": link("n_p.result"), "op": "==", "b": True},
            next={"ok": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    cmp(g, "n_p", link("n_e.value"), b=1)
    assert run(tmp_path, g) == []


def test_pure_reading_own_consumer_output_is_dominance_error_not_cycle(tmp_path: Path) -> None:
    # 순수 P가 exec E의 출력을 읽고, E가 P를 읽는다 → E가 자기 출력을 읽는 것 = 지배 오류
    g = (
        GraphBuilder(plugins={"testkit": "0"})
        .entry("n_e")
        .node(
            "n_e",
            "testkit.read_text",
            inputs={"readable": link("n_p.result")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    cmp(g, "n_p", link("n_e.text"), b="x")
    diags = run(tmp_path, g)
    assert where(diags) == [("link_not_dominated", "n_e", "/nodes/n_e/in/readable")]
    assert "'n_p' ← 'n_e.text'" in diags[0].message


def test_transitive_closure_terminates_after_cycle_reported(tmp_path: Path) -> None:
    # 순환이 있어도 전이 폐포 계산이 끝나고, 순환 너머의 exec 출력까지 지배 검사를 한다
    g = (
        GraphBuilder(plugins={"testkit": "0"})
        .entry("n_read")
        .node("n_read", "testkit.read_text", next={"done": "n_pass", "unreadable": "n_check"})
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": link("n_a.result"), "op": "==", "b": True},
            next={"ok": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    cmp(g, "n_a", link("n_b.result"))
    cmp(g, "n_b", link("n_a.result"), b=link("n_read.text"))
    diags = run(tmp_path, g)
    assert where(diags) == [
        ("pure_cycle", "n_a", "/nodes/n_a/in/a"),
        ("link_not_dominated", "n_check", "/nodes/n_check/in/a"),
    ]
    assert "'n_a' ← 'n_b' ← 'n_read.text'" in diags[1].message
