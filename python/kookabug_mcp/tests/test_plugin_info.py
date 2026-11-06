"""MCP와 플러그인 (M6 계획 3.8·3.9, B4): 설치·제거·준비 도구는 없고(툴셋을 다 켜도), 노드 찾기·
프로젝트 정보에 설치 플러그인의 ID·권한·환경 상태가 보인다. 실제 `kookabug mcp` 하위 프로세스."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from helpers.plugins import Rig, plugin_world, rig

from kb_testing.daemon import ThreadDaemon, daemon_env
from kb_testing.mcp_client import McpClient
from kb_testing.proc import Spawned
from kookabug_core.permissions import TOOLSETS

__all__ = ["plugin_world", "rig"]

pytestmark = [pytest.mark.packaging, pytest.mark.process, pytest.mark.timeout(600)]

CHANGING: re.Pattern[str] = re.compile(r"plugin|install|uninstall|sync|relock|gc|upgrade")


def test_no_install_tool_and_node_search_shows_plugin(
    rig: Rig, spawned: Spawned, tmp_path: Path
) -> None:
    rig.add("sample")
    lock = rig.lock_bytes()
    with ThreadDaemon(
        rig.root,
        environ={"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")},
        agent_toolsets=("core",),
        plugin_environ=rig.world.environ,
    ):
        mcp = McpClient.start(spawned, rig.root, tmp_path / "mcp", env=daemon_env(tmp_path))
        try:
            mcp.initialize()
            mcp.data("kb_toolset_enable", {"toolsets": [t for t in TOOLSETS if t != "core"]})
            names = mcp.tool_names()
            assert names and not [n for n in names if CHANGING.search(n)], names
            found = mcp.data("kb_node_search", {"query": "sample."})["nodes"]
            by_type = {n["type"]: n for n in found}
            reverse = by_type["sample.text.reverse"]
            assert reverse["plugin"] == "sample"
            assert reverse["plugin_permissions"] == ["capture"]
            assert reverse["plugin_env_status"] == "ready"
            assert by_type["sample.window.title"]["effects"] == ["capture"]
            # 코어 노드에는 플러그인 권한·환경 상태가 없다
            core = mcp.data("kb_node_search", {"query": "core.test.pass"})["nodes"][0]
            assert "plugin_env_status" not in core
            info = mcp.data("kb_project_info")
            assert info["installed_plugins"] == [
                {"id": "sample", "version": "0.1.0", "title": "Sample",
                 "permissions": ["capture"], "env": "shared", "env_status": "ready"}
            ]  # fmt: skip
            assert info["plugin_stale_reason"] is None
            assert mcp.close() == 0
        finally:
            mcp.__exit__(None, None, None)
    assert rig.lock_bytes() == lock
