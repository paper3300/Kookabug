"""Windows Job Object (구현 계획 M0b 2.3 "실행 Job 수명").

실행 Job은 감독자가 이름 있는 Job을 `KILL_ON_JOB_CLOSE`로 만들고, runner가 어떤 자식도 띄우기
전에 이름으로 열어 자기를 넣는다. 그래서 핸들이 둘이고, **둘 다 닫혀야** OS가 Job 안 프로세스를
끝낸다. 핸들은 상속하지 않는다(보안 속성 기본값) — 다른 프로세스에 넘기는 일이 없다.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Final, Self

from kookabug_core.win import _kernel32 as k
from kookabug_core.win.process import PROCESS_SET_QUOTA, PROCESS_TERMINATE, Process

__all__ = ["RUN_JOB_PREFIX", "Job", "run_job_name"]

RUN_JOB_PREFIX: Final = "Local\\Kookabug.Run."

_JOB_OBJECT_ALL_ACCESS: Final = 0x1F001F
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: Final = 0x2000
_JobObjectBasicProcessIdList: Final = 3
_JobObjectExtendedLimitInformation: Final = 9


class _BasicLimit(ctypes.Structure):
    _fields_ = (
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    )


class _IoCounters(ctypes.Structure):
    _fields_ = tuple(
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    )


class _ExtendedLimit(ctypes.Structure):
    _fields_ = (
        ("BasicLimitInformation", _BasicLimit),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    )


def run_job_name(run_id: str) -> str:
    return f"{RUN_JOB_PREFIX}{run_id}"


class Job(k.OwnedHandle):
    """Job 핸들 하나. 닫으면(마지막 핸들이면) `KILL_ON_JOB_CLOSE` Job 안 프로세스가 끝난다."""

    __slots__ = ("name",)

    def __init__(self, handle: int, name: str | None) -> None:
        super().__init__(handle)
        self.name = name

    @classmethod
    def create(cls, name: str | None = None, *, kill_on_close: bool = True) -> Self:
        """새 Job. 같은 이름이 이미 있으면 `FileExistsError` — 남의 Job에 붙지 않는다."""
        ctypes.set_last_error(0)
        handle = k.check_handle(k.CreateJobObjectW(None, name), f"CreateJobObjectW({name})")
        job = cls(handle, name)
        if ctypes.get_last_error() == k.ERROR_ALREADY_EXISTS:
            job.close()
            raise FileExistsError(f"Job이 이미 있다: {name}")
        if kill_on_close:
            job._set_kill_on_close()
        return job

    @classmethod
    def open(cls, name: str) -> Self:
        """이름 있는 Job을 연다. 없으면 `FileNotFoundError`."""
        handle = k.OpenJobObjectW(_JOB_OBJECT_ALL_ACCESS, False, name)
        return cls(k.check_handle(handle, f"OpenJobObjectW({name})"), name)

    def _set_kill_on_close(self) -> None:
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k.check(
            k.SetInformationJobObject(
                self.handle,
                _JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            ),
            "SetInformationJobObject",
        )

    @property
    def inheritable(self) -> bool:
        return k.is_inheritable(self.handle)

    def assign(self, pid: int) -> None:
        """다른 프로세스를 넣는다. 그 프로세스가 이미 띄운 자식은 따라 들어오지 않는다."""
        with Process.open(pid, extra_access=PROCESS_SET_QUOTA | PROCESS_TERMINATE) as proc:
            self._assign_handle(proc.handle, pid)

    def assign_current(self) -> None:
        """이 프로세스를 넣는다. 이후 띄우는 자식은 생성 시점부터 Job 소속이다."""
        self._assign_handle(k.GetCurrentProcess(), None)

    def _assign_handle(self, process: int, pid: int | None) -> None:
        k.check(
            k.AssignProcessToJobObject(self.handle, process), f"AssignProcessToJobObject({pid})"
        )

    def contains(self, pid: int | None = None) -> bool:
        """그 프로세스(없으면 이 프로세스)가 이 Job(또는 그 하위 Job)에 있는가."""
        result = k.BOOL()
        if pid is None:
            k.check(
                k.IsProcessInJob(k.GetCurrentProcess(), self.handle, ctypes.byref(result)),
                "IsProcessInJob",
            )
        else:
            with Process.open(pid) as proc:
                k.check(
                    k.IsProcessInJob(proc.handle, self.handle, ctypes.byref(result)),
                    "IsProcessInJob",
                )
        return bool(result.value)

    def process_ids(self) -> list[int]:
        """지금 Job 안에 있는 프로세스 PID들."""
        capacity = 64
        while True:

            class _List(ctypes.Structure):
                _fields_ = (
                    ("NumberOfAssignedProcesses", wintypes.DWORD),
                    ("NumberOfProcessIdsInList", wintypes.DWORD),
                    ("ProcessIdList", ctypes.c_size_t * capacity),
                )

            info = _List()
            ok = k.QueryInformationJobObject(
                self.handle,
                _JobObjectBasicProcessIdList,
                ctypes.byref(info),
                ctypes.sizeof(info),
                None,
            )
            if not ok and ctypes.get_last_error() != k.ERROR_MORE_DATA:
                raise k.win_error("QueryInformationJobObject")
            if ok and info.NumberOfProcessIdsInList == info.NumberOfAssignedProcesses:
                return [int(pid) for pid in info.ProcessIdList[: info.NumberOfProcessIdsInList]]
            capacity = max(capacity * 2, info.NumberOfAssignedProcesses + 16)

    def terminate(self, exit_code: int = 1) -> None:
        """Job 안 모든 프로세스(손자 포함)를 끝낸다. 키 해제를 대신하지 않는다."""
        k.check(k.TerminateJobObject(self.handle, exit_code), "TerminateJobObject")
