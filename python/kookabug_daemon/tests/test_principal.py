"""연결별 주체와 메서드 → 도구 판정 어댑터 (M2 계획 2.4 "주체", 2.5)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon, make_workspace
from kookabug_core.permissions import Decision, Principal
from kookabug_core.service import ApprovalRequired, PermissionDenied
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods import registry as default_registry
from kookabug_daemon.methods.tools import HUMAN_ONLY_M8, METHOD_TOOLS, RECORDER_METHODS
from kookabug_daemon.protocol import UI_ONLY, methods

pytestmark = pytest.mark.process

UI = {"kind": "ui", "name": "desktop", "version": "0.1.0"}


def agent(**extra: Any) -> dict[str, Any]:
    return {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-7", **extra}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return make_workspace(tmp_path / "ws")


class RecordingService:
    """`WorkspaceService.require` 대역: 받은 인자를 그대로 기록하고 정한 결과를 낸다."""

    def __init__(self) -> None:
        self.calls: list[tuple[Principal, str, str, bool]] = []
        self.outcome = "allow"
        self.lock = threading.Lock()

    def require(
        self, principal: Principal, tool: str, arg: str = "", *, approved: bool = False
    ) -> Decision:
        with self.lock:
            self.calls.append((principal, tool, arg, approved))
        verdict: Any = self.outcome
        decision = Decision(verdict, verdict, "project", "rule:x", "rule")
        if verdict == "deny":
            raise PermissionDenied(tool, decision)
        if verdict == "ask":
            raise ApprovalRequired(tool, decision)
        return decision

    def authorize(self, principal: Principal, tool: str, arg: str = "") -> Decision:
        """집행 없는 판정 보기 (`run.start`의 사람 확인 사전 확인). 기록하지 않는다."""
        verdict: Any = self.outcome
        return Decision(verdict, verdict, "project", "rule:x", "rule")


@pytest.fixture
def recorded(root: Path) -> Iterator[tuple[ThreadDaemon, RecordingService, list[Call]]]:
    service = RecordingService()
    handled: list[Call] = []

    async def cancel(call: Call) -> dict[str, Any]:
        handled.append(call)
        return {}

    def run_id(call: Call) -> str:
        return str(call.params["run_id"])

    registry = {**default_registry(), "run.cancel": MethodSpec(cancel, run_id)}
    with ThreadDaemon(root, service=service, methods=registry) as d:
        yield d, service, handled


def test_ui_client_is_attended_user(root: Path) -> None:
    with ThreadDaemon(root) as d:
        with d.client(UI) as first, d.client(UI) as second:
            assert first.hello_result is not None and second.hello_result is not None
            p1, p2 = first.hello_result["principal"], second.hello_result["principal"]
        assert p1["kind"] == "user" and p1["attended"] is True
        assert p1["id"].startswith("ui:") and p1["id"] != p2["id"]


def test_agent_client_requires_id_and_defaults_unattended(root: Path) -> None:
    with ThreadDaemon(root) as d:
        with d.client(agent()) as client:
            assert client.hello_result is not None
            assert client.hello_result["principal"] == {
                "kind": "agent",
                "id": "agent-7",
                "attended": False,
            }
        with d.client(agent(attended=True)) as client:
            assert client.hello_result is not None
            assert client.hello_result["principal"]["attended"] is True
        # id 없는 agent는 params 형식 오류로 거부하고 닫는다
        no_id = {k: v for k, v in agent().items() if k != "id"}
        raw = DaemonClient.open(d.port, check=False)
        params = {"token": d.session.token, "protocol": 1, "client": no_id}
        with pytest.raises(DaemonError) as caught:
            raw.call("session.hello", params, timeout=10)
        assert caught.value.code == -32602
        assert raw.wait_closed(10) == 1008


def test_every_method_has_tool_or_ui_only() -> None:
    # 계약의 메서드 목록 = 표, 메서드마다 같은 도구 (M2 계획 2.5)
    contract = {name: info.tool for name, info in methods().items()}
    assert contract == METHOD_TOOLS
    for name, tool in METHOD_TOOLS.items():
        assert tool == UI_ONLY or tool.startswith("kb_"), name
    assert {m for m, t in METHOD_TOOLS.items() if t == UI_ONLY} == {
        "session.hello",
        "daemon.shutdown",
        "graph.close",
        "run.unsubscribe",
        # M3 디버거·내보내기
        "debug.breakpoints.get",
        "debug.breakpoints.set",
        "run.pause",
        "run.resume",
        "run.restart",
        "run.export",
        # M5 B3 사람 확인·권한 설정
        "approval.list",
        "approval.respond",
        "approval.preview",
        "permissions.set",
        # M5 B5 에이전트 패널·설정
        "agent.connections",
        "agents.get",
        "agents.detect",
        "agents.set",
        # M6 B4 플러그인 변경 (목록 plugins.list는 kb_project_info)
        "plugins.preview",
        "plugins.install",
        "plugins.upgrade",
        "plugins.remove",
        "plugins.sync",
        "plugins.relock",
        "plugins.gc",
        "plugins.cancel",
        # M7 탐색 세션 목록 (사람 화면용)
        "explore.list",
        # M7 B3 화면 지도 사람 전용 (승격·버리기·확인·카드 배치)
        "screens.check",
        "screens.promote",
        "screens.discard",
        "screens.layout_get",
        "screens.layout_set",
    } | RECORDER_METHODS | HUMAN_ONLY_M8


@pytest.mark.parametrize(
    "client", [UI, agent(), agent(attended=True)], ids=["ui", "agent", "panel"]
)
def test_adapter_passes_principal_unchanged_to_service(
    recorded: tuple[ThreadDaemon, RecordingService, list[Call]], client: dict[str, Any]
) -> None:
    d, service, handled = recorded
    with d.client(client) as conn:
        assert conn.hello_result is not None
        shown = conn.hello_result["principal"]
        assert conn.call("run.cancel", {"run_id": "abcd1234"}) == {}
    [(principal, tool, arg, approved)] = service.calls
    assert (principal.kind, principal.id, principal.attended) == (
        shown["kind"],
        shown["id"],
        shown["attended"],
    )
    assert (tool, arg, approved) == ("kb_run_cancel", "abcd1234", False)
    # 처리기가 받은 주체도 같은 객체다 (어댑터가 바꾸지 않는다)
    [call] = handled
    assert call.principal is principal


@pytest.mark.parametrize(
    ("outcome", "kind"), [("deny", "permission_denied"), ("ask", "approval_required")]
)
def test_adapter_denial_not_handled(
    recorded: tuple[ThreadDaemon, RecordingService, list[Call]], outcome: str, kind: str
) -> None:
    d, service, handled = recorded
    service.outcome = outcome
    with (
        d.client(agent(attended=outcome == "ask")) as conn,
        pytest.raises(DaemonError) as caught,
    ):
        conn.call("run.cancel", {"run_id": "abcd1234"})
    assert caught.value.kind == kind
    assert caught.value.data["decision"]["final"] == outcome
    assert handled == []  # 처리기를 부르지 않았다


def test_ui_only_not_judged_and_agent_shutdown_denied(
    recorded: tuple[ThreadDaemon, RecordingService, list[Call]],
) -> None:
    d, service, _ = recorded
    with d.client(agent(attended=True)) as conn:
        with pytest.raises(DaemonError) as caught:
            conn.call("daemon.shutdown", {})
        assert caught.value.kind == "permission_denied"
    assert service.calls == []  # ui_only는 서비스 판정을 거치지 않는다
    assert d.is_running()
    with d.client(UI) as conn:
        assert conn.call("daemon.shutdown", {}) == {}
    assert service.calls == []
    assert d.finished(10) == "daemon.shutdown"
