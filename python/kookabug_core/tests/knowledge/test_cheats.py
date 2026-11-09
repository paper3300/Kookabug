"""치트 구현 그래프의 참조 폐포 digest (계획 9장 R2)."""

from __future__ import annotations

import shutil
from pathlib import Path

from kb_testing.packaging import REPO_ROOT
from kookabug_core.knowledge.cheats import graph_closure
from kookabug_core.workspace import Workspace

SAMPLE = REPO_ROOT / "fixtures" / "sample-game" / "workspace"


def test_closure_covers_subgraphs_targets_and_images(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    shutil.copytree(SAMPLE, root)
    ws = Workspace.open(root)
    first = graph_closure(ws, "tests/inventory_open.graph.json")
    assert "subgraphs/enter_world.graph.json" in first.files
    assert any(p.endswith(".target.json") for p in first.files)
    assert any(p.endswith(".png") for p in first.files)
    assert first.nodes and graph_closure(ws, "tests/inventory_open.graph.json") == first
    # 서브그래프가 쓰는 PNG 한 바이트만 바뀌어도 digest가 바뀐다
    png = next(p for p in first.files if p.endswith(".png") and first.files[p])
    path = root / png
    path.write_bytes(path.read_bytes() + b"\0")
    assert graph_closure(ws, "tests/inventory_open.graph.json").digest != first.digest
