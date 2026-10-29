"""반복 정적 규칙 (스키마 v0 7장).

명시적 exec 순환 금지, 범위 단일 진입(포함 또는 분리), 범위 밖 읽기.
"""

from pathlib import Path
from typing import Any

from helpers.graphs import GraphBuilder, check, link, make_workspace
from testkit import registry_with_testkit

from kookabug_core.diagnostics import Diagnostic

GRAPH = "tests/l.graph.json"


def run(tmp_path: Path, g: GraphBuilder) -> list[Diagnostic]:
    ws = make_workspace(tmp_path)
    return check(ws, g.write(ws, GRAPH), registry=registry_with_testkit())


def where(diags: list[Diagnostic]) -> list[tuple[str, str | None, str | None]]:
    return [(d.code, d.node, d.pointer) for d in diags]


def base(start: str) -> GraphBuilder:
    return GraphBuilder(plugins={"testkit": "0"}).entry(start).node("n_pass", "core.test.pass")


def repeat(g: GraphBuilder, node_id: str, body: str | None, done: str | None) -> GraphBuilder:
    next = {k: v for k, v in {"body": body, "done": done}.items() if v is not None}
    return g.node(node_id, "core.flow.repeat", inputs={"times": 2}, next=next)


def tap(g: GraphBuilder, node_id: str, done: str | None = None) -> GraphBuilder:
    return g.node(
        node_id, "testkit.input.tap", inputs={"x": 1, "y": 1}, next={"done": done} if done else None
    )


def compare(g: GraphBuilder, node_id: str, a: Any, ok: str | None = None) -> GraphBuilder:
    return g.node(
        node_id,
        "core.assert.compare",
        inputs={"a": a, "op": "!=", "b": None},
        next={"ok": ok} if ok else None,
    )


def test_explicit_exec_cycle_rejected(tmp_path: Path) -> None:
    g = base("n_a")
    tap(g, "n_a", "n_b")
    tap(g, "n_b", "n_a")
    diags = run(tmp_path, g)
    assert where(diags) == [("exec_cycle", "n_b", "/nodes/n_b/next/done")]
    assert "'n_a' → 'n_b' → 'n_a'" in diags[0].message


def test_exec_self_cycle_rejected(tmp_path: Path) -> None:
    g = base("n_a")
    tap(g, "n_a", "n_a")
    assert where(run(tmp_path, g)) == [("exec_cycle", "n_a", "/nodes/n_a/next/done")]


def test_body_end_to_loop_node_rejected(tmp_path: Path) -> None:
    # 반복은 암묵적 귀환으로만: 본문 끝을 반복 노드에 직접 연결하면 오류
    g = repeat(base("n_loop"), "n_loop", "n_tap", "n_pass")
    tap(g, "n_tap", "n_loop")
    diags = run(tmp_path, g)
    assert where(diags) == [("exec_cycle", "n_tap", "/nodes/n_tap/next/done")]
    assert "암묵적 귀환" in diags[0].message


def test_loop_scope_partial_overlap_rejected(tmp_path: Path) -> None:
    # 두 반복의 본문이 n_shared에서 합류한다 → 범위가 부분적으로 겹침 (범위를 넘는 합류)
    g = repeat(base("n_l1"), "n_l1", "n_a", "n_l2")
    repeat(g, "n_l2", "n_b", "n_pass")
    tap(g, "n_a", "n_shared")
    tap(g, "n_b", "n_shared")
    tap(g, "n_shared")
    diags = run(tmp_path, g)
    assert where(diags) == [
        ("loop_scope_entry", "n_a", "/nodes/n_a/next/done"),
        ("loop_scope_entry", "n_b", "/nodes/n_b/next/done"),
    ]
    assert "'n_l2'" in diags[0].message and "'n_l1'" in diags[1].message


def test_merge_from_outside_into_body_rejected(tmp_path: Path) -> None:
    # 반복 밖(여기서는 done 뒤)에서 본문 중간으로 들어오는 연결
    g = repeat(base("n_loop"), "n_loop", "n_a", "n_after")
    tap(g, "n_a", "n_b")
    tap(g, "n_b")
    tap(g, "n_after", "n_b")
    assert where(run(tmp_path, g)) == [("loop_scope_entry", "n_after", "/nodes/n_after/next/done")]


def test_loop_done_into_own_body_rejected(tmp_path: Path) -> None:
    g = repeat(base("n_loop"), "n_loop", "n_a", "n_a")
    tap(g, "n_a")
    diags = run(tmp_path, g)
    assert [(c, n, p) for c, n, p in where(diags) if c == "loop_scope_entry"] == [
        ("loop_scope_entry", "n_loop", "/nodes/n_loop/next/done")
    ]


def test_nested_scopes_contained_allowed(tmp_path: Path) -> None:
    # 안쪽 범위가 바깥 범위에 완전히 포함된 정상 중첩. 바깥 본문에서 만든 값·바깥 index는
    # 안쪽에서 읽을 수 있다. 안쪽 done 뒤 노드는 바깥 본문의 끝 (바깥 반복으로 돌아감)
    g = repeat(base("n_outer"), "n_outer", "n_read", "n_pass")
    g.node("n_read", "testkit.read_text", next={"done": "n_inner"})
    repeat(g, "n_inner", "n_c1", "n_after_inner")
    compare(g, "n_c1", link("n_read.text"), ok="n_c2")
    compare(g, "n_c2", link("n_outer.index"), ok="n_c3")
    compare(g, "n_c3", link("n_inner.index"))
    tap(g, "n_after_inner")
    assert run(tmp_path, g) == []


def test_terminal_node_shared_inside_and_outside_scope_allowed(tmp_path: Path) -> None:
    # 종료 노드는 범위 계산의 경계: 반복 안의 fail 분기와 밖의 fail 분기가 같은 test.fail로 간다
    g = repeat(base("n_loop"), "n_loop", "n_in", "n_out")
    g.node("n_in", "testkit.fail_once", inputs={"exit": "ok"}, next={"fail": "n_fail"})
    g.node(
        "n_out",
        "testkit.fail_once",
        inputs={"exit": "ok"},
        next={"ok": "n_pass", "fail": "n_fail"},
    )
    g.node("n_fail", "core.test.fail")
    assert run(tmp_path, g) == []


def test_terminal_shared_input_still_dominance_checked(tmp_path: Path) -> None:
    # 공유한 종료 노드도 입력 검사는 그대로: 범위 안 노드의 출력을 읽으면 밖에서 올 때 값이 없다
    g = repeat(base("n_loop"), "n_loop", "n_read", "n_out")
    g.node("n_read", "testkit.read_text", next={"done": "n_in"})
    g.node("n_in", "testkit.fail_once", inputs={"exit": "ok"}, next={"fail": "n_fail"})
    g.node(
        "n_out",
        "testkit.fail_once",
        inputs={"exit": "ok"},
        next={"ok": "n_pass", "fail": "n_fail"},
    )
    g.node("n_fail", "core.test.fail", inputs={"reason": link("n_read.text")})
    diags = run(tmp_path, g)
    assert where(diags) == [("link_out_of_scope", "n_fail", "/nodes/n_fail/in/reason")]
    assert "범위 밖에서도 오는 종료 노드" in diags[0].message


def test_terminal_only_inside_body_reads_body_output_allowed(tmp_path: Path) -> None:
    # 본문 안에서만 도달하는 종료 노드는 그 회차의 본문 출력·index를 읽는다 (지배 검사만)
    g = repeat(base("n_loop"), "n_loop", "n_read", "n_pass")
    g.node("n_read", "testkit.read_text", next={"done": "n_in"})
    g.node("n_in", "testkit.fail_once", inputs={"exit": "ok"}, next={"fail": "n_fail"})
    g.node("n_fail", "core.test.fail", inputs={"reason": link("n_read.text")})
    assert run(tmp_path, g) == []

    g = repeat(base("n_loop"), "n_loop", "n_skip", "n_pass")
    g.node("n_skip", "core.test.skip", inputs={"reason": link("n_fmt.text")})
    g.node(
        "n_fmt",
        "core.text.format",
        inputs={"template": "{i}", "values": {"i": link("n_loop.index")}},
    )
    diags = run(tmp_path / "2", g)
    # text.format 출력(string|secret) → reason(string)은 타입 문제일 뿐 범위 문제가 아니다
    assert [d.code for d in diags] == ["type_mismatch"]


def test_terminal_inside_nested_body_reads_outer_body_output_allowed(tmp_path: Path) -> None:
    g = repeat(base("n_outer"), "n_outer", "n_read", "n_pass")
    g.node("n_read", "testkit.read_text", next={"done": "n_inner"})
    repeat(g, "n_inner", "n_in", None)
    g.node("n_in", "testkit.fail_once", inputs={"exit": "ok"}, next={"fail": "n_fail"})
    g.node("n_fail", "core.test.fail", inputs={"reason": link("n_read.text")})
    assert run(tmp_path, g) == []


def test_terminal_inside_outer_body_reads_inner_body_output_rejected(tmp_path: Path) -> None:
    # 바깥 본문(안쪽 반복의 done 뒤)에서 오는 종료 노드는 안쪽 범위 밖이다
    g = repeat(base("n_outer"), "n_outer", "n_inner", "n_pass")
    repeat(g, "n_inner", "n_read", "n_in")
    g.node("n_read", "testkit.read_text")
    g.node("n_in", "testkit.fail_once", inputs={"exit": "ok"}, next={"fail": "n_fail"})
    g.node("n_fail", "core.test.fail", inputs={"reason": link("n_read.text")})
    assert where(run(tmp_path, g)) == [("link_out_of_scope", "n_fail", "/nodes/n_fail/in/reason")]


def test_terminal_only_inside_body_still_dominance_checked(tmp_path: Path) -> None:
    # 본문 안에서만 오더라도 생산 노드를 지나지 않는 분기에서 오면 지배 오류
    g = repeat(base("n_loop"), "n_loop", "n_in", "n_pass")
    g.node(
        "n_in", "testkit.fail_once", inputs={"exit": "ok"}, next={"ok": "n_read", "fail": "n_fail"}
    )
    g.node("n_read", "testkit.read_text", next={"unreadable": "n_fail"})
    g.node("n_fail", "core.test.fail", inputs={"reason": link("n_read.text")})
    assert where(run(tmp_path, g)) == [("link_not_dominated", "n_fail", "/nodes/n_fail/in/reason")]


def test_read_body_output_after_done_rejected(tmp_path: Path) -> None:
    g = repeat(base("n_loop"), "n_loop", "n_read", "n_check")
    g.node("n_read", "testkit.read_text")
    compare(g, "n_check", link("n_read.text"), ok="n_pass")
    diags = run(tmp_path, g)
    assert where(diags) == [("link_out_of_scope", "n_check", "/nodes/n_check/in/a")]
    assert "core.var.set" in diags[0].message


def test_read_body_output_after_done_via_pure_rejected(tmp_path: Path) -> None:
    g = repeat(base("n_loop"), "n_loop", "n_read", "n_check")
    g.node("n_read", "testkit.read_text")
    g.node("n_cmp", "core.logic.compare", inputs={"a": link("n_read.text"), "op": "==", "b": "x"})
    compare(g, "n_check", link("n_cmp.result"), ok="n_pass")
    assert where(run(tmp_path, g)) == [("link_out_of_scope", "n_check", "/nodes/n_check/in/a")]


def test_index_outside_scope_rejected(tmp_path: Path) -> None:
    g = repeat(base("n_loop"), "n_loop", "n_tap", "n_check")
    tap(g, "n_tap")
    compare(g, "n_check", link("n_loop.index"), ok="n_pass")
    diags = run(tmp_path, g)
    assert where(diags) == [("link_out_of_scope", "n_check", "/nodes/n_check/in/a")]
    assert "반복 노드의 출력" in diags[0].message


def test_while_condition_reading_own_index_rejected(tmp_path: Path) -> None:
    # 조건은 본문 전에 계산되므로 반복 노드 자신의 index(본문 출구만 줌)를 읽을 수 없다
    g = base("n_while").node(
        "n_while",
        "core.flow.while",
        inputs={"condition": link("n_lt.result"), "max_iterations": 5},
        next={"body": "n_tap", "done": "n_pass"},
    )
    g.node("n_lt", "core.logic.compare", inputs={"a": link("n_while.index"), "op": "<", "b": 3})
    tap(g, "n_tap")
    assert where(run(tmp_path, g)) == [
        ("link_out_of_scope", "n_while", "/nodes/n_while/in/condition")
    ]


def test_body_end_unconnected_ok_no_warning(tmp_path: Path) -> None:
    # 본문 끝의 연결 안 된 ok 출구는 반복 노드로 돌아가므로 경고하지 않는다
    g = repeat(base("n_loop"), "n_loop", "n_tap", "n_pass")
    tap(g, "n_tap")
    assert run(tmp_path, g) == []
