import json
from pathlib import Path

import pytest

from kb_testing import packaging as pk
from kookabug_core.schema import KINDS

PYTHON = pk.REPO_ROOT / "python"

CHECK_INSTALLED = """\
import json
from importlib import resources
import kookabug_core
from kookabug_core.schema import check_shape
from kookabug_core.schema.models.graph import Graph

graph = {
    "format": "kookabug.graph/0",
    "kind": "test",
    "nodes": {
        "n_entry": {"next": {"start": "n_pass"}, "type": "core.graph.entry", "version": 1},
        "n_pass": {"in": {"x": {"$link": "n_entry.a"}}, "type": "core.test.pass", "version": 1},
    },
    "plugins": {"core": "0.1.0"},
}
bad = json.loads(json.dumps(graph))
bad["nodes"]["n_pass"]["in"]["x"] = {"$foo": 1}
bad["nodes"]["n_pass"]["oops"] = 1
print(json.dumps({
    "module": kookabug_core.__file__,
    "schemas": str(resources.files("kookabug_core.schema").joinpath("json")),
    "valid": [d.to_dict() for d in check_shape(graph)],
    "invalid": sorted(d.code for d in check_shape(bad)),
    "model": Graph.model_validate(graph).nodes["n_pass"].in_,
}))
"""


@pytest.mark.packaging
def test_core_wheel_contains_metaschemas_and_shape_check_works_installed(tmp_path: Path) -> None:
    sdk = pk.build_dists(PYTHON / "kookabug_sdk", tmp_path / "dist-sdk")
    nodes = pk.build_dists(PYTHON / "kookabug_nodes", tmp_path / "dist-nodes")
    core = pk.build_dists(PYTHON / "kookabug_core", tmp_path / "dist-core")

    files = core.wheel_files()
    for kind in KINDS:
        assert f"kookabug_core/schema/json/{kind}.schema.json" in files
        assert f"kookabug_core/schema/models/{kind.replace('-', '_')}.py" in files
    assert "kookabug_core/schema/shape.py" in files
    assert not [f for f in files if "__pycache__" in f]

    py = pk.make_clean_venv(tmp_path / "venv")
    pk.install(py, sdk.wheel, nodes.wheel, core.wheel)
    out = json.loads(pk.run_isolated(py, CHECK_INSTALLED, cwd=tmp_path).stdout)

    venv = (tmp_path / "venv").resolve()
    assert Path(out["module"]).resolve().is_relative_to(venv)
    assert Path(out["schemas"]).resolve().is_relative_to(venv)
    assert out["valid"] == []
    assert out["invalid"] == ["special_value_unknown", "unknown_field"]
    assert out["model"] == {"x": {"$link": "n_entry.a"}}
