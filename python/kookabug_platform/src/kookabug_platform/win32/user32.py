"""user32 바인딩."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Final

from kookabug_platform.win32._ffi import bind

_dll = ctypes.WinDLL("user32", use_last_error=True)

HWND = wintypes.HWND
BOOL = wintypes.BOOL
UINT = wintypes.UINT
DWORD = wintypes.DWORD
LONG = wintypes.LONG

GW_OWNER: Final = 4
GA_PARENT: Final = 1
GA_ROOT: Final = 2
GA_ROOTOWNER: Final = 3
GWL_STYLE: Final = -16
GWL_EXSTYLE: Final = -20
WS_CAPTION: Final = 0x00C00000
WS_CHILD: Final = 0x40000000
SW_RESTORE: Final = 9
SW_SHOW: Final = 5
SWP_NOSIZE: Final = 0x0001
SWP_NOMOVE: Final = 0x0002
SWP_NOZORDER: Final = 0x0004
SWP_NOACTIVATE: Final = 0x0010
WM_CLOSE: Final = 0x0010
WM_QUIT: Final = 0x0012
WM_APP: Final = 0x8000
MONITOR_DEFAULTTONEAREST: Final = 2
EVENT_OBJECT_DESTROY: Final = 0x8001
WINEVENT_OUTOFCONTEXT: Final = 0x0000
WINEVENT_SKIPOWNPROCESS: Final = 0x0002
OBJID_WINDOW: Final = 0
CHILDID_SELF: Final = 0
DESKTOP_READOBJECTS: Final = 0x0001
DESKTOP_SWITCHDESKTOP: Final = 0x0100
UOI_NAME: Final = 2
PM_NOREMOVE: Final = 0x0000

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2: Final = -4


class MONITORINFO(ctypes.Structure):
    _fields_ = (
        ("cbSize", DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", DWORD),
    )


WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HWND, wintypes.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, DWORD, HWND, LONG, LONG, DWORD, DWORD)

EnumWindows = bind(_dll, "EnumWindows", BOOL, WNDENUMPROC, wintypes.LPARAM)
IsWindow = bind(_dll, "IsWindow", BOOL, HWND)
IsWindowVisible = bind(_dll, "IsWindowVisible", BOOL, HWND)
IsIconic = bind(_dll, "IsIconic", BOOL, HWND)
GetWindow = bind(_dll, "GetWindow", HWND, HWND, UINT)
GetAncestor = bind(_dll, "GetAncestor", HWND, HWND, UINT)
GetWindowThreadProcessId = bind(
    _dll, "GetWindowThreadProcessId", DWORD, HWND, ctypes.POINTER(DWORD)
)
GetWindowTextW = bind(_dll, "GetWindowTextW", ctypes.c_int, HWND, wintypes.LPWSTR, ctypes.c_int)
GetClassNameW = bind(_dll, "GetClassNameW", ctypes.c_int, HWND, wintypes.LPWSTR, ctypes.c_int)
GetClientRect = bind(_dll, "GetClientRect", BOOL, HWND, ctypes.POINTER(wintypes.RECT))
GetWindowRect = bind(_dll, "GetWindowRect", BOOL, HWND, ctypes.POINTER(wintypes.RECT))
ClientToScreen = bind(_dll, "ClientToScreen", BOOL, HWND, ctypes.POINTER(wintypes.POINT))
WindowFromPoint = bind(_dll, "WindowFromPoint", HWND, wintypes.POINT)
GetForegroundWindow = bind(_dll, "GetForegroundWindow", HWND)
SetForegroundWindow = bind(_dll, "SetForegroundWindow", BOOL, HWND)
BringWindowToTop = bind(_dll, "BringWindowToTop", BOOL, HWND)
ShowWindow = bind(_dll, "ShowWindow", BOOL, HWND, ctypes.c_int)
AttachThreadInput = bind(_dll, "AttachThreadInput", BOOL, DWORD, DWORD, BOOL)
GetDpiForWindow = bind(_dll, "GetDpiForWindow", UINT, HWND)
MonitorFromWindow = bind(_dll, "MonitorFromWindow", wintypes.HMONITOR, HWND, DWORD)
GetMonitorInfoW = bind(
    _dll, "GetMonitorInfoW", BOOL, wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)
)
GetWindowLongPtrW = bind(_dll, "GetWindowLongPtrW", ctypes.c_ssize_t, HWND, ctypes.c_int)
GetMenu = bind(_dll, "GetMenu", wintypes.HMENU, HWND)
AdjustWindowRectExForDpi = bind(
    _dll, "AdjustWindowRectExForDpi", BOOL, ctypes.POINTER(wintypes.RECT), DWORD, BOOL, DWORD, UINT
)
SetWindowPos = bind(
    _dll,
    "SetWindowPos",
    BOOL,
    HWND,
    HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    UINT,
)
PostMessageW = bind(_dll, "PostMessageW", BOOL, HWND, UINT, wintypes.WPARAM, wintypes.LPARAM)
PostThreadMessageW = bind(
    _dll, "PostThreadMessageW", BOOL, DWORD, UINT, wintypes.WPARAM, wintypes.LPARAM
)
GetMessageW = bind(_dll, "GetMessageW", BOOL, ctypes.POINTER(wintypes.MSG), HWND, UINT, UINT)
PeekMessageW = bind(
    _dll, "PeekMessageW", BOOL, ctypes.POINTER(wintypes.MSG), HWND, UINT, UINT, UINT
)
TranslateMessage = bind(_dll, "TranslateMessage", BOOL, ctypes.POINTER(wintypes.MSG))
DispatchMessageW = bind(_dll, "DispatchMessageW", wintypes.LPARAM, ctypes.POINTER(wintypes.MSG))
SetWinEventHook = bind(
    _dll,
    "SetWinEventHook",
    wintypes.HANDLE,
    DWORD,
    DWORD,
    wintypes.HMODULE,
    WINEVENTPROC,
    DWORD,
    DWORD,
    DWORD,
)
UnhookWinEvent = bind(_dll, "UnhookWinEvent", BOOL, wintypes.HANDLE)
SetThreadDpiAwarenessContext = bind(
    _dll, "SetThreadDpiAwarenessContext", ctypes.c_void_p, ctypes.c_void_p
)
OpenInputDesktop = bind(_dll, "OpenInputDesktop", wintypes.HANDLE, DWORD, BOOL, DWORD)
CloseDesktop = bind(_dll, "CloseDesktop", BOOL, wintypes.HANDLE)
GetUserObjectInformationW = bind(
    _dll,
    "GetUserObjectInformationW",
    BOOL,
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    DWORD,
    ctypes.POINTER(DWORD),
)
