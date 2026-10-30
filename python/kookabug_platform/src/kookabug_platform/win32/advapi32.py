"""advapi32 바인딩 (토큰 무결성 수준)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Final

from kookabug_platform.win32._ffi import bind

_dll = ctypes.WinDLL("advapi32", use_last_error=True)

TOKEN_QUERY: Final = 0x0008
TokenIntegrityLevel: Final = 25


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = (("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD))


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = (("Label", SID_AND_ATTRIBUTES),)


OpenProcessToken = bind(
    _dll,
    "OpenProcessToken",
    wintypes.BOOL,
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
)
GetTokenInformation = bind(
    _dll,
    "GetTokenInformation",
    wintypes.BOOL,
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
)
GetSidSubAuthorityCount = bind(
    _dll, "GetSidSubAuthorityCount", ctypes.POINTER(ctypes.c_ubyte), ctypes.c_void_p
)
GetSidSubAuthority = bind(
    _dll, "GetSidSubAuthority", ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, wintypes.DWORD
)
