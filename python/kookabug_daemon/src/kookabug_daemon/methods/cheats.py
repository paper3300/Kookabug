"""`cheats.list`·`cheats.adopt`·`cheats.unadopt`·`cheats.categories.set` (M8 계획 3.2·3.5·3.13).

모두 `ui_only` + `AGENT_DENIED`: 에이전트 연결은 판정 전에 `permission_denied`(Agent는 채택·분류를
못 한다). 쓰기는 코어 `knowledge.cheats`(지식 연산 `ops.apply` → `filetx`)로만 한다 — 새 쓰기 경로
없음. 채택 digest는 Kookabug가 지금 워크스페이스에서 계산하고, 구현에 미해결·동적 의존성이 있으면
`validation_failed`로 거부한다.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.knowledge import cheats
from kookabug_core.knowledge.formats import KnowledgeError
from kookabug_core.workspace import WorkspaceError
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.protocol import RequestFailed

__all__ = ["METHODS"]


def _failed(exc: KnowledgeError) -> RequestFailed:
    code = exc.code
    if code in ("unknown_id", "category_unknown"):
        return RequestFailed("not_found", exc.message, path=str(exc.fields.get("id", "")))
    if code == "revision_conflict":
        return RequestFailed("revision_conflict", exc.message, revision=None)
    if code in ("cheat_not_adoptable", "format"):
        diagnostic = Diagnostic("error", code, exc.message, file="knowledge/cheats.json")
        return RequestFailed("validation_failed", exc.message, diagnostics=[diagnostic.to_dict()])
    if code == "adoption_reserved":
        return RequestFailed("permission_denied", exc.message)
    if code == "recovery_pending":
        return RequestFailed("recovery_pending", exc.message)
    return RequestFailed("io_error", exc.message, message=exc.message)


def _run(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except KnowledgeError as exc:
        raise _failed(exc) from exc
    except WorkspaceError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc


async def _list(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_run, cheats.list_cheats, call.daemon.root)


async def _adopt(call: Call) -> dict[str, Any]:
    p = call.params
    return await asyncio.to_thread(
        _run,
        cheats.adopt,
        call.daemon.root,
        str(p["id"]),
        int(p["rev"]),
        str(p["category"]),
        by=call.principal.id,
    )


async def _unadopt(call: Call) -> dict[str, Any]:
    p = call.params
    return await asyncio.to_thread(
        _run, cheats.unadopt, call.daemon.root, str(p["id"]), int(p["rev"]), by=call.principal.id
    )


async def _categories_set(call: Call) -> dict[str, Any]:
    p = call.params
    sha = await asyncio.to_thread(
        _run,
        cheats.set_policy,
        call.daemon.root,
        enabled=bool(p["enabled"]),
        categories=[dict(c) for c in p["categories"]],
        base_sha256=str(p["base_sha256"]),
    )
    return {"sha256": sha}


METHODS: Final[dict[str, MethodSpec]] = {
    "cheats.list": MethodSpec(_list),
    "cheats.adopt": MethodSpec(_adopt),
    "cheats.unadopt": MethodSpec(_unadopt),
    "cheats.categories.set": MethodSpec(_categories_set),
}
