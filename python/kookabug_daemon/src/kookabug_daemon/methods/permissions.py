"""`permissions.get/set` (M5 계획 3.5·3.6): 권한 설정 화면.

- `permissions.get`은 `kb_project_info`로 판정한다. agent 연결에는 자기 주체의 도구별 판정만 주고
  계층 파일 값은 주지 않는다. ui 연결에는 계층(프로젝트·사용자·팀) 값·revision·진단과, 사람이
  지켜보는 에이전트 기준의 도구별 판정
- `permissions.set`은 `ui_only`이고 `AGENT_DENIED`(에이전트가 자기 권한을 바꾸지 못함). 쓰기 규칙은
  `permission_files.PermissionFiles`
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

from kookabug_core.permissions import TOOLS, Principal, decide
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.principal import principal_json

__all__ = ["METHODS"]

PREVIEW_AGENT: Final = Principal("agent", "settings-preview", attended=True)
"""ui 연결의 도구별 판정을 계산할 주체 (사람이 지켜보는 에이전트)."""


def _get_sync(call: Call) -> dict[str, Any]:
    service = call.daemon.service
    policy = service.policy()
    agent = call.principal.kind == "agent"
    principal = call.principal if agent else PREVIEW_AGENT
    tools: list[dict[str, Any]] = []
    for name, info in TOOLS.items():
        decision = decide(policy, principal, name, "")
        tools.append(
            {
                "tool": name,
                "toolset": info.toolset,
                "mutating": info.mutating,
                "verdict": decision.verdict,
                "final": decision.final,
                "layer": decision.layer,
                "source": decision.source,
                "reason": decision.reason,
            }
        )
    result: dict[str, Any] = {"principal": principal_json(principal), "tools": tools}
    if not agent:
        result["layers"] = call.daemon.permission_files.layers(policy)
    return result


async def _get(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_get_sync, call)


async def _set(call: Call) -> dict[str, Any]:
    params = call.params
    layer = str(params["layer"])
    assert layer in ("user", "project")  # 계약 형식 검사를 지났다
    base = params["base_revision"]
    revision = await asyncio.to_thread(
        call.daemon.permission_files.set,
        layer,  # pyright: ignore[reportArgumentType]
        dict(params["permissions"]),
        None if base is None else str(base),
    )
    return {"revision": revision}


METHODS: Final = {
    "permissions.get": MethodSpec(_get),
    "permissions.set": MethodSpec(_set),
}
