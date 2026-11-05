"""`kookabug mcp` → daemon 주체 전달 (M5 계획 3.1·D5, 완료 기준 3, B1).

daemon이 본 주체 = `--agent-id`·`--unattended` 그대로. CLI의 `KOOKABUG_AGENT`는 늘 사람 없음이므로
같은 판정 비교는 MCP `--unattended`와 한다.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.mcp_client import McpClient
from kookabug_core.permissions import Principal
from kookabug_core.service import WorkspaceService, cli_principal

pytestmark = pytest.mark.process

type Start = Callable[..., McpClient]

GRAPH = "tests/inventory_open.graph.json"


def seen(daemon: ThreadDaemon) -> dict[str, tuple[Principal, str]]:
    """daemon 연결의 (주체, client.name) — 주체 ID별."""
    out: dict[str, tuple[Principal, str]] = {}
    for conn in daemon.daemon.transport.connections:
        if conn.principal is not None and conn.principal.kind == "agent":
            out[conn.principal.id] = (conn.principal, conn.client_name)
    return out


def test_mcp_passes_agent_id_and_attended(
    ws: Path, environ: dict[str, str], daemon: ThreadDaemon, start_mcp: Start
) -> None:
    panel = start_mcp("--agent-id", "panel:s1", "--client", "panel")
    ci = start_mcp("--agent-id", "ci-1", "--unattended")
    default = start_mcp()
    for mcp in (panel, ci, default):
        mcp.initialize()
    infos = {name: m.data("kb_project_info")["principal"] for name, m in
             (("panel", panel), ("ci", ci), ("default", default))}  # fmt: skip
    assert infos["panel"] == {"kind": "agent", "id": "panel:s1", "attended": True}
    assert infos["ci"] == {"kind": "agent", "id": "ci-1", "attended": False}
    assert infos["default"] == {
        "kind": "agent",
        "id": f"mcp:{default.proc.pid}",
        "attended": True,
    }
    connections = seen(daemon)
    assert connections["panel:s1"] == (Principal("agent", "panel:s1", attended=True), "panel")
    assert connections["ci-1"] == (Principal("agent", "ci-1", attended=False), "mcp")
    # CLI KOOKABUG_AGENT 주체 = MCP --unattended 주체 → 같은 판정
    cli = cli_principal({"KOOKABUG_AGENT": "ci-1"})
    assert cli == connections["ci-1"][0]
    expected = WorkspaceService(ws, environ=environ).authorize(cli, "kb_graph_patch", GRAPH)
    ci.data("kb_toolset_enable", {"toolsets": ["graph_edit"]})
    base = ci.data("kb_graph_get", {"path": GRAPH})["revision"]
    error = ci.error(
        "kb_graph_patch",
        {"path": GRAPH, "base_revision": base, "ops": [{"op": "set_meta", "title": "x"}]},
    )
    assert error["decision"] == expected.to_dict()
    for mcp in (panel, ci, default):
        assert mcp.close() == 0
