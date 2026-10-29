"""`core.test.*` 종료 노드의 `reason` (`string|secret`, P12)."""

from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder, check, make_workspace, secret
from helpers.run import run_graph

from kookabug_sdk.schema import load_installed

TERMINALS = {"core.test.pass": "pass", "core.test.fail": "fail", "core.test.skip": "skipped"}


@pytest.fixture(scope="module")
def nodes() -> dict[str, dict[str, Any]]:
    return {n["type"]: n for n in load_installed("kookabug_nodes")["nodes"]}


@pytest.mark.parametrize("node_type", sorted(TERMINALS))
def test_test_reason_accepts_secret(
    node_type: str, nodes: dict[str, dict[str, Any]], tmp_path: Path
) -> None:
    node = nodes[node_type]
    assert node["version"] == 1  # 받는 값만 넓혔다 (그래프 호환)
    assert node["inputs"]["reason"] == {"default": None, "nullable": True, "type": "string|secret"}

    ws = make_workspace(tmp_path)
    g = GraphBuilder().entry("n_end").node("n_end", node_type, inputs={"reason": secret("pw")})
    assert check(ws, g.write(ws, "tests/t.graph.json"), secrets={"pw": "x"}) == []


@pytest.mark.parametrize(("node_type", "verdict"), sorted(TERMINALS.items()))
def test_secret_reason_masked_in_verdict_and_events(
    node_type: str, verdict: str, tmp_path: Path
) -> None:
    g = GraphBuilder().entry("n_end").node("n_end", node_type, inputs={"reason": secret("pw")})
    ran = run_graph(make_workspace(tmp_path), g, secrets={"pw": "hunter2"})
    r = ran.result
    assert (r.verdict, r.reason) == (verdict, "***")
    assert "hunter2" not in repr(r)
    assert "hunter2" not in repr(ran.events)
