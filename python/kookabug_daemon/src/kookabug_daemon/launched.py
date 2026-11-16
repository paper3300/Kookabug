"""daemon이 `app.launch`로 띄운 게임의 정리 (UX8 B).

같은 주체(`job:<작업>`·`agent:<agent>`, `game_window.game_key`)가 전에 띄운 게임이 아직 살아
있으면 새로 띄우기 전에 끝내고, 작업이 끝나면(정상·취소·실패 모두) 그 작업이 띄운 게임을 끝낸다.
사람이 띄운 게임은 기억하지 않으므로 끝내지 않는다.

**daemon이 띄운 프로세스만** 끝낸다: 띄울 때 멈춘 채(`CREATE_SUSPENDED`) 띄워 이 게임만의 Job에
넣은 뒤 이어 돌린다 — 런처가 띄운 아래 프로세스도 처음부터 그 Job 안이다. 끝낼 때는 실행 Job
정리와 같은 방법(`recovery.clean_job` — `TerminateJobObject` → 끝나기 기다림 → 핸들 닫기)이다.
Job에 넣지 못했으면 그 프로세스 하나만 PID + 생성 시각이 같을 때 끝낸다(PID 재사용으로 남의
프로세스를 끄지 않게). Job은
`KILL_ON_JOB_CLOSE`가 아니다 — daemon이 죽어도 게임은 남는다(지금까지와 같음).
"""

from __future__ import annotations

import contextlib
import logging
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ["GameStopFailed", "Launched", "LaunchedGames", "spawn_game"]

log = logging.getLogger(__name__)

_CREATE_SUSPENDED = 0x00000004
_ERROR_INVALID_PARAMETER = 87
"""`OpenProcess`가 없는 PID에 내는 오류."""


@dataclass(slots=True)
class Launched:
    pid: int
    created: int | None
    """프로세스 생성 시각 (FILETIME). 못 읽으면 None — 그때는 Job으로만 끈다."""
    job: Any = None
    """이 게임만의 Job (`kookabug_core.win.job.Job`). 넣지 못했으면 None."""
    fake: bool = False


def spawn_game(argv: Sequence[str], cwd: str | None, flags: int) -> Launched:
    """게임을 띄운다: 멈춘 채 띄워 Job에 넣고 이어 돌린다. Job을 못 쓰면 그냥 이어 돌린다.
    `flags`가 `PermissionError`(daemon을 띄운 쪽 Job이 빠져나가기를 막음)면 호출자가 다른 값으로
    다시 부른다."""
    proc = subprocess.Popen(
        list(argv),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags | _CREATE_SUSPENDED,
        close_fds=True,
    )
    job: Any = None
    created: int | None = None
    try:
        from kookabug_core.win import identify
        from kookabug_core.win.job import Job

        ident = identify(proc.pid)
        created = None if ident is None else ident.created
        job = Job.create(kill_on_close=False)
        try:
            job.assign(proc.pid)
        except OSError:
            job.close()
            job = None
            log.warning("게임 PID %d를 Job에 넣지 못했다 — 그 프로세스 하나만 정리한다", proc.pid)
    except Exception:
        log.warning("게임 PID %d: Job을 만들지 못했다", proc.pid, exc_info=True)
        if job is not None:
            with contextlib.suppress(Exception):
                job.close()
            job = None
    finally:
        try:
            from kookabug_core.win.process import resume_suspended

            resume_suspended(proc.pid)
        except Exception:
            # 멈춘 채 남기지 않는다: 이어 돌리지 못하면 끝내고 실패로 알린다
            with contextlib.suppress(OSError):
                proc.kill()
            if job is not None:
                job.close()
            raise
    return Launched(proc.pid, created, job)


class LaunchedGames:
    """주체 키별 마지막으로 띄운 게임. 어느 스레드에서나 부른다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_key: dict[str, Launched] = {}
        self.fake_stop: Callable[[int], bool] | None = None
        """검사 전용 (가짜 플랫폼 `launch_fake`): 가짜 게임을 닫는다. 살아 있었으면 True."""

    def put(self, key: str, launched: Launched) -> None:
        with self._lock:
            old = self._by_key.pop(key, None)
            self._by_key[key] = launched
        if old is not None:  # 호출자가 먼저 stop했으면 이미 비어 있다 (방어)
            try:
                self._stop(old)
            except GameStopFailed:
                log.warning("이전 게임 PID %d를 끝내지 못했다", old.pid, exc_info=True)

    def stop(self, key: str) -> int | None:
        """그 주체가 띄운 게임을 끝낸다. 살아 있던 것을 끝냈으면 그 PID, 이미 끝나 있었으면 None.
        끝내지 못했으면 `GameStopFailed` — 소유 기록은 그대로 남는다(다시 시도할 수 있게)."""
        with self._lock:
            launched = self._by_key.get(key)
        if launched is None:
            return None
        stopped = self._stop(launched)  # 실패면 예외 (기록을 지우지 않는다)
        with self._lock:
            if self._by_key.get(key) is launched:
                del self._by_key[key]
        return launched.pid if stopped else None

    def _stop(self, launched: Launched) -> bool:
        """끝냈으면 True, 이미 끝나 있었으면 False, 끝내지 못했으면 `GameStopFailed`."""
        if launched.fake:
            stop = self.fake_stop
            return bool(stop(launched.pid)) if stop is not None else False
        if launched.job is not None:
            from kookabug_core.recovery import clean_job

            try:
                alive = bool(launched.job.process_ids())
            except OSError:
                alive = True
            clean_job(launched.job)  # 핸들도 닫는다
            launched.job = None
            if alive:
                log.info("daemon이 띄운 게임 PID %d(Job)을 끝냈다", launched.pid)
            return alive
        if launched.created is None:
            return False
        return _stop_process(launched.pid, launched.created)


class GameStopFailed(Exception):
    """daemon이 띄운 게임이 아직 살아 있는데 끝내지 못했다 (소유 기록은 남긴다)."""

    def __init__(self, pid: int, reason: str) -> None:
        super().__init__(f"게임 PID {pid}를 끝내지 못했다: {reason}")
        self.pid = pid


def _stop_process(pid: int, created: int) -> bool:
    """Job에 넣지 못한 게임 하나: PID + 생성 시각이 같을 때만 종료 권한으로 열어 끝내고 끝났는지
    확인한다. 이미 끝났거나 PID가 다른 프로세스면 False."""
    from kookabug_core.win import ProcessId
    from kookabug_core.win.process import Process

    ident = ProcessId(pid, created)
    try:
        proc = Process.open(ident, terminate=True)
    except ProcessLookupError as exc:
        # 끌 것이 없는 경우는 둘뿐: 프로세스가 없거나(OpenProcess가 ERROR_INVALID_PARAMETER),
        # 같은 PID가 다른 프로세스다(생성 시각이 다름 — 원인 오류 없음). 접근 거부 등 확인하지
        # 못한 실패는 살아 있을 수 있으므로 실패로 알린다 (UX8 검수 2 Mid)
        code = getattr(exc.__cause__, "winerror", None)
        if exc.__cause__ is None or code == _ERROR_INVALID_PARAMETER:
            return False
        raise GameStopFailed(pid, str(exc)) from exc
    with proc:
        if not proc.alive():
            return False
        try:
            proc.terminate(1)
        except OSError as exc:
            raise GameStopFailed(pid, str(exc)) from exc
        if proc.wait(5.0) is None:
            raise GameStopFailed(pid, "끝내기를 요청했지만 5초 안에 끝나지 않았다")
    log.info("daemon이 띄운 게임 PID %d를 끝냈다", pid)
    return True
