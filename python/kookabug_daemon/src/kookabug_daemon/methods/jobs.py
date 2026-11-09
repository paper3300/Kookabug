"""`job.begin`·`job.end`·`job.note` (M8 계획 3.9·3.13, 9장 R7·R8 일부).

- `job.begin`·`job.end`는 사람 전용(`ui_only` + `AGENT_DENIED`): Agent 연결은 작업을 만들거나 끝내지
  못한다(재귀 금지, E11). `agent-job` CLI가 `ui` 연결로 부른다
- `job.end`는 토큰을 **먼저** 폐기한 뒤 그 작업의 실행을 취소한다(R8 순서의 앞 두 단계 — 보고 생성은
  B5)
- `job.note`(`kb_report_note`)는 작업 토큰 연결 전용(`job_only`). 글자 검사를 지난 글만 둔다
- `job.finish`·`jobs.list`는 B5가 붙인다
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

from kookabug_core.knowledge.formats import KnowledgeError
from kookabug_daemon.jobs import DEFAULT_TTL_S
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods.adopt import checker_of
from kookabug_daemon.protocol import RequestFailed

__all__ = ["METHODS"]


async def _begin(call: Call) -> dict[str, Any]:
    p = call.params
    toolsets = p.get("toolsets")
    job, token = call.daemon.jobs.begin(
        str(p["playbook"]),
        basis=None if p.get("basis") is None else str(p["basis"]),
        trigger=str(p.get("trigger", "manual")),
        budget={str(k): int(v) for k, v in dict(p.get("budget") or {}).items()},
        toolsets=None if toolsets is None else [str(t) for t in toolsets],
        ttl_s=float(p.get("ttl_s", DEFAULT_TTL_S)),
    )
    return {"job": job.id, "agent_id": job.agent, "token": token, "expires_at": job.expires_at}


async def _end(call: Call) -> dict[str, Any]:
    job_id = str(call.params["job"])
    # 토큰 먼저 (그 뒤 이 작업 연결의 요청은 모두 job_token_invalid) → 실행 취소
    job = call.daemon.jobs.revoke(job_id, str(call.params["reason"]))
    if job is None:
        raise RequestFailed("not_found", "모르는 작업이다", path=job_id)
    cancelled = await asyncio.to_thread(call.daemon.run_manager.cancel_job, job_id)
    return {"job": job_id, "cancelled": cancelled}


def _note_sync(call: Call) -> dict[str, Any]:
    job = call.principal.job
    if job is None:
        raise RequestFailed("job_only", "보고 메모는 작업 토큰 연결만 쓴다")
    text = str(call.params["text"])
    try:
        checker_of(call)([("text", text)])
    except KnowledgeError as exc:
        raise RequestFailed(exc.code, exc.message) from exc
    return {"job": job, "bytes": call.daemon.jobs.note(job, text)}


async def _note(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_note_sync, call)


METHODS: Final[dict[str, MethodSpec]] = {
    "job.begin": MethodSpec(_begin),
    "job.end": MethodSpec(_end),
    "job.note": MethodSpec(_note),
}
