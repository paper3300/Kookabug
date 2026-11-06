"""`agents.get/detect/set` (M5 계획 3.5·3.12, B5): 사용자 설정의 에이전트 목록.

셋 다 `ui_only`이고 `AGENT_DENIED`다 — 에이전트가 자기가 띄워질 명령을 바꾸지 못한다. 목록은 판단
노드(runner)와 에이전트 패널(앱)이 같이 보고, 쓰기는 daemon 한 곳(`permission_files`의 쓰기 규칙).
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

from kookabug_core.agents.detect import detect
from kookabug_daemon.methods import Call, MethodSpec

__all__ = ["METHODS"]


async def _get(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(call.daemon.permission_files.read_agents)


async def _detect(call: Call) -> dict[str, Any]:
    return {"candidates": await asyncio.to_thread(detect)}


async def _set(call: Call) -> dict[str, Any]:
    params = call.params
    base = params["base_revision"]
    default = params["default_agent"]
    revision = await asyncio.to_thread(
        call.daemon.permission_files.set_agents,
        list(params["agents"]),
        None if default is None else str(default),
        None if base is None else str(base),
    )
    return {"revision": revision}


METHODS: Final = {
    "agents.get": MethodSpec(_get),
    "agents.detect": MethodSpec(_detect),
    "agents.set": MethodSpec(_set),
}
