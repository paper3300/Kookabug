"""프로세스 식별·살아 있음·종료 코드와 자식 띄우기 (구현 계획 M0b 2.3).

프로세스 식별 = (PID, 생성 시각). PID만 보면 재사용된 PID를 같은 프로세스로 오인한다.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from collections.abc import Mapping, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Final, Self

from kookabug_core.win import _kernel32 as k

__all__ = [
    "CHILD_FLAGS",
    "Process",
    "ProcessId",
    "current",
    "identify",
    "is_alive",
    "spawn",
]

PROCESS_TERMINATE: Final = 0x0001
PROCESS_SET_QUOTA: Final = 0x0100
PROCESS_QUERY_LIMITED_INFORMATION: Final = 0x1000

_QUERY: Final = PROCESS_QUERY_LIMITED_INFORMATION | k.SYNCHRONIZE
_ERROR_ACCESS_DENIED: Final = 5
_TERMINATING_WAIT_S: Final = 5.0

# 감독자가 띄우는 자식: 콘솔 Ctrl+C는 감독자가 취소 순서로 전하고, 창은 띄우지 않는다
CHILD_FLAGS: Final = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW


@dataclass(frozen=True, slots=True)
class ProcessId:
    """프로세스 식별. `created`는 생성 시각 FILETIME(100ns 단위)."""

    pid: int
    created: int

    def to_json(self) -> dict[str, int]:
        return {"pid": self.pid, "created": self.created}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ProcessId:
        return cls(pid=int(data["pid"]), created=int(data["created"]))


def _filetime(ft: wintypes.FILETIME) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def _creation_time(handle: int) -> int:
    times = [wintypes.FILETIME() for _ in range(4)]
    k.check(
        k.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)),
        "GetProcessTimes",
    )
    return _filetime(times[0])


class Process(k.OwnedHandle):
    """열린 프로세스 핸들. 핸들을 쥐고 있는 동안은 프로세스가 끝나도 종료 코드를 읽을 수 있다."""

    __slots__ = ("created", "pid")

    def __init__(self, handle: int, pid: int) -> None:
        super().__init__(handle)
        self.pid = pid
        self.created = _creation_time(handle)

    @classmethod
    def open(
        cls, target: ProcessId | int, *, terminate: bool = False, extra_access: int = 0
    ) -> Self:
        """`ProcessId`를 주면 생성 시각까지 같아야 연다. 없거나 다르면 `ProcessLookupError`."""
        pid = target.pid if isinstance(target, ProcessId) else target
        access = _QUERY | (PROCESS_TERMINATE if terminate else 0) | extra_access
        handle = k.OpenProcess(access, False, pid)
        if not handle:
            err = k.win_error(f"OpenProcess({pid})")
            raise ProcessLookupError(f"프로세스 {pid}를 열 수 없다: {err}") from err
        proc = cls(handle, pid)
        if isinstance(target, ProcessId) and proc.created != target.created:
            proc.close()
            raise ProcessLookupError(f"PID {pid}는 다른 프로세스다 (생성 시각이 다름)")
        return proc

    @property
    def ident(self) -> ProcessId:
        return ProcessId(self.pid, self.created)

    def _ended(self, timeout: float | None) -> bool:
        # 살아 있음은 대기 결과로 판정한다: 종료 코드 259(STILL_ACTIVE)로 끝난 프로세스와 구별
        result = k.WaitForSingleObject(self.handle, k.to_ms(timeout))
        if result == k.WAIT_TIMEOUT:
            return False
        if result != k.WAIT_OBJECT_0:
            raise k.win_error("WaitForSingleObject")
        return True

    def _exit_code(self) -> int:
        code = wintypes.DWORD()
        k.check(k.GetExitCodeProcess(self.handle, ctypes.byref(code)), "GetExitCodeProcess")
        return code.value

    def wait(self, timeout: float | None = None) -> int | None:
        """끝날 때까지 기다려 종료 코드를 돌려준다. 기한을 넘기면 None."""
        return self._exit_code() if self._ended(timeout) else None

    def alive(self) -> bool:
        return not self._ended(0)

    def exit_code(self) -> int | None:
        """끝났으면 종료 코드, 아직 살아 있으면 None."""
        return self.wait(0)

    def terminate(self, exit_code: int = 1) -> None:
        """`TerminateProcess`. 이미 끝났거나 끝나는 중이면 아무것도 하지 않는다."""
        if k.TerminateProcess(self.handle, exit_code):
            return
        code = ctypes.get_last_error()
        # 이미 끝나는 중인 프로세스(Job 종료 등)에는 ERROR_ACCESS_DENIED가 온다
        if code == _ERROR_ACCESS_DENIED and self.wait(_TERMINATING_WAIT_S) is not None:
            return
        if self.alive():
            raise k.win_error("TerminateProcess", code)


def identify(pid: int) -> ProcessId | None:
    """지금 그 PID를 가진 프로세스의 식별. 열 수 없으면 None."""
    try:
        with Process.open(pid) as proc:
            return proc.ident
    except ProcessLookupError:
        return None


def current() -> ProcessId:
    handle = k.GetCurrentProcess()  # 의사 핸들: 닫지 않는다
    return ProcessId(os.getpid(), _creation_time(handle))


def is_alive(ident: ProcessId) -> bool:
    """열 수 있고, 생성 시각이 같고, 아직 끝나지 않았다."""
    try:
        with Process.open(ident) as proc:
            return proc.alive()
    except ProcessLookupError:
        return False


def spawn(
    args: Sequence[str | Path],
    *,
    stdout: Path,
    stderr: Path,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    stdin: int | IO[Any] | None = subprocess.DEVNULL,
) -> subprocess.Popen[bytes]:
    """감독자·runner가 자식을 띄우는 방식. stdout·stderr는 **파일**로 보낸다 —
    부모가 죽거나 읽지 않아도 파이프 버퍼로 자식이 막히지 않는다."""
    for path in (stdout, stderr):
        path.parent.mkdir(parents=True, exist_ok=True)
    with stdout.open("ab") as out, stderr.open("ab") as err:
        return subprocess.Popen(
            [str(a) for a in args],
            stdin=stdin,
            stdout=out,
            stderr=err,
            env=None if env is None else dict(env),
            cwd=cwd,
            creationflags=CHILD_FLAGS,
            close_fds=True,
        )
