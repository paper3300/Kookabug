"""`agent-job run` 감독 본체 (M8 계획 3.9, 9장 R8·R9) — 엄격: 입력 안전·비밀값.

순서:

1. `jobs.lock`(워크스페이스당 작업 하나, 기다리지 않음 — 있으면 `job_active`)
2. daemon에 `ui` 연결로 붙어 `job.begin` — 이 연결이 소유 연결이다(R8 heartbeat). 사람 입력
   임대권·녹화 중이면 daemon이 토큰 없이 `prep_failed`로 끝내고 보고를 남긴다
3. 작업 폴더에 `prompt.md`(플레이북 + 머리말)·`mcp.json`(토큰 없음)·`job.json`(토큰·인증 값 없음)
4. 외부 CLI를 **멈춘 채 띄워 Job Object에 넣은 뒤** 이어 돌린다 — 손자까지 처음부터 그 Job 안이고,
   끝낼 때 `TerminateJobObject`로 트리 전체를 정리한다(이 프로세스가 죽어도 `KILL_ON_JOB_CLOSE`)
5. 감독: 벽시계 예산, `job.budget` 알림 뒤 유예, daemon이 끝낸 작업(`job.changed`), daemon 연결
   유실, Ctrl+C·`stop` — 모두 CLI 트리를 끝내고 `job.finish`(daemon 종료 경로: 토큰 폐기 → 실행 취소
   → 입력 복구 → 보고)로 간다. daemon이 끝 상태를 줄 때까지(`ending`이면 다시) `jobs.lock`을 쥔다.
   daemon 연결을 잃으면 daemon 프로세스가 없어졌고 입력이 풀렸음을 확인한 뒤에만 `interrupted`
   보고를 직접 쓴다 — 확인하지 못하면 `job.json`에 `recovery_unconfirmed`만 남긴다
6. 표준 출력·오류는 해석하지 않고 `agent.log`에 쓴다: 알려진 비밀값(워크스페이스 비밀값 공급자 값,
   프로필 인증 값, 작업 토큰)을 `***`로 바꾸고(청크 경계를 넘는 값도 — 최대 값 길이만큼 겹쳐 둔다)
   20 MB에서 자른다. 비밀값을 모으지 못하면 원문을 남기지 않는다("가림 불가로 생략")
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Final, Protocol, TextIO

from kookabug_core.agent_job import SECURITY_NOTE, jobdir, profiles
from kookabug_core.agent_job import report as reports

__all__ = [
    "EXIT_ACTIVE",
    "EXIT_DONE",
    "EXIT_ENDED",
    "EXIT_PREP",
    "EXIT_USAGE",
    "LOG_MAX",
    "AgentLog",
    "Connect",
    "DaemonLink",
    "JobOptions",
    "JobOutcome",
    "Redactor",
    "known_secrets",
    "run_job",
]

EXIT_DONE: Final = 0
EXIT_ENDED: Final = 1
"""작업이 `done` 밖의 상태로 끝났다 (failed·cancelled·budget_exhausted·interrupted)."""
EXIT_ACTIVE: Final = 3
EXIT_PREP: Final = 4
EXIT_USAGE: Final = 6
LOG_MAX: Final = 20 * 1024 * 1024
GRACE_S: Final = 30.0
"""`job.budget` 알림 뒤 CLI를 끝내기까지 유예 (3.9)."""
HEARTBEAT_EVERY_S: Final = 10.0
"""소유 연결 heartbeat 간격 (daemon은 30초 간격을 3번 놓치면 유실)."""
FINISH_TIMEOUT_S: Final = 300.0
_SUPPRESSED: Final = "[agent.log: 비밀값을 확인하지 못해 가림 불가로 생략]\n".encode()
_TRUNCATED: Final = "\n[agent.log: 20 MB에서 잘랐다]\n".encode()
_MASK: Final = b"***"


# ---------------------------------------------------------------- 비밀값 가림 (R9)


class Redactor:
    """스트림 하나의 가림: 알려진 값을 `***`로 바꾼다. 청크 경계를 넘는 값을 위해 마지막
    (최대 값 길이 - 1) 바이트를 다음 청크까지 들고 있는다."""

    def __init__(self, values: Iterable[str]) -> None:
        raw = {v.encode("utf-8") for v in values if v}
        # 긴 값부터 (한 값이 다른 값을 담을 때 긴 쪽을 먼저 가린다)
        self.values = sorted(raw, key=len, reverse=True)
        self.keep = max((len(v) for v in self.values), default=1) - 1
        self._carry = b""

    def _scrub(self, data: bytes) -> bytes:
        for value in self.values:
            data = data.replace(value, _MASK)
        return data

    def feed(self, chunk: bytes) -> bytes:
        data = self._scrub(self._carry + chunk)
        if self.keep <= 0:
            self._carry = b""
            return data
        cut = max(0, len(data) - self.keep)
        self._carry = data[cut:]
        return data[:cut]

    def flush(self) -> bytes:
        data = self._scrub(self._carry)
        self._carry = b""
        return data


class AgentLog:
    """`agent.log` 쓰기 (두 스트림이 같은 파일에, 20 MB 상한). `values`가 None이면 원문을 남기지
    않는다."""

    def __init__(self, path: Path, values: list[str] | None, limit: int = LOG_MAX) -> None:
        self.file = path.open("wb")
        self.lock = threading.Lock()
        self.limit = limit
        self.written = 0
        self.values = values
        self.cut = False
        if values is None:
            self.file.write(_SUPPRESSED)
            self.file.flush()

    def _write(self, data: bytes) -> None:
        if not data or self.values is None:
            return
        with self.lock:
            if self.cut:
                return
            room = self.limit - self.written
            if len(data) > room:
                data = data[: max(0, room)]
                self.cut = True
            self.file.write(data)
            self.written += len(data)
            if self.cut:
                self.file.write(_TRUNCATED)
            self.file.flush()

    def pump(self, stream: IO[bytes]) -> None:
        """스트림을 끝까지 읽어 가려 쓴다 (읽기 스레드). 가림 불가면 읽고 버린다."""
        redactor = Redactor(self.values or [])
        fd = stream.fileno()
        while True:
            chunk = os.read(fd, 65536)  # 온 만큼 (줄을 기다리지 않는다 — 가림이 경계를 맡는다)
            if not chunk:
                break
            self._write(redactor.feed(chunk))
        self._write(redactor.flush())

    def close(self) -> None:
        with self.lock:
            self.file.close()


def known_secrets(root: Path, environ: Mapping[str, str]) -> list[str]:
    """이번 워크스페이스 비밀값 공급자의 값들: 환경 변수 `KOOKABUG_SECRET_*` + (워크스페이스 ID가
    있으면) Windows 자격 증명 관리자의 그 워크스페이스 키. 못 읽으면 예외 — 부르는 쪽은 로그를
    남기지 않는다."""
    from kookabug_core.workspace import Workspace, workspace_id

    values = [v for k, v in environ.items() if k.upper().startswith("KOOKABUG_SECRET_") and v]
    wid = workspace_id(Workspace.open(root))
    if wid is not None:
        from kookabug_core.win.credentials import CredentialStore, available

        if available():
            store = CredentialStore()
            for key in store.keys(wid):
                value = store.read(wid, key)
                if value:
                    values.append(value)
    return values


# ---------------------------------------------------------------- 옵션·결과


@dataclass(slots=True)
class JobOptions:
    root: Path
    playbook: str
    agent: str = "custom"
    agent_command: str | None = None
    basis: str = "working"
    minutes: int | None = None
    runs: int | None = None
    trigger: str = "manual"
    pass_env: Sequence[str] = ()
    grace_s: float = GRACE_S
    heartbeat_s: float = HEARTBEAT_EVERY_S
    stop: threading.Event | None = None
    """검사·내장 호출의 취소 신호 (Ctrl+C와 같은 경로)."""
    deadline_s: float | None = None
    """시간 예산을 초로 (검사용 — 없으면 `minutes`)."""
    on_started: Callable[[str, int], None] | None = None
    """CLI를 띄운 뒤 (작업 ID, CLI PID) — 검사가 쓴다."""
    settle_poll_s: float = 1.0
    """daemon이 `ending`(입력 복구 확인 전)을 돌려줄 때 다시 묻는 간격."""
    gone_wait_s: float = 10.0
    """연결 유실 뒤 daemon 프로세스가 없어지기를 기다리는 한도."""
    input_settled: Callable[[Path, Mapping[str, str]], bool] | None = None
    """감독자 유실 뒤 입력 해제 확인 (기본 `settle.input_settled`, 검사가 바꿔 끼운다)."""


@dataclass(slots=True)
class JobOutcome:
    exit_code: int
    state: str | None
    job: str | None
    report: str | None = None
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_json(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "state": self.state,
            "job": self.job,
            "report": self.report,
            "message": self.message,
            **self.extra,
        }


def _iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _exit_for(state: str | None) -> int:
    if state == "done":
        return EXIT_DONE
    if state == "prep_failed":
        return EXIT_PREP
    return EXIT_ENDED


# ---------------------------------------------------------------- 본체


class DaemonLink(Protocol):
    """소유 연결 (`ui`). core는 daemon 패키지에 기대지 않으므로 CLI가 만들어 넘긴다."""

    notifications: queue.Queue[dict[str, Any]]

    def call(self, method: str, params: Mapping[str, Any], timeout: float = 60.0) -> Any:
        """daemon 오류는 `kind` 속성(오류 종류)이 있는 예외로 낸다."""
        ...

    @property
    def lost(self) -> bool: ...

    def gone(self, timeout: float) -> bool:
        """daemon 프로세스가 실제로 없어졌다 (최대 `timeout`초 기다린다)."""
        ...

    def close(self) -> None: ...


type Connect = Callable[[Path], DaemonLink]


def _spawn(
    argv: Sequence[str], env: Mapping[str, str], cwd: Path
) -> tuple[subprocess.Popen[bytes], Any]:
    """멈춘 채 띄워 새 Job(KILL_ON_JOB_CLOSE)에 넣고 이어 돌린다. (프로세스, Job)."""
    from kookabug_core.win import CHILD_FLAGS, resume_suspended
    from kookabug_core.win.job import Job
    from kookabug_core.win.process import CREATE_SUSPENDED

    job = Job.create(None, kill_on_close=True)
    try:
        proc = subprocess.Popen(
            list(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(env),
            cwd=str(cwd),
            creationflags=CHILD_FLAGS | CREATE_SUSPENDED,
            close_fds=True,
        )
    except BaseException:
        job.close()
        raise
    try:
        job.assign(proc.pid)
        resume_suspended(proc.pid)
    except BaseException:
        proc.kill()
        proc.wait(10)
        job.close()
        raise
    return proc, job


def _feed_prompt(proc: subprocess.Popen[bytes], prompt: bytes) -> None:
    assert proc.stdin is not None
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
    except OSError:
        pass  # CLI가 stdin을 읽지 않고 끝났다


def run_job(
    options: JobOptions,
    *,
    out: TextIO,
    connect: Connect,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    secrets: Callable[[], list[str]] | None = None,
) -> JobOutcome:
    """`agent-job run` 하나를 끝까지 (막히는 호출). 사람 전용 판단(`KOOKABUG_AGENT`)은 CLI가
    한다."""
    from kookabug_core import filetx, playbooks
    from kookabug_core.workspace import Workspace

    env = dict(os.environ if environ is None else environ)
    root = options.root
    print(SECURITY_NOTE, file=out)
    try:
        playbook = playbooks.load(options.playbook)
    except playbooks.PlaybookError as exc:
        return JobOutcome(EXIT_USAGE, None, None, message=str(exc))
    workspace = Workspace.open(root)
    defaults = workspace.automation()["budget"]
    budget = {
        "minutes": int(options.minutes or defaults.get("minutes", 60)),
        "runs": int(options.runs or defaults.get("runs", 30)),
    }
    lock = jobdir.JobLock(root)
    try:
        lock.acquire()
    except jobdir.JobActive as exc:
        if options.trigger == "schedule":
            _skipped_report(root, options, budget)
        return JobOutcome(EXIT_ACTIVE, None, None, message=str(exc), extra={"code": "job_active"})
    except filetx.TxError as exc:
        return JobOutcome(EXIT_USAGE, None, None, message=exc.message)
    try:
        return _run_locked(
            options, playbook, budget, env, out=out, connect=connect, which=which, secrets=secrets
        )
    finally:
        lock.release()


def _skipped_report(root: Path, options: JobOptions, budget: Mapping[str, int]) -> None:
    """예약 실행이 다른 작업과 겹쳤다: 그 회차를 건너뛰고 보고 하나 (3.9)."""
    from kookabug_core.knowledge.formats import new_id

    job_id = new_id("j")
    meta = {
        "id": job_id,
        "playbook": options.playbook,
        "trigger": options.trigger,
        "agent": {"profile": options.agent},
        "started_at": _iso(),
        "budget": dict(budget),
    }
    zero = {"runs": 0, "tool_calls": 0, "minutes": 0}
    built = reports.build(root, meta, state="prep_failed", used=zero, notes=None, prep="job_active")
    reports.write(root, built)


def _run_locked(
    options: JobOptions,
    playbook: Any,
    budget: Mapping[str, int],
    env: dict[str, str],
    *,
    out: TextIO,
    connect: Connect,
    which: Callable[[str], str | None],
    secrets: Callable[[], list[str]] | None,
) -> JobOutcome:
    from kookabug_core.win import current
    from kookabug_core.workspace import Workspace

    root = options.root
    try:
        daemon = connect(root)
    except Exception as exc:
        return JobOutcome(EXIT_USAGE, None, None, message=f"daemon에 붙지 못했다: {exc}")
    try:
        try:
            begun = daemon.call(
                "job.begin",
                {
                    "playbook": options.playbook,
                    "basis": options.basis,
                    "trigger": options.trigger,
                    "budget": dict(budget),
                    "toolsets": list(playbook.tools),
                    "agent": options.agent,
                },
            )
        except Exception as exc:
            kind = getattr(exc, "kind", None)
            if kind == "job_active":
                # daemon에 아직 끝나지 않은 작업(입력 복구 확인 전 포함)이 있다
                return JobOutcome(
                    EXIT_ACTIVE, None, None, message=str(exc), extra={"code": "job_active"}
                )
            return JobOutcome(EXIT_USAGE, None, None, message=f"job.begin 실패 ({kind})")
        job_id = str(begun["job"])
        me = current()
        doc: dict[str, Any] = {
            "id": job_id,
            "playbook": options.playbook,
            "playbook_version": playbook.version,
            "agent": {"profile": options.agent, "command": None, "version": None},
            "basis": options.basis,
            "trigger": options.trigger,
            "budget": dict(budget),
            "used": {"runs": 0, "tool_calls": 0, "minutes": 0},
            "state": "running",
            "exit_code": None,
            "report": None,
            "started_at": begun.get("started_at") or _iso(),
            "ended_at": None,
            "owner": {"pid": me.pid, "created": str(me.created)},
        }
        if begun["state"] == "prep_failed":
            doc.update(state="prep_failed", report=begun.get("report"), ended_at=_iso())
            _save(root, doc)
            print(f"작업 {job_id}: 준비 실패 ({begun.get('reason')})", file=out)
            return JobOutcome(
                EXIT_PREP, "prep_failed", job_id, begun.get("report"), str(begun.get("reason"))
            )
        token = str(begun["token"])
        return _supervise(
            options,
            playbook,
            budget,
            env,
            daemon,
            doc,
            token,
            out=out,
            which=which,
            secrets=secrets,
            workspace_name=str(Workspace.open(root).config.get("name") or root.name),
        )
    finally:
        daemon.close()


def _save(root: Path, doc: Mapping[str, Any]) -> None:
    """`job.json`을 쓴다. 작업 폴더가 링크·정션이면 쓰지 않는다 (밖에 쓰지 않는 것이 우선)."""
    from kookabug_core import filetx

    with contextlib.suppress(filetx.TxError):
        jobdir.write_job(root, doc)


def _prep_failed(
    daemon: DaemonLink, root: Path, doc: dict[str, Any], reason: str, out: TextIO
) -> JobOutcome:
    """작업을 만든 뒤 준비 실패 (CLI 없음·명령 틀림·폴더 안전 실패): 같은 종료 경로로 끝낸다."""
    ended = daemon.call(
        "job.finish",
        {"job": doc["id"], "state": "prep_failed", "prep_reason": reason},
        timeout=FINISH_TIMEOUT_S,
    )
    doc.update(state="prep_failed", report=ended.get("report"), ended_at=_iso(), used=ended["used"])
    _save(root, doc)
    print(f"작업 {doc['id']}: 준비 실패 ({reason})", file=out)
    return JobOutcome(EXIT_PREP, "prep_failed", str(doc["id"]), ended.get("report"), reason)


def _supervise(
    options: JobOptions,
    playbook: Any,
    budget: Mapping[str, int],
    env: dict[str, str],
    daemon: DaemonLink,
    doc: dict[str, Any],
    token: str,
    *,
    out: TextIO,
    which: Callable[[str], str | None],
    secrets: Callable[[], list[str]] | None,
    workspace_name: str,
) -> JobOutcome:
    from kookabug_core import filetx

    root = options.root
    job_id = str(doc["id"])
    try:
        folder = jobdir.job_path(root, job_id)
        folder.mkdir(parents=True, exist_ok=True)
        folder = jobdir.job_path(root, job_id)
        mcp_path = jobdir.job_path(root, job_id, "mcp.json")
        log_path = jobdir.job_path(root, job_id, "agent.log")
    except filetx.TxError:
        return _prep_failed(daemon, root, doc, "job_dir_unsafe", out)
    try:
        command = profiles.command_line(
            options.agent,
            root=root,
            job_id=job_id,
            mcp_path=mcp_path,
            agent_command=options.agent_command,
            which=which,
        )
    except profiles.ProfileError as exc:
        return _prep_failed(daemon, root, doc, exc.code, out)
    doc["agent"]["command"] = command.name
    prompt = profiles.build_prompt(
        playbook.body,
        playbook=options.playbook,
        version=playbook.version,
        job_id=job_id,
        basis=options.basis,
        budget=budget,
        trigger=options.trigger,
        workspace=workspace_name,
    )
    rel = f"{jobdir.JOBS_DIR}/{job_id}"
    try:
        jobdir.write_bytes(root, f"{rel}/prompt.md", prompt.encode("utf-8"))
        config = profiles.mcp_config(root, job_id)
        jobdir.write_bytes(
            root,
            f"{rel}/mcp.json",
            (json.dumps(config, ensure_ascii=False, indent=1) + "\n").encode(),
        )
        jobdir.write_job(root, doc)
    except filetx.TxError:
        return _prep_failed(daemon, root, doc, "job_dir_unsafe", out)
    child = profiles.child_env(
        options.agent,
        env,
        token=token,
        job_id=job_id,
        job_dir=folder,
        mcp_path=mcp_path,
        pass_env=options.pass_env,
    )
    # 가림 대상: 워크스페이스 비밀값 + 자식에게 실제로 넘기는 환경 중 시스템 기본(`BASE_ENV`) 밖의
    # 값 전부(프로필 인증·`--pass-env`·작업 변수 — 이름을 바꿔 넘긴 인증 값도). 못 모으면 원문을
    # 남기지 않는다
    try:
        values: list[str] | None = list((secrets or (lambda: known_secrets(root, env)))())
        values += profiles.passed_values(child)
        values.append(token)
    except Exception:
        values = None
    log = AgentLog(log_path, values)
    try:
        proc, process_job = _spawn(command.argv, child, root)
    except OSError:
        log.close()
        return _prep_failed(daemon, root, doc, "spawn_failed", out)
    print(f"작업 {job_id}: {options.playbook} 시작 ({command.name})", file=out)
    readers = [
        threading.Thread(target=log.pump, args=(s,), name=f"agent-log-{n}", daemon=True)
        for n, s in (("out", proc.stdout), ("err", proc.stderr))
    ]
    for reader in readers:
        reader.start()
    threading.Thread(
        target=_feed_prompt, args=(proc, prompt.encode("utf-8")), name="agent-prompt", daemon=True
    ).start()
    if options.on_started is not None:
        options.on_started(job_id, proc.pid)
    state, lost = _watch(options, budget, daemon, job_id, proc)
    # CLI 트리를 끝낸다 (이미 끝났어도 남은 손자까지)
    with contextlib.suppress(OSError):
        process_job.terminate(1)
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()
    process_job.close()
    for reader in readers:
        reader.join(10)
    log.close()
    exit_code = proc.returncode
    ended = None if lost else _finish(daemon, job_id, state, exit_code, options)
    if ended is None:
        # daemon 연결 유실·finish 예외: 감독자 유실 확인 → 입력 해제 확인 → 보고 (못 하면 표시만)
        ended = _write_interrupted(root, doc, daemon, env, options)
    final = str(ended.get("state") or state)
    doc.update(
        state=final,
        exit_code=exit_code,
        report=ended.get("report"),
        used=ended.get("used") or doc["used"],
        ended_at=_iso(),
    )
    _save(root, doc)
    print(f"작업 {job_id}: {final} (보고 {ended.get('report')})", file=out)
    extra = {"probe_ok": bool(ended.get("probe_ok")), "used": doc["used"]}
    return JobOutcome(_exit_for(final), final, job_id, ended.get("report"), final, extra)


def _finish(
    daemon: DaemonLink, job_id: str, state: str, exit_code: int | None, options: JobOptions
) -> dict[str, Any] | None:
    """`job.finish` — daemon이 끝 상태를 줄 때까지 부른다 (R8). 입력 복구를 확인하기 전이면 daemon이
    `ending`을 돌려주고, 같은 완료를 다시 기다린다(그동안 `jobs.lock`을 쥔다). 연결 유실·오류면
    None."""
    params = {"job": job_id, "state": state, "exit_code": exit_code}
    while True:
        try:
            ended = daemon.call("job.finish", params, timeout=FINISH_TIMEOUT_S)
        except Exception:
            return None
        if ended.get("state") != "ending":
            return dict(ended)
        if daemon.lost:
            return None
        time.sleep(options.settle_poll_s)


def _write_interrupted(
    root: Path,
    doc: Mapping[str, Any],
    daemon: DaemonLink,
    env: Mapping[str, str],
    options: JobOptions,
) -> dict[str, Any]:
    """daemon 연결 유실·`job.finish` 오류 (R8):

    1. daemon 프로세스가 실제로 없어졌는지 확인한다 (살아 있으면 그 daemon이 아직 감독 중일 수 있다)
    2. 없어졌으면 그 daemon의 runner는 감독자 유실로 스스로 입력을 풀고 끝난다 — 입력 임대권으로
       그것을 확인한 뒤(`settle.input_settled`) `interrupted` 보고를 쓴다
    3. 확인하지 못하면 보고를 쓰지 않고 `recovery_unconfirmed`만 남긴다 — 다음 daemon 시작의
       `_recover_jobs`가 이어받는다
    """
    from kookabug_core.agent_job.settle import input_settled

    # 기다리는 동안 daemon이 종료 경로를 마치면(입력 복구 확인 뒤에만 쓰는 끝 보고가 생긴다) 따른다
    deadline = time.monotonic() + options.gone_wait_s
    gone = False
    while True:
        try:
            stored = reports.read_report(root, str(doc["id"]))
        except Exception:
            stored = None
        if stored is not None and stored.get("state") in jobdir.TERMINAL:
            return {"state": stored["state"], "report": stored.get("rendered")}
        try:
            gone = bool(daemon.gone(0))
        except Exception:
            gone = False
        if gone or time.monotonic() >= deadline:
            break
        time.sleep(0.2)
    settled = False
    if gone:
        try:
            settled = (options.input_settled or input_settled)(root, env)
        except Exception:
            settled = False
    if not settled:
        return {"state": jobdir.UNCONFIRMED, "report": None}
    try:
        built = reports.build(
            root, doc, state="interrupted", used=doc.get("used") or {}, notes=None
        )
        written = reports.write(root, built)
        return {"state": "interrupted", "report": written.get("rendered")}
    except Exception:
        return {"state": "interrupted", "report": None}


def _watch(
    options: JobOptions,
    budget: Mapping[str, int],
    daemon: DaemonLink,
    job_id: str,
    proc: subprocess.Popen[bytes],
) -> tuple[str, bool]:
    """끝날 때까지 감독한다. (끝 상태, daemon 유실)."""
    seconds = options.deadline_s if options.deadline_s is not None else budget["minutes"] * 60
    deadline = time.monotonic() + seconds
    next_beat = time.monotonic() + options.heartbeat_s
    budget_at: float | None = None
    stop = options.stop or threading.Event()
    try:
        while True:
            code = proc.poll()
            if code is not None:
                return ("done" if code == 0 else "failed"), False
            now = time.monotonic()
            if stop.is_set():
                return "cancelled", False
            if now >= deadline:
                return "budget_exhausted", False
            if budget_at is not None and now >= budget_at + options.grace_s:
                return "budget_exhausted", False
            if daemon.lost:
                return "interrupted", True
            while True:
                try:
                    message = daemon.notifications.get_nowait()
                except queue.Empty:
                    break
                params = message.get("params") or {}
                if params.get("job") != job_id:
                    continue
                if message.get("method") == "job.budget" and budget_at is None:
                    budget_at = time.monotonic()
                if message.get("method") == "job.changed" and params.get("state") != "running":
                    return str(params.get("state")), False
            if now >= next_beat:
                next_beat = now + options.heartbeat_s
                try:
                    daemon.call("job.heartbeat", {"job": job_id}, timeout=10)
                except Exception as exc:
                    kind = getattr(exc, "kind", None)
                    if kind == "job_ended":
                        return "cancelled", False
                    if kind is None:
                        return "interrupted", True  # 연결 끊김·기한 초과
                    raise
            time.sleep(0.1)
    except KeyboardInterrupt:
        return "cancelled", False
