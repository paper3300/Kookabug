"""imm32 바인딩 (녹화 훅 프로세스의 IME 모드 표본, M4 T3)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from kookabug_platform.win32._ffi import bind

_dll = ctypes.WinDLL("imm32", use_last_error=True)

ImmGetDefaultIMEWnd = bind(_dll, "ImmGetDefaultIMEWnd", wintypes.HWND, wintypes.HWND)
