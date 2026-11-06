"""`kb_project_info` (M5 계획 3.3·3.12, B3): `AGENTS.md` 관리 구간과 이 연결의 도구별 판정 요약.

판정 요약은 `permissions.get`(kb_project_info로 판정)에서 온다 — 다른 도구로 판정되는 메서드를
부르지 않는다(`test_tool_permissions`).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.mcp_client import McpClient
from kookabug_core.workspace import AGENTS_SECTION

pytestmark = pytest.mark.process


def test_project_info_agents_md_and_decisions(
    ws: Path, daemon: ThreadDaemon, start_mcp: Callable[..., McpClient]
) -> None:
    mcp = start_mcp("--unattended")
    mcp.initialize()
    info = mcp.data("kb_project_info")
    assert info["agents_md"] == AGENTS_SECTION.strip("\n")
    # 기본 프리셋(graph_author) · 사람 없음: ask는 deny로 집행된다
    assert info["permissions"]["kb_graph_get"] == "allow"
    assert info["permissions"]["kb_graph_patch"] == "deny"
    assert info["permissions"]["kb_input_click"] == "deny"
    assert "kb_screen_save" not in info["permissions"]
    # 정책을 바꾸면 다음 호출부터 반영
    local = ws / ".kookabug" / "local.json"
    local.parent.mkdir(exist_ok=True)
    body = {"format": "kookabug.local/0", "permissions": {"preset": "full"}}
    local.write_text(json.dumps(body), encoding="utf-8")
    assert mcp.data("kb_project_info")["permissions"]["kb_input_click"] == "allow"
    assert mcp.close() == 0
