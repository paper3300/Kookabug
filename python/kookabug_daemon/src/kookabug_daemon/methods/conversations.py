"""`conversations.*` (UX4) — 에이전트 패널 이전 대화. 사람 전용(`ui_only`, Agent 연결은 판정
전 거부).

본체는 코어 `conversations`: `.kookabug/conversations/<id>.json`(이 PC). 저장 전에 `agent.log`와
같은 가림(작업 토큰 원문 + 워크스페이스 비밀값 공급자)을 하고, 가림 값을 못 모으면 쓰지 않는다
(`secret_unchecked`).
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

from kookabug_core import conversations, filetx
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods.sources import secret_values
from kookabug_daemon.protocol import RequestFailed

__all__ = ["METHODS"]


def _guarded(fn: Any, call: Call) -> Any:
    try:
        return fn(call)
    except conversations.ConversationError as exc:
        raise RequestFailed(exc.code if exc.code != "bad_id" else "not_found", exc.message) from exc
    except filetx.TxError as exc:
        raise RequestFailed(
            "path_outside_workspace", exc.message, path=str(exc.fields.get("path", ""))
        ) from exc
    except OSError as exc:
        raise RequestFailed("io_error", f"대화 파일을 다루지 못했다: {exc}") from exc


def _list_sync(call: Call) -> dict[str, Any]:
    return {"conversations": conversations.list_summaries(call.daemon.root)}


def _get_sync(call: Call) -> dict[str, Any]:
    return {"conversation": conversations.get(call.daemon.root, str(call.params["id"]))}


def _save_sync(call: Call) -> dict[str, Any]:
    try:
        secrets: list[str] | None = secret_values(call)
    except Exception:
        secrets = None  # 가림 값을 확인하지 못하면 쓰지 않는다
    summary = conversations.save(call.daemon.root, call.params["conversation"], secrets)
    return {"conversation": summary}


def _delete_sync(call: Call) -> dict[str, Any]:
    return {"deleted": conversations.delete(call.daemon.root, str(call.params["id"]))}


def _async(fn: Any) -> Any:
    async def handler(call: Call) -> dict[str, Any]:
        return await asyncio.to_thread(_guarded, fn, call)

    return handler


METHODS: Final[dict[str, MethodSpec]] = {
    "conversations.list": MethodSpec(_async(_list_sync)),
    "conversations.get": MethodSpec(_async(_get_sync)),
    "conversations.save": MethodSpec(_async(_save_sync)),
    "conversations.delete": MethodSpec(_async(_delete_sync)),
}
