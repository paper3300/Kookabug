"""노드 호출 경계: `NodeInvoker`(exec·순수 모두), 실행 ctx의 config 기본값, 호출 후 취소 확인."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import link, make_workspace
from helpers.run import check_ok, run_graph, tk

from kookabug_core.engine import CancelToken, InProcessInvoker
from kookabug_core.ir import Node
from kookabug_core.registry import NodeDef
from kookabug_sdk import Result
from kookabug_sdk.context import Context


class RecordingInvoker:
    """부른 노드를 (ID, 순수 여부)로 남기고 같은 프로세스 구현에 넘긴다."""

    def __init__(self, after: Any = None) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.inner = InProcessInvoker()
        self.after = after

    def invoke(
        self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
    ) -> Result:
        self.calls.append((node.id, nodedef.pure))
        result = self.inner.invoke(nodedef, node, ctx, inputs)
        if self.after is not None:
            self.after(node)
        return result


def test_exec_and_pure_nodes_go_through_invoker(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_set")
        .node("n_get", "core.var.get", inputs={"name": "x"})
        .node("n_cmp", "core.logic.compare", inputs={"a": link("n_get.value"), "op": "==", "b": 1})
        .node("n_set", "core.var.set", inputs={"name": "x", "value": 1}, next={"done": "n_check"})
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": link("n_cmp.result"), "op": "==", "b": True},
        )
    )
    invoker = RecordingInvoker()
    ran = run_graph(make_workspace(tmp_path), g, invoker=invoker)
    assert ran.result.verdict == "pass"
    # 엔진 노드(entry)는 실행기가 처리한다. 순수 노드는 소비 스텝(n_check)의 입력 계산 때 불린다
    assert invoker.calls == [
        ("n_set", False),
        ("n_get", True),
        ("n_cmp", True),
        ("n_check", False),
    ]


def test_cancel_while_last_node_runs_is_error(tmp_path: Path) -> None:
    # 노드가 ctx를 다시 부르지 않고 돌아와도, 그동안 생긴 취소는 결과를 확정하기 전에 본다
    token = CancelToken()
    invoker = RecordingInvoker(after=lambda node: token.cancel() if node.id == "n_check" else None)
    g = tk().entry("n_check").node("n_check", "core.assert.compare", inputs=check_ok())
    ran = run_graph(make_workspace(tmp_path), g, cancel=token, invoker=invoker)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "cancelled", ("n_check",))
    assert ran.end("n_check")["status"] == "cancelled"


@pytest.mark.parametrize("explicit", [False, True], ids=["default", "explicit"])
def test_dynamic_exits_config_default_same_as_explicit(tmp_path: Path, explicit: bool) -> None:
    # config.exits를 생략하면 선언 기본값 ["done"] — 검증과 실행이 같은 값을 본다
    g = (
        tk()
        .entry("n_choose")
        .node(
            "n_choose",
            "testkit.flow.choose",
            config={"exits": ["done"]} if explicit else None,
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass", ran.result.reason
    assert ran.end("n_choose")["exit"] == "done"


@pytest.mark.parametrize(
    ("config", "expected"), [(None, 3), ({"n": 5}, 5)], ids=["default", "given"]
)
def test_ctx_config_has_declared_defaults(
    tmp_path: Path, config: dict[str, Any] | None, expected: int
) -> None:
    g = (
        tk()
        .entry("n_cfg")
        .node("n_cfg", "testkit.config_value", config=config, next={"done": "n_check"})
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": link("n_cfg.n"), "op": "==", "b": expected},
        )
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass", ran.result.reason
    # 그래프의 config 자체는 바뀌지 않는다
    assert ran.program.graphs["tests/t.graph.json"].nodes["n_cfg"].config == (config or {})
