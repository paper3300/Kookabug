"""`approval.list/respond/preview` (M5 계획 3.5·3.6): 사람 확인 카드.

셋 다 `ui_only`이고 `AGENT_DENIED`다 — 에이전트 연결은 전송이 판정 전에 거부한다(자기 요청 승인
금지). 확인 흐름은 `approvals.ApprovalBroker`.
"""

from __future__ import annotations

from typing import Any, Final

from kookabug_daemon.methods import Call, MethodSpec

__all__ = ["METHODS"]


async def _list(call: Call) -> dict[str, Any]:
    return {"requests": call.daemon.approvals.list()}


async def _respond(call: Call) -> dict[str, Any]:
    verdict = str(call.params["verdict"])
    # 계약 형식 검사를 지났다. allow_session은 탐색 세션이 있는 요청에만 (M7 B3)
    assert verdict in ("allow_once", "allow_always", "allow_session", "deny")
    await call.daemon.approvals.respond(
        str(call.params["id"]),
        verdict,  # pyright: ignore[reportArgumentType]
        call.principal.id,
    )
    return {}


async def _preview(call: Call) -> dict[str, Any]:
    return await call.daemon.approvals.preview(str(call.params["id"]))


METHODS: Final = {
    "approval.list": MethodSpec(_list),
    "approval.respond": MethodSpec(_respond),
    "approval.preview": MethodSpec(_preview),
}
