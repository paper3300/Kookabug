"""메서드 → 권한 도구 표와 판정 어댑터 (M2 계획 2.5).

daemon의 메서드는 모두 도구 이름 하나(구현 계획 7장)에 대응하거나 `ui_only`다. 표는 계약
(`daemon-rpc.schema.json`의 `Methods` 표 `tool`)과 같아야 하고, 검사가 둘을 비교한다.

판정은 `WorkspaceService.require(principal, tool, arg)`만 한다. daemon에는 판정 코드를 두지 않고,
연결의 주체를 바꾸지 않고 그대로 넘긴다. user 주체는 서비스가 판정하지 않는다(`human`).
`ui_only`는 판정하지 않는다. 단 agent 연결이 `AGENT_DENIED`의 메서드를 부르면 거부한다.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Final, Protocol

from kookabug_core.permissions import TOOLS, Decision, Principal
from kookabug_core.service import ApprovalRequired, PermissionDenied
from kookabug_daemon.protocol import UI_ONLY, RequestFailed

__all__ = [
    "AGENT_DENIED",
    "AGENT_RAW",
    "HUMAN_SCREEN_METHODS",
    "METHOD_TOOLS",
    "PLUGIN_CHANGE_METHODS",
    "RECORDER_METHODS",
    "UI_ONLY_AGENT_ALLOWED",
    "Authorizer",
    "ServiceLike",
    "agent_use_safe_api",
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
        "recorder.target.materialize",
        "secrets.list",
        "secrets.create",
        "target.read_text",
    }
)

PLUGIN_CHANGE_METHODS: Final = frozenset(
    {
        "plugins.preview",
        "plugins.install",
        "plugins.upgrade",
        "plugins.remove",
        "plugins.sync",
        "plugins.relock",
        "plugins.gc",
        "plugins.cancel",
    }
)
"""M6 플러그인 설치·제거·준비·다시 잠그기·정리 (계획 3.8·3.9, 엄격: Agent 권한): 사람만. 미리보기도
원천을 받고(네트워크·디스크) 거래를 시작하므로 여기에 든다. 공개 MCP 도구는 없다."""

HUMAN_SCREEN_METHODS: Final = frozenset(
    {
        "screens.check",
        "screens.promote",
        "screens.discard",
        "screens.layout_get",
        "screens.layout_set",
    }
)
"""M7 화면 지도의 사람 전용 메서드 (계획 3.7·3.8, 엄격: Agent 권한): 에이전트가 자기 탐색 결과를
확정하거나 지우지 못하게. 처리기는 B4(승격·버리기·확인)·B5(배치)가 붙인다 — 그 전에도 에이전트
연결은 판정 전에 `permission_denied`다(전송이 처리기 유무보다 먼저 막는다)."""

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
    # M5 B1: 연결별 툴셋·경로로 고치기 (계획 3.5)
    "agent.toolsets.get": "kb_toolset_enable",
    "agent.toolsets.enable": "kb_toolset_enable",
    "graph.patch": "kb_graph_patch",
    # M5 B1 검수: MCP 도구 이름 그대로 판정하는 진입점
    "graph.list": "kb_graph_list",
    "graph.check": "kb_graph_validate",
    # M5 B2: 에이전트용 기록 읽기(가린 결과)·관측·화면 지도 (계획 3.5)
    "run.failure": "kb_run_status",
    "run.events": "kb_run_events",
    "run.search": "kb_log_search",
    "run.artifact": "kb_run_artifact_get",
    "run.diff": "kb_run_compare",
    "screen.read_text": "kb_ocr_read",
    "screens.list": "kb_screen_list",
    "screens.get": "kb_screen_get",
    # M7 탐색 세션·화면 지도 저장·식별 (계획 3.4~3.6). 목록은 사람 화면용
    "screens.identify": "kb_screen_identify",
    # M7 B4 이동 그래프 (계획 3.3, 3.8 — 조회, 썸네일은 사람에게만)
    "screens.map": "kb_screen_list",
    "screens.save": "kb_screen_save",
    "explore.start": "kb_explore_start",
    "explore.end": "kb_explore_end",
    "explore.list": UI_ONLY,
    # M7 사람 전용 화면 지도 메서드 (계획 3.7·3.8, B3 엄격): 승격·버리기·확인·카드 배치
    **dict.fromkeys(sorted(HUMAN_SCREEN_METHODS), UI_ONLY),
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
    # M5 B3: 사람 확인·권한 설정 (계획 3.5·3.6) — 답·설정은 사람만
    "approval.list": UI_ONLY,
    "approval.respond": UI_ONLY,
    "approval.preview": UI_ONLY,
    "permissions.get": "kb_project_info",
    "permissions.set": UI_ONLY,
    # M5 B3: 게임 조작 (계획 3.9) — 한 스텝짜리 제어 실행
    "control.click": "kb_input_click",
    "control.key": "kb_input_key",
    "control.type": "kb_input_type",
    "app.launch": "kb_app_launch",
    # M5 B5: 에이전트 패널·설정 — 사람만 (에이전트가 자기 실행 명령을 바꾸지 못하게)
    "agent.connections": UI_ONLY,
    "agents.get": UI_ONLY,
    "agents.detect": UI_ONLY,
    "agents.set": UI_ONLY,
    # M6 B4: 플러그인 — 목록은 조회(kb_project_info), 변경은 사람만
    "plugins.list": "kb_project_info",
    **dict.fromkeys(sorted(PLUGIN_CHANGE_METHODS), UI_ONLY),
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
        # 에이전트가 자기 확인 요청을 승인하거나 권한을 바꾸지 못하게 (M5 3.6 엄격 항목)
        "approval.list",
        "approval.respond",
        "approval.preview",
        "permissions.set",
        "agent.connections",
        "agents.get",
        "agents.detect",
        "agents.set",
        # 에이전트는 플러그인을 설치·제거·준비하지 못한다 (M6 3.9, 사람 확인으로도 — U3)
        *PLUGIN_CHANGE_METHODS,
        # 탐색 세션 목록은 사람 화면용 (M7 3.8)
        "explore.list",
        # 에이전트는 자기 탐색 결과를 승격·버리기·확인하거나 지도 배치를 바꾸지 못한다 (M7 3.7, B3)
        *HUMAN_SCREEN_METHODS,
    }
)
"""`ui_only`이지만 agent 연결에는 판정 전에 거부하는 메서드. `ui_only`는 판정을 건너뛰므로
표시만으로는 에이전트를 막지 못한다 (M3 계획 2.1). 사람 없는 실행이 멈추거나 에이전트가 실행
기록을 임의 경로에 쓰지 않게 디버그·내보내기 메서드를, 에이전트가 녹화를 켜거나 읽지 못하게
녹화·비밀값 메서드(M4 C20)를 여기에 넣는다. `target.read_text`는 녹화 프레임(비밀번호가 찍힐 수
있는 임시 화면)도 읽으므로 M4에서는 사람만 쓴다."""

AGENT_RAW: Final = frozenset(
    {"run.index", "run.children", "run.step", "run.file", "run.compare", "run.subscribe"}
)
"""사람 화면용 기록 원문 메서드 (M5 계획 3.5 H2). agent 연결은 판정 전에 `agent_use_safe_api`로
거부한다 — 에이전트는 가린 결과를 주는 `run.events/artifact/diff/failure/search`로만 읽는다.
`target.load_image`의 `runs/` 경로·`workspace.tree/read`의 `screens/`는 인자에 따라 처리기가
거부한다."""

UI_ONLY_AGENT_ALLOWED: Final = frozenset({"session.hello", "graph.close", "run.unsubscribe"})
"""`ui_only`인데 agent 연결에도 허용하는 기존 메서드 (자기 연결의 문서·구독만 닫는다). 새 `ui_only`
메서드는 여기나 `AGENT_DENIED` 중 한 곳에 넣어야 한다 (표 검사가 빠짐을 잡는다)."""


def agent_use_safe_api(what: str) -> RequestFailed:
    """에이전트 연결이 기록 원문 경로를 부를 때 (M5 3.5)."""
    return RequestFailed(
        "agent_use_safe_api",
        f"에이전트 연결은 {what}를 쓸 수 없다 (원문 기록 경로). 실행 기록은 kb_run_events·"
        "kb_run_artifact_get·kb_run_compare·kb_run_status로 읽는다 (비밀값을 가린 결과)",
    )


class ServiceLike(Protocol):
    """`WorkspaceService`의 판정 부분 (검사가 대역을 넣는다)."""

    def require(
        self, principal: Principal, tool: str, arg: str = "", *, approved: bool = False
    ) -> Decision: ...

    def authorize(self, principal: Principal, tool: str, arg: str = "") -> Decision: ...


class Authorizer:
    """연결의 주체로 메서드 하나를 판정한다. 거부·승인 필요는 `RequestFailed`."""

    def __init__(self, service: ServiceLike) -> None:
        self.service = service

    def gate(self, principal: Principal, method: str, toolsets: Collection[str]) -> None:
        """판정 전 거부 (M5 계획 3.6 1~2단계): `AGENT_DENIED` → 툴셋 꺼짐(`toolset_disabled`).
        사람(user) 연결은 툴셋과 무관하다. 전송이 모든 요청(스스로 판정하는 메서드 포함)에
        부른다."""
        if principal.kind != "agent":
            return
        if method in AGENT_RAW:
            raise agent_use_safe_api(method)
        tool = METHOD_TOOLS[method]
        if tool == UI_ONLY:
            if method in AGENT_DENIED:
                raise RequestFailed(
                    "permission_denied", f"에이전트 연결은 {method}를 쓸 수 없다 (ui_only)"
                )
            return
        toolset = TOOLS[tool].toolset
        if toolset not in toolsets:
            raise RequestFailed(
                "toolset_disabled",
                f"툴셋 {toolset}이(가) 꺼져 있다 ({tool}). kb_toolset_enable로 먼저 켠다",
                toolset=toolset,
            )

    def peek(self, principal: Principal, method: str, arg: str = "") -> Decision | None:
        """집행하지 않고 판정만 본다 (`ui_only`면 None). 스스로 판정하는 메서드가 ask인지 미리 볼
        때 쓴다 — 집행은 그 메서드의 `require`가 한다."""
        tool = METHOD_TOOLS[method]
        if tool == UI_ONLY:
            return None
        return self.service.authorize(principal, tool, arg)

    def require(
        self, principal: Principal, method: str, arg: str = "", *, approved: bool = False
    ) -> Decision | None:
        """판정했으면 그 결과, `ui_only`라 판정하지 않았으면 None. ask는 `approved`(사람 확인을
        받았음, `approvals.ApprovalBroker`)일 때만 통과하고 아니면 `approval_required`다."""
        tool = METHOD_TOOLS[method]
        if tool == UI_ONLY:
            if principal.kind == "agent" and method in AGENT_DENIED:
                raise RequestFailed(
                    "permission_denied", f"에이전트 연결은 {method}를 쓸 수 없다 (ui_only)"
                )
            return None
        try:
            return self.service.require(principal, tool, arg, approved=approved)
        except PermissionDenied as exc:
            raise RequestFailed(
                "permission_denied", str(exc), decision=exc.decision.to_dict()
            ) from exc
        except ApprovalRequired as exc:
            raise RequestFailed(
                "approval_required", str(exc), decision=exc.decision.to_dict()
            ) from exc
