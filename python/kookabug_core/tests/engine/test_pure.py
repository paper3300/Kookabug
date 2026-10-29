"""순수 노드 즉석 계산 (스키마 v0 7장): 소비 1회당 1번 계산, 다음 소비 때 다시, 재진입은 error."""

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from helpers.graphs import GraphBuilder, link, make_workspace
from helpers.run import run_graph, tk
from testkit.nodes import COUNTS

from kookabug_core.engine import GraphInvalid


def test_pure_computed_once_per_consumption(tmp_path: Path) -> None:
    # 한 소비(스텝 입력 계산) 안에서 같은 순수 노드를 여러 번 읽어도 같은 값, 계산 1번
    g = (
        tk()
        .entry("n_check")
        .node("n_count", "testkit.pure.count")
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": link("n_count.n"), "op": "==", "b": link("n_count.n")},
        )
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"
    assert COUNTS["c"] == 1


def test_pure_diamond_shared_computed_once(tmp_path: Path) -> None:
    # D가 읽는 A·B가 둘 다 C를 읽는다 → 한 소비에서 C는 1번
    g = (
        tk()
        .entry("n_d")
        .node("n_c", "testkit.pure.count")
        .node("n_a", "core.logic.compare", inputs={"a": link("n_c.n"), "op": ">=", "b": 1})
        .node("n_b", "core.logic.compare", inputs={"a": link("n_c.n"), "op": "<=", "b": 1})
        .node(
            "n_d",
            "core.assert.compare",
            inputs={"a": link("n_a.result"), "op": "==", "b": link("n_b.result")},
        )
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"
    assert COUNTS["c"] == 1


def test_pure_recomputed_next_consumption(tmp_path: Path) -> None:
    # 두 스텝이 같은 순수 노드를 읽으면 스텝마다 다시 계산한다 (1, 2)
    g = (
        tk()
        .entry("n_first")
        .node("n_count", "testkit.pure.count")
        .node(
            "n_first",
            "core.assert.compare",
            inputs={"a": link("n_count.n"), "op": "==", "b": 1},
            next={"ok": "n_second"},
        )
        .node(
            "n_second", "core.assert.compare", inputs={"a": link("n_count.n"), "op": "==", "b": 2}
        )
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"
    assert COUNTS["c"] == 2


def test_var_get_reflects_value_at_evaluation(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_set1")
        .node("n_get", "core.var.get", inputs={"name": "x"})
        .node("n_set1", "core.var.set", inputs={"name": "x", "value": 1}, next={"done": "n_check1"})
        .node(
            "n_check1",
            "core.assert.compare",
            inputs={"a": link("n_get.value"), "op": "==", "b": 1},
            next={"ok": "n_set2"},
        )
        .node("n_set2", "core.var.set", inputs={"name": "x", "value": 2}, next={"done": "n_check2"})
        .node(
            "n_check2", "core.assert.compare", inputs={"a": link("n_get.value"), "op": "==", "b": 2}
        )
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"


def test_var_value_is_copied_not_shared(tmp_path: Path) -> None:
    # 소비 노드(testkit.mutate)가 받은 중첩 목록을 고쳐도 변수·생산 노드 출력·그래프 상수는 그대로다
    g = (
        tk()
        .entry("n_set")
        .node("n_get", "core.var.get", inputs={"name": "xs"})
        .node(
            "n_set",
            "core.var.set",
            inputs={"name": "xs", "value": [1, [2]]},
            next={"done": "n_m1"},
        )
        .node(
            "n_m1", "testkit.mutate", inputs={"items": link("n_get.value")}, next={"done": "n_m2"}
        )
        .node(
            "n_m2", "testkit.mutate", inputs={"items": link("n_m1.items")}, next={"done": "n_var"}
        )
        .node(
            "n_var",
            "core.assert.compare",
            inputs={"a": link("n_get.value"), "op": "==", "b": [1, [2]]},
            next={"ok": "n_out"},
        )
        .node(
            "n_out",
            "core.assert.compare",
            inputs={"a": link("n_m1.items"), "op": "==", "b": [1, [2, "x"], "x"]},
            next={"ok": "n_m3"},
        )
        .node("n_m3", "testkit.mutate", inputs={"items": [7, [8]]})
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass", ran.result.reason
    assert ran.end("n_m2")["outputs"] == {"items": [1, [2, "x", "x"], "x", "x"]}
    nodes = ran.program.graphs["tests/t.graph.json"].nodes
    assert nodes["n_set"].inputs["value"] == [1, [2]]
    assert nodes["n_m3"].inputs["items"] == [7, [8]]


def test_copy_test_detects_missing_copies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 위 테스트의 검증력: 실행기·SDK 순수 변수 읽기의 복사를 없애면 위 테스트가 실패해야 한다
    import kookabug_core.engine.pure as engine_pure
    import kookabug_sdk.pure as sdk_pure

    no_copy = SimpleNamespace(deepcopy=lambda value: value)
    monkeypatch.setattr(engine_pure, "copy", no_copy)
    monkeypatch.setattr(sdk_pure, "copy", no_copy)
    with pytest.raises(AssertionError):
        test_var_value_is_copied_not_shared(tmp_path)


def _self_cycle() -> GraphBuilder:
    return (
        tk()
        .entry("n_br")
        .node("n_p", "core.logic.compare", inputs={"a": link("n_p.result"), "op": "==", "b": True})
        .node(
            "n_br",
            "core.flow.branch",
            inputs={"condition": link("n_p.result")},
            next={"true": "n_pass", "false": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


def _mutual_cycle() -> GraphBuilder:
    return (
        tk()
        .entry("n_br")
        .node("n_p", "core.logic.compare", inputs={"a": link("n_q.result"), "op": "==", "b": True})
        .node("n_q", "core.logic.compare", inputs={"a": link("n_p.result"), "op": "==", "b": True})
        .node(
            "n_br",
            "core.flow.branch",
            inputs={"condition": link("n_p.result")},
            next={"true": "n_pass", "false": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


@pytest.mark.parametrize(
    ("graph", "cycle"),
    [(_self_cycle, "'n_p' → 'n_p'"), (_mutual_cycle, "'n_p' → 'n_q' → 'n_p'")],
    ids=["self", "mutual"],
)
def test_pure_reentry_is_error(
    tmp_path: Path, graph: Callable[[], GraphBuilder], cycle: str
) -> None:
    ws = make_workspace(tmp_path)
    with pytest.raises(GraphInvalid) as invalid:
        run_graph(ws, graph())
    assert "pure_cycle" in {d.code for d in invalid.value.diagnostics}

    ran = run_graph(ws, graph(), validate=False)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "pure_reentry", ("n_br",))
    assert cycle in r.reason
    assert "n_pass" not in ran.order()


def test_pure_node_capture_is_error(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_check")
        .node("n_cap", "testkit.pure.capture")
        .node(
            "n_check", "core.assert.compare", inputs={"a": link("n_cap.ok"), "op": "==", "b": True}
        )
    )
    ran = run_graph(make_workspace(tmp_path), g, frames=["title.png"])
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "context_violation", ("n_check",))
    assert "ctx.capture" in r.reason
    assert ran.platform.captured == 0


def test_pure_node_logging_is_error(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_check")
        .node("n_log", "testkit.pure.log")
        .node(
            "n_check", "core.assert.compare", inputs={"a": link("n_log.ok"), "op": "==", "b": True}
        )
    )
    ran = run_graph(make_workspace(tmp_path), g)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "context_violation", ("n_check",))
    assert "ctx.log.info" in r.reason
    assert ran.of("log") == []


def test_pure_node_error_is_consumer_step_error(tmp_path: Path) -> None:
    # 순수 노드 예외(대소 비교 타입 불일치)는 그것을 소비하는 스텝의 error다
    g = (
        tk()
        .entry("n_br")
        .node("n_cmp", "core.logic.compare", inputs={"a": 1, "op": "<", "b": "x"})
        .node(
            "n_br",
            "core.flow.branch",
            inputs={"condition": link("n_cmp.result")},
            next={"true": "n_pass", "false": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run_graph(make_workspace(tmp_path), g)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "node_error", ("n_br",))
    assert "'n_cmp'" in r.reason
