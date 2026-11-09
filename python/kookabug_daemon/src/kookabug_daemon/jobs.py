"""작업 토큰 (M8 계획 3.9·3.14, 9장 R7) — 엄격: Agent 권한.

`agent-job`(사람 쪽 CLI, `ui` 연결)이 `job.begin`으로 작업을 만들면 daemon이 32바이트 무작위 토큰을
준다. 외부 Agent CLI의 MCP 연결은 그 토큰(`session.hello`의 `client.job_token`)으로만 작업에
묶인다 — 자기 신고 ID로는 묶이지 않는다.

토큰 계약(R7) = {워크스페이스, 작업 ID, 주체 Agent(`job:<작업>`), 허용 범위(툴셋), 만료}.

- daemon은 토큰 원문을 두지 않고 sha256만 둔다(로그·덤프에 원문이 남지 않게). 원문은 `job.begin`
  응답에만 있다
- 묶기(`bind`): 해시가 없거나, 만료·폐기됐거나, 다른 워크스페이스의 작업이거나, 연결의 `client.id`가
  토큰의 주체와 다르면(다른 작업의 토큰) `job_token_invalid` — 연결을 닫는다
- 연결 뒤에도 요청마다 살아 있는지 본다(`require_alive`): 만료·폐기된 작업의 연결은 그 뒤 모든
  요청이 `job_token_invalid`
- `revoke`는 멱등이다. 작업을 끝내는 경로(`job.end`)는 토큰을 **먼저** 폐기한 뒤 실행을 취소한다(R8)
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from kookabug_core.knowledge.formats import new_id
from kookabug_core.permissions import Principal
from kookabug_daemon.protocol import RequestFailed

__all__ = ["DEFAULT_TTL_S", "JOB_NOTE_MAX", "Job", "JobRegistry", "agent_id_of"]

DEFAULT_TTL_S: Final = 4 * 60 * 60
"""토큰 기본 수명 (작업 예산 60분보다 넉넉히. agent-job이 끝나면 먼저 폐기한다)."""
JOB_NOTE_MAX: Final = 4096
"""`job.note` 글 최대 바이트 (3.11 notes 4 KB)."""


def agent_id_of(job: str) -> str:
    """작업 토큰 연결의 주체 ID (`kookabug mcp --agent-id job:<작업>`)."""
    return f"job:{job}"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class Job:
    id: str
    workspace: str
    agent: str
    playbook: str
    basis: str | None
    trigger: str
    budget: Mapping[str, int]
    toolsets: frozenset[str] | None
    """허용 범위: 이 작업 연결이 켤 수 있는 툴셋 (None이면 제한 없음)."""
    expires: float
    """만료 시각 (`time.monotonic`)."""
    expires_at: str
    revoked: str | None = None
    """폐기 이유 (살아 있으면 None)."""
    notes: list[str] = field(default_factory=list[str])

    def alive(self, now: float) -> bool:
        return self.revoked is None and now < self.expires


class JobRegistry:
    """이 daemon의 작업 (메모리). daemon이 다시 시작되면 모든 토큰이 무효다(작업은 `interrupted`,
    B5)."""

    def __init__(self, workspace: str, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.workspace = workspace
        self._clock = clock
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._by_digest: dict[str, str] = {}

    def begin(
        self,
        playbook: str,
        *,
        basis: str | None = None,
        trigger: str = "manual",
        budget: Mapping[str, int] | None = None,
        toolsets: Collection[str] | None = None,
        ttl_s: float = DEFAULT_TTL_S,
    ) -> tuple[Job, str]:
        """새 작업과 토큰 원문 (원문은 돌려주기만 하고 두지 않는다)."""
        token = secrets.token_urlsafe(32)
        with self._lock:
            job_id = new_id("j")
            while job_id in self._jobs:
                job_id = new_id("j")
            expires_at = datetime.now(UTC) + timedelta(seconds=ttl_s)
            job = Job(
                id=job_id,
                workspace=self.workspace,
                agent=agent_id_of(job_id),
                playbook=playbook,
                basis=basis,
                trigger=trigger,
                budget=dict(budget or {}),
                toolsets=None if toolsets is None else frozenset(toolsets) | {"core"},
                expires=self._clock() + ttl_s,
                expires_at=expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            self._jobs[job_id] = job
            self._by_digest[_digest(token)] = job_id
        return job, token

    def bind(self, token: str, client_id: str) -> Job:
        """hello의 토큰 → 살아 있는 작업. 아니면 `job_token_invalid` (이유는 고정 글자)."""
        with self._lock:
            job_id = self._by_digest.get(_digest(token))
            job = None if job_id is None else self._jobs.get(job_id)
            if job is None:
                raise _invalid("모르는 작업 토큰이다")
            if job.workspace != self.workspace:
                raise _invalid("다른 워크스페이스의 작업 토큰이다")
            if not job.alive(self._clock()):
                raise _invalid("작업 토큰이 만료됐거나 폐기됐다")
            if client_id != job.agent:
                raise _invalid("작업 토큰의 주체와 연결의 ID가 다르다 (다른 작업의 토큰)")
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def require_alive(self, principal: Principal) -> Job | None:
        """작업 연결이면 그 작업이 아직 살아 있어야 한다 (아니면 `job_token_invalid`)."""
        if principal.job is None:
            return None
        with self._lock:
            job = self._jobs.get(principal.job)
            if job is None or not job.alive(self._clock()) or job.agent != principal.id:
                raise _invalid("작업이 끝났거나 토큰이 만료·폐기됐다 — 이 연결은 더 쓸 수 없다")
            return job

    def revoke(self, job_id: str, reason: str) -> Job | None:
        """토큰을 폐기한다 (멱등). 없는 작업이면 None."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.revoked is None:
                job.revoked = reason
            return job

    def note(self, job_id: str, text: str) -> int:
        """보고 요약 글 (마지막 글이 이긴다). 바이트 수."""
        data = text.encode("utf-8")
        if len(data) > JOB_NOTE_MAX:
            raise RequestFailed("too_large", "보고 메모는 4 KB까지다")
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise _invalid("모르는 작업이다")
            job.notes = [text]
        return len(data)

    def describe(self, job: Job) -> dict[str, Any]:
        """사람 화면용 (토큰 없음)."""
        return {
            "job": job.id,
            "playbook": job.playbook,
            "trigger": job.trigger,
            "basis": job.basis,
            "expires_at": job.expires_at,
            "state": "running" if job.alive(self._clock()) else (job.revoked or "expired"),
        }


def _invalid(text: str) -> RequestFailed:
    return RequestFailed("job_token_invalid", text)
