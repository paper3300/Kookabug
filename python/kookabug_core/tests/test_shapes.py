"""노드 모양 (M2 계획 2.7): 정적·동적 출구·FromInterface·대체 모양."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from helpers.corpus import CORPUS_DIR
from helpers.graphs import GraphBuilder, link, make_workspace, subgraph_interface

from kookabug_core.canonical import loads_strict
from kookabug_core.registry import default_registry
from kookabug_core.shapes import Shape, node_shapes, value_shapes
from kookabug_core.validate import check_graph, check_graph_value
from kookabug_core.workspace import Workspace

REGISTRY = default_registry()


def shapes_of(ws: Workspace, rel: str) -> dict[str, Shape]:
    program, _ = check_graph(ws, rel, registry=REGISTRY)
    return node_shapes(program, program.graphs[rel], REGISTRY)


def names(items: Any) -> list[str]:
    return [i.name for i in items]


def test_static_shape_matches_registry(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    g = GraphBuilder().entry("n_click").node("n_click", "core.input.click")
    g.node("n_cmp", "core.logic.compare", inputs={"a": 1, "b": 2, "op": "=="})
    rel = g.write(ws, "tests/a.graph.json")
    shapes = shapes_of(ws, rel)

    click = shapes["n_click"]
    decl = REGISTRY.get("core.input.click")
    assert decl is not None and isinstance(decl.inputs, tuple)
    # 선언 입력 + exec 노드 공통 입력 window
    assert names(click.inputs) == [*names(decl.inputs), "window"]
    assert not click.unknown
    button = next(p for p in click.inputs if p.name == "button")
    assert button.to_json() == {
        "name": "button",
        "type": "string",
        "nullable": False,
        "optional": False,
        "required": False,
        "default": "left",
        "enum": ["left", "right", "middle", "x1", "x2"],
    }
    assert [e.to_json() for e in click.exits] == [{"name": "done", "kind": "ok", "outputs": []}]
    # 순수 노드는 window가 없고 출구도 없다
    cmp_ = shapes["n_cmp"]
    assert names(cmp_.inputs) == ["a", "b", "op"] and cmp_.exits == ()
    assert names(cmp_.outputs) == ["result"]
    # 시작 노드 (테스트라 interface 출력 없음). exec 노드라 검증과 같이 공통 입력 window가 있다
    assert shapes["n_entry"].to_json() == {
        "unknown": False,
        "inputs": [
            {
                "name": "window",
                "type": "window",
                "nullable": True,
                "optional": True,
                "required": False,
            }
        ],
        "outputs": [],
        "exits": [{"name": "start", "kind": "ok", "outputs": []}],
    }


def test_wait_any_exits_from_config_order(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    g = GraphBuilder().entry("n_wait")
    g.node(
        "n_wait", "core.image.wait_any", inputs={"targets": {}}, config={"exits": ["z", "a", "m"]}
    )
    rel = g.write(ws, "tests/a.graph.json")
    wait = shapes_of(ws, rel)["n_wait"]
    assert [(e.name, e.kind, e.outputs) for e in wait.exits] == [
        ("z", "ok", ("match",)),
        ("a", "ok", ("match",)),
        ("m", "ok", ("match",)),
        ("timeout", "fail", ()),
    ]
    # config가 틀리면 출구는 next 키로 채운다 (나머지는 선언 그대로)
    g.nodes["n_wait"]["config"] = {"exits": "bad"}
    g.nodes["n_wait"]["next"] = {"a": "n_entry"}
    program, _ = check_graph_value(ws, rel, g.build(), registry=REGISTRY)
    wait = value_shapes(program, rel, g.build(), REGISTRY)["n_wait"]
    assert not wait.unknown and names(wait.exits) == ["a"]
    assert names(wait.inputs) == ["targets", "timeout_ms", "window"]


def test_graph_call_exits_from_subgraph_interface(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    interface = subgraph_interface(
        exits={"lobby": "ok", "login_failed": "fail"},
        inputs={
            "account": {"type": "string", "description": "계정"},
            "server": {"type": "string", "default": "S1"},
        },
        outputs={"server_name": "string"},
    )
    sub = GraphBuilder("subgraph", interface=interface).entry("n_x").exit("n_x", "lobby")
    sub.write(ws, "subgraphs/s.graph.json")
    g = (
        GraphBuilder()
        .entry("n_call")
        .call("n_call", "subgraphs/s.graph.json", inputs={"account": "a"})
    )
    rel = g.write(ws, "tests/a.graph.json")
    call = shapes_of(ws, rel)["n_call"]
    assert not call.unknown
    assert [(p.name, p.required, p.description) for p in call.inputs] == [
        ("account", True, "계정"),
        ("server", False, None),
        ("window", False, None),
    ]
    assert [(o.name, o.type) for o in call.outputs] == [("server_name", "string")]
    assert [(e.name, e.kind, e.outputs) for e in call.exits] == [
        ("lobby", "ok", ("server_name",)),
        ("login_failed", "fail", ("server_name",)),
    ]
    # 서브그래프 안 시작·출구 노드도 자기 interface에서 온다
    sub_shapes = shapes_of(ws, "subgraphs/s.graph.json")
    assert names(sub_shapes["n_entry"].outputs) == ["account", "server"]
    assert names(sub_shapes["n_x"].inputs) == ["server_name", "window"]


def test_unknown_type_fallback_from_json_keys(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    rel = "unknown-node.graph.json"
    value = loads_strict((CORPUS_DIR / rel).read_text(encoding="utf-8"))
    program, _ = check_graph_value(ws, rel, value, registry=REGISTRY)
    magic = value_shapes(program, rel, value, REGISTRY)["n_magic"]
    assert magic.unknown
    assert [(p.name, p.type, p.required) for p in magic.inputs] == [
        ("region", "any", False),
        ("target", "any", False),
    ]
    assert names(magic.exits) == ["found", "missing"]
    assert [(o.name, o.type) for o in magic.outputs] == [("label", "any"), ("reason", "any")]


def test_broken_subgraph_call_fallback(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    (tmp_path / "subgraphs").mkdir()
    (tmp_path / "subgraphs" / "broken.graph.json").write_text("{", encoding="utf-8")
    g = (
        GraphBuilder()
        .entry("n_call")
        .call(
            "n_call",
            "subgraphs/broken.graph.json",
            inputs={"account": "a"},
            next={"lobby": "n_log"},
        )
    )
    g.node("n_log", "core.log.message", inputs={"text": link("n_call.server_name")})
    g.call("n_missing", "subgraphs/none.graph.json", next={"x": "n_log"})
    rel = g.write(ws, "tests/a.graph.json")
    shapes = shapes_of(ws, rel)
    call = shapes["n_call"]
    assert call.unknown
    assert names(call.inputs) == ["account"]
    assert names(call.outputs) == ["server_name"]
    assert names(call.exits) == ["lobby"]
    assert shapes["n_missing"].unknown and names(shapes["n_missing"].exits) == ["x"]
    assert not shapes["n_log"].unknown


def test_shapes_when_root_fails_shape_check(tmp_path: Path) -> None:
    # 모르는 키로 형식 검사에 걸린 그래프도 값에서 노드를 읽어 모양을 낸다
    ws = make_workspace(tmp_path)
    rel = "unknown-keys.graph.json"
    value = loads_strict((CORPUS_DIR / rel).read_text(encoding="utf-8"))
    program, diags = check_graph_value(ws, rel, value, registry=REGISTRY)
    assert rel not in program.graphs and diags
    shapes = value_shapes(program, rel, value, REGISTRY)
    assert set(shapes) == {"n_entry", "n_pass"}
    assert not shapes["n_pass"].unknown
    assert names(shapes["n_pass"].inputs) == ["reason", "window"]
    assert names(shapes["n_entry"].exits) == ["start"]
    # 노드가 아닌 값·틀린 필드는 건너뛴다
    odd = {"nodes": {"n_a": 1, "n_b": {"type": 3, "next": {"x": 1}}}, "interface": "bad"}
    assert {k: s.unknown for k, s in value_shapes(program, "x", odd, REGISTRY).items()} == {
        "n_b": True
    }
