import importlib
import tomllib
from typing import Any

import pytest

from kb_testing.core_nodes import (
    CORE_NODE_MODULES,
    CORE_NODE_TYPES,
    ENGINE_NODE_TYPES,
    SDK_NODE_TYPES,
)
from kb_testing.packaging import REPO_ROOT
from kookabug_core.schema import check_shape
from kookabug_sdk import NodeContractError, NodeFunction
from kookabug_sdk.schema import load_installed
from kookabug_sdk.testing import fake_context

PROJECT = REPO_ROOT / "python" / "kookabug_nodes"


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return load_installed("kookabug_nodes")


@pytest.fixture(scope="module")
def nodes(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["type"]: n for n in schema["nodes"]}


def node_functions() -> dict[str, NodeFunction]:
    found: dict[str, NodeFunction] = {}
    for name in CORE_NODE_MODULES:
        for value in vars(importlib.import_module(name)).values():
            if isinstance(value, NodeFunction):
                found[value.spec.type] = value
    return found


def test_core_node_types_exact(schema: dict[str, Any]) -> None:
    types = [n["type"] for n in schema["nodes"]]
    assert len(types) == 16
    assert set(types) == CORE_NODE_TYPES
    assert schema["plugin"]["id"] == "core"


def test_engine_nodes_exact(nodes: dict[str, dict[str, Any]]) -> None:
    assert {t for t, n in nodes.items() if "engine" in n} == ENGINE_NODE_TYPES
    assert len(ENGINE_NODE_TYPES) == 8


def test_sdk_nodes_exact(nodes: dict[str, dict[str, Any]]) -> None:
    assert {t for t, n in nodes.items() if "engine" not in n} == SDK_NODE_TYPES
    assert len(SDK_NODE_TYPES) == 8


def test_schema_matches_node_schema_metaschema(schema: dict[str, Any]) -> None:
    assert check_shape(schema, "node-schema") == []


def test_modules_list_matches_pyproject() -> None:
    with (PROJECT / "pyproject.toml").open("rb") as f:
        tool = tomllib.load(f)["tool"]["kookabug"]
    assert tuple(tool["modules"]) == CORE_NODE_MODULES
    assert tool["permissions"] == []


def test_every_schema_node_has_a_function(nodes: dict[str, dict[str, Any]]) -> None:
    functions = node_functions()
    assert set(functions) == set(nodes)
    for node_type, fn in functions.items():
        assert fn.schema() == nodes[node_type]


@pytest.mark.parametrize("node_type", sorted(ENGINE_NODE_TYPES))
def test_engine_node_body_not_called(node_type: str) -> None:
    with pytest.raises(NodeContractError, match="실행기"):
        node_functions()[node_type].invoke(fake_context(), {})


def test_node_kinds(nodes: dict[str, dict[str, Any]]) -> None:
    assert {t for t, n in nodes.items() if n.get("pure")} == {
        "core.var.get",
        "core.logic.compare",
        "core.text.format",
    }
    assert {t for t, n in nodes.items() if n.get("assertion")} == {"core.assert.compare"}
    # 종료 노드: 출구 없는 exec 노드
    assert {t for t, n in nodes.items() if n.get("exits") == []} == {
        "core.graph.exit",
        "core.test.pass",
        "core.test.fail",
        "core.test.skip",
    }
    for node_type, n in nodes.items():
        assert "effects" not in n, node_type
        assert "retry" not in n, node_type  # 전부 never (G2: assert.compare 포함)
        assert "timeout_ms" not in n["inputs"], node_type  # 기다리는 노드만 선언 (G13)


@pytest.mark.parametrize("node_type", ["core.flow.repeat", "core.flow.while"])
def test_loop_index_only_on_body(nodes: dict[str, dict[str, Any]], node_type: str) -> None:
    exits = {e["name"]: e for e in nodes[node_type]["exits"]}
    assert exits["body"] == {"kind": "ok", "name": "body", "outputs": ["index"]}
    assert exits["done"] == {"kind": "ok", "name": "done", "outputs": []}
    assert nodes[node_type]["outputs"] == {"index": {"type": "int"}}


def test_loop_inputs(nodes: dict[str, dict[str, Any]]) -> None:
    assert nodes["core.flow.repeat"]["inputs"] == {"times": {"minimum": 0, "type": "int"}}
    assert nodes["core.flow.while"]["inputs"] == {
        "condition": {"type": "bool"},
        "max_iterations": {"minimum": 1, "type": "int"},
    }
    limit = next(e for e in nodes["core.flow.while"]["exits"] if e["name"] == "limit")
    assert limit == {"kind": "fail", "name": "limit", "outputs": []}


def test_graph_nodes_from_interface(nodes: dict[str, dict[str, Any]]) -> None:
    entry = nodes["core.graph.entry"]
    assert entry["outputs"] == {"from_interface": "inputs"}
    assert entry["exits"] == [{"kind": "ok", "name": "start", "outputs": []}]
    exit_ = nodes["core.graph.exit"]
    assert exit_["inputs"] == {"from_interface": "outputs"}
    assert exit_["config"]["exit"]["type"] == "string"
    call = nodes["core.graph.call"]
    assert (call["inputs"], call["outputs"], call["exits"]) == (
        {"from_interface": "inputs"},
        {"from_interface": "outputs"},
        {"from_interface": "exits"},
    )
    assert call["config"]["graph"]["type"] == "string"


def test_value_node_pins(nodes: dict[str, dict[str, Any]]) -> None:
    ops = ["==", "!=", "<", "<=", ">", ">=", "contains"]
    for node_type in ("core.logic.compare", "core.assert.compare"):
        assert nodes[node_type]["inputs"]["op"] == {"enum": ops, "type": "string"}
    fmt = nodes["core.text.format"]
    assert fmt["inputs"] == {"template": {"type": "string"}, "values": {"type": "dict[str,any]"}}
    assert fmt["outputs"] == {"text": {"type": "string|secret"}}
    # 생략(키 없음)과 명시적 null을 구분하도록 default 값 없이 optional로 선언한다
    assert nodes["core.var.get"]["inputs"]["default"] == {
        "nullable": True,
        "optional": True,
        "type": "any",
    }
    log = nodes["core.log.message"]["inputs"]
    assert log["text"] == {"type": "string|secret"}
    assert log["level"]["enum"] == ["info", "warn", "error"]
