"""프로세스 자원 측정: 핸들·스레드·개인 바이트 (구현 계획 M1 2.3 장시간 안정성 검사).

`soak` 검사가 시작과 끝을 재서 증가량 상한(핸들 ≤ 50, 스레드 ≤ 2, 개인 바이트 ≤ 64 MiB)을 본다.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
TH32CS_SNAPTHREAD = 0x00000004
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = (
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    )


class THREADENTRY32(ctypes.Structure):
    _fields_ = (
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    )


def _sig(fn: Any, restype: Any, *argtypes: Any) -> Any:
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


_OpenProcess = _sig(
    _kernel32.OpenProcess, wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
)
_CloseHandle = _sig(_kernel32.CloseHandle, wintypes.BOOL, wintypes.HANDLE)
_GetProcessHandleCount = _sig(
    _kernel32.GetProcessHandleCount, wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)
)
_GetProcessMemoryInfo = _sig(
    _kernel32.K32GetProcessMemoryInfo,
    wintypes.BOOL,
    wintypes.HANDLE,
    ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
    wintypes.DWORD,
)
_CreateToolhelp32Snapshot = _sig(
    _kernel32.CreateToolhelp32Snapshot, wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD
)
_Thread32First = _sig(
    _kernel32.Thread32First, wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)
)
_Thread32Next = _sig(
    _kernel32.Thread32Next, wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)
)


def _check(ok: object, what: str) -> None:
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error(), what)


@dataclass(frozen=True)
class ResourceSample:
    handles: int
    threads: int
    private_bytes: int

    def __sub__(self, other: ResourceSample) -> ResourceSample:
        return ResourceSample(
            self.handles - other.handles,
            self.threads - other.threads,
            self.private_bytes - other.private_bytes,
        )


def count_threads(pid: int) -> int:
    snap = _CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap in (None, INVALID_HANDLE_VALUE):
        raise ctypes.WinError(ctypes.get_last_error(), "CreateToolhelp32Snapshot")
    try:
        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(THREADENTRY32)
        count = 0
        more = _Thread32First(snap, ctypes.byref(entry))
        while more:
            if entry.th32OwnerProcessID == pid:
                count += 1
            more = _Thread32Next(snap, ctypes.byref(entry))
        return count
    finally:
        _CloseHandle(snap)


def sample(pid: int | None = None) -> ResourceSample:
    """프로세스(기본: 현재)의 핸들 수·스레드 수·개인 바이트(커밋된 전용 메모리)."""
    pid = os.getpid() if pid is None else pid
    handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid)
    _check(handle, f"OpenProcess({pid})")
    try:
        handles = wintypes.DWORD()
        _check(_GetProcessHandleCount(handle, ctypes.byref(handles)), "GetProcessHandleCount")
        mem = PROCESS_MEMORY_COUNTERS_EX()
        mem.cb = ctypes.sizeof(mem)
        _check(_GetProcessMemoryInfo(handle, ctypes.byref(mem), mem.cb), "GetProcessMemoryInfo")
    finally:
        _CloseHandle(handle)
    return ResourceSample(handles.value, count_threads(pid), mem.PrivateUsage)
