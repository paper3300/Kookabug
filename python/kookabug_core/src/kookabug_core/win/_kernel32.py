"""kernel32 ctypes 바인딩 (`kookabug_core.win` 안에서만 쓴다).

pywin32 대신 ctypes를 쓴다: 런타임 의존성·라이선스 감사 항목이 늘지 않는다 (구현 계획 M0b 2.3).
"""

from __future__ import annotations

import contextlib
import ctypes
from ctypes import wintypes
from types import TracebackType
from typing import Any, Final, Self

kernel32: Final = ctypes.WinDLL("kernel32", use_last_error=True)

HANDLE = wintypes.HANDLE
BOOL = wintypes.BOOL
DWORD = wintypes.DWORD
LPCWSTR = wintypes.LPCWSTR

INFINITE: Final = 0xFFFFFFFF
WAIT_OBJECT_0: Final = 0x0
WAIT_ABANDONED: Final = 0x80
WAIT_TIMEOUT: Final = 0x102
WAIT_FAILED: Final = 0xFFFFFFFF

ERROR_FILE_NOT_FOUND: Final = 2
ERROR_ALREADY_EXISTS: Final = 183
ERROR_MORE_DATA: Final = 234
ERROR_NOT_OWNER: Final = 288

SYNCHRONIZE: Final = 0x00100000
HANDLE_FLAG_INHERIT: Final = 0x1


def _fn(name: str, restype: Any, *argtypes: Any) -> Any:
    f = getattr(kernel32, name)
    f.restype = restype
    f.argtypes = argtypes
    return f


CloseHandle = _fn("CloseHandle", BOOL, HANDLE)
GetHandleInformation = _fn("GetHandleInformation", BOOL, HANDLE, ctypes.POINTER(DWORD))
WaitForSingleObject = _fn("WaitForSingleObject", DWORD, HANDLE, DWORD)
GetCurrentProcess = _fn("GetCurrentProcess", HANDLE)

CreateJobObjectW = _fn("CreateJobObjectW", HANDLE, ctypes.c_void_p, LPCWSTR)
OpenJobObjectW = _fn("OpenJobObjectW", HANDLE, DWORD, BOOL, LPCWSTR)
SetInformationJobObject = _fn(
    "SetInformationJobObject", BOOL, HANDLE, ctypes.c_int, ctypes.c_void_p, DWORD
)
QueryInformationJobObject = _fn(
    "QueryInformationJobObject",
    BOOL,
    HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    DWORD,
    ctypes.POINTER(DWORD),
)
AssignProcessToJobObject = _fn("AssignProcessToJobObject", BOOL, HANDLE, HANDLE)
TerminateJobObject = _fn("TerminateJobObject", BOOL, HANDLE, ctypes.c_uint)
IsProcessInJob = _fn("IsProcessInJob", BOOL, HANDLE, HANDLE, ctypes.POINTER(BOOL))

CreateMutexW = _fn("CreateMutexW", HANDLE, ctypes.c_void_p, BOOL, LPCWSTR)
ReleaseMutex = _fn("ReleaseMutex", BOOL, HANDLE)

OpenProcess = _fn("OpenProcess", HANDLE, DWORD, BOOL, DWORD)
GetProcessTimes = _fn(
    "GetProcessTimes",
    BOOL,
    HANDLE,
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
)
GetExitCodeProcess = _fn("GetExitCodeProcess", BOOL, HANDLE, ctypes.POINTER(DWORD))
TerminateProcess = _fn("TerminateProcess", BOOL, HANDLE, ctypes.c_uint)

CreateEventW = _fn("CreateEventW", HANDLE, ctypes.c_void_p, BOOL, BOOL, LPCWSTR)
SetEvent = _fn("SetEvent", BOOL, HANDLE)
WaitForMultipleObjects = _fn(
    "WaitForMultipleObjects", DWORD, DWORD, ctypes.POINTER(HANDLE), BOOL, DWORD
)
MAXIMUM_WAIT_OBJECTS: Final = 64

FILE_APPEND_DATA: Final = 0x0004
FILE_SHARE_ALL: Final = 0x0001 | 0x0002 | 0x0004  # READ | WRITE | DELETE
OPEN_ALWAYS: Final = 4
FILE_ATTRIBUTE_NORMAL: Final = 0x80
INVALID_HANDLE_VALUE: Final = HANDLE(-1).value

CreateFileW = _fn(
    "CreateFileW", HANDLE, LPCWSTR, DWORD, DWORD, ctypes.c_void_p, DWORD, DWORD, HANDLE
)
WriteFile = _fn(
    "WriteFile", BOOL, HANDLE, ctypes.c_char_p, DWORD, ctypes.POINTER(DWORD), ctypes.c_void_p
)


def win_error(what: str, code: int | None = None) -> OSError:
    """마지막 Win32 오류를 OSError로. winerror에 맞는 하위 클래스(FileNotFoundError 등)가 된다."""
    err = ctypes.get_last_error() if code is None else code
    return OSError(None, f"{what}: {ctypes.FormatError(err).strip()}", None, err)


def check(ok: Any, what: str) -> None:
    if not ok:
        raise win_error(what)


def check_handle(handle: int | None, what: str) -> int:
    if not handle:
        raise win_error(what)
    return handle


def to_ms(timeout: float | None) -> int:
    """초 → `WaitFor*`의 밀리초. None은 무한."""
    if timeout is None:
        return INFINITE
    return max(0, min(int(timeout * 1000), INFINITE - 1))


def is_inheritable(handle: int) -> bool:
    flags = DWORD()
    check(GetHandleInformation(handle, ctypes.byref(flags)), "GetHandleInformation")
    return bool(flags.value & HANDLE_FLAG_INHERIT)


class OwnedHandle:
    """닫아야 하는 커널 핸들 하나. 컨텍스트 관리자이고 두 번 닫아도 된다.

    `keep_until_exit()`를 부른 핸들은 Python이 닫지 않는다(소멸자 포함) — 프로세스가 끝날 때
    OS가 닫는다.
    """

    __slots__ = ("_handle", "_keep")

    def __init__(self, handle: int) -> None:
        self._handle: int | None = handle
        self._keep = False

    def keep_until_exit(self) -> Self:
        """프로세스가 끝날 때까지 닫지 않는다. 닫는 순간 이 프로세스에 영향이 있는 핸들용 —
        예: 자기 자신이 든 `KILL_ON_JOB_CLOSE` Job. 인터프리터 종료 중에 소멸자가 닫으면 그때
        이 프로세스가 강제 종료돼 종료 코드가 바뀐다."""
        if self._handle is None:
            raise ValueError("이미 닫은 핸들이다")
        self._keep = True
        return self

    @property
    def handle(self) -> int:
        if self._handle is None:
            raise ValueError("이미 닫은 핸들이다")
        return self._handle

    @property
    def closed(self) -> bool:
        return self._handle is None

    def close(self) -> None:
        if self._keep:
            raise ValueError("프로세스가 끝날 때까지 유지하는 핸들이다 (keep_until_exit)")
        handle, self._handle = self._handle, None
        if handle is not None:
            check(CloseHandle(handle), "CloseHandle")

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __del__(self) -> None:
        # 인터프리터 종료 중에는 모듈 전역이 이미 없을 수 있다
        handle = getattr(self, "_handle", None)
        if handle is not None and not getattr(self, "_keep", False):
            with contextlib.suppress(Exception):
                CloseHandle(handle)
