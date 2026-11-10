"""작업 토큰과 작업 감독 (M8 계획 3.9·3.14, 9장 R7·R8) — 엄격: Agent 권한·입력 안전.

`agent-job`(사람 쪽 CLI, `ui` 연결)이 `job.begin`으로 작업을 만들면 daemon이 32바이트 무작위 토큰을
준다. 외부 Agent CLI의 MCP 연결은 그 토큰(`session.hello`의 `client.job_token`)으로만 작업에
묶인다 — 자기 신고 ID로는 묶이지 않는다.

토큰 계약(R7) = {워크스페이스, 작업 ID, 주체 Agent(`job:<작업>`), 허용 범위(툴셋), 만료}.

- 묶기는 sha256으로 한다. 원문은 `job.begin` 응답과 **daemon 메모리**에만 있다 — 글자 검사기가
  원문을 걸러 메모·지식·위키·보고에 남지 않게 한다(R9). 원문은 그 작업의 보고를 쓴 뒤 지운다.
  디스크에는 원문도 해시도 쓰지 않는다
- 묶기(`bind`): 해시가 없거나, 만료·폐기됐거나, 다른 워크스페이스의 작업이거나, 연결의 `client.id`가
  토큰의 주체와 다르면(다른 작업의 토큰) `job_token_invalid` — 연결을 닫는다
- 연결 뒤에도 요청마다 살아 있는지 본다(`require_alive`): 만료·폐기된 작업의 연결은 그 뒤 모든
  요청이 `job_token_invalid`

작업 감독(R8):

- 작업을 만든 연결이 **소유 연결**이다. 소유 연결은 `job.heartbeat`를 보낸다(기본 30초, 3번 놓치면
  유실). 소유 연결이 끊기거나 heartbeat를 놓치거나 기한(시간 예산 + 여유)을 넘기면 감독이 끝낸다
- 부모 유실·`job.finish`·`job.end`·기한 초과·예산 초과는 **같은 멱등 종료 경로**
  (`JobSupervisor.end`)를 지난다: 토큰 폐기 → 그 작업의 실행·채택 검증 취소 → 감독자 입력
  복구 완료(실행 마무리 대기, 못 하면 강제 복구) → 보고. 두 번째 호출은 첫 결과를 기다려 그대로
  돌려준다
- 입력 복구를 확인하지 못하면 끝난 것이 아니다: 상태는 `ending`, 보고·끝 알림을 내지 않고 작업
  슬롯도 쥔다. 감독(`retry_unsettled`)이 강제 복구를 다시 해 확인한 뒤에 마저 끝낸다
- 워크스페이스당 끝나지 않은 작업(`running`·`ending`)은 하나다 — `begin`이 원자적으로
  `job_active`로 거부한다
- 예산: 실행 수(`run.start`·자동 채택 검증 실행)는 `take_run`이 원자적으로 집계·강제하고, Kookabug
  도구 호출 수는 `count_call`이 센다
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol

from kookabug_core.knowledge.formats import new_id
from kookabug_core.permissions import Principal
from kookabug_daemon.protocol import RequestFailed

__all__ = [
    "DEADLINE_GRACE_S",
    "DEFAULT_TTL_S",
    "HEARTBEAT_MISSES",
    "HEARTBEAT_S",
    "JOB_NOTE_MAX",
    "Job",
    "JobHost",
    "JobRegistry",
    "JobSupervisor",
    "agent_id_of",
]

log = logging.getLogger(__name__)

DEFAULT_TTL_S: Final = 4 * 60 * 60
"""토큰 기본 수명 (작업 예산 60분보다 넉넉히. 작업이 끝나면 먼저 폐기한다)."""
JOB_NOTE_MAX: Final = 4096
"""`job.note` 글 최대 바이트 (3.11 notes 4 KB)."""
HEARTBEAT_S: Final = 30.0
"""소유 연결 heartbeat 간격 (R8). `HEARTBEAT_MISSES`번 놓치면 유실이다."""
HEARTBEAT_MISSES: Final = 3
DEADLINE_GRACE_S: Final = 60.0
"""시간 예산 뒤 daemon 기한까지의 여유 (agent-job이 먼저 끝내고 `job.finish`를 보낼 시간)."""
RECOVERY_WAIT_S: Final = 120.0
"""종료 경로가 실행·채택 마무리(감독자 입력 복구 포함)를 기다리는 한도."""
RETRY_S: Final = 5.0
"""입력 복구를 확인하지 못한 작업의 강제 복구 재시도 간격."""


def agent_id_of(job: str) -> str:
    """작업 토큰 연결의 주체 ID (`kookabug mcp --agent-id job:<작업>`)."""
    return f"job:{job}"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


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
    owner: int | None = None
    """소유 연결 번호 (`job.begin`을 부른 연결, R8). None이면 감독하지 않는다(검사 대역)."""
    profile: str | None = None
    """Agent 프로필 이름 (보고 `agent`)."""
    started: float = 0.0
    started_at: str = ""
    last_beat: float = 0.0
    deadline: float | None = None
    """daemon 기한 (`time.monotonic`): 시간 예산 + 여유. None이면 시간 예산 없음."""
    runs: int = 0
    tool_calls: int = 0
    tools_seen: set[str] = field(default_factory=set[str])
    """이 작업 연결이 부른 도구 이름 (`probe` 성공 판정 — 모델 응답을 해석하지 않는다)."""
    stalled: set[str] = field(default_factory=set[str])
    budget_hit: bool = False
    state: str = "running"
    """`running` → `ending`(종료 경로, 입력 복구 확인 전) → 끝 상태."""
    target: str | None = None
    """종료 경로가 정한 끝 상태 (확인 뒤 `state`가 된다)."""
    prep: str | None = None
    pending_runs: list[str] = field(default_factory=list[str])
    """종료 경로가 취소한 실행 (입력 복구를 확인할 대상)."""
    last_try: float = 0.0
    attempts: int = 0
    drive: threading.Lock = field(default_factory=threading.Lock)
    """복구 확인 → 보고는 한 스레드만 (종료 호출·재시도가 겹쳐도)."""
    ending: threading.Event = field(default_factory=threading.Event)
    ended: threading.Event = field(default_factory=threading.Event)
    """복구를 확인하고 보고를 쓴 뒤에만 선다 — 작업 슬롯이 풀린다."""
    result: dict[str, Any] | None = None

    def alive(self, now: float) -> bool:
        return self.revoked is None and now < self.expires

    def used(self, now: float) -> dict[str, int]:
        minutes = 0 if not self.started else int((now - self.started) // 60)
        return {"runs": self.runs, "tool_calls": self.tool_calls, "minutes": minutes}


class JobRegistry:
    """이 daemon의 작업 (메모리). daemon이 다시 시작되면 모든 토큰이 무효다 — 남은 작업은 다음
    daemon 시작 때 `interrupted`로 끝낸다(`agent-job`이 살아 있으면 그쪽이 끝낸다)."""

    def __init__(self, workspace: str, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.workspace = workspace
        self._clock = clock
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._by_digest: dict[str, str] = {}
        self._tokens: dict[str, str] = {}
        """작업 → 토큰 원문 (글자 검사 대상, R9). 보고를 쓴 뒤 `forget_token`이 지운다."""
        self.on_budget: Callable[[Job], None] | None = None
        """실행 예산에 처음 막혔을 때 (`job.budget` 알림)."""

    def now(self) -> float:
        return self._clock()

    def begin(
        self,
        playbook: str,
        *,
        basis: str | None = None,
        trigger: str = "manual",
        budget: Mapping[str, int] | None = None,
        toolsets: Collection[str] | None = None,
        ttl_s: float = DEFAULT_TTL_S,
        owner: int | None = None,
        profile: str | None = None,
    ) -> tuple[Job, str]:
        """새 작업과 토큰 원문. 끝나지 않은 작업(`running`·`ending`)이 있으면 `job_active`
        (워크스페이스당 하나, 원자적). 원문은 글자 검사용으로 메모리에만 둔다."""
        token = secrets.token_urlsafe(32)
        budget = dict(budget or {})
        with self._lock:
            busy = next((j for j in self._jobs.values() if not j.ended.is_set()), None)
            if busy is not None:
                raise RequestFailed(
                    "job_active",
                    f"이 워크스페이스에 끝나지 않은 작업 {busy.id}({busy.state})이(가) 있다",
                )
            job_id = new_id("j")
            while job_id in self._jobs:
                job_id = new_id("j")
            now = self._clock()
            moment = datetime.now(UTC)
            minutes = budget.get("minutes")
            job = Job(
                id=job_id,
                workspace=self.workspace,
                agent=agent_id_of(job_id),
                playbook=playbook,
                basis=basis,
                trigger=trigger,
                budget=budget,
                toolsets=None if toolsets is None else frozenset(toolsets) | {"core"},
                expires=now + ttl_s,
                expires_at=_iso(moment + timedelta(seconds=ttl_s)),
                owner=owner,
                profile=profile,
                started=now,
                started_at=_iso(moment),
                last_beat=now,
                deadline=None if minutes is None else now + minutes * 60 + DEADLINE_GRACE_S,
            )
            self._jobs[job_id] = job
            self._by_digest[_digest(token)] = job_id
            self._tokens[job_id] = token
        return job, token

    def secret_values(self) -> list[str]:
        """메모리의 토큰 원문 전부 (살아 있는 것 + 폐기했지만 보고를 아직 쓰지 않은 것)."""
        with self._lock:
            return list(self._tokens.values())

    def forget_token(self, job_id: str) -> None:
        """보고를 쓴 뒤 그 작업의 토큰 원문을 지운다 (해시는 남아 폐기된 토큰으로 판정된다)."""
        with self._lock:
            self._tokens.pop(job_id, None)

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

    def all(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.id)

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

    # ------------------------------------------------------------ 감독 (R8)

    def heartbeat(self, job_id: str, connection: int) -> Job:
        """소유 연결의 heartbeat. 다른 연결이면 `permission_denied`, 끝난 작업이면 `job_ended`."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise RequestFailed("not_found", "모르는 작업이다", path=job_id)
            if job.owner != connection:
                raise RequestFailed("permission_denied", "작업을 만든 연결만 heartbeat를 보낸다")
            if job.state != "running" or job.ending.is_set():
                raise RequestFailed("job_ended", f"이미 끝난 작업이다 ({job.state})")
            job.last_beat = self._clock()
            return job

    def overdue(self, heartbeat_s: float) -> list[tuple[Job, str]]:
        """감독이 끝낼 작업: (작업, 끝 상태). heartbeat 유실 → interrupted, 기한 초과 →
        budget_exhausted."""
        now = self._clock()
        out: list[tuple[Job, str]] = []
        with self._lock:
            for job in self._jobs.values():
                if job.ending.is_set() or job.owner is None:
                    continue
                if now - job.last_beat > heartbeat_s * HEARTBEAT_MISSES:
                    out.append((job, "interrupted"))
                elif job.deadline is not None and now > job.deadline:
                    out.append((job, "budget_exhausted"))
        return out

    def start_ending(self, job: Job) -> bool:
        """종료 경로에 처음 들어가면 True (그 뒤 호출은 False — 첫 결과를 기다린다)."""
        with self._lock:
            if job.ending.is_set():
                return False
            # 감독 재시도(`unsettled`)가 첫 종료 호출과 겹쳐 먼저 몰지 않게 시도 시각을 지금으로
            job.last_try = self._clock()
            job.ending.set()
            return True

    def unsettled(self, every_s: float = RETRY_S) -> list[Job]:
        """종료 경로에 들어갔지만 입력 복구를 확인하지 못한 작업 (마지막 시도 뒤 `every_s`가 지난
        것)."""
        now = self._clock()
        with self._lock:
            return [
                j
                for j in self._jobs.values()
                if j.ending.is_set() and not j.ended.is_set() and now - j.last_try >= every_s
            ]

    def owned_by(self, connection: int) -> list[Job]:
        with self._lock:
            return [
                j for j in self._jobs.values() if j.owner == connection and not j.ending.is_set()
            ]

    def basis_of(self, job_id: str) -> str | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else job.basis

    def active_id(self) -> str | None:
        """끝나지 않은 작업(`running`·`ending`)의 ID (없으면 None) — 작업 중 비작업 Agent 거부."""
        with self._lock:
            return next((j.id for j in self._jobs.values() if not j.ended.is_set()), None)

    def require_running(self, job_id: str) -> None:
        """종료 경로에 들어간 작업이면 `job_token_invalid` (시작 잠금 안에서 부른다 — 종료 경로의
        실행 취소가 시작 잠금을 잡으므로, 그 뒤에 오는 시작은 여기서 막힌다)."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.ending.is_set() or job.revoked is not None:
                raise _invalid("작업이 끝났다 — 새 실행·입력을 시작하지 않는다")

    def take_run(self, job_id: str) -> None:
        """실행 하나를 예산에서 쓴다 (원자적). 상한이면 `job_budget_exhausted` — 쓰지 않는다."""
        notify: Job | None = None
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.ending.is_set() or job.revoked is not None:
                raise _invalid("작업이 끝났다 — 새 실행을 시작하지 않는다")
            limit = job.budget.get("runs")
            if limit is not None and job.runs >= limit:
                if not job.budget_hit:
                    job.budget_hit = True
                    notify = job
                error = RequestFailed(
                    "job_budget_exhausted",
                    f"작업 실행 예산({job.runs}/{limit}회)을 다 썼다 — 새 실행을 시작하지 않는다",
                )
            else:
                job.runs += 1
                return
        if notify is not None and self.on_budget is not None:
            self.on_budget(notify)
        raise error

    def count_call(self, job_id: str, tool: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.tool_calls += 1
                job.tools_seen.add(tool)

    def mark_stalled(self, job_id: str, test: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.stalled.add(test)

    def describe(self, job: Job) -> dict[str, Any]:
        """사람 화면용 (토큰 없음)."""
        now = self._clock()
        return {
            "job": job.id,
            "playbook": job.playbook,
            "trigger": job.trigger,
            "basis": job.basis,
            "agent": job.profile,
            "started_at": job.started_at,
            "expires_at": job.expires_at,
            "state": job.state,
            "budget": dict(job.budget),
            "used": job.used(now),
            # 보고를 쓰지 못하고 끝났으면 null (끝나기 전에도 null)
            "report": None if job.result is None else job.result.get("report"),
        }


class JobHost(Protocol):
    """종료 경로가 daemon에서 쓰는 것 (검사가 대역을 넣는다)."""

    def cancel_job_runs(self, job: str) -> list[str]:
        """그 작업의 실행과 채택 검증 실행을 취소한다 (채택 요청에는 취소 표시)."""
        ...

    def wait_job_settled(self, job: str, runs: list[str], timeout: float) -> bool:
        """취소한 실행의 감독자 마무리(입력 복구 포함)와 채택 요청 스레드가 끝나기를 기다린다.
        복구를 **확인**했을 때만 True (복구 기록 오류·임대권을 못 얻어 떼지 못함은 False)."""
        ...

    def force_settle(self, job: str, runs: list[str], timeout: float) -> bool:
        """감독자 강제 복구 경로로 다시 한다 (runner 하드 종료 → 복구, 복구 오류면 복구 경로를
        다시). 모두 확인하면 True."""
        ...

    def write_report(self, job: Job, state: str, prep: str | None) -> str | None:
        """보고를 쓰고 렌더 경로를 돌려준다 (못 쓰면 None — 종료는 계속한다)."""
        ...

    def job_changed(self, job: Job) -> None: ...


class JobSupervisor:
    """같은 멱등 종료 경로 하나 (R8): 토큰 폐기 → 실행 취소 → 입력 복구 완료 → 보고.

    입력 복구를 확인하지 못하면 `ending`에 머문다(보고·끝 알림·슬롯 해제 없음). 감독이
    `retry_unsettled`로 강제 복구를 다시 해 확인한 뒤에 마저 끝낸다. 겹친 종료 호출은 같은 완료를
    기다린다."""

    def __init__(self, jobs: JobRegistry, host: JobHost) -> None:
        self.jobs = jobs
        self.host = host

    def end(
        self, job_id: str, state: str, *, prep: str | None = None, wait_s: float = RECOVERY_WAIT_S
    ) -> dict[str, Any]:
        """작업을 끝낸다 (막히는 호출). 이미 끝나는 중이면 그 완료를 기다려 돌려준다 — 기다리는
        동안 끝나지 않았으면 `state: ending`(`settled: false`)."""
        job = self.jobs.get(job_id)
        if job is None:
            raise RequestFailed("not_found", "모르는 작업이다", path=job_id)
        if not self.jobs.start_ending(job):
            job.ended.wait(wait_s + 30)
            return self.snapshot(job)
        # ① 토큰 먼저: 그 뒤 이 작업 연결의 모든 요청은 job_token_invalid
        self.jobs.revoke(job.id, state)
        job.target, job.prep = state, prep
        job.state = "ending"
        # ② 그 작업의 실행·채택 검증 취소 (실패해도 다음 단계로 — 확인은 ③이 한다)
        try:
            job.pending_runs = list(self.host.cancel_job_runs(job.id))
        except Exception:
            log.exception("작업 %s: 실행 취소 중 오류", job.id)
        self._drive(job, wait_s, block=True)
        return self.snapshot(job)

    def retry_unsettled(self, wait_s: float = 10.0) -> None:
        """입력 복구를 확인하지 못한 작업마다 강제 복구를 다시 한다 (감독 스레드가 부른다 — 다른
        스레드가 몰고 있으면 건너뛴다)."""
        for job in self.jobs.unsettled():
            self._drive(job, wait_s)

    def snapshot(self, job: Job) -> dict[str, Any]:
        if job.result is not None:
            return dict(job.result)
        return {
            "job": job.id,
            "state": job.state,
            "cancelled": list(job.pending_runs),
            "settled": False,
            "used": job.used(self.jobs.now()),
            "report": None,
            "probe_ok": "kb_project_info" in job.tools_seen,
        }

    def _drive(self, job: Job, wait_s: float, *, block: bool = False) -> None:
        """③ 입력 복구 확인 → ④ 보고 → 끝 알림·슬롯 해제. 확인하지 못하면 아무것도 내지 않는다.
        `block`(첫 종료 호출): 다른 스레드가 몰고 있으면 그 시도가 끝나기를 기다린 뒤 이어서
        한다."""
        acquired = job.drive.acquire(timeout=wait_s * 2 + 30) if block else job.drive.acquire(False)
        if not acquired:
            return  # 다른 스레드가 하고 있다 (end는 snapshot으로, 재시도는 다음 회차로)
        finished = False
        try:
            if job.ended.is_set():
                return
            job.last_try = self.jobs.now()
            job.attempts += 1
            settled = False
            try:
                settled = self.host.wait_job_settled(job.id, job.pending_runs, wait_s)
            except Exception:
                log.exception("작업 %s: 실행 마무리 대기 중 오류", job.id)
            if not settled:
                # 감독자 강제 복구 경로로 다시 한다
                try:
                    settled = self.host.force_settle(job.id, job.pending_runs, wait_s)
                except Exception:
                    log.exception("작업 %s: 강제 복구 중 오류", job.id)
            if not settled:
                log.warning(
                    "작업 %s: 입력 복구를 확인하지 못했다 (%d번째) — ending에 머문다",
                    job.id,
                    job.attempts,
                )
                job.last_try = self.jobs.now()
                return
            state = job.target or "interrupted"
            rendered: str | None = None
            try:
                rendered = self.host.write_report(job, state, job.prep)
            except Exception:
                # 복구는 확인됐다: 보고만 없이 끝내고 슬롯을 푼다 (영구 IO 실패로 막히지 않게)
                log.warning("작업 %s: 보고를 쓰지 못했다 — report 없이", job.id, exc_info=True)
            self.jobs.forget_token(job.id)
            job.state = state
            job.result = {
                "job": job.id,
                "state": state,
                "cancelled": list(job.pending_runs),
                "settled": True,
                "used": job.used(self.jobs.now()),
                "report": rendered,
                "probe_ok": "kb_project_info" in job.tools_seen,
            }
            job.ended.set()
            finished = True
        finally:
            job.drive.release()
        if finished:
            self.host.job_changed(job)


def _invalid(text: str) -> RequestFailed:
    return RequestFailed("job_token_invalid", text)
