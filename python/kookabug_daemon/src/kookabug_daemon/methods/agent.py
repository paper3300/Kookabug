"""`agent.toolsets.get/enable` (M5 계획 D3·3.5): 연결별 MCP 툴셋.

MCP 프로세스 하나 = daemon 연결 하나라 툴셋은 연결 상태다. agent 연결은 hello 때 `core`만 켜져
있고, 꺼진 툴셋의 메서드는 전송이 판정 전에 `toolset_disabled`로 거부한다(`tools.Authorizer.gate`).
켜기만 하고 끄기는 없다. 켜도 도구마다의 권한 판정은 그대로다. ui 연결은 툴셋과 무관하다.
"""

from __future__ import annotations

from typing import Any, Final

from kookabug_core.permissions import TOOLS, TOOLSETS
from kookabug_daemon.methods import Call, MethodSpec

__all__ = ["METHODS", "tools_of"]


def tools_of(toolsets: frozenset[str]) -> list[str]:
    """그 툴셋들의 권한 표 도구 이름 (정렬)."""
    return sorted(name for name, info in TOOLS.items() if info.toolset in toolsets)


def _ordered(toolsets: frozenset[str]) -> list[str]:
    return [t for t in TOOLSETS if t in toolsets]


async def _get(call: Call) -> dict[str, Any]:
    enabled = call.daemon.connection_toolsets(call.connection)
    return {"enabled": _ordered(enabled), "available": list(TOOLSETS)}


async def _enable(call: Call) -> dict[str, Any]:
    before = call.daemon.connection_toolsets(call.connection)
    asked = frozenset(str(t) for t in call.params["toolsets"])
    after = call.daemon.enable_toolsets(call.connection, asked)
    return {"enabled": _ordered(after), "tools": tools_of(after - before)}


METHODS: Final = {
    "agent.toolsets.get": MethodSpec(_get),
    "agent.toolsets.enable": MethodSpec(_enable),
}
