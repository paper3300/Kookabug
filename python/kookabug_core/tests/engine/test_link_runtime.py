"""`$link` 런타임 규칙 (스키마 v0 7장 "`$link` 평가"): exec 출력은 이미 만든 값만 읽는다."""

from pathlib import Path

import pytest
from helpers.graphs import link, make_workspace, secret
from helpers.run import run_graph, tk
from testkit.nodes import COUNTS

from kookabug_core.engine import GraphInvalid


def test_reads_existing_output_without_rerunning_producer(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_a")
        .node("n_a", "testkit.fail_once", inputs={"exit": "ok", "value": 5}, next={"ok": "n_tap"})
        .node("n_tap", "testkit.input.tap", inputs={"x": 1, "y": 1}, next={"done": "n_check"})
        .node("n_check", "core.assert.compare", inputs={"a": link("n_a.value"), "op": "==", "b": 5})
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"
    assert ran.order() == ["n_entry", "n_a", "n_tap", "n_check"]
    assert ran.end("n_a")["outputs"] == {"value": 5}


def _skipped_branch_read():
    # 분기 false → n_a를 건너뛰고 합류한 n_merge가 n_a.value를 읽는다 (정적: link_not_dominated)
    return (
        tk()
        .entry("n_br")
        .node(
            "n_br",
            "core.flow.branch",
            inputs={"condition": False},
            next={"true": "n_a", "false": "n_merge"},
        )
        .node("n_a", "testkit.fail_once", inputs={"exit": "ok"}, next={"ok": "n_merge"})
        .node("n_merge", "core.assert.compare", inputs={"a": link("n_a.value"), "op": "==", "b": 1})
    )


def test_missing_output_at_runtime_is_error(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    with pytest.raises(GraphInvalid) as invalid:
        run_graph(ws, _skipped_branch_read())
    assert "link_not_dominated" in {d.code for d in invalid.value.diagnostics}

    ran = run_graph(ws, _skipped_branch_read(), validate=False)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "link_missing", ("n_merge",))
    assert "n_a" not in ran.order()


def test_output_not_given_by_taken_exit_is_error(tmp_path: Path) -> None:
    # n_a가 fail 출구(출력 없음)로 나간 뒤 그 출력을 읽는다 (정적으로는 link_not_dominated)
    g = (
        tk()
        .entry("n_a")
        .node(
            "n_a",
            "testkit.fail_once",
            inputs={"exit": "fail"},
            next={"fail": "n_read", "ok": "n_read"},
        )
        .node("n_read", "core.assert.compare", inputs={"a": link("n_a.value"), "op": "==", "b": 1})
    )
    ran = run_graph(make_workspace(tmp_path), g, validate=False)
    assert (ran.result.verdict, ran.result.code) == ("error", "link_missing")
    assert "주지 않는다" in ran.result.reason


def test_inputs_computed_once_per_step(tmp_path: Path) -> None:
    # 한 스텝의 입력 여러 곳(목록 안 포함)이 같은 순수 노드를 읽어도 입력 계산은 한 번이다
    n = link("n_count.n")
    g = (
        tk()
        .entry("n_check")
        .node("n_count", "testkit.pure.count", inputs={"key": "once"})
        .node("n_check", "core.assert.compare", inputs={"a": [n, n], "op": "==", "b": [n, 1]})
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"
    assert COUNTS["once"] == 1


def test_secret_through_any_into_string_pin_is_error(tmp_path: Path) -> None:
    # var.set(any) → var.get(any) → test.fail.reason(string): 정적으로는 막지 못하고 실행 때 막는다
    g = (
        tk()
        .entry("n_set")
        .node(
            "n_set",
            "core.var.set",
            inputs={"name": "pw", "value": secret("acc.pw")},
            next={"done": "n_fail"},
        )
        .node("n_get", "core.var.get", inputs={"name": "pw"})
        .node("n_fail", "core.test.fail", inputs={"reason": link("n_get.value")})
    )
    ran = run_graph(make_workspace(tmp_path), g, secrets={"acc.pw": "hunter2"})
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "type_mismatch", ("n_fail",))
    assert "hunter2" not in repr(ran.events)
