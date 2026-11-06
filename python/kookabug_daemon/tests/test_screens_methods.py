"""화면 지도 조회 집행 (M5 계획 3.5 H4, B2).

화면 지도(`screens/`)는 screens 툴셋 도구(`kb_screen_list`·`kb_screen_get`)로만 판정한다. agent
연결이 `workspace.tree`·`workspace.read`(kb_project_info로 판정)로 돌아가 screens를 막은 정책을
피하지 못한다. 직접 RPC와 실제 `kookabug mcp` 둘 다 본다.
"""

from __future__ import annotations

import json
import queue
import time
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon, copy_sample_workspace, daemon_env
from kb_testing.mcp_client import McpClient
from kb_testing.proc import Spawned
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = pytest.mark.process

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-9", "attended": True}
SCREEN = "screens/login.screen.json"


def write_policy(root: Path, permissions: dict[str, Any]) -> None:
    path = root / ".kookabug" / "local.json"
    path.parent.mkdir(exist_ok=True)
    body = {"format": "kookabug.local/0", "permissions": permissions}
    path.write_text(json.dumps(body), encoding="utf-8")


def kind(client: DaemonClient, method: str, params: dict[str, Any]) -> str:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params)
    return str(caught.value.kind)


def no_screens_by_workspace(agent: DaemonClient) -> None:
    """agent의 workspace.tree에 screens/가 없고 workspace.read로 읽지 못한다 (어느 정책이든)."""
    entries = agent.call("workspace.tree")["entries"]
    assert entries and not [e for e in entries if e["path"].casefold().startswith("screens")]
    assert kind(agent, "workspace.read", {"path": SCREEN}) == "permission_denied"
    assert kind(agent, "workspace.read", {"path": "Screens/login.screen.json"}) == (
        "permission_denied"
    )


def test_screens_enforced_direct_rpc_and_mcp(tmp_path: Path, spawned: Spawned) -> None:
    root = copy_sample_workspace(tmp_path / "ws")
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")}
    with ThreadDaemon(root, environ=environ, agent_toolsets=("core",)) as d:
        with d.client() as ui:
            # 사람(UI)은 그대로 본다
            assert any(e["path"] == SCREEN for e in ui.call("workspace.tree")["entries"])
            assert "detect" in ui.call("workspace.read", {"path": SCREEN})["text"]

        # 1) 툴셋 꺼짐: screens.*는 toolset_disabled, workspace 길로도 못 본다, core는 그대로
        with d.client(AGENT) as agent:
            assert kind(agent, "screens.list", {}) == "toolset_disabled"
            assert kind(agent, "screens.get", {"path": SCREEN}) == "toolset_disabled"
            no_screens_by_workspace(agent)
            assert agent.call("workspace.info")["root"]

            # 2) 켜고 기본 정책(조회 allow): 전용 메서드로만 읽는다
            agent.call("agent.toolsets.enable", {"toolsets": ["screens"]})
            listed = agent.call("screens.list", {})["screens"]
            assert {"path": SCREEN, "id": "login"}.items() <= next(
                s for s in listed if s["path"] == SCREEN
            ).items()
            got = agent.call("screens.get", {"path": SCREEN})
            assert got["path"] == SCREEN and "detect" in got["value"]
            # screens.get은 screens/ 밖 파일을 읽지 않는다 (다른 파일을 읽는 길이 아님)
            with pytest.raises(DaemonError) as caught:
                agent.call("screens.get", {"path": "tests/inventory_open.graph.json"})
            assert caught.value.code == -32602
            no_screens_by_workspace(agent)

        # 3) screens 툴셋 deny: 조회도 막힌다, workspace 길도 막혀 있다
        write_policy(root, {"preset": "full", "toolsets": {"screens": "deny"}})
        with d.client(AGENT) as agent:
            agent.call("agent.toolsets.enable", {"toolsets": ["screens"]})
            assert kind(agent, "screens.list", {}) == "permission_denied"
            assert kind(agent, "screens.get", {"path": SCREEN}) == "permission_denied"
            no_screens_by_workspace(agent)
            assert agent.call("workspace.info")["root"]  # core는 allow

        # 4) kb_screen_get만 명시 deny: 목록은 되고 내용은 안 된다
        write_policy(
            root, {"preset": "full", "rules": [{"rule": "kb_screen_get", "verdict": "deny"}]}
        )
        with d.client(AGENT) as agent:
            agent.call("agent.toolsets.enable", {"toolsets": ["screens"]})
            assert agent.call("screens.list", {})["screens"]
            assert kind(agent, "screens.get", {"path": SCREEN}) == "permission_denied"
            no_screens_by_workspace(agent)

        # 5) 실제 kookabug mcp: 같은 집행
        mcp = McpClient.start(spawned, root, tmp_path / "mcp", env=daemon_env(tmp_path))
        try:
            mcp.initialize()
            assert mcp.error("kb_screen_list")["code"] == "toolset_disabled"
            mcp.data("kb_toolset_enable", {"toolsets": ["screens"]})
            assert mcp.data("kb_screen_list")["screens"]
            error = mcp.error("kb_screen_get", {"path": SCREEN})
            assert error["code"] == "permission_denied"
            assert error["decision"]["source"] == "rule:kb_screen_get"
            # kb_project_info(core)는 allow, 폴더 규칙만 알려 주고 화면 지도 내용은 없다
            info = mcp.data("kb_project_info")
            assert "detect" not in json.dumps(info, ensure_ascii=False)
            assert mcp.close() == 0
        finally:
            mcp.__exit__(None, None, None)


def _changed_paths(client: DaemonClient, until: str, timeout: float = 10.0) -> list[str]:
    """`until` 경로가 든 `workspace.changed`까지 받은 경로 전부."""
    seen: list[str] = []
    deadline = time.monotonic() + timeout
    while until not in seen:
        left = deadline - time.monotonic()
        if left <= 0:
            raise AssertionError(f"{timeout}초 안에 {until}의 workspace.changed가 없다: {seen}")
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            continue
        if message["method"] == "workspace.changed":
            seen += message["params"]["paths"]
    return seen


def test_workspace_changed_hides_screens_from_agent(tmp_path: Path) -> None:
    root = copy_sample_workspace(tmp_path / "ws")
    with ThreadDaemon(root) as d, d.client() as ui, d.client(AGENT) as agent:
        time.sleep(1.5)  # 감시의 첫 목록(기준)을 잡을 시간
        (root / "screens" / "new.screen.json").write_text("{}", encoding="utf-8")
        _changed_paths(ui, "screens/new.screen.json")  # 사람은 그대로 받는다 (알림이 나갔다)
        # 그 뒤 표식 파일: agent가 표식까지 받은 것에 screens/ 알림이 끼어 있으면 안 된다
        (root / "tests" / "marker.graph.json").write_text('{"kind": "test"}', encoding="utf-8")
        agent_seen = _changed_paths(agent, "tests/marker.graph.json")
        assert not [p for p in agent_seen if p.casefold().startswith("screens")], agent_seen
