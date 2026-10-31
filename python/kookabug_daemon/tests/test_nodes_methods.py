"""`nodes.list` (M2 계획 2.7, T4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_testing.daemon import ThreadDaemon, make_workspace
from kookabug_core import palette
from kookabug_core.registry import default_registry
from kookabug_core.schema import check_shape

pytestmark = pytest.mark.process


def test_nodes_list_equals_palette_export(tmp_path: Path) -> None:
    root = make_workspace(tmp_path / "ws")
    with ThreadDaemon(root) as d, d.client() as client:
        result = client.call("nodes.list")
    expected = json.loads(json.dumps(palette.export(default_registry())))
    assert result == {"schemas": expected}
    assert [s["plugin"]["id"] for s in result["schemas"]] == ["core"]
    for schema in result["schemas"]:
        assert check_shape(schema, "node-schema") == []
