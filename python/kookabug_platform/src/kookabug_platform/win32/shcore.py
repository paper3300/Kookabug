"""shcore 바인딩 (모니터 DPI)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Final

from kookabug_platform.win32._ffi import bind

_dll = ctypes.WinDLL("shcore")

MDT_EFFECTIVE_DPI: Final = 0

# HRESULT를 예외로 바꾸지 않는다
GetDpiForMonitor = bind(
    _dll,
    "GetDpiForMonitor",
    ctypes.c_long,
    wintypes.HMONITOR,
    ctypes.c_int,
    ctypes.POINTER(wintypes.UINT),
    ctypes.POINTER(wintypes.UINT),
)
