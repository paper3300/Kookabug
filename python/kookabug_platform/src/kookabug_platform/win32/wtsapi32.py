"""wtsapi32 바인딩 (세션 잠금 상태)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Final

from kookabug_platform.win32._ffi import bind

_dll = ctypes.WinDLL("wtsapi32", use_last_error=True)

WTS_CURRENT_SESSION: Final = 0xFFFFFFFF
WTSSessionInfoEx: Final = 25
WTS_SESSIONSTATE_LOCK: Final = 0
WTS_SESSIONSTATE_UNLOCK: Final = 1


class WTSINFOEX_HEAD(ctypes.Structure):
    # WTSINFOEXW { DWORD Level; union { WTSINFOEX_LEVEL1_W } }의 앞부분. 공용체는 8바이트 정렬
    _fields_ = (
        ("Level", wintypes.DWORD),
        ("_pad", wintypes.DWORD),
        ("SessionId", wintypes.ULONG),
        ("SessionState", ctypes.c_int),
        ("SessionFlags", wintypes.LONG),
    )


WTSQuerySessionInformationW = bind(
    _dll,
    "WTSQuerySessionInformationW",
    wintypes.BOOL,
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(wintypes.DWORD),
)
WTSFreeMemory = bind(_dll, "WTSFreeMemory", None, ctypes.c_void_p)
