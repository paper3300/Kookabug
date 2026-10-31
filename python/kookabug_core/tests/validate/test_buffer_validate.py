"""편집 버퍼 검증 `check_graph_value` (M2 계획 2.7): 루트만 메모리 값, 나머지는 디스크."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from helpers.corpus import CORPUS_DIR, SAMPLE_WORKSPACE, corpus_files, corpus_id
from helpers.graphs import GraphBuilder, make_workspace, subgraph_interface, write_json

from kookabug_core.canonical import loads_strict
from kookabug_core.registry import default_registry
from kookabug_core.validate import check_graph, check_graph_value
from kookabug_core.workspace import MemorySecrets, Workspace

REGISTRY = default_registry()
SAMPLE = SAMPLE_WORKSPACE.resolve()


def both(ws: Workspace, rel: str, secrets: MemorySecrets | None = None) -> tuple[list, list]:
    path = ws.resolve(rel)
    assert path is not None
    value = loads_strict(path.read_bytes().decode("utf-8"))
    _, from_file = check_graph(ws, rel, registry=REGISTRY, secrets=secrets)
    _, from_value = check_graph_value(ws, rel, value, registry=REGISTRY, secrets=secrets)
    return from_file, from_value


@pytest.mark.parametrize("src", corpus_files(), ids=corpus_id)
def test_same_bytes_same_diagnostics_as_check_graph(src: Path, tmp_path: Path) -> None:
    if src.is_relative_to(SAMPLE):
        # 예제 워크스페이스 그래프는 그 자리에서 (서브그래프·target·화면이 있는 실제 워크스페이스)
        ws = Workspace.open(SAMPLE)
        rel = src.relative_to(SAMPLE).as_posix()
    else:
        ws = make_workspace(tmp_path, settings={"game.title": "SampleRPG"})
        rel = f"tests/{src.name}"
        (tmp_path / "tests").mkdir()
        (tmp_path / rel).write_bytes(src.read_bytes())
    from_file, from_value = both(ws, rel)
    assert from_value == from_file


def test_buffer_overrides_root_only(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    sub = GraphBuilder("subgraph", interface=subgraph_interface()).entry("n_x").exit("n_x", "done")
    sub.write(ws, "subgraphs/s.graph.json")
    root = GraphBuilder().entry("n_call").call("n_call", "subgraphs/s.graph.json")
    root.node("n_pass", "core.test.pass")
    root.nodes["n_call"]["next"] = {"done": "n_pass"}
    rel = root.write(ws, "tests/a.graph.json")
    disk = (tmp_path / rel).read_bytes()
    _, clean = check_graph(ws, rel, registry=REGISTRY)
    assert clean == []

    buffer = copy.deepcopy(root.build())
    buffer["nodes"]["n_pass"]["in"] = {"nope": 1}
    program, diags = check_graph_value(ws, rel, buffer, registry=REGISTRY)
    assert [(d.code, d.node, d.file) for d in diags] == [("unknown_input", "n_pass", rel)]
    # 디스크는 그대로, 서브그래프는 디스크에서 읽었다
    assert (tmp_path / rel).read_bytes() == disk
    assert set(program.graphs) == {rel, "subgraphs/s.graph.json"}
    assert program.graphs[rel].nodes["n_pass"].inputs == {"nope": 1}
    # 버퍼 값을 바꿔도 프로그램은 사본을 쓴다
    buffer["nodes"]["n_pass"]["in"]["nope"] = 2
    assert program.graphs[rel].nodes["n_pass"].inputs == {"nope": 1}


def test_buffer_of_missing_file_is_validated(tmp_path: Path) -> None:
    # 아직 디스크에 없는 경로도 버퍼로 검증한다 (graph_missing 아님)
    ws = make_workspace(tmp_path)
    value = GraphBuilder().entry("n_pass").node("n_pass", "core.test.pass").build()
    _, diags = check_graph_value(ws, "tests/new.graph.json", value, registry=REGISTRY)
    assert diags == []


def test_subgraph_read_from_disk(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    sub = GraphBuilder("subgraph", interface=subgraph_interface()).entry("n_x").exit("n_x", "done")
    sub.write(ws, "subgraphs/s.graph.json")
    root = GraphBuilder().entry("n_call").call("n_call", "subgraphs/s.graph.json")
    rel = root.write(ws, "tests/a.graph.json")
    value = root.build()
    _, before = check_graph_value(ws, rel, value, registry=REGISTRY)
    assert "subgraph_missing_exit" not in {d.code for d in before}
    # 디스크의 서브그래프를 깨뜨리면 같은 버퍼의 검증 결과가 바뀐다
    write_json(ws, "subgraphs/s.graph.json", {"format": "kookabug.graph/0"})
    _, after = check_graph_value(ws, rel, value, registry=REGISTRY)
    assert any(d.file == "subgraphs/s.graph.json" for d in after)
    assert after == check_graph(ws, rel, registry=REGISTRY)[1]


def test_doc_examples_in_corpus_match_schema_doc() -> None:
    # 말뭉치의 문서 예시는 문서 블록 원문과 같아야 한다 (문서를 고치면 말뭉치도 다시 만든다)
    from kb_testing.doc_examples import json_blocks

    blocks = {
        b.data.get("kind"): b.text
        for b in json_blocks()
        if b.data.get("format") == "kookabug.graph/0"
    }
    assert (CORPUS_DIR / "doc-enter-world.graph.json").read_text(encoding="utf-8") == blocks[
        "subgraph"
    ]
    assert (CORPUS_DIR / "doc-inventory-open.graph.json").read_text(encoding="utf-8") == blocks[
        "test"
    ]


def test_corpus_manifest_lists_every_file() -> None:
    listed = {p.resolve() for p in corpus_files()}
    on_disk = {p.resolve() for p in CORPUS_DIR.glob("*.graph.json")}
    on_disk |= {p.resolve() for p in SAMPLE.rglob("*.graph.json")}
    assert listed == on_disk
