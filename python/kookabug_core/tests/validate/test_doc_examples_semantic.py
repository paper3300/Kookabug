"""설계 문서 예시 그래프의 의미 검증 (스키마 v0 1장 `enter_world`, 3장 `inventory_open`).

문서의 ```json 블록을 꺼내 임시 워크스페이스에 그대로 쓰고 실행 전 검증 전체를 돌린다.
- 참조하는 target 파일은 문서의 target 예시(4장)로 채운다 (이미지는 각 target 옆에 만든다)
- `kookabug.json`은 워크스페이스 문서 예시 그대로(`game.executable`이 `null`), `local.json`에
  실행 경로
- `$secret`은 메모리 비밀값, M1 노드는 선언만 한 스텁(`fixtures.doc_examples.stub_nodes`)
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fixtures.doc_examples.stub_nodes import registry_with_stubs
from helpers.graphs import check, check_program, write_json

from kb_testing.doc_examples import json_blocks
from kookabug_core.diagnostics import Diagnostic
from kookabug_core.validate.context import ValidationContext
from kookabug_core.workspace import LOCAL_FILE, WORKSPACE_FILE, Workspace

ENTER_WORLD = "subgraphs/enter_world.graph.json"
INVENTORY_OPEN = "tests/inventory_open.graph.json"
SECRETS = {"accounts.qa_tester_01": "hunter2"}
EXECUTABLE = "D:/Games/SampleRPG/SampleRPG.exe"


def doc(format: str, kind: str | None = None) -> dict[str, Any]:
    found = [
        b.data
        for b in json_blocks()
        if b.data.get("format") == format and (kind is None or b.data.get("kind") == kind)
    ]
    assert len(found) == 1, (format, kind)
    return found[0]


def target_refs(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        if set(value) == {"$target"}:
            yield value["$target"]
        else:
            for v in value.values():
                yield from target_refs(v)
    elif isinstance(value, list):
        for v in value:
            yield from target_refs(v)


def doc_workspace(root: Path, *, executable: str | None = EXECUTABLE) -> Workspace:
    subgraph = doc("kookabug.graph/0", "subgraph")
    test = doc("kookabug.graph/0", "test")
    target = doc("kookabug.target/0")
    write_json(root, WORKSPACE_FILE, doc("kookabug.workspace/0"))
    if executable is not None:
        local = {"format": "kookabug.local/0", "settings": {"game.executable": executable}}
        write_json(root, LOCAL_FILE, local)
    for rel in sorted({*target_refs(subgraph), *target_refs(test)}):
        path = write_json(root, rel, target)
        (path.parent / target["image"]).write_bytes(b"\x89PNG\r\n\x1a\n")
    write_json(root, ENTER_WORLD, subgraph)
    write_json(root, INVENTORY_OPEN, test)
    return Workspace.open(root)


def run(ws: Workspace, rel: str) -> list[Diagnostic]:
    return check(ws, rel, registry=registry_with_stubs(), secrets=SECRETS)


def test_enter_world_validates_without_errors(tmp_path: Path) -> None:
    assert run(doc_workspace(tmp_path), ENTER_WORLD) == []


def test_inventory_open_validates_without_errors(tmp_path: Path) -> None:
    # 테스트에서 시작하면 부르는 서브그래프까지 같이 검증한다
    ws = doc_workspace(tmp_path)
    program, diags = check_program(
        ws, INVENTORY_OPEN, registry=registry_with_stubs(), secrets=SECRETS
    )
    assert sorted(program.graphs) == [ENTER_WORLD, INVENTORY_OPEN]
    assert diags == []


def test_inventory_open_unconnected_login_failed_is_not_a_validation_error(tmp_path: Path) -> None:
    # login_failed(fail)는 연결하지 않았다 → 실행 때 처리되지 않은 실패(판정 2행)일 뿐
    # 검증 오류가 아니다
    ws = doc_workspace(tmp_path)
    registry = registry_with_stubs()
    program, diags = check_program(ws, INVENTORY_OPEN, registry=registry, secrets=SECRETS)
    graph = program.graphs[INVENTORY_OPEN]
    call = graph.nodes["n_enter_world"]
    pins = ValidationContext(program, registry).pins(graph, call)
    assert pins is not None and pins.exits is not None
    assert {name: e.kind for name, e in pins.exits.items()} == {
        "login_failed": "fail",
        "maintenance": "fail",
        "success": "ok",
    }
    assert "login_failed" not in call.next
    assert [d for d in diags if d.node == "n_enter_world"] == []
    assert diags == []


def test_missing_local_setting_reports_hint(tmp_path: Path) -> None:
    # 문서 예시 그대로(kookabug.json의 game.executable = null, local.json 없음)면
    # 오류 + 넣을 곳 안내
    ws = doc_workspace(tmp_path, executable=None)
    diags = run(ws, INVENTORY_OPEN)
    assert [(d.code, d.severity, d.file, d.node, d.pointer) for d in diags] == [
        ("setting_null", "error", ENTER_WORLD, "n_launch", "/nodes/n_launch/in/path")
    ]
    assert str(ws.local_path) in diags[0].message
    assert '"game.executable"' in diags[0].message
