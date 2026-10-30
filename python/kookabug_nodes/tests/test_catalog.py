import importlib
import tomllib
from typing import Any

import pytest

import kookabug_nodes
from kb_testing.core_nodes import (
    CORE_NODE_MODULES,
    CORE_NODE_TYPES,
    ENGINE_NODE_TYPES,
    M0A_SDK_NODE_TYPES,
    M1_APP_WINDOW_INPUT_NODE_TYPES,
    M1_NODE_TYPES,
    M1_OBSERVE_NODE_TYPES,
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
    assert len(types) == 38
    assert set(types) == CORE_NODE_TYPES
    assert schema["plugin"]["id"] == "core"


def test_engine_nodes_exact(nodes: dict[str, dict[str, Any]]) -> None:
    assert {t for t, n in nodes.items() if "engine" in n} == ENGINE_NODE_TYPES
    assert len(ENGINE_NODE_TYPES) == 8


def test_sdk_nodes_exact(nodes: dict[str, dict[str, Any]]) -> None:
    assert {t for t, n in nodes.items() if "engine" not in n} == SDK_NODE_TYPES
    assert len(SDK_NODE_TYPES) == 30


def test_schema_matches_node_schema_metaschema(schema: dict[str, Any]) -> None:
    assert check_shape(schema, "node-schema") == []


def test_modules_list_matches_pyproject(nodes: dict[str, dict[str, Any]]) -> None:
    with (PROJECT / "pyproject.toml").open("rb") as f:
        tool = tomllib.load(f)["tool"]["kookabug"]
    assert tuple(tool["modules"]) == CORE_NODE_MODULES
    assert kookabug_nodes.MODULES == CORE_NODE_MODULES
    # 노드 effects 합집합 = 플러그인 permissions (빌드가 effects ⊆ permissions를 본다)
    used = {e for n in nodes.values() for e in n.get("effects", [])}
    assert sorted(tool["permissions"]) == sorted(used) == ["capture", "input", "process"]


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
    assert {t for t, n in nodes.items() if n.get("assertion")} == {
        "core.assert.compare",
        "core.assert.visible",
        "core.assert.not_visible",
        "core.assert.text",
    }
    # 종료 노드: 출구 없는 exec 노드
    assert {t for t, n in nodes.items() if n.get("exits") == []} == {
        "core.graph.exit",
        "core.test.pass",
        "core.test.fail",
        "core.test.skip",
    }
    for node_type in ENGINE_NODE_TYPES | M0A_SDK_NODE_TYPES:
        n = nodes[node_type]
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


# ---------------------------------------------------------------- 앱·창·입력 (M1 T10)

# 노드 타입 → (effects, 출구 (이름, 종류, 출력), 기다리는 노드인가)
APP_WINDOW_INPUT: dict[str, tuple[list[str], list[tuple[str, str, list[str]]], bool]] = {
    "core.app.launch": (
        ["process"],
        [("attached", "ok", ["process", "window"]), ("timeout", "fail", ["process"])],
        True,
    ),
    "core.app.close": (["process"], [("closed", "ok", []), ("timeout", "fail", [])], False),
    "core.window.attach": (
        ["process"],
        [("found", "ok", ["window"]), ("not_found", "fail", [])],
        False,
    ),
    "core.window.set_current": (["process"], [("done", "ok", [])], False),
    "core.window.set_size": (["process"], [("done", "ok", []), ("fail", "fail", [])], False),
    "core.input.click": (["input"], [("done", "ok", [])], False),
    "core.input.drag": (["input"], [("done", "ok", [])], False),
    "core.input.scroll": (["input"], [("done", "ok", [])], False),
    "core.input.key": (["input"], [("done", "ok", [])], False),
    "core.input.type_text": (["capture", "input"], [("done", "ok", [])], False),
}


def test_app_window_input_nodes_exact() -> None:
    assert set(APP_WINDOW_INPUT) == M1_APP_WINDOW_INPUT_NODE_TYPES
    assert len(M1_APP_WINDOW_INPUT_NODE_TYPES) == 10


@pytest.mark.parametrize("node_type", sorted(APP_WINDOW_INPUT))
def test_app_window_input_effects_exits_retry(
    nodes: dict[str, dict[str, Any]], node_type: str
) -> None:
    effects, exits, waits = APP_WINDOW_INPUT[node_type]
    n = nodes[node_type]
    assert n["effects"] == effects
    assert [(e["name"], e["kind"], e["outputs"]) for e in n["exits"]] == exits
    # 게임에 영향을 주는 노드는 전부 retry never (MVP 노드 목록 7장)
    assert "retry" not in n
    assert ("timeout_ms" in n["inputs"]) is waits
    assert "window" not in n["inputs"] or node_type == "core.window.set_current"
    assert not n.get("pure") and not n.get("assertion") and "engine" not in n


def test_app_window_node_pins(nodes: dict[str, dict[str, Any]]) -> None:
    launch = nodes["core.app.launch"]
    assert launch["inputs"] == {
        "args": {"default": None, "nullable": True, "type": "list[string]"},
        "cwd": {"default": None, "nullable": True, "type": "string"},
        "path": {"type": "string"},
        "timeout_ms": {"default": 30000, "minimum": 0, "type": "int"},
        "window_title": {"default": None, "nullable": True, "type": "string"},
    }
    assert launch["outputs"] == {"process": {"type": "process"}, "window": {"type": "window"}}
    assert nodes["core.app.close"]["inputs"] == {
        "force_after_ms": {"default": 5000, "minimum": 0, "type": "int"},
        "process": {"type": "process"},
    }
    attach = nodes["core.window.attach"]
    assert attach["inputs"] == {
        "owned": {"default": False, "type": "bool"},
        "process_name": {"default": None, "nullable": True, "type": "string"},
        "title": {"default": None, "nullable": True, "type": "string"},
    }
    assert attach["outputs"] == {"window": {"type": "window"}}
    assert nodes["core.window.set_current"]["inputs"] == {"window": {"type": "window"}}
    assert nodes["core.window.set_size"]["inputs"] == {
        "client_size": {"min_items": 2, "type": "list[int]"}
    }


def test_input_node_pins(nodes: dict[str, dict[str, Any]]) -> None:
    buttons = ["left", "right", "middle", "x1", "x2"]
    button = {"default": "left", "enum": buttons, "type": "string"}
    assert nodes["core.input.click"]["inputs"] == {
        "button": button,
        "count": {"default": 1, "minimum": 1, "type": "int"},
        "match": {"default": None, "nullable": True, "type": "match"},
        "point": {"default": None, "nullable": True, "type": "point"},
    }
    assert nodes["core.input.drag"]["inputs"] == {
        "button": button,
        "duration_ms": {"default": 300, "minimum": 0, "type": "int"},
        "end": {"type": "match|point"},
        "start": {"type": "match|point"},
    }
    assert nodes["core.input.scroll"]["inputs"] == {
        "amount": {"type": "int"},
        "point": {"type": "point"},
    }
    assert nodes["core.input.key"]["inputs"] == {
        "hold_ms": {"default": 0, "minimum": 0, "type": "int"},
        "keys": {"type": "string"},
    }
    # 비밀값을 받는 글자 입력 (스키마 6장: secret은 secret을 포함한 핀에만)
    assert nodes["core.input.type_text"]["inputs"] == {
        "clear": {"default": False, "type": "bool"},
        "target": {"default": None, "nullable": True, "type": "target"},
        "text": {"type": "string|secret"},
    }
    for node_type in M1_APP_WINDOW_INPUT_NODE_TYPES - {"core.app.launch", "core.window.attach"}:
        assert nodes[node_type]["outputs"] == {}, node_type


# ---------------------------------------------------------------- 화면·이미지·검증·OCR (M1 T11)

# 노드 타입 → (effects, 출구 (이름, 종류, 출력), retry (mode, on) 또는 None = never)
OBSERVE: dict[
    str, tuple[list[str], list[tuple[str, str, list[str]]], tuple[str, list[str]] | None]
] = {
    "core.image.wait": (
        ["capture"],
        [("found", "ok", ["match"]), ("timeout", "fail", [])],
        ("observation", ["timeout"]),
    ),
    "core.image.wait_gone": (
        ["capture"],
        [("gone", "ok", []), ("timeout", "fail", [])],
        ("observation", ["timeout"]),
    ),
    "core.image.click": (
        ["capture", "input"],
        [("done", "ok", ["match"]), ("not_found", "fail", [])],
        None,
    ),
    "core.screen.wait_stable": (
        ["capture"],
        [("stable", "ok", []), ("timeout", "fail", [])],
        ("observation", ["timeout"]),
    ),
    "core.screen.capture": (["capture"], [("done", "ok", ["image"])], None),
    "core.assert.visible": (
        ["capture"],
        [("ok", "ok", ["match"]), ("fail", "fail", [])],
        ("observation", ["fail"]),
    ),
    "core.assert.not_visible": (
        ["capture"],
        [("ok", "ok", []), ("fail", "fail", [])],
        ("observation", ["fail"]),
    ),
    "core.assert.text": (
        ["capture"],
        [("ok", "ok", ["text"]), ("fail", "fail", ["text"])],
        ("observation", ["fail"]),
    ),
    "core.ocr.read": (
        ["capture"],
        [("done", "ok", ["confidence", "number", "text"]), ("unreadable", "fail", [])],
        ("observation", ["unreadable"]),
    ),
    "core.ocr.wait_text": (
        ["capture"],
        [("found", "ok", ["match", "text"]), ("timeout", "fail", [])],
        ("observation", ["timeout"]),
    ),
    "core.ocr.click_text": (
        ["capture", "input"],
        [("done", "ok", ["match"]), ("not_found", "fail", [])],
        None,
    ),
}


def test_m1_nodes_are_22() -> None:
    assert set(OBSERVE) | {"core.image.wait_any"} == M1_OBSERVE_NODE_TYPES
    assert M1_NODE_TYPES == M1_APP_WINDOW_INPUT_NODE_TYPES | M1_OBSERVE_NODE_TYPES
    assert len(M1_NODE_TYPES) == 22


@pytest.mark.parametrize("node_type", sorted(OBSERVE))
def test_observe_effects_exits_retry(nodes: dict[str, dict[str, Any]], node_type: str) -> None:
    effects, exits, retry = OBSERVE[node_type]
    n = nodes[node_type]
    assert n["effects"] == effects
    assert [(e["name"], e["kind"], sorted(e["outputs"])) for e in n["exits"]] == exits
    assert (None if "retry" not in n else (n["retry"]["mode"], n["retry"]["on"])) == retry
    assert not n.get("pure") and "engine" not in n


def test_retry_modes_match_mvp_list(nodes: dict[str, dict[str, Any]]) -> None:
    """MVP 노드 목록 7장: 대기·OCR·화면 검증은 observation, 입력·실행과 image.click·
    ocr.click_text는 never."""
    observation = {t for t, n in nodes.items() if n.get("retry", {}).get("mode") == "observation"}
    assert observation == {
        "core.image.wait",
        "core.image.wait_any",
        "core.image.wait_gone",
        "core.screen.wait_stable",
        "core.ocr.read",
        "core.ocr.wait_text",
        "core.assert.visible",
        "core.assert.not_visible",
        "core.assert.text",
    }
    for node_type in M1_APP_WINDOW_INPUT_NODE_TYPES | {"core.image.click", "core.ocr.click_text"}:
        assert "retry" not in nodes[node_type], node_type


def test_wait_any_dynamic_exits(nodes: dict[str, dict[str, Any]]) -> None:
    n = nodes["core.image.wait_any"]
    assert n["exits"] == {
        "extra": [{"kind": "fail", "name": "timeout", "outputs": []}],
        "from_config": "exits",
        "kind": "ok",
        "outputs": ["match"],
    }
    assert n["config"]["exits"] == {"min_items": 2, "type": "list[string]"}
    assert n["inputs"]["targets"] == {"type": "dict[str,target]"}
    assert n["retry"] == {"mode": "observation", "on": ["timeout"]}


def test_observe_node_pins(nodes: dict[str, dict[str, Any]]) -> None:
    region = {"default": None, "nullable": True, "type": "target|rect"}
    assert nodes["core.ocr.read"]["inputs"] == {
        "parse": {"default": "text", "enum": ["text", "number"], "type": "string"},
        "region": region,
    }
    assert nodes["core.ocr.read"]["outputs"] == {
        "confidence": {"nullable": True, "type": "float"},
        "number": {"nullable": True, "type": "float"},
        "text": {"type": "string|secret"},
    }
    assert nodes["core.ocr.wait_text"]["inputs"]["region"] == region
    assert nodes["core.assert.text"]["outputs"] == {"text": {"type": "string|secret"}}
    stable = nodes["core.screen.wait_stable"]["inputs"]
    assert stable["region"] == {"default": None, "nullable": True, "type": "rect"}
    assert stable["tolerance"] == {"default": 0.001, "maximum": 1, "minimum": 0, "type": "float"}
    assert nodes["core.screen.capture"]["outputs"] == {"image": {"type": "image"}}
    # 기다리는 노드만 timeout_ms를 선언한다 (G13): 글자 읽기·스크린샷은 기다리지 않는다
    waits = {t for t in M1_OBSERVE_NODE_TYPES if "timeout_ms" in nodes[t]["inputs"]}
    assert waits == M1_OBSERVE_NODE_TYPES - {"core.ocr.read", "core.screen.capture"}
