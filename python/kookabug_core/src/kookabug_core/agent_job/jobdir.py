"""작업 폴더 `.kookabug/jobs/<작업>/`와 `jobs.lock` (M8 계획 3.1·3.9).

- `jobs.lock`: 프로세스 공통 바이트 잠금(`screen_lock`·`filetx.file_lock`과 같은 방식).
  워크스페이스당 작업 하나 — 쥔 `agent-job`이 죽으면 OS가 핸들과 함께 푼다(남지 않는다).
  기다리지 않는다: 쥐고 있으면 `job_active`
- 쓰는 경로는 `filetx.plain`으로 조각마다 링크·정션이 아니고 실경로가 워크스페이스 안이어야 한다
  (`job.json`·`prompt.md`·`mcp.json`·`agent.log`·예약 XML 모두)
- `job.json`에는 토큰·인증 값·전체 명령줄을 넣지 않는다(R9). 명령은 실행 파일 이름만
"""

from __future__ import annotations

import contextlib
import json
import msvcrt
import os
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

from kookabug_core import filetx
from kookabug_core.documents import write_atomic

__all__ = [
    "JOBS_DIR",
    "JOB_FORMAT",
    "JOB_ID",
    "LOCK_FILE",
    "STATES",
    "TERMINAL",
    "UNCONFIRMED",
    "JobActive",
    "JobLock",
    "job_path",
    "job_running",
    "list_jobs",
    "lock_free",
    "read_job",
    "write_bytes",
    "write_job",
]

JOBS_DIR: Final = ".kookabug/jobs"
LOCK_FILE: Final = ".kookabug/jobs.lock"
JOB_FORMAT: Final = "kookabug.job/0"
JOB_ID: Final = re.compile(r"^j-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
UNCONFIRMED: Final = "recovery_unconfirmed"
"""감독자(daemon)가 없어졌는데 입력 복구를 확인하지 못했다 — 보고를 쓰지 않았다. 다음 daemon 시작의
`_recover_jobs`가 확인을 이어받아 끝낸다 (R8)."""
STATES: Final = (
    "running",
    UNCONFIRMED,
    "done",
    "failed",
    "cancelled",
    "budget_exhausted",
    "interrupted",
    "prep_failed",
)
TERMINAL: Final = frozenset(STATES) - {"running", UNCONFIRMED}


class JobActive(Exception):
    """다른 `agent-job`이 이 워크스페이스의 작업을 돌리고 있다 (`job_active`, 종료 코드 3)."""

    code = "job_active"


class JobLock:
    """`jobs.lock` 바이트 하나. `acquire`는 기다리지 않는다. 핸들은 상속하지 않는다(자식 CLI가 쥐고
    남지 않게)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._fd: int | None = None

    def acquire(self) -> None:
        path = filetx.plain(self.root, LOCK_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOINHERIT, 0o644)
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            os.close(fd)
            raise JobActive("이 워크스페이스에서 다른 작업이 돌고 있다 (jobs.lock)") from None
        self._fd = fd

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        os.lseek(fd, 0, os.SEEK_SET)
        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        os.close(fd)

    def __enter__(self) -> JobLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


def lock_free(root: Path) -> bool:
    """지금 `jobs.lock`을 쥔 프로세스가 없는가 (daemon 시작 때 남은 `running` 작업 정리 판단)."""
    probe = JobLock(root)
    try:
        probe.acquire()
    except JobActive:
        return False
    except filetx.TxError, OSError:
        return False
    probe.release()
    return True


def job_running(root: Path) -> bool:
    """`jobs.lock`을 쥔 `agent-job`이 있는가 (비차단 시도). 잠금 파일이 없으면 만들지 않고 False —
    CLI 실행 판정이 워크스페이스에 파일을 남기지 않게."""
    try:
        path = filetx.plain(root, LOCK_FILE)
    except filetx.TxError:
        return True  # 링크·정션: 확인할 수 없으면 안전 쪽
    if not path.is_file():
        return False
    return not lock_free(root)


def _check_id(job_id: str) -> str:
    if not JOB_ID.fullmatch(job_id):
        raise ValueError(f"작업 ID 형식이 틀렸다: {job_id!r}")
    return job_id


def job_path(root: Path, job_id: str, name: str = "") -> Path:
    """작업 폴더(또는 그 안 파일)의 확인된 경로. 링크·정션·밖이면 `filetx.TxError`."""
    rel = f"{JOBS_DIR}/{_check_id(job_id)}" + (f"/{name}" if name else "")
    return filetx.plain(root, rel)


def write_bytes(root: Path, rel: str, data: bytes) -> Path:
    """워크스페이스 안 확인된 경로에 원자적으로 쓴다 (폴더는 만든다 — 만든 뒤 다시 확인)."""
    path = filetx.plain(root, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path = filetx.plain(root, rel)
    write_atomic(path, data)
    return path


def write_job(root: Path, doc: Mapping[str, Any]) -> Path:
    job_id = _check_id(str(doc["id"]))
    body = {"format": JOB_FORMAT, **doc}
    data = (json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    return write_bytes(root, f"{JOBS_DIR}/{job_id}/job.json", data)


def read_job(root: Path, job_id: str) -> dict[str, Any] | None:
    try:
        path = job_path(root, job_id, "job.json")
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError, filetx.TxError:
        return None
    return value if isinstance(value, dict) else None


def list_jobs(root: Path) -> Iterator[dict[str, Any]]:
    """작업 폴더의 `job.json`들 (ID 순). 링크·정션 폴더와 형식이 틀린 것은 건너뛴다."""
    try:
        base = filetx.plain(root, JOBS_DIR)
    except filetx.TxError:
        return
    if not base.is_dir():
        return
    for entry in sorted(base.iterdir(), key=lambda p: p.name):
        if not JOB_ID.fullmatch(entry.name) or entry.is_symlink() or entry.is_junction():
            continue
        doc = read_job(root, entry.name)
        if doc is not None:
            yield doc
