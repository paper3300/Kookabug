"""MCP 서버 기본 (M5 계획 D1·3.2·3.3, B1): 판 협상, 기본 core 툴셋, 툴셋 켜기, 도구 표."""

from __future__ import annotations

import queue
from collections.abc import Callable
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from kb_testing.daemon import ThreadDaemon, daemon_env
from kb_testing.mcp_client import McpClient, McpError
from kb_testing.proc import Spawned
from kookabug_core.permissions import TOOLS
from kookabug_mcp.server import PROTOCOL_VERSIONS, negotiate
from kookabug_mcp.tools import TOOL_DEFS

pytestmark = pytest.mark.process

type Start = Callable[..., McpClient]

CORE = {name for name, info in TOOLS.items() if info.toolset == "core"}
GRAPH_EDIT = {name for name, info in TOOLS.items() if info.toolset == "graph_edit"}


def test_initialize_and_list_core_only(daemon: ThreadDaemon, start_mcp: Start) -> None:
    mcp = start_mcp()
    result = mcp.initialize("2025-03-26")
    assert result["protocolVersion"] == "2025-03-26"
    assert result["capabilities"]["tools"] == {"listChanged": True}
    assert result["serverInfo"]["name"] == "kookabug"
    assert mcp.request("ping")["result"] == {}
    assert set(mcp.tool_names()) == CORE
    # 모르는 판은 최신 판으로 답한다
    other = start_mcp()
    assert other.initialize("1999-01-01")["protocolVersion"] == PROTOCOL_VERSIONS[0]
    assert negotiate("2024-11-05") == "2024-11-05"
    # 모르는 메서드·도구·입력 형식 틀림만 JSON-RPC 오류
    with pytest.raises(McpError) as caught:
        mcp.request("resources/list")
    assert caught.value.code == -32601
    with pytest.raises(McpError) as caught:
        mcp.request("tools/call", {"name": "kb_nope", "arguments": {}})
    assert caught.value.code == -32602
    with pytest.raises(McpError) as caught:
        mcp.request("tools/call", {"name": "kb_graph_get", "arguments": {"path": 3}})
    assert caught.value.code == -32602
    info = mcp.data("kb_project_info")
    assert {t["name"]: t["enabled"] for t in info["toolsets"]}["core"] is True
    assert {t["name"]: t["enabled"] for t in info["toolsets"]}["graph_edit"] is False
    assert mcp.close() == 0
    assert other.close() == 0
    # stdout에는 프로토콜 메시지만 (로그는 stderr)
    mcp.assert_protocol_only()
    other.assert_protocol_only()
    assert mcp.lines, "응답을 받지 못했다"


def test_toolset_enable_lists_more_and_notifies(daemon: ThreadDaemon, start_mcp: Start) -> None:
    mcp = start_mcp()
    mcp.initialize()
    # 꺼진 툴셋 도구는 daemon이 판정 전에 거부한다 (isError)
    error = mcp.error("kb_graph_create", {"path": "tests/x.graph.json", "kind": "test"})
    assert error["code"] == "toolset_disabled"
    assert error["toolset"] == "graph_edit"
    with pytest.raises(queue.Empty):
        mcp.notifications.get(timeout=0.2)

    enabled = mcp.data("kb_toolset_enable", {"toolsets": ["graph_edit"]})
    assert enabled["enabled"] == ["core", "graph_edit"]
    assert set(enabled["tools"]) == GRAPH_EDIT
    note = mcp.notifications.get(timeout=10)
    assert note["method"] == "notifications/tools/list_changed"
    assert set(mcp.tool_names()) == CORE | GRAPH_EDIT
    # 같은 툴셋을 다시 켜면 바뀐 것이 없다 (알림 없음)
    again = mcp.data("kb_toolset_enable", {"toolsets": ["graph_edit"]})
    assert again["tools"] == []
    with pytest.raises(queue.Empty):
        mcp.notifications.get(timeout=0.5)
    # daemon도 이 연결의 툴셋을 안다
    [agent] = [c for c in daemon.daemon.transport.connections if c.client_kind == "agent"]
    assert agent.toolsets == frozenset({"core", "graph_edit"})
    assert mcp.close() == 0
    mcp.assert_protocol_only()


def test_reconnects_after_daemon_restart_with_toolsets(
    ws: Path, environ: dict[str, str], start_mcp: Start
) -> None:
    # daemon이 바뀌면 다음 호출에서 한 번 다시 붙고, 켜 둔 툴셋을 다시 켠다 (3.1)
    with ThreadDaemon(ws, environ=environ, agent_toolsets=("core",)):
        mcp = start_mcp("--agent-id", "agent-r")
        mcp.initialize()
        mcp.data("kb_toolset_enable", {"toolsets": ["graph_edit"]})
    with ThreadDaemon(ws, environ=environ, agent_toolsets=("core",)) as second:
        info = mcp.data("kb_project_info")
        assert info["principal"]["id"] == "agent-r"
        assert {t["name"]: t["enabled"] for t in info["toolsets"]}["graph_edit"] is True
        [agent] = [c for c in second.daemon.transport.connections if c.client_kind == "agent"]
        assert agent.toolsets == frozenset({"core", "graph_edit"})
    assert mcp.close() == 0
    mcp.assert_protocol_only()


def test_no_workspace_exits_6_without_stdout(tmp_path: Path, spawned: Spawned) -> None:
    mcp = McpClient.start(spawned, tmp_path / "none", tmp_path / "out", env=daemon_env(tmp_path))
    assert mcp.close() == 6
    assert mcp.lines == []
    assert "kookabug.json" in mcp.stderr()


def test_tool_definitions_match_permissions_table() -> None:
    # 권한 표의 도구와 MCP 정의가 1:1 (M7: kb_screen_save까지), 툴셋·조회/변경이 같다
    defined = {d.name: d for d in TOOL_DEFS}
    assert len(defined) == len(TOOL_DEFS)
    assert set(defined) == set(TOOLS)
    for name, tool in defined.items():
        assert tool.toolset == TOOLS[name].toolset
        assert tool.read_only is (not TOOLS[name].mutating)
        Draft202012Validator.check_schema(tool.input_schema)
        assert tool.input_schema["type"] == "object"
        assert "$ref" not in str(tool.input_schema), name  # 클라이언트에는 참조 없는 스키마
        listing = tool.listing()
        assert listing["annotations"]["readOnlyHint"] is tool.read_only
