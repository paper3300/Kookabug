"""판정 코드가 쓰는 Win32 호출 묶음 (`WindowApi`)과 실제 구현(`Win32Api`).

포그라운드·점 아래 창·무결성·입력 데스크톱·창 수명 판정은 이 프로토콜만 부른다. 검사는 가짜를
넘겨(바인딩 바꿔 끼움) 실제 창 없이 판정식을 확인한다. 좌표를 다루는 호출은 그 스레드만
Per-Monitor V2로 두고 부른다 — 프로세스 수준과 무관하게 물리 픽셀이다.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Final, Protocol

from kookabug_core.win import identify
from kookabug_platform.dpi import per_monitor_v2_thread
from kookabug_platform.win32 import advapi32, dwmapi, kernel32, user32, wtsapi32
from kookabug_platform.win32._ffi import last_error_text

__all__ = ["DEFAULT_API", "INTEGRITY_MEDIUM", "Win32Api", "WindowApi"]

INTEGRITY_UNTRUSTED: Final = 0x0000
INTEGRITY_LOW: Final = 0x1000
INTEGRITY_MEDIUM: Final = 0x2000
INTEGRITY_HIGH: Final = 0x3000
INTEGRITY_SYSTEM: Final = 0x4000


class WindowApi(Protocol):
    """판정에 필요한 Win32 호출. 창 핸들은 정수, 좌표는 화면 물리 픽셀."""

    def is_window(self, hwnd: int) -> bool: ...
    def is_visible(self, hwnd: int) -> bool: ...
    def is_minimized(self, hwnd: int) -> bool: ...
    def is_cloaked(self, hwnd: int) -> bool: ...
    def owner(self, hwnd: int) -> int: ...
    def root(self, hwnd: int) -> int: ...
    def top_level_windows(self) -> list[int]: ...
    def foreground_window(self) -> int: ...
    def window_from_point(self, x: int, y: int) -> int: ...
    def client_to_screen(self, hwnd: int, x: int, y: int) -> tuple[int, int]: ...
    def window_pid(self, hwnd: int) -> int: ...
    def window_title(self, hwnd: int) -> str: ...
    def window_class(self, hwnd: int) -> str: ...
    def process_created(self, pid: int) -> int | None: ...
    def process_name(self, pid: int) -> str: ...
    def process_integrity(self, pid: int | None) -> int | None: ...
    def input_desktop(self) -> tuple[str | None, str]: ...
    def session_locked(self) -> bool | None: ...


class Win32Api:
    """`WindowApi`의 실제 구현."""

    def is_window(self, hwnd: int) -> bool:
        return bool(hwnd) and bool(user32.IsWindow(hwnd))

    def is_visible(self, hwnd: int) -> bool:
        return bool(user32.IsWindowVisible(hwnd))

    def is_minimized(self, hwnd: int) -> bool:
        return bool(user32.IsIconic(hwnd))

    def is_cloaked(self, hwnd: int) -> bool:
        value = wintypes.DWORD()
        hr = dwmapi.DwmGetWindowAttribute(
            hwnd, dwmapi.DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)
        )
        return hr == 0 and value.value != 0

    def owner(self, hwnd: int) -> int:
        return user32.GetWindow(hwnd, user32.GW_OWNER) or 0

    def root(self, hwnd: int) -> int:
        return user32.GetAncestor(hwnd, user32.GA_ROOT) or 0

    def top_level_windows(self) -> list[int]:
        found: list[int] = []

        def collect(hwnd: int, _lparam: int) -> bool:
            found.append(hwnd)
            return True

        user32.EnumWindows(user32.WNDENUMPROC(collect), 0)
        return found

    def foreground_window(self) -> int:
        return user32.GetForegroundWindow() or 0

    def window_from_point(self, x: int, y: int) -> int:
        with per_monitor_v2_thread():
            return user32.WindowFromPoint(wintypes.POINT(x, y)) or 0

    def client_to_screen(self, hwnd: int, x: int, y: int) -> tuple[int, int]:
        pt = wintypes.POINT(x, y)
        with per_monitor_v2_thread():
            if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
                raise OSError(f"ClientToScreen 실패: hwnd={hwnd}")
        return pt.x, pt.y

    def window_pid(self, hwnd: int) -> int:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def window_title(self, hwnd: int) -> str:
        # 다른 프로세스 창이면 WM_GETTEXT를 보내지 않고 저장된 제목을 읽는다(멈춘 창에도 안전)
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, len(buf))
        return buf.value

    def window_class(self, hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, len(buf))
        return buf.value

    def process_created(self, pid: int) -> int | None:
        ident = identify(pid)
        return None if ident is None else ident.created

    def process_name(self, pid: int) -> str:
        """실행 파일 이름 (`game.exe`). 열 수 없으면 빈 문자열."""
        handle = kernel32.OpenProcess(kernel32.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return ""
            return os.path.basename(buf.value)
        finally:
            kernel32.CloseHandle(handle)

    def process_integrity(self, pid: int | None) -> int | None:
        """토큰 무결성 수준 RID(`0x2000` = 보통). `pid`가 None이면 이 프로세스.
        읽을 수 없으면 None."""
        own = pid is None
        handle = (
            kernel32.GetCurrentProcess()
            if own
            else kernel32.OpenProcess(kernel32.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        )
        if not handle:
            return None
        token = wintypes.HANDLE()
        try:
            if not advapi32.OpenProcessToken(handle, advapi32.TOKEN_QUERY, ctypes.byref(token)):
                return None
            try:
                return _token_integrity(token.value)
            finally:
                kernel32.CloseHandle(token)
        finally:
            if not own:
                kernel32.CloseHandle(handle)

    def input_desktop(self) -> tuple[str | None, str]:
        """입력 데스크톱 이름 (열 수 없으면 None과 사유)."""
        desk = user32.OpenInputDesktop(
            0, False, user32.DESKTOP_READOBJECTS | user32.DESKTOP_SWITCHDESKTOP
        )
        if not desk:
            return None, last_error_text()
        try:
            buf = ctypes.create_unicode_buffer(256)
            needed = wintypes.DWORD()
            ok = user32.GetUserObjectInformationW(
                desk, user32.UOI_NAME, buf, ctypes.sizeof(buf), ctypes.byref(needed)
            )
            return (buf.value if ok else "?"), ""
        finally:
            user32.CloseDesktop(desk)

    def session_locked(self) -> bool | None:
        """이 세션이 잠겨 있는가 (모르면 None). Windows 10·11 잠금 화면은 Default 데스크톱 위에
        뜨므로 `OpenInputDesktop`만으로는 알 수 없다."""
        buf = ctypes.c_void_p()
        size = wintypes.DWORD()
        if not wtsapi32.WTSQuerySessionInformationW(
            None,
            wtsapi32.WTS_CURRENT_SESSION,
            wtsapi32.WTSSessionInfoEx,
            ctypes.byref(buf),
            ctypes.byref(size),
        ):
            return None
        try:
            info = ctypes.cast(buf, ctypes.POINTER(wtsapi32.WTSINFOEX_HEAD)).contents
            flags = info.SessionFlags
            if info.Level != 1 or flags not in (
                wtsapi32.WTS_SESSIONSTATE_LOCK,
                wtsapi32.WTS_SESSIONSTATE_UNLOCK,
            ):
                return None
            return flags == wtsapi32.WTS_SESSIONSTATE_LOCK
        finally:
            wtsapi32.WTSFreeMemory(buf)


def _token_integrity(token: int | None) -> int | None:
    size = wintypes.DWORD()
    advapi32.GetTokenInformation(token, advapi32.TokenIntegrityLevel, None, 0, ctypes.byref(size))
    if not size.value:
        return None
    buf = ctypes.create_string_buffer(size.value)
    if not advapi32.GetTokenInformation(
        token, advapi32.TokenIntegrityLevel, buf, size, ctypes.byref(size)
    ):
        return None
    label = ctypes.cast(buf, ctypes.POINTER(advapi32.TOKEN_MANDATORY_LABEL)).contents
    sid = label.Label.Sid
    count = advapi32.GetSidSubAuthorityCount(sid).contents.value
    if count == 0:
        return None
    return int(advapi32.GetSidSubAuthority(sid, count - 1).contents.value)


DEFAULT_API: Final[WindowApi] = Win32Api()
