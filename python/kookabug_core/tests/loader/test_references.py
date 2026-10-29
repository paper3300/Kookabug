"""로더의 참조 발견: `discovered`는 없는·깨진 파일, 깊이 한도 밖 서브그래프까지 담는다 (M0b 2.8)."""

from pathlib import Path

from helpers.graphs import (
    GraphBuilder,
    make_workspace,
    subgraph_interface,
    target,
    write_target,
)

from kookabug_core.loader import MAX_CALL_DEPTH, Program, load_program
from kookabug_core.workspace import MemorySecrets, Workspace

TEST = "tests/t.graph.json"


def load(ws: Workspace, rel: str = TEST) -> Program:
    return load_program(ws, rel, secrets=MemorySecrets())


def calling(*callees: str, kind: str = "test") -> GraphBuilder:
    """entry → 호출들을 차례로 → (테스트면 pass, 서브그래프면 exit)."""
    iface = subgraph_interface() if kind == "subgraph" else None
    g = GraphBuilder(kind, interface=iface)
    ids = [f"n_call{i}" for i in range(len(callees))]
    g.entry(ids[0] if ids else "n_end")
    for i, (node, callee) in enumerate(zip(ids, callees, strict=True)):
        nxt = ids[i + 1] if i + 1 < len(ids) else "n_end"
        g.call(node, callee, next={"done": nxt})
    if kind == "subgraph":
        return g.exit("n_end", "done")
    return g.node("n_end", "core.test.pass")


def using(*targets: str) -> GraphBuilder:
    g = GraphBuilder().entry("n_set")
    return g.node(
        "n_set",
        "core.var.set",
        inputs={"name": "v", "value": [target(t) for t in targets]},
        next={"done": "n_pass"},
    ).node("n_pass", "core.test.pass")


def test_discovered_includes_missing_subgraph(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    calling("subgraphs/none.graph.json", "../outside.graph.json").write(ws, TEST)
    refs = load(ws).references
    assert refs.discovered == {TEST, "subgraphs/none.graph.json"}
    assert "subgraphs/none.graph.json" not in refs.graphs


def test_discovered_includes_missing_target(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_target(ws, "targets/ok.target.json")
    using("targets/none.target.json", "targets/ok.target.json", "../out.target.json").write(
        ws, TEST
    )
    refs = load(ws).references
    assert refs.discovered == {
        TEST,
        "targets/none.target.json",
        "targets/ok.target.json",
        "targets/ok.png",
    }
    assert refs.targets == {"targets/ok.target.json"}


def test_discovered_includes_missing_image(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_target(ws, "targets/a.target.json", image="../img/a.png", create_image=False)
    using("targets/a.target.json").write(ws, TEST)
    refs = load(ws).references
    assert "img/a.png" in refs.discovered
    assert refs.images == set()
    assert refs.targets == {"targets/a.target.json"}


def test_discovered_includes_broken_subgraph(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    (tmp_path / "subgraphs").mkdir()
    (tmp_path / "subgraphs" / "bad.graph.json").write_text("{", "utf-8")
    write_target(ws, "targets/bad.target.json")
    (tmp_path / "targets" / "bad.target.json").write_text("{", "utf-8")
    g = calling("subgraphs/bad.graph.json")
    g.node(
        "n_end", "core.var.set", inputs={"name": "v", "value": target("targets/bad.target.json")}
    )
    g.write(ws, TEST)
    program = load(ws)
    refs = program.references
    assert {"subgraphs/bad.graph.json", "targets/bad.target.json"} <= refs.discovered
    assert program.broken == {"subgraphs/bad.graph.json"}


def test_discovered_includes_unloaded_beyond_depth_limit(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    n = MAX_CALL_DEPTH + 3
    for i in range(1, n):
        calling(f"subgraphs/c{i + 1}.graph.json", kind="subgraph").write(
            ws, f"subgraphs/c{i}.graph.json"
        )
    calling("subgraphs/c1.graph.json").write(ws, TEST)
    program = load(ws)
    beyond = f"subgraphs/c{MAX_CALL_DEPTH + 2}.graph.json"
    last_read = f"subgraphs/c{MAX_CALL_DEPTH + 1}.graph.json"
    assert program.calls[(last_read, "n_call0")].status == "unloaded"
    assert beyond in program.references.discovered
    assert beyond not in program.references.graphs
    # 한도 밖 그래프가 부르는 것은 읽지 않았으니 발견하지도 않는다
    assert f"subgraphs/c{MAX_CALL_DEPTH + 3}.graph.json" not in program.references.discovered


def test_read_sets_unchanged(tmp_path: Path) -> None:
    # graphs·targets·images는 있는 파일만 (M0a 의미 그대로). discovered는 그 상위 집합
    ws = make_workspace(tmp_path)
    write_target(ws, "targets/a.target.json")
    write_target(ws, "targets/noimg.target.json", create_image=False)
    g = GraphBuilder("subgraph", interface=subgraph_interface()).entry("n_set")
    g.node(
        "n_set",
        "core.var.set",
        inputs={
            "name": "v",
            "value": [
                target("targets/a.target.json"),
                target("targets/noimg.target.json"),
                target("targets/none.target.json"),
            ],
        },
        next={"done": "n_exit"},
    ).exit("n_exit", "done").write(ws, "subgraphs/s.graph.json")
    calling("subgraphs/s.graph.json", "subgraphs/none.graph.json").write(ws, TEST)

    refs = load(ws).references
    assert refs.graphs == {TEST, "subgraphs/s.graph.json"}
    assert refs.targets == {"targets/a.target.json", "targets/noimg.target.json"}
    assert refs.images == {"targets/a.png"}
    assert refs.all() == sorted(refs.graphs | refs.targets | refs.images)
    assert refs.discovered == set(refs.all()) | {
        "subgraphs/none.graph.json",
        "targets/none.target.json",
        "targets/noimg.png",
    }
