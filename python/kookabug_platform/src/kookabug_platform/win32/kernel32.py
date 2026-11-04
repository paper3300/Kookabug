"""kernel32 바인딩 (창·프로세스 쪽에서 쓰는 것만. Job·프로세스 식별은 `kookabug_core.win`)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Final

from kookabug_platform.win32._ffi import bind

_dll = ctypes.WinDLL("kernel32", use_last_error=True)

HANDLE = wintypes.HANDLE
BOOL = wintypes.BOOL
DWORD = wintypes.DWORD

PROCESS_QUERY_LIMITED_INFORMATION: Final = 0x1000
CREATE_NEW_PROCESS_GROUP: Final = 0x00000200
CREATE_UNICODE_ENVIRONMENT: Final = 0x00000400
CREATE_NO_WINDOW: Final = 0x08000000
ERROR_ACCESS_DENIED: Final = 5


class STARTUPINFOW(ctypes.Structure):
    _fields_ = (
        ("cb", DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", DWORD),
        ("dwY", DWORD),
        ("dwXSize", DWORD),
        ("dwYSize", DWORD),
        ("dwXCountChars", DWORD),
        ("dwYCountChars", DWORD),
        ("dwFillAttribute", DWORD),
        ("dwFlags", DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", HANDLE),
        ("hStdOutput", HANDLE),
        ("hStdError", HANDLE),
    )


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = (
        ("hProcess", HANDLE),
        ("hThread", HANDLE),
        ("dwProcessId", DWORD),
        ("dwThreadId", DWORD),
    )


GetCurrentThreadId = bind(_dll, "GetCurrentThreadId", DWORD)
GetCurrentProcess = bind(_dll, "GetCurrentProcess", HANDLE)
CloseHandle = bind(_dll, "CloseHandle", BOOL, HANDLE)
OpenProcess = bind(_dll, "OpenProcess", HANDLE, DWORD, BOOL, DWORD)
QueryFullProcessImageNameW = bind(
    _dll, "QueryFullProcessImageNameW", BOOL, HANDLE, DWORD, wintypes.LPWSTR, ctypes.POINTER(DWORD)
)
CreateProcessW = bind(
    _dll,
    "CreateProcessW",
    BOOL,
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    BOOL,
    DWORD,
    ctypes.c_void_p,
    wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW),
    ctypes.POINTER(PROCESS_INFORMATION),
)

# 녹화 훅 프로세스 (M4 T3): 훅 스레드 우선순위, 세션 마지막 입력 시각과 같은 틱
THREAD_PRIORITY_HIGHEST: Final = 2
GetCurrentThread = bind(_dll, "GetCurrentThread", HANDLE)
SetThreadPriority = bind(_dll, "SetThreadPriority", BOOL, HANDLE, ctypes.c_int)
GetTickCount = bind(_dll, "GetTickCount", DWORD)
GetModuleHandleW = bind(_dll, "GetModuleHandleW", wintypes.HMODULE, wintypes.LPCWSTR)
