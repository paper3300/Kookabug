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


def test_ui_only_methods_agent_denied_or_allowlisted() -> None:
    ui_only = {name for name, info in methods().items() if info.tool == UI_ONLY}
    assert ui_only == {name for name, tool in METHOD_TOOLS.items() if tool == UI_ONLY}
    assert ui_only >= AGENT_DENIED
    assert ui_only - AGENT_DENIED == UI_ONLY_AGENT_ALLOWED == ALLOWED_BEFORE_M3
    assert {"daemon.shutdown"} | M3_DENIED == AGENT_DENIED


class _NoService:
    def require(self, principal: Principal, tool: str, arg: str = "", *, approved: bool = False):
        raise AssertionError("ui_only 메서드는 판정하지 않는다")


@pytest.mark.parametrize("method", sorted(M3_DENIED))
def test_agent_denied_before_decision(method: str) -> None:
    authorizer = Authorizer(_NoService())
    agent = Principal("agent", "codex-1", attended=True)
    with pytest.raises(RequestFailed) as caught:
        authorizer.require(agent, method)
    assert caught.value.code == "permission_denied"
    user = Principal("user", "ui:1", attended=True)
    assert authorizer.require(user, method) is None
