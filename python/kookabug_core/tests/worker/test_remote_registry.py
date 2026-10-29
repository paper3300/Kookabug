"""원격 노드 등록, 결과 재대조, 실행 위치 고르기 (프로세스 없이)."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import pytest
from helpers.graphs import make_workspace
from helpers.run import tk
from testkit import NODES, PLUGIN_ID

from kookabug_core.engine import Executor, InProcessInvoker, RoutingInvoker
from kookabug_core.ir import Node
from kookabug_core.loader import load_program
from kookabug_core.registry import NodeDef, Registry, RegistryError, default_registry
from kookabug_core.workerhost import check_remote_result
from kookabug_sdk import NodeContractError, Result
from kookabug_sdk.context import Context
from kookabug_sdk.schema import FORMAT


def remote_schema(version: str = "0") -> dict[str, Any]:
    return {
        "format": FORMAT,
        "nodes": [f.schema() for f in sorted(NODES, key=lambda f: f.spec.type)],
        "plugin": {"id": PLUGIN_ID, "version": version},
    }


def remote_registry() -> Registry:
    registry = default_registry()
    registry.add_remote(remote_schema())
    return registry


def test_add_remote_registers_declarations_without_functions() -> None:
    registry = remote_registry()
    nodedef = registry.get("testkit.observe.wait_any")
    assert nodedef is not None and nodedef.remote and nodedef.function is None
    assert nodedef.effects == {"capture"}
    assert registry.plugins[PLUGIN_ID] == "0"
    core = registry.get("core.test.pass")
    assert core is not None and not core.remote


def test_add_remote_rejects_duplicates_engine_and_bad_shape() -> None:
    registry = remote_registry()
    with pytest.raises(RegistryError, match="이미 등록"):
        registry.add_remote(remote_schema())
    core = copy.deepcopy(remote_schema())
    core["plugin"]["id"] = "core"
    with pytest.raises(RegistryError):
        default_registry().add_remote(core)
    engine = remote_schema()
    engine["nodes"][0]["engine"] = "graph_call"
    with pytest.raises(RegistryError, match="engine"):
        Registry().add_remote(engine)
    with pytest.raises(RegistryError, match="형식"):
        Registry().add_remote({"format": FORMAT, "nodes": "x", "plugin": {"id": "t"}})
    other = remote_schema()
    other["nodes"][0]["type"] = "other.node"
    with pytest.raises(RegistryError, match="플러그인"):
        Registry().add_remote(other)


def nodedef(node_type: str) -> NodeDef:
    found = remote_registry().get(node_type)
    assert found is not None
    return found


def test_check_remote_result_accepts_and_fills_nullable() -> None:
    out = check_remote_result(nodedef("testkit.shot"), Result.ok("done", image=None), {})
    assert out.outputs == {"image": None, "saved": None}
    pure = check_remote_result(nodedef("testkit.pure.count"), Result(None, None, {"n": 1}), {})
    assert pure.outputs == {"n": 1}
    dynamic = check_remote_result(
        nodedef("testkit.flow.choose"), Result.ok("left"), {"exits": ["left", "right"]}
    )
    assert dynamic.exit == "left"
    failed = check_remote_result(nodedef("testkit.read_text"), Result.fail("unreadable", "x"), {})
    assert (failed.kind, failed.message) == ("fail", "x")


@pytest.mark.parametrize(
    ("node_type", "result", "config", "match"),
    [
        ("testkit.liar", Result.ok("other"), {}, "선언하지 않은 출구"),
        ("testkit.read_text", Result.ok("unreadable"), {}, "fail 출구"),
        ("testkit.read_text", Result.ok("done"), {}, "'text'이\\(가\\) 빠졌다"),
        ("testkit.read_text", Result.ok("done", text="t", extra=1), {}, "선언하지 않은 출력"),
        ("testkit.read_text", Result.fail("unreadable", text="t"), {}, "주지 않는다"),
        ("testkit.flow.choose", Result.ok("left"), {"exits": ["right"]}, "선언하지 않은 출구"),
        ("testkit.pure.count", Result.ok("done", n=1), {}, "순수 노드"),
        ("testkit.read_text", Result(None, None, {}), {}, "Result.ok/fail"),
    ],
)
def test_check_remote_result_rejects(
    node_type: str, result: Result, config: Mapping[str, Any], match: str
) -> None:
    with pytest.raises(NodeContractError, match=match):
        check_remote_result(nodedef(node_type), result, config)


def test_routing_without_worker_is_error_and_in_process_refuses_remote(tmp_path: Any) -> None:
    ws = make_workspace(tmp_path)
    tk().entry("n_read").node("n_read", "testkit.read_text").write(ws, "tests/t.graph.json")
    program = load_program(ws, "tests/t.graph.json")
    registry = remote_registry()
    result = Executor(registry, invoker=RoutingInvoker(None)).run(program)
    assert result.code == "worker_missing"
    result = Executor(registry, invoker=InProcessInvoker()).run(program)
    assert result.code == "remote_node_in_process"


class Recording:
    def __init__(self) -> None:
        self.types: list[str] = []

    def invoke(
        self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
    ) -> Result:
        self.types.append(nodedef.type)
        return Result.ok("done", text="원격")


def test_routing_sends_non_core_plugins_to_remote(tmp_path: Any) -> None:
    ws = make_workspace(tmp_path)
    graph = (
        tk()
        .entry("n_read")
        .node("n_read", "testkit.read_text", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    graph.write(ws, "tests/t.graph.json")
    program = load_program(ws, "tests/t.graph.json")
    remote = Recording()
    result = Executor(remote_registry(), invoker=RoutingInvoker(remote)).run(program)
    assert result.verdict == "pass"
    assert remote.types == ["testkit.read_text"]
