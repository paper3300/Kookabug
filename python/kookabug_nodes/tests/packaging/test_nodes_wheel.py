import json
from pathlib import Path

import pytest

from kb_testing import packaging as pk
from kb_testing.core_nodes import CORE_NODE_MODULES, CORE_NODE_TYPES

PYTHON = pk.REPO_ROOT / "python"
SCHEMA = "kookabug_nodes/kookabug.schema.json"

LOAD = f"""\
import importlib, json
import kookabug_nodes
from kookabug_sdk import NodeFunction
from kookabug_sdk.schema import load_installed

schema = load_installed("kookabug_nodes")
functions = sorted(
    v.spec.type
    for m in {list(CORE_NODE_MODULES)!r}
    for v in vars(importlib.import_module(m)).values()
    if isinstance(v, NodeFunction)
)
print(json.dumps({{
    "module": kookabug_nodes.__file__,
    "types": [n["type"] for n in schema["nodes"]],
    "functions": functions,
    "schema": schema,
}}))
"""


@pytest.fixture(scope="module")
def dists(tmp_path_factory: pytest.TempPathFactory) -> tuple[pk.Dists, pk.Dists, Path]:
    root = tmp_path_factory.mktemp("nodes-wheel")
    pk.assert_outside_repo(root)
    sdk = pk.build_dists(PYTHON / "kookabug_sdk", root / "dist-sdk")
    nodes = pk.build_dists(PYTHON / "kookabug_nodes", root / "dist-nodes")
    return sdk, nodes, root


@pytest.mark.packaging
def test_nodes_wheel_and_sdist_build(dists: tuple[pk.Dists, pk.Dists, Path]) -> None:
    _, nodes, _ = dists
    assert nodes.wheel.name.startswith("kookabug_nodes-")
    wheel_files = nodes.wheel_files()
    for module in ("__init__", *(m.rsplit(".", 1)[1] for m in CORE_NODE_MODULES)):
        assert f"kookabug_nodes/{module}.py" in wheel_files
    assert not [f for f in wheel_files if "__pycache__" in f or "/tests/" in f]
    sdist_files = nodes.sdist_files()
    assert [f for f in sdist_files if f.endswith("/src/kookabug_nodes/kookabug.schema.json")]
    assert [f for f in sdist_files if f.endswith("/pyproject.toml")]


@pytest.mark.packaging
def test_nodes_wheel_contains_schema_json(dists: tuple[pk.Dists, pk.Dists, Path]) -> None:
    _, nodes, _ = dists
    assert SCHEMA in nodes.wheel_files()


@pytest.mark.packaging
def test_installed_schema_loads_outside_repo(dists: tuple[pk.Dists, pk.Dists, Path]) -> None:
    sdk, nodes, root = dists
    py = pk.make_clean_venv(root / "venv")
    pk.install(py, sdk.wheel, nodes.wheel)
    out = json.loads(pk.run_isolated(py, LOAD, cwd=root).stdout)

    assert Path(out["module"]).resolve().is_relative_to((root / "venv").resolve())
    assert len(out["types"]) == 16
    assert set(out["types"]) == CORE_NODE_TYPES
    assert out["functions"] == sorted(CORE_NODE_TYPES)
    committed = json.loads((PYTHON / "kookabug_nodes" / "src" / SCHEMA).read_text("utf-8"))
    assert out["schema"] == committed
