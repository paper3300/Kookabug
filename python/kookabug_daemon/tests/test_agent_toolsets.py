"""연결별 MCP 툴셋 (M5 계획 D3·3.6 1~2단계, B1).

agent 연결은 hello 때 `core`만 켜져 있다. 꺼진 툴셋의 메서드는 판정(`require`) 전에
`toolset_disabled`로 거부하고 아무것도 쓰지 않는다. 켜면 그 뒤로는 정책대로 판정한다. ui 연결은
툴셋과 무관하다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon, copy_sample_workspace
from kookabug_core.permissions import Decision, Principal
from kookabug_core.service import WorkspaceService
from kookabug_daemon.client import DaemonError

pytestmark = pytest.mark.process

NEW = "tests/agent_new.graph.json"
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-7", "attended": True}


class RecordingService:
    """판정 호출을 기록하고 진짜 서비스로 넘긴다."""

    def __init__(self, inner: WorkspaceService) -> None:
        self.inner = inner
        self.calls: list[tuple[str, str]] = []

    def require(
        self, principal: Principal, tool: str, arg: str = "", *, approved: bool = False
    ) -> Decision:
        self.calls.append((tool, arg))
        return self.inner.require(principal, tool, arg, approved=approved)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def test_disabled_toolset_rejected_before_decide(tmp_path: Path) -> None:
    root = copy_sample_workspace(tmp_path / "ws")
    service = RecordingService(
        WorkspaceService(root, environ={"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")})
    )
    with ThreadDaemon(root, service=service, agent_toolsets=("core",)) as d:
        with d.client(AGENT) as agent:
            assert agent.call("agent.toolsets.get") == {
                "enabled": ["core"],
                "available": [
                    "core",
                    "graph_edit",
                    "run",
                    "observe",
                    "control",
                    "screens",
                    "knowledge",
                    "cases",
                ],
            }
            service.calls.clear()
            for method, params in (
                ("graph.create", {"path": NEW, "kind": "test"}),
                ("run.start", {"path": "tests/inventory_open.graph.json"}),
                ("windows.list", {}),
            ):
                with pytest.raises(DaemonError) as caught:
                    agent.call(method, params)
                assert caught.value.kind == "toolset_disabled", method
                assert caught.value.data["toolset"] in {"graph_edit", "run", "observe"}
            # 판정을 부르지 않았다 (승인 요청·판정 기록 없음), 파일도 없다
            assert service.calls == []
            assert not (root / NEW).exists()
            assert not (root / "runs").exists()
            # core 도구는 그대로 판정한다
            agent.call("workspace.info")
            assert service.calls == [("kb_project_info", "")]

            enabled = agent.call("agent.toolsets.enable", {"toolsets": ["graph_edit"]})
            assert enabled["enabled"] == ["core", "graph_edit"]
            assert enabled["tools"] == ["kb_graph_create", "kb_graph_patch", "kb_target_create"]
            # 켠 뒤에는 정책(기본 graph_author: graph_edit ask)대로 판정한다
            service.calls.clear()
            with pytest.raises(DaemonError) as caught:
                agent.call("graph.create", {"path": NEW, "kind": "test"})
            assert caught.value.kind == "approval_required"
            assert service.calls == [("kb_graph_create", NEW)]
            assert not (root / NEW).exists()
        # 툴셋은 연결 상태다: 새 연결은 다시 core만
        with d.client(AGENT) as again:
            assert again.call("agent.toolsets.get")["enabled"] == ["core"]
        # ui 연결은 툴셋과 무관하다
        with d.client() as ui:
            assert len(ui.call("agent.toolsets.get")["enabled"]) == 8  # M8 knowledge·cases
            ui.call("graph.create", {"path": NEW, "kind": "test"})
        assert (root / NEW).exists()
