"""팔레트 내보내기 (M2 계획 2.7): 노드 스키마 문서 형식 그대로."""

from __future__ import annotations

from kookabug_core import palette
from kookabug_core.registry import Registry, default_registry
from kookabug_core.schema import check_shape
from kookabug_sdk.schema import load_installed


def test_palette_is_node_schema_shape() -> None:
    docs = palette.export(default_registry())
    assert [d["plugin"]["id"] for d in docs] == ["core"]
    for doc in docs:
        assert check_shape(doc, "node-schema") == []
    # 설치된 코어 노드 스키마 파일과 같은 문서다
    assert docs[0] == load_installed("kookabug_nodes")


def test_all_core_categories_present() -> None:
    installed = load_installed("kookabug_nodes")
    [doc] = palette.export(default_registry())
    assert {n["category"] for n in doc["nodes"]} == {n["category"] for n in installed["nodes"]}
    assert [n["type"] for n in doc["nodes"]] == sorted(n["type"] for n in installed["nodes"])
    assert len(doc["nodes"]) == 38


def test_remote_plugin_exported_and_copies_are_independent() -> None:
    registry = default_registry()
    remote = {
        "format": "kookabug.nodes/0",
        "nodes": [
            {
                "category": "acme",
                "exits": [{"kind": "ok", "name": "done", "outputs": []}],
                "inputs": {},
                "outputs": {},
                "title": "원격",
                "type": "acme.remote.do",
                "version": 1,
            }
        ],
        "plugin": {"id": "acme", "title": "에이크미", "version": "1.2.3"},
    }
    registry.add_remote(remote)
    docs = palette.export(registry)
    assert [d["plugin"] for d in docs] == [
        {"id": "acme", "title": "에이크미", "version": "1.2.3"},
        load_installed("kookabug_nodes")["plugin"],
    ]
    docs[0]["nodes"][0]["title"] = "바꿈"
    assert palette.export(registry)[0]["nodes"][0]["title"] == "원격"
    assert palette.export(Registry()) == []
