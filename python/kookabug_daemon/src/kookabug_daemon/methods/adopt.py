"""`adopt.request`·`adopt.revert`·`adoptions.list`·`evidence.pin` (M8 계획 3.8·3.13, B3).

모두 지금은 `ui_only` + `AGENT_DENIED`다(에이전트 연결은 판정 전에 `permission_denied`). Agent용
MCP 도구(`kb_adopt_request`·`kb_evidence_pin`)와 툴셋 `cases`·프리셋 판정은 B4가 붙인다 — 그때
`adopt.request`·`evidence.pin`을 도구로 옮기고, `adopt.revert`는 사람 전용 그대로 둔다.

- `adopt.request`: 조건 1~8을 Kookabug가 결정적으로 검사한다(`kookabug_daemon.adopt`). 검증 실행은
  Kookabug가 고른다 — 요청은 실행 ID를 받지 않는다. 요청이 준 음성 프레임은 **이 연결이 만든** 정지
  화면만이다
- `adopt.revert`: 채택 뒤 바이트일 때만 원래 바이트로 한 번
- `evidence.pin`: 실행 기록 → 가림 처리한 최소 묶음. 지우거나 고치는 메서드는 없다
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, Final

from kookabug_core import adopt as rules
from kookabug_core.filetx import TxError
from kookabug_core.knowledge.formats import Actor, KnowledgeError, secret_checker
from kookabug_core.workspace import Workspace, WorkspaceError, default_secrets
from kookabug_daemon.adopt import Adopter, RunVerifier, pin_run, request_negatives, secret_keys_of
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.protocol import RequestFailed

__all__ = ["METHODS", "failed", "guarded"]

_PASS: Final = frozenset(
    {
        "revision_conflict",
        "already_reverted",
        "change_not_active",
        "nothing_to_revert",
        "evidence_missing",
        "recovery_pending",
        "knowledge_busy",
        "policy_path",
        "exists",
        "secret_in_text",
        "secret_unchecked",
    }
)


def failed(exc: KnowledgeError | TxError) -> RequestFailed:
    code = exc.code
    if code == "unknown_id":
        return RequestFailed(
            "not_found", exc.message, path=str(getattr(exc, "fields", {}).get("id", ""))
        )
    if code == "path_outside_workspace":
        return RequestFailed("policy_path", exc.message)
    if code == "format":
        return RequestFailed("validation_failed", exc.message, diagnostics=[])
    if code == "revision_conflict":
        return RequestFailed("revision_conflict", exc.message, revision=None)
    if code in _PASS:
        return RequestFailed(code, exc.message)
    return RequestFailed("io_error", exc.message, message=exc.message)


def guarded(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except (KnowledgeError, TxError) as exc:
        raise failed(exc) from exc
    except WorkspaceError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc


def actor_of(call: Call) -> Actor:
    p = call.principal
    if p.kind == "agent":
        return Actor(
            "agent", p.id, client=call.daemon.connection_name(call.connection) or None, job=p.job
        )
    return Actor("human", p.id)


def _negatives(call: Call, items: list[Mapping[str, Any]]) -> list[Any]:
    """요청 음성 프레임: 이 연결이 만든 정지 화면만 (다른 연결·녹화 프레임은 거부)."""
    out: list[tuple[str, Any, str, str]] = []
    for item in items:
        frame = call.daemon.frames.get(str(item["frame_id"]))
        if frame.owner != call.connection or frame.origin == "recorder":
            raise RequestFailed(
                "frame_not_owned",
                "음성 대조에는 이 연결이 만든 정지 화면만 쓴다",
                frame_id=frame.frame_id,
            )
        out.append(
            (frame.frame_id, frame.pixels, f"connection:{call.connection}", str(item["note"]))
        )
    return request_negatives(out)


def _checker(call: Call) -> Any:
    """보호 기록의 비밀값 키로 만든 글자 검사기 (채택 기록·감사 이력·증거 묶음)."""
    guard = call.daemon.guard
    workspace = Workspace.open(call.daemon.root)
    return secret_checker(
        set(getattr(guard, "secret_keys", ()) or ()),
        default_secrets(workspace),
        blocked=bool(getattr(guard, "save_blocked", False)),
    )


async def _request(call: Call) -> dict[str, Any]:
    p = call.params
    extra = _negatives(call, list(p.get("negatives") or []))
    try:
        check = _checker(call)
    except WorkspaceError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
    adopter = Adopter(call.daemon.root, RunVerifier(call.daemon.run_manager), check_secrets=check)
    return await asyncio.to_thread(
        guarded, adopter.request, str(p["case"]), str(p["change"]), extra
    )


async def _revert(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(
        guarded, rules.revert, call.daemon.root, str(call.params["adoption"]), by=call.principal.id
    )


async def _list(call: Call) -> dict[str, Any]:
    found = await asyncio.to_thread(guarded, rules.list_adoptions, call.daemon.root)
    return {"adoptions": found}


def _pin_sync(call: Call) -> dict[str, Any]:
    p = call.params
    run_id = str(p["run"])
    where = call.daemon.run_manager.locate(run_id)
    guard = call.daemon.guard
    workspace = Workspace.open(call.daemon.root)
    keys = set(getattr(guard, "secret_keys", ()) or ()) | secret_keys_of(where.folder)
    check = secret_checker(
        keys, default_secrets(workspace), blocked=bool(getattr(guard, "save_blocked", False))
    )

    def guard_of(pixels: Any) -> str:
        from kookabug_daemon.frames import EditorFrame

        size = (int(pixels.shape[1]), int(pixels.shape[0]))
        verdict = guard.check(EditorFrame("evidence", pixels, size, 96, "", origin="run"))
        return "clear" if verdict.clear else str(verdict.reason or "frame_protected")

    actor = actor_of(call)
    by = {"kind": actor.kind} | ({"id": actor.id} if actor.id else {})
    step = p.get("step")
    return pin_run(
        call.daemon.root,
        where.folder,
        where.run_id,
        step=None if step is None else str(step),
        note=str(p["note"]),
        by=by,
        actor=actor,
        check_secrets=check,
        guard_of=guard_of,
    )


async def _pin(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(guarded, _pin_sync, call)


METHODS: Final[dict[str, MethodSpec]] = {
    "adopt.request": MethodSpec(_request),
    "adopt.revert": MethodSpec(_revert),
    "adoptions.list": MethodSpec(_list),
    "evidence.pin": MethodSpec(_pin),
}
