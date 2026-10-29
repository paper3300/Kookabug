import json
from pathlib import Path

import pytest

from kb_testing import packaging as pk
from kb_testing.core_nodes import CORE_NODE_TYPES

PYTHON = pk.REPO_ROOT / "python"

CHECK_INSTALLED = """\
import json, pathlib, sys
import kookabug_core, kookabug_nodes
from kookabug_core.registry import default_registry
from kookabug_core.validate import check_graph
from kookabug_core.workspace import MemorySecrets, Workspace

registry = default_registry()

root = pathlib.Path(sys.argv[1])
root.mkdir()
(root / "kookabug.json").write_text('{"format": "kookabug.workspace/0"}', encoding="utf-8")
(root / "tests").mkdir()
graph = {
    "format": "kookabug.graph/0",
    "kind": "test",
    "nodes": {
        "n_entry": {"next": {"start": "n_check"}, "type": "core.graph.entry", "version": 1},
        "n_check": {
            "in": {"a": 1, "b": "x", "op": "=="},
            "next": {"ok": "n_bad"},
            "type": "core.assert.compare",
            "version": 1,
        },
        "n_bad": {"in": {"times": "3"}, "type": "core.flow.repeat", "version": 1},
    },
    "plugins": {"core": "0.1.0"},
}
(root / "tests" / "t.graph.json").write_text(json.dumps(graph), encoding="utf-8")
_, diags = check_graph(Workspace.open(root), "tests/t.graph.json", secrets=MemorySecrets())
print(json.dumps({
    "core": kookabug_core.__file__,
    "nodes": kookabug_nodes.__file__,
    "types": sorted(registry.types()),
    "plugins": dict(registry.plugins),
    "diagnostics": [[d.code, d.pointer] for d in diags],
}))
"""


@pytest.mark.packaging
def test_default_registry_from_installed_wheels(tmp_path: Path) -> None:
    sdk = pk.build_dists(PYTHON / "kookabug_sdk", tmp_path / "dist-sdk")
    nodes = pk.build_dists(PYTHON / "kookabug_nodes", tmp_path / "dist-nodes")
    core = pk.build_dists(PYTHON / "kookabug_core", tmp_path / "dist-core")
    py = pk.make_clean_venv(tmp_path / "venv")
    pk.install(py, sdk.wheel, nodes.wheel, core.wheel)

    ws = tmp_path / "ws"
    proc = pk.run([py, "-I", "-c", CHECK_INSTALLED, str(ws)], cwd=tmp_path)
    out = json.loads(proc.stdout)

    venv = (tmp_path / "venv").resolve()
    assert Path(out["core"]).resolve().is_relative_to(venv)
    assert Path(out["nodes"]).resolve().is_relative_to(venv)
    assert len(out["types"]) == 16
    assert set(out["types"]) == CORE_NODE_TYPES
    assert out["plugins"] == {"core": "0.1.0.dev0"}
    # 설치본에서도 검증이 노드 스키마를 쓴다 (repeat.times는 int)
    assert out["diagnostics"] == [["type_mismatch", "/nodes/n_bad/in/times"]]
