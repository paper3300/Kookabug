"""dwmapi 바인딩."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Final

from kookabug_platform.win32._ffi import bind

_dll = ctypes.WinDLL("dwmapi")

DWMWA_EXTENDED_FRAME_BOUNDS: Final = 9
DWMWA_CLOAKED: Final = 14

# HRESULT를 예외로 바꾸지 않는다(창이 사라진 경우 등은 호출한 쪽이 판정한다)
DwmGetWindowAttribute = bind(
    _dll,
    "DwmGetWindowAttribute",
    ctypes.c_long,
    wintypes.HWND,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
)
