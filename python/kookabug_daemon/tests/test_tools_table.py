"""메서드 → 권한 도구 표의 에이전트 거부 목록 (M3 계획 2.1, 검수 M2).

`ui_only`는 판정을 건너뛰므로, 에이전트에게 막아야 하는 메서드는 `AGENT_DENIED`에 따로 있어야 한다.
`ui_only`인데 `AGENT_DENIED`에 없는 메서드는 정해 둔 기존 허용 목록과 같아야 한다 — 새 `ui_only`
메서드를 표에만 넣고 거부 목록을 빠뜨리면 여기서 실패한다.
"""

from __future__ import annotations

import pytest

from kookabug_core.permissions import Principal
from kookabug_daemon.methods.tools import (
    AGENT_DENIED,
    METHOD_TOOLS,
    UI_ONLY_AGENT_ALLOWED,
    Authorizer,
)
from kookabug_daemon.protocol import UI_ONLY, RequestFailed, methods

# M2까지 있던 ui_only 중 에이전트 연결도 쓰는 것 (자기 연결의 문서·구독만 닫는다)
ALLOWED_BEFORE_M3 = {"session.hello", "graph.close", "run.unsubscribe"}
M3_DENIED = {
    "debug.breakpoints.get",
    "debug.breakpoints.set",
    "run.pause",
    "run.resume",
    "run.restart",
    "run.export",
}
# M4 녹화·비밀값 (계획 2.9 C20)
M4_DENIED = {
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
# M5 B3 사람 확인·권한 설정 (계획 3.6 엄격: 에이전트가 자기 요청을 승인하거나 권한을 바꾸지 못함)
M5_DENIED = {"approval.list", "approval.respond", "approval.preview", "permissions.set"}
# M5 B5 에이전트 패널·설정 (에이전트가 자기 실행 명령·다른 에이전트 연결을 보거나 바꾸지 못함)
M5_DENIED |= {"agent.connections", "agents.get", "agents.detect", "agents.set"}
# M6 B4 플러그인 (계획 3.9 엄격: 에이전트는 설치·제거·준비·다시 잠그기·정리를 못 함)
M7_DENIED = {
    "explore.list",
    "screens.check",
    "screens.promote",
    "screens.discard",
    "screens.layout_get",
    "screens.layout_set",
}
"""M7 탐색 세션 목록·화면 지도 승격·버리기·확인·카드 배치 — 사람만 (B3 엄격)."""
M8_DENIED = {"cheats.list", "cheats.adopt", "cheats.unadopt", "cheats.categories.set"}
"""M8 치트 채택·분류 — 사람만 (B2 엄격: Agent 권한)."""
M8_DENIED |= {
    "adopt.revert",
    "adoptions.list",
    "working.accept",
    "working.list",
    "working.reject",
}
"""M8 B3 채택 되돌리기·묶음 수락·거절·목록 — 사람만. `adopt.request`·`evidence.pin`은 B4부터
`cases` 툴셋 도구."""
M8_DENIED |= {
    "cases.close",
    "unknowns.answer",
    "project.automation.set",
    "project.sources.set",
    "sources.check",
    "job.begin",
    "job.end",
    "job.finish",
    "jobs.list",
    "reports.list",
    "reports.get",
    "report.decide",
    "wizard.get",
    "wizard.set",
}
"""M8 B4 사건 닫기·미지수 답·정책·원본·작업·보고함·마법사 — 사람만 (계획 3.13)."""
M8_DENIED |= {"job.heartbeat"}
"""M8 B5 작업 소유 연결 heartbeat (R8) — 사람만."""
M8_DENIED |= {"project.setup.set", "local.settings.set"}
M8_DENIED |= {"jobs.activity"}
M8_DENIED |= {
    "conversations.list",
    "conversations.get",
    "conversations.save",
    "conversations.delete",
}
"""UX4 에이전트 패널 이전 대화 — 사람 화면만 (이 PC 대화 기록)."""
"""UX1 진행 중 작업의 활동 목록 — 사람 화면용 읽기."""
"""M8 B7 마법사 2·8단계 설정 쓰기 — 사람만."""
M6_DENIED = {
    "plugins.preview",
    "plugins.install",
    "plugins.upgrade",
    "plugins.remove",
    "plugins.sync",
    "plugins.relock",
    "plugins.gc",
    "plugins.cancel",
}


def test_ui_only_methods_agent_denied_or_allowlisted() -> None:
    ui_only = {name for name, info in methods().items() if info.tool == UI_ONLY}
    assert ui_only == {name for name, tool in METHOD_TOOLS.items() if tool == UI_ONLY}
    assert ui_only >= AGENT_DENIED
    assert ui_only - AGENT_DENIED == UI_ONLY_AGENT_ALLOWED == ALLOWED_BEFORE_M3
    assert {
        "daemon.shutdown"
    } | M3_DENIED | M4_DENIED | M5_DENIED | M6_DENIED | M7_DENIED | M8_DENIED == AGENT_DENIED


def test_every_plugin_method_but_list_is_agent_denied() -> None:
    """계약의 `plugins.*` 전부: 목록만 조회 도구, 나머지는 ui_only + 에이전트 거부 (빠짐 없음)."""
    plugin_methods = {name for name in methods() if name.startswith("plugins.")}
    assert plugin_methods == M6_DENIED | {"plugins.list"}
    assert METHOD_TOOLS["plugins.list"] == "kb_project_info"
    for name in M6_DENIED:
        assert METHOD_TOOLS[name] == UI_ONLY and name in AGENT_DENIED, name


class _NoService:
    def require(self, principal: Principal, tool: str, arg: str = "", *, approved: bool = False):
        raise AssertionError("ui_only 메서드는 판정하지 않는다")

    def authorize(self, principal: Principal, tool: str, arg: str = ""):
        raise AssertionError("ui_only 메서드는 판정하지 않는다")


@pytest.mark.parametrize(
    "method", sorted(M3_DENIED | M4_DENIED | M5_DENIED | M6_DENIED | M7_DENIED | M8_DENIED)
)
def test_agent_denied_before_decision(method: str) -> None:
    authorizer = Authorizer(_NoService())
    agent = Principal("agent", "codex-1", attended=True)
    with pytest.raises(RequestFailed) as caught:
        authorizer.require(agent, method)
    assert caught.value.code == "permission_denied"
    user = Principal("user", "ui:1", attended=True)
    assert authorizer.require(user, method) is None
