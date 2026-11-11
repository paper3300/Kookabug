"""`sources.list`·`sources.read` (UX2 A) — 등록된 원본 읽기. 엄격: 경계·비밀값.

Agent 도구 `kb_source_list`·`kb_source_read`(툴셋 core, 읽기). 본체는 코어
`knowledge.source_read`: `kookabug.json#sources`·`local.json`에 등록된 원본 루트 아래만,
링크·정션·`..`·파생 폴더·URL은 거부, 쓰기 없음. 돌려주는 글은 `agent.log`와 같은 가림(작업 토큰
원문 + 워크스페이스 비밀값 공급자)을 하고, 가림 값을 못 모으면 글을 주지 않는다
(`secret_unchecked`).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Final

from kookabug_core.knowledge import source_read
from kookabug_core.workspace import Workspace
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods.knowledge import run_guarded

__all__ = ["METHODS", "secret_values"]


def secret_values(call: Call) -> list[str]:
    """가림 값: daemon 메모리의 작업 토큰 원문 + 워크스페이스 비밀값 공급자 값 (`agent.log`와 같다).
    못 모으면 예외 — 부르는 쪽은 글을 주지 않는다."""
    from kookabug_core.agent_job.runner import known_secrets

    jobs = getattr(call.daemon, "jobs", None)
    tokens = [] if jobs is None else list(jobs.secret_values())
    return tokens + list(known_secrets(call.daemon.root, os.environ))


def _arg(call: Call) -> str:
    return f"{call.params.get('source', '')}:{call.params.get('path', '')}"


def _list_sync(call: Call) -> dict[str, Any]:
    workspace = Workspace.open(call.daemon.root)
    source = call.params.get("source")
    if source is None:
        return {"sources": source_read.list_sources(workspace)}
    return source_read.list_source(workspace, str(source), str(call.params.get("path") or ""))


async def _list(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(run_guarded, _list_sync, call)


def _read_sync(call: Call) -> dict[str, Any]:
    p = call.params
    return source_read.read_source(
        Workspace.open(call.daemon.root),
        str(p["source"]),
        str(p.get("path") or ""),
        offset=int(p.get("offset") or 0),
        secrets=lambda: secret_values(call),
    )


async def _read(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(run_guarded, _read_sync, call)


METHODS: Final[dict[str, MethodSpec]] = {
    "sources.list": MethodSpec(_list, _arg),
    "sources.read": MethodSpec(_read, _arg),
}
