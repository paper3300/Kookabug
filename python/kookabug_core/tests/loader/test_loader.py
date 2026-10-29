from pathlib import Path

import pytest
from helpers.graphs import (
    GraphBuilder,
    check_program,
    codes,
    literal,
    make_workspace,
    only,
    subgraph_interface,
    target,
    without_flow,
    write_json,
    write_target,
)

from kookabug_core.ir import Link, LinkRef, Unresolved
from kookabug_core.loader import load_program
from kookabug_core.workspace import MemorySecrets, Workspace, WorkspaceError
from kookabug_sdk.types import Target

GRAPH = "tests/a.graph.json"


def test_literal_unwrapped_as_is(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    raw = {"$link": "n_x.y", "nested": {"$secret": "k"}, "list": [{"$target": "t.target.json"}]}
    GraphBuilder().entry("n_set").node(
        "n_set",
        "core.var.set",
        inputs={"name": "v", "value": literal(raw)},
    ).write(ws, GRAPH)
    program, diags = check_program(ws, GRAPH)
    assert without_flow(diags) == []
    graph = program.graphs[GRAPH]
    assert graph.nodes["n_set"].inputs["value"] == raw
    assert graph.links == []
    assert program.references.targets == set()


def test_special_values_inside_containers_resolved(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path, settings={"s": "S"})
    GraphBuilder().entry("n_set").node(
        "n_set",
        "core.var.set",
        inputs={
            "name": "v",
            "value": {"a": [{"$link": "n_entry.x"}, {"$setting": "s"}], "b": {"$literal": 1}},
        },
    ).write(ws, GRAPH)
    program, _ = check_program(ws, GRAPH)
    graph = program.graphs[GRAPH]
    assert graph.nodes["n_set"].inputs["value"] == {"a": [LinkRef("n_entry", "x"), "S"], "b": 1}
    assert graph.links == [Link("n_set", ("value", "a", 0), "n_entry", "x")]


def test_target_path_relative_to_workspace_image_relative_to_target(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    # image는 target 파일 기준: targets/login/../shared/button.png = targets/shared/button.png
    write_target(
        ws, "targets/login/button.target.json", image="../shared/button.png", create_image=False
    )
    (tmp_path / "targets" / "shared").mkdir(parents=True)
    (tmp_path / "targets" / "shared" / "button.png").write_bytes(b"png")
    # 루트에 같은 이름의 이미지가 있어도 쓰지 않는다
    (tmp_path / "button.png").write_bytes(b"png")
    GraphBuilder().entry("n_set").node(
        "n_set",
        "core.var.set",
        inputs={"name": "v", "value": target("targets/login/button.target.json")},
    ).write(ws, GRAPH)

    program, diags = check_program(ws, GRAPH)
    assert without_flow(diags) == []
    value = program.graphs[GRAPH].nodes["n_set"].inputs["value"]
    assert isinstance(value, Target)
    assert value.name == "targets/login/button.target.json"
    assert value.path == tmp_path.resolve() / "targets" / "login" / "button.target.json"
    assert value.spec["image"] == "../shared/button.png"
    assert program.references.images == {"targets/shared/button.png"}


@pytest.mark.parametrize(
    ("path", "make", "code"),
    [
        ("targets/none.target.json", False, "target_missing"),
        ("../outside.target.json", False, None),  # 형식 검사 단계에서 통과하지만 루트 밖
        ("targets/broken.target.json", True, "target_invalid"),
    ],
)
def test_target_problems(tmp_path: Path, path: str, make: bool, code: str | None) -> None:
    ws = make_workspace(tmp_path)
    if make:
        write_json(ws, path, {"format": "kookabug.target/0"})
    GraphBuilder().entry("n_set").node(
        "n_set", "core.var.set", inputs={"name": "v", "value": target(path)}
    ).write(ws, GRAPH)
    program, diags = check_program(ws, GRAPH)
    expected = code or "target_missing"
    (d,) = only(diags, expected)
    assert d.pointer == "/nodes/n_set/in/value"
    assert program.graphs[GRAPH].nodes["n_set"].inputs["value"] == Unresolved("$target", path)


def test_target_image_missing_is_invalid(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_target(ws, "targets/a.target.json", create_image=False)
    GraphBuilder().entry("n_set").node(
        "n_set", "core.var.set", inputs={"name": "v", "value": target("targets/a.target.json")}
    ).write(ws, GRAPH)
    _, diags = check_program(ws, GRAPH)
    (d,) = only(diags, "target_invalid")
    assert "targets/a.png" in d.message


def test_target_image_outside_workspace_is_invalid(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_target(ws, "targets/a.target.json", image="../../x.png", create_image=False)
    GraphBuilder().entry("n_set").node(
        "n_set", "core.var.set", inputs={"name": "v", "value": target("targets/a.target.json")}
    ).write(ws, GRAPH)
    assert codes(without_flow(check_program(ws, GRAPH)[1])) == ["target_invalid"]


def test_reference_closure_lists_subgraphs_targets_images(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    for name in ("a", "b", "c", "unused"):
        write_target(ws, f"targets/{name}.target.json")
    iface = subgraph_interface(exits={"done": "ok"}, inputs={"t": "target"})
    # 테스트 → sub_one → sub_two(두 번 불러도 한 번만), 각 그래프가 target을 하나씩 쓴다
    (
        GraphBuilder("subgraph", interface=subgraph_interface())
        .entry("n_set")
        .node(
            "n_set",
            "core.var.set",
            inputs={"name": "v", "value": target("targets/c.target.json")},
            next={"done": "n_exit"},
        )
        .exit("n_exit", "done")
        .write(ws, "subgraphs/two.graph.json")
    )
    (
        GraphBuilder("subgraph", interface=iface)
        .entry("n_call")
        .call("n_call", "subgraphs/two.graph.json", next={"done": "n_call2"})
        .call("n_call2", "subgraphs/two.graph.json", next={"done": "n_exit"})
        .exit("n_exit", "done")
        .write(ws, "subgraphs/one.graph.json")
    )
    (
        GraphBuilder()
        .entry("n_set")
        .node(
            "n_set",
            "core.var.set",
            inputs={"name": "v", "value": target("targets/a.target.json")},
            next={"done": "n_call"},
        )
        .call(
            "n_call",
            "subgraphs/one.graph.json",
            inputs={"t": target("targets/b.target.json")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
        .write(ws, GRAPH)
    )

    program, diags = check_program(ws, GRAPH)
    assert diags == []
    refs = program.references
    assert refs.graphs == {GRAPH, "subgraphs/one.graph.json", "subgraphs/two.graph.json"}
    assert refs.targets == {f"targets/{n}.target.json" for n in "abc"}
    assert refs.images == {f"targets/{n}.png" for n in "abc"}
    assert refs.all() == sorted(refs.graphs | refs.targets | refs.images)
    assert set(program.graphs) == refs.graphs


def test_missing_root_graph(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    program = load_program(ws, "tests/none.graph.json", secrets=MemorySecrets())
    assert codes(program.diagnostics) == ["graph_missing"]
    assert program.graphs == {}


def test_invalid_json_and_shape_stop_before_ir(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "bad.graph.json").write_text('{"a": 1, "a": 2}', "utf-8")
    program = load_program(ws, "tests/bad.graph.json", secrets=MemorySecrets())
    assert codes(program.diagnostics) == ["json_invalid"]
    assert program.broken == {"tests/bad.graph.json"}

    data = GraphBuilder().entry().build()
    data["nodes"]["n_entry"]["colour"] = 1
    write_json(ws, "tests/shape.graph.json", data)
    program = load_program(ws, "tests/shape.graph.json", secrets=MemorySecrets())
    assert [(d.code, d.file) for d in program.diagnostics] == [
        ("unknown_field", "tests/shape.graph.json")
    ]
    assert program.graphs == {}


def test_load_program_accepts_absolute_path(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    GraphBuilder().entry("n_pass").node("n_pass", "core.test.pass").write(ws, GRAPH)
    program = load_program(ws, tmp_path / "tests" / "a.graph.json", secrets=MemorySecrets())
    assert program.root == GRAPH
    with pytest.raises(WorkspaceError):
        load_program(ws, tmp_path.parent / "x.graph.json")


def test_workspace_resolve_rejects_paths_outside_root(tmp_path: Path) -> None:
    ws: Workspace = make_workspace(tmp_path)
    assert ws.resolve("tests/a.graph.json") == tmp_path.resolve() / "tests" / "a.graph.json"
    for bad in ("../a", "/a", "a\\b", "a//b", "./a", "C:/a", ""):
        assert ws.resolve(bad) is None, bad
    assert ws.resolve_from("targets/x/a.target.json", "../b.png") == "targets/b.png"
    assert ws.resolve_from("targets/a.target.json", "../../b.png") is None
    assert ws.resolve_from("a.target.json", "b.png") == "b.png"
