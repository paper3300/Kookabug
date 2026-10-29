"""Windows 기반: Job Object, 이름 있는 뮤텍스, 프로세스 식별 (ctypes, 구현 계획 M0b 2.3)."""

from kookabug_core.win.job import RUN_JOB_PREFIX, Job, run_job_name
from kookabug_core.win.mutex import NamedMutex, WaitResult
from kookabug_core.win.process import (
    CHILD_FLAGS,
    Process,
    ProcessId,
    current,
    identify,
    is_alive,
    spawn,
)

__all__ = [
    "CHILD_FLAGS",
    "RUN_JOB_PREFIX",
    "Job",
    "NamedMutex",
    "Process",
    "ProcessId",
    "WaitResult",
    "current",
    "identify",
    "is_alive",
    "run_job_name",
    "spawn",
]
