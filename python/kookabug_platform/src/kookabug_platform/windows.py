"""창 찾기·식별·한 시점 정보와 입력 전 판정 (구현 계획 M1 2.2).

판정식 (계획 검수 2차 N1 반영 — 아래 "포그라운드"·"점 아래 창"):

- **포그라운드**(키보드·글자): 포그라운드 창이 대상 창 자신이거나, 소유자 사슬(`GW_OWNER`)을
  따라가면 대상 창이 나오는 팝업이면 통과. 같은 프로세스의 **독립 최상위 창은 통과하지 않는다**
  (`window_not_foreground`). 소유 팝업 자체를 `attach`해 대상으로 삼았으면 그 팝업이 포그라운드일 때
  통과한다(자기 자신).
- **점 아래 창**(마우스): `WindowFromPoint(화면 점)`을 `GA_ROOT`(부모 사슬만)로 최상위 창까지 올린
  것이 **정확히 대상 창**이어야 한다. 자식 컨트롤은 대상 창으로 올라가 통과하고, 대상 창이 소유한
  팝업이 클릭 지점을 덮으면 그 팝업이 나와 `point_obscured`다 — WGC 창 캡처에는 소유 팝업이 찍히지
  않아 관측과 입력 대상이 어긋나기 때문이다. 팝업을 누르려면 그 팝업을 `attach(owned=True)`로 대상
  창으로 바꾼다.

이 모듈은 입력을 보내지 않는다 — `bring_to_front`의 Alt 누르기·떼기는 부르는 쪽이 준
`tap_alt`(runner 입력 액터)가 넣고, runner 플랫폼이 실행 첫 창을 앞으로 가져올 때만 준다(D1). 입력
직전 확인의 순서·스레드는 액터(T5)가 정한다.
"""

from __future__ import annotations

import ctypes
import re
from collections.abc import Callable, Collection
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Final, Protocol

from kookabug_platform.dpi import per_monitor_v2_thread
from kookabug_platform.errors import (
    INPUT_DESKTOP_UNAVAILABLE,
    POINT_OBSCURED,
    TARGET_ELEVATED,
    WINDOW_GONE,
    WINDOW_MINIMIZED,
    WINDOW_NOT_FOREGROUND,
    PlatformError,
)
from kookabug_platform.win32 import dwmapi, kernel32, shcore, user32
from kookabug_platform.win32.api import DEFAULT_API, WindowApi

__all__ = [
    "WIN32_FOREGROUND",
    "ForegroundOps",
    "Win32Foreground",
    "WindowInfo",
    "activate",
    "bring_to_front",
    "check_foreground",
    "check_input_desktop",
    "check_integrity",
    "check_not_minimized",
    "check_point",
    "describe",
    "find_window",
    "find_windows",
    "integrity_exceeds",
    "is_fullscreen",
    "is_owned_by",
    "set_client_size",
    "title_matches",
    "window_info",
]

_OWNER_CHAIN_LIMIT: Final = 64
_SIZE_ATTEMPTS: Final = 3
"""크기 맞춤: 계산값으로 한 번 + 실측 차이로 고쳐 두 번."""

type Box = tuple[int, int, int, int]
"""`(left, top, right, bottom)` 화면 물리 픽셀."""


@dataclass(frozen=True, slots=True)
class WindowInfo:
    """창 하나의 한 시점 정보. 좌표·크기는 물리 픽셀."""

    hwnd: int
    pid: int
    process_created: int
    """프로세스 생성 시각 FILETIME(100ns). 읽을 수 없으면 0."""
    process_name: str
    title: str
    class_name: str
    client_size: tuple[int, int]
    client_origin: tuple[int, int]
    """클라이언트 (0, 0)의 화면 좌표."""
    frame_bounds: Box
    """`DWMWA_EXTENDED_FRAME_BOUNDS` (그림자 제외 창 경계). WGC 프레임이 이 크기다."""
    window_rect: Box
    """`GetWindowRect` (보이지 않는 크기 조절 테두리 포함)."""
    dpi: int
    """창 DPI (`GetDpiForWindow`). DPI를 모르는(unaware) 창은 모니터와 무관하게 늘 96이다."""
    monitor_dpi: int
    """창이 있는 모니터의 실제 DPI (`GetDpiForMonitor`, 96 = 100%). 물리 픽셀 배율은 이것이다 —
    unaware 창은 논리 크기에 `monitor_dpi / 96`을 곱한 크기로 확대돼 그려진다."""
    monitor: Box
    minimized: bool
    visible: bool
    cloaked: bool
    fullscreen: bool
    integrity: int | None
    """토큰 무결성 수준 RID. 읽을 수 없으면 None."""


# ---------------------------------------------------------------- 정보


def _rect(fn: Any, hwnd: int) -> wintypes.RECT:
    rect = wintypes.RECT()
    if not fn(hwnd, ctypes.byref(rect)):
        raise PlatformError(WINDOW_GONE, f"창 {hwnd:#x}의 사각형을 읽을 수 없다 (창이 닫혔다)")
    return rect


def _box(rect: wintypes.RECT) -> Box:
    return rect.left, rect.top, rect.right, rect.bottom


def is_fullscreen(window_rect: Box, monitor_rect: Box, style: int) -> bool:
    """전체화면 추정: 창 경계가 모니터 경계를 덮고 캡션이 없다 (테두리 없는 전체화면·독점 모두)."""
    left, top, right, bottom = window_rect
    m_left, m_top, m_right, m_bottom = monitor_rect
    covers = left <= m_left and top <= m_top and right >= m_right and bottom >= m_bottom
    return covers and (style & user32.WS_CAPTION) != user32.WS_CAPTION


def _monitor_dpi(monitor: int | None) -> int:
    # PMv2 스레드에서 불러야 가상화되지 않은 실제 값이다. 못 읽으면 96(100%)
    x, y = wintypes.UINT(), wintypes.UINT()
    if not monitor or shcore.GetDpiForMonitor(
        monitor, shcore.MDT_EFFECTIVE_DPI, ctypes.byref(x), ctypes.byref(y)
    ):
        return 96
    return int(x.value)


def window_info(hwnd: int, api: WindowApi = DEFAULT_API) -> WindowInfo:
    """지금 그 창의 정보. 창이 없으면 `window_gone`."""
    if not api.is_window(hwnd):
        raise PlatformError(WINDOW_GONE, f"창 {hwnd:#x}가 없다")
    pid = api.window_pid(hwnd)
    with per_monitor_v2_thread():
        client = _rect(user32.GetClientRect, hwnd)
        origin = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(origin))
        window = _rect(user32.GetWindowRect, hwnd)
        frame = wintypes.RECT()
        hr = dwmapi.DwmGetWindowAttribute(
            hwnd, dwmapi.DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(frame), ctypes.sizeof(frame)
        )
        if hr != 0:
            frame = window
        monitor = user32.MONITORINFO()
        monitor.cbSize = ctypes.sizeof(monitor)
        handle = user32.MonitorFromWindow(hwnd, user32.MONITOR_DEFAULTTONEAREST)
        monitor_box = (
            _box(monitor.rcMonitor)
            if user32.GetMonitorInfoW(handle, ctypes.byref(monitor))
            else (0, 0, 0, 0)
        )
        dpi = int(user32.GetDpiForWindow(hwnd))
        monitor_dpi = _monitor_dpi(handle)
    style = int(user32.GetWindowLongPtrW(hwnd, user32.GWL_STYLE))
    window_box = _box(window)
    return WindowInfo(
        hwnd=hwnd,
        pid=pid,
        process_created=api.process_created(pid) or 0,
        process_name=api.process_name(pid),
        title=api.window_title(hwnd),
        class_name=api.window_class(hwnd),
        client_size=(client.right - client.left, client.bottom - client.top),
        client_origin=(origin.x, origin.y),
        frame_bounds=_box(frame),
        window_rect=window_box,
        dpi=dpi,
        monitor_dpi=monitor_dpi,
        monitor=monitor_box,
        minimized=api.is_minimized(hwnd),
        visible=api.is_visible(hwnd),
        cloaked=api.is_cloaked(hwnd),
        fullscreen=is_fullscreen(window_box, monitor_box, style),
        integrity=api.process_integrity(pid),
    )


def describe(hwnd: int, api: WindowApi = DEFAULT_API) -> str:
    """메시지용 창 설명: `'제목' (game.exe pid 123, hwnd 0x1a2b)`."""
    if not hwnd:
        return "(창 없음)"
    if not api.is_window(hwnd):
        return f"(닫힌 창 hwnd {hwnd:#x})"
    pid = api.window_pid(hwnd)
    name = api.process_name(pid) or "?"
    return f"{api.window_title(hwnd)!r} ({name} pid {pid}, hwnd {hwnd:#x})"


# ---------------------------------------------------------------- 찾기


def title_matches(pattern: str, title: str) -> bool:
    """`/정규식/`이면 정규식 검색, 아니면 대소문자 무시 부분 일치."""
    if len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/"):
        return re.search(pattern[1:-1], title) is not None
    return pattern.casefold() in title.casefold()


def find_windows(
    *,
    title: str | None = None,
    process_name: str | None = None,
    pids: Collection[int] | None = None,
    owned: bool = False,
    api: WindowApi = DEFAULT_API,
) -> list[int]:
    """조건에 맞는 보이는 최상위 창들 (Z 순서 앞부터).

    기본은 소유자 없는 창만. `owned=True`면 소유 팝업도 포함한다(소유 팝업은 늘 소유자보다 앞이다).
    `cloaked`(다른 가상 데스크톱·UWP 숨김) 창은 뺀다. `process_name`은 실행 파일 이름
    (대소문자 무시).
    """
    if title is not None:
        title_matches(title, "")  # 잘못된 정규식은 여기서 바로 re.error
    wanted_pids = None if pids is None else set(pids)
    names: dict[int, str] = {}
    found: list[int] = []
    for hwnd in api.top_level_windows():
        if not api.is_visible(hwnd) or api.is_cloaked(hwnd):
            continue
        if not owned and api.owner(hwnd):
            continue
        pid = api.window_pid(hwnd)
        if wanted_pids is not None and pid not in wanted_pids:
            continue
        if process_name is not None:
            if pid not in names:
                names[pid] = api.process_name(pid)
            if names[pid].casefold() != process_name.casefold():
                continue
        if title is not None and not title_matches(title, api.window_title(hwnd)):
            continue
        found.append(hwnd)
    return found


def find_window(
    *,
    title: str | None = None,
    process_name: str | None = None,
    pids: Collection[int] | None = None,
    owned: bool = False,
    api: WindowApi = DEFAULT_API,
) -> int | None:
    """`find_windows`의 첫 창 (없으면 None)."""
    found = find_windows(title=title, process_name=process_name, pids=pids, owned=owned, api=api)
    return found[0] if found else None


# ---------------------------------------------------------------- 판정


def is_owned_by(hwnd: int, target: int, api: WindowApi = DEFAULT_API) -> bool:
    """`hwnd`가 `target` 자신이거나 소유자 사슬에 `target`이 있는가."""
    current = hwnd
    for _ in range(_OWNER_CHAIN_LIMIT):
        if not current:
            return False
        if current == target:
            return True
        current = api.owner(current)
    return False


def check_foreground(target: int, api: WindowApi = DEFAULT_API) -> None:
    """키보드·글자 입력 전: 포그라운드가 대상 창 자신이나 대상 창이 소유한 팝업이어야 한다."""
    fg = api.foreground_window()
    top = api.root(fg) if fg else 0
    if top and is_owned_by(top, target, api):
        return
    raise PlatformError(
        WINDOW_NOT_FOREGROUND,
        f"대상 창 {describe(target, api)}이 포그라운드가 아니다. "
        f"지금 포그라운드: {describe(top, api)}",
    )


def check_point(target: int, screen_point: tuple[int, int], api: WindowApi = DEFAULT_API) -> None:
    """마우스 입력 전: 화면 점 아래 최상위 창(`GA_ROOT`)이 정확히 대상 창이어야 한다."""
    hit = api.window_from_point(*screen_point)
    top = api.root(hit) if hit else 0
    if top == target:
        return
    raise PlatformError(
        POINT_OBSCURED,
        f"대상 창 {describe(target, api)}의 클릭 지점 {screen_point}을 "
        f"{describe(top, api)}이 덮고 있다",
    )


def check_not_minimized(target: int, api: WindowApi = DEFAULT_API) -> None:
    if api.is_minimized(target):
        raise PlatformError(WINDOW_MINIMIZED, f"대상 창 {describe(target, api)}이 최소화돼 있다")


def integrity_exceeds(target: int | None, own: int | None) -> bool:
    """대상 무결성이 runner보다 높은가. 대상을 읽을 수 없으면(None) 높다고 본다 — 같은 사용자의
    보통 수준 프로세스는 언제나 읽히므로, 거부는 상승된(또는 보호된) 프로세스라는 뜻이다."""
    if own is None:
        return False
    return target is None or target > own


def check_integrity(target: int, api: WindowApi = DEFAULT_API) -> None:
    """대상 프로세스 무결성 > runner면 `target_elevated` (UIPI가 입력을 조용히 버린다)."""
    pid = api.window_pid(target)
    level = api.process_integrity(pid)
    own = api.process_integrity(None)
    if not integrity_exceeds(level, own):
        return
    shown = "읽을 수 없음(접근 거부)" if level is None else f"{level:#06x}"
    raise PlatformError(
        TARGET_ELEVATED,
        f"대상 창 {describe(target, api)}의 프로세스 권한 수준({shown})이 runner({own:#06x})보다 "
        "높다. 입력이 버려진다 — 관리자 권한 터미널에서 실행하라",
    )


def check_input_desktop(api: WindowApi = DEFAULT_API) -> None:
    """입력 데스크톱을 열 수 있고, 세션이 잠겨 있지 않아야 한다."""
    name, error = api.input_desktop()
    if name is None:
        raise PlatformError(
            INPUT_DESKTOP_UNAVAILABLE,
            f"입력 데스크톱을 열 수 없다 — 잠금 화면·UAC 화면이거나 세션 없음 ({error})",
        )
    if name.casefold() != "default":
        raise PlatformError(INPUT_DESKTOP_UNAVAILABLE, f"입력 데스크톱이 {name!r}다 (Default 아님)")
    if api.session_locked():
        raise PlatformError(INPUT_DESKTOP_UNAVAILABLE, "세션이 잠겨 있다 (잠금 화면)")


# ---------------------------------------------------------------- 조작


class ForegroundOps(Protocol):
    """`bring_to_front`가 쓰는 Win32 조작 (검사가 바꿔 끼운다)."""

    def is_window(self, hwnd: int) -> bool: ...
    def restore(self, hwnd: int) -> None:
        """최소화돼 있으면 되살린다."""
        ...

    def is_foreground(self, hwnd: int) -> bool: ...
    def set_foreground(self, hwnd: int) -> None:
        """`BringWindowToTop` + `SetForegroundWindow`."""
        ...

    def set_foreground_attached(self, hwnd: int) -> None:
        """지금 포그라운드 스레드에 입력 큐를 붙이고(`AttachThreadInput`) 앞으로, 그다음 뗀다."""
        ...

    def alt_held(self) -> bool:
        """Alt가 지금 눌려 있다 (사람이 누르고 있음 등 — 합성 떼기로 그 상태를 바꾸지 않는다)."""
        ...


class Win32Foreground:
    def is_window(self, hwnd: int) -> bool:
        return bool(user32.IsWindow(hwnd))

    def restore(self, hwnd: int) -> None:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, user32.SW_RESTORE)

    def is_foreground(self, hwnd: int) -> bool:
        fg = user32.GetForegroundWindow()
        return bool(fg) and user32.GetAncestor(fg, user32.GA_ROOT) == hwnd

    def set_foreground(self, hwnd: int) -> None:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)

    def set_foreground_attached(self, hwnd: int) -> None:
        fg = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        me = kernel32.GetCurrentThreadId()
        attached = bool(
            fg_thread and fg_thread != me and user32.AttachThreadInput(me, fg_thread, 1)
        )
        try:
            self.set_foreground(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(me, fg_thread, 0)

    def alt_held(self) -> bool:
        return bool(int(user32.GetAsyncKeyState(VK_MENU)) & 0x8000)


VK_MENU: Final = 0x12
WIN32_FOREGROUND: Final[ForegroundOps] = Win32Foreground()


def bring_to_front(
    hwnd: int,
    *,
    tap_alt: Callable[[], bool] | None = None,
    ops: ForegroundOps = WIN32_FOREGROUND,
) -> str | None:
    """창을 포그라운드로. 된 방법(`already`·`direct`·`attach`·`alt`)을, 못 했으면 None을 준다.

    Windows는 포그라운드 잠금으로 다른 프로세스의 `SetForegroundWindow`를 막는다(작업 표시줄만
    깜박임). 차례대로 해 본다:

    1. `direct`: 그냥 `SetForegroundWindow` — 포그라운드 창이 없는 등 문서의 허용 조건이면 된다
    2. `attach`: 지금 포그라운드 스레드에 `AttachThreadInput`으로 붙어 같은 입력 상태를 쓰고 다시
       한다. 포그라운드 프로세스가 더 높은 무결성(관리자로 도는 보안·근태 프로그램 등)이면 붙기가
       거부된다
    3. `alt`(`tap_alt`를 줬을 때만): Alt 누르기·떼기를 넣은 뒤 다시 한다.
       `LockSetForegroundWindow` 문서대로 시스템은 사용자가 Alt를 누르면 `SetForegroundWindow`
       호출을 다시 허용한다(포그라운드 잠금 해제). Alt만 눌렀다 떼면 문자가 들어가지 않고, 그 Alt는
       아직 포그라운드인 다른 프로그램이 받는다(그 창의 메뉴 표시줄이 켜질 수 있다). UIPI(상위
       무결성 포그라운드)에 막히면 주입도 전환도 안 될 수 있다. Alt가 이미 눌려 있으면(사람이 누르는
       중) 넣지 않는다 — 합성 떼기가 그 상태를 풀기 때문이다. `tap_alt`는 runner의 입력 액터를 거쳐
       임대권·게이트·입력 기록·복구를 지키고, 실행 첫 창 가져오기에서만 준다

    `AllowSetForegroundWindow`는 이미 포그라운드 권한이 있는 프로세스가 남에게 넘기는 함수라, 다른
    프로그램이 포그라운드를 쥔 경우에는 도움이 안 된다. `SPI_SETFOREGROUNDLOCKTIMEOUT`은 시스템
    전체 설정을 바꾸므로 쓰지 않는다.
    """
    if not ops.is_window(hwnd):
        return None
    ops.restore(hwnd)
    if ops.is_foreground(hwnd):
        return "already"
    ops.set_foreground(hwnd)
    if ops.is_foreground(hwnd):
        return "direct"
    ops.set_foreground_attached(hwnd)
    if ops.is_foreground(hwnd):
        return "attach"
    if tap_alt is not None and not ops.alt_held() and tap_alt():
        ops.set_foreground(hwnd)
        if ops.is_foreground(hwnd):
            return "alt"
    return None


def activate(hwnd: int, *, tap_alt: Callable[[], bool] | None = None) -> bool:
    """최선 노력으로 앞으로 가져온다(`bring_to_front`). 예외를 던지지 않는다. 포그라운드가 됐으면
    True.

    입력 경로는 이것을 부르지 않는다(U1: 실행 도중 포커스를 잃으면 입력하지 않고 오류). `launch`·
    `attach`·`set_current`가 창을 정한 직후 한 번 부르고(입력 없이), 실행에서 처음 정한 창은
    실행기가 가져온다(D1, runner 플랫폼 `bring_forward`만 `tap_alt`를 준다).
    """
    try:
        return bring_to_front(hwnd, tap_alt=tap_alt) is not None
    except Exception:
        return False


def set_client_size(hwnd: int, width: int, height: int) -> bool:
    """클라이언트 영역을 정확히 `width` x `height` 물리 픽셀로. 다시 읽어 다르면 False.

    창 스타일·메뉴·창 DPI로 바깥 크기를 계산하고(`AdjustWindowRectExForDpi`), 다시 읽은 클라이언트가
    다르면 그 차이만큼 바깥 크기를 고쳐 한 번 더 맞춘다 — DPI를 모르는(unaware) 창은 창 DPI가 96이라
    첫 계산의 테두리 크기가 실제(확대된) 물리 테두리와 다르다. 창이 크기를 거부하거나(최소·최대
    크기, 고정 크기 게임) 배율 때문에 그 물리 크기를 가질 수 없거나 최소화 상태면 False다.
    """
    if not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        return False
    style = int(user32.GetWindowLongPtrW(hwnd, user32.GWL_STYLE)) & 0xFFFFFFFF
    exstyle = int(user32.GetWindowLongPtrW(hwnd, user32.GWL_EXSTYLE)) & 0xFFFFFFFF
    has_menu = bool(user32.GetMenu(hwnd)) and not style & user32.WS_CHILD
    flags = user32.SWP_NOMOVE | user32.SWP_NOZORDER | user32.SWP_NOACTIVATE
    with per_monitor_v2_thread():
        rect = wintypes.RECT(0, 0, width, height)
        dpi = int(user32.GetDpiForWindow(hwnd))
        if not user32.AdjustWindowRectExForDpi(ctypes.byref(rect), style, has_menu, exstyle, dpi):
            return False
        outer = (rect.right - rect.left, rect.bottom - rect.top)
        for _ in range(_SIZE_ATTEMPTS):
            if not user32.SetWindowPos(hwnd, None, 0, 0, outer[0], outer[1], flags):
                return False
            client = _client_size(hwnd)
            if client is None:
                return False
            if client == (width, height):
                return True
            window = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(window)):
                return False
            outer = (
                window.right - window.left + width - client[0],
                window.bottom - window.top + height - client[1],
            )
    return False


def _client_size(hwnd: int) -> tuple[int, int] | None:
    client = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(client)):
        return None
    return client.right - client.left, client.bottom - client.top
