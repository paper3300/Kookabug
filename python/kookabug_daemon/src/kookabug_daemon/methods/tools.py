"""메서드 → 권한 도구 표와 판정 어댑터 (M2 계획 2.5).

daemon의 메서드는 모두 도구 이름 하나(구현 계획 7장)에 대응하거나 `ui_only`다. 표는 계약
(`daemon-rpc.schema.json`의 `Methods` 표 `tool`)과 같아야 하고, 검사가 둘을 비교한다.

판정은 `WorkspaceService.require(principal, tool, arg)`만 한다. daemon에는 판정 코드를 두지 않고,
연결의 주체를 바꾸지 않고 그대로 넘긴다. user 주체는 서비스가 판정하지 않는다(`human`).
`ui_only`는 판정하지 않는다. 단 agent 연결이 `AGENT_DENIED`의 메서드를 부르면 거부한다.
"""

from __future__ import annotations

from typing import Final, Protocol

from kookabug_core.permissions import Decision, Principal
from kookabug_core.service import ApprovalRequired, PermissionDenied
from kookabug_daemon.protocol import UI_ONLY, RequestFailed

__all__ = [
    "AGENT_DENIED",
    "METHOD_TOOLS",
    "RECORDER_METHODS",
    "UI_ONLY_AGENT_ALLOWED",
    "Authorizer",
    "ServiceLike",
]

# M4 녹화·비밀값 (계획 2.3·2.8·2.9): 키 입력 전체를 읽는 기능이라 사람만 쓴다. 처리기는 T7·T8·T11이
# 붙인다 (그 전에는 method_not_found "아직 없다")
RECORDER_METHODS: Final = frozenset(
    {
        "recorder.start",
        "recorder.pause",
        "recorder.resume",
        "recorder.stop",
        "recorder.discard",
        "recorder.state",
        "recorder.steps",
        "recorder.step.update",
        "recorder.frame",
        "recorder.insert_check",
        "recorder.commit_prepare",
        "recorder.commit_finish",
        "recorder.commit_abort",
        "secrets.list",
        "secrets.create",
        "target.read_text",
    }
)

METHOD_TOOLS: Final[dict[str, str]] = {
    "session.hello": UI_ONLY,
    "daemon.shutdown": UI_ONLY,
    "workspace.info": "kb_project_info",
    "workspace.tree": "kb_project_info",
    "workspace.read": "kb_project_info",
    "nodes.list": "kb_node_search",
    "graph.open": "kb_graph_get",
    "graph.validate": "kb_graph_validate",
    "graph.save": "kb_graph_patch",
    "graph.create": "kb_graph_create",
    "graph.close": UI_ONLY,
    "run.start": "kb_run_start",
    "run.cancel": "kb_run_cancel",
    "run.status": "kb_run_status",
    "run.list": "kb_run_status",
    "run.subscribe": "kb_run_events",
    "run.unsubscribe": UI_ONLY,
    "windows.list": "kb_screen_capture",
    "target.capture": "kb_screen_capture",
    "target.load_image": "kb_image_find",
    "target.open": "kb_image_find",
    "target.preview": "kb_image_find",
    "target.save": "kb_target_create",
    # M3 기록 읽기 (계획 2.7)
    "run.index": "kb_run_events",
    "run.children": "kb_run_events",
    "run.step": "kb_run_events",
    "run.file": "kb_run_events",
    "run.compare": "kb_run_events",
    # M3 디버거·내보내기 (계획 2.1·2.3): 사람만 쓴다
    "debug.breakpoints.get": UI_ONLY,
    "debug.breakpoints.set": UI_ONLY,
    "run.pause": UI_ONLY,
    "run.resume": UI_ONLY,
    "run.restart": UI_ONLY,
    "run.export": UI_ONLY,
    **dict.fromkeys(sorted(RECORDER_METHODS), UI_ONLY),
}

AGENT_DENIED: Final = frozenset(
    {
        "daemon.shutdown",
        "debug.breakpoints.get",
        "debug.breakpoints.set",
        "run.pause",
        "run.resume",
        "run.restart",
        "run.export",
        *RECORDER_METHODS,
    }
)
"""`ui_only`이지만 agent 연결에는 판정 전에 거부하는 메서드. `ui_only`는 판정을 건너뛰므로
표시만으로는 에이전트를 막지 못한다 (M3 계획 2.1). 사람 없는 실행이 멈추거나 에이전트가 실행
기록을 임의 경로에 쓰지 않게 디버그·내보내기 메서드를, 에이전트가 녹화를 켜거나 읽지 못하게
녹화·비밀값 메서드(M4 C20)를 여기에 넣는다. `target.read_text`는 녹화 프레임(비밀번호가 찍힐 수
있는 임시 화면)도 읽으므로 M4에서는 사람만 쓴다."""

UI_ONLY_AGENT_ALLOWED: Final = frozenset({"session.hello", "graph.close", "run.unsubscribe"})
"""`ui_only`인데 agent 연결에도 허용하는 기존 메서드 (자기 연결의 문서·구독만 닫는다). 새 `ui_only`
메서드는 여기나 `AGENT_DENIED` 중 한 곳에 넣어야 한다 (표 검사가 빠짐을 잡는다)."""


class ServiceLike(Protocol):
    """`WorkspaceService`의 판정 부분 (검사가 대역을 넣는다)."""

    def require(
        self, principal: Principal, tool: str, arg: str = "", *, approved: bool = False
    ) -> Decision: ...


class Authorizer:
    """연결의 주체로 메서드 하나를 판정한다. 거부·승인 필요는 `RequestFailed`."""

    def __init__(self, service: ServiceLike) -> None:
        self.service = service

    def require(self, principal: Principal, method: str, arg: str = "") -> Decision | None:
        """판정했으면 그 결과, `ui_only`라 판정하지 않았으면 None."""
        tool = METHOD_TOOLS[method]
        if tool == UI_ONLY:
            if principal.kind == "agent" and method in AGENT_DENIED:
                raise RequestFailed(
                    "permission_denied", f"에이전트 연결은 {method}를 쓸 수 없다 (ui_only)"
                )
            return None
        # M2에는 승인 UI가 없다: ask는 approved 없이 넘겨 approval_required가 된다 (2.5)
        try:
            return self.service.require(principal, tool, arg)
        except PermissionDenied as exc:
            raise RequestFailed(
                "permission_denied", str(exc), decision=exc.decision.to_dict()
            ) from exc
        except ApprovalRequired as exc:
            raise RequestFailed(
                "approval_required", str(exc), decision=exc.decision.to_dict()
            ) from exc
