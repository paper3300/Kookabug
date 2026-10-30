"""ole32 바인딩 (프로세스 MTA 유지, COM 아파트 확인)."""

from __future__ import annotations

import ctypes
from typing import Final

from kookabug_platform.win32._ffi import bind

_dll = ctypes.WinDLL("ole32")

CO_E_NOTINITIALIZED: Final = 0x800401F0
APTTYPE_MTA: Final = 1

# HRESULT를 예외로 바꾸지 않는다
CoIncrementMTAUsage = bind(
    _dll, "CoIncrementMTAUsage", ctypes.c_long, ctypes.POINTER(ctypes.c_void_p)
)
CoGetApartmentType = bind(
    _dll,
    "CoGetApartmentType",
    ctypes.c_long,
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
)
