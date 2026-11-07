"""`windows.list`와 창 한 장 캡처 (M2 계획 2.4·2.9). Windows가 아니면 `platform_unavailable`.

창 함수는 좌표를 읽는 동안 그 스레드를 Per-Monitor V2로 둔다(`kookabug_platform.dpi`). daemon
진입점도 프로세스 수준을 PMv2로 정한다. 그래서 크기·좌표는 물리 픽셀이다.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, Any, Final

from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.protocol import RequestFailed

if TYPE_CHECKING:
    from kookabug_platform.capture import CapturedFrame

__all__ = ["CAPTURE_TIMEOUT_MS", "METHODS", "capture_window", "require_windows"]

CAPTURE_TIMEOUT_MS: Final = 2000
"""창 한 장을 기다리는 시간 (`kookabug target test`와 같다)."""


def require_windows() -> None:
    """Windows이고 kookabug-platform이 설치돼 있어야 한다. 아니면 `platform_unavailable`."""
    if sys.platform != "win32":
        text = "창·캡처는 Windows에서만 쓸 수 있다"
        raise RequestFailed("platform_unavailable", text, message=text)
    from kookabug_daemon.targets import require_platform

    require_platform()


def _windows() -> list[dict[str, Any]]:
    from kookabug_platform.errors import PlatformError
    from kookabug_platform.windows import find_windows, window_info

    found: list[dict[str, Any]] = []
    for hwnd in find_windows():
        try:
            info = window_info(hwnd)
        except PlatformError, OSError:  # 그 사이 닫힌 창
            continue
        if info.minimized or info.client_size[0] <= 0 or info.client_size[1] <= 0:
            continue
        found.append(
            {
                "handle": hwnd,
                "title": info.title,
                "process": info.process_name,
                "pid": info.pid,
                "client_size": list(info.client_size),
                "dpi": max(1, info.dpi),
            }
        )
    return found


async def _list(call: Call) -> dict[str, Any]:
    # 원천: 실제 Windows(`_windows`) 또는 장면 가짜 게임(숨은 --platform-fake, M7 3.12)
    return {"windows": await asyncio.to_thread(call.daemon.screen_source.windows)}


def capture_window(hwnd: int) -> CapturedFrame:
    """그 창의 클라이언트 영역 한 장 (WGC). 창이 없으면 `window_not_found`, 캡처 오류는 M1 코드."""
    from kookabug_platform.capture import CaptureService
    from kookabug_platform.deadline import ObservationDeadline
    from kookabug_platform.errors import PlatformError
    from kookabug_platform.tracker import WindowTracker
    from kookabug_platform.win32.api import DEFAULT_API

    require_windows()
    if hwnd <= 0 or not DEFAULT_API.is_window(hwnd):
        raise RequestFailed("window_not_found", f"창 {hwnd:#x}이(가) 없다", message="창이 없다")
    tracker = WindowTracker()
    try:
        tracker.start()
        service = CaptureService(tracker)
        try:
            binding = tracker.bind(hwnd)
            return service.capture(binding, deadline=ObservationDeadline(CAPTURE_TIMEOUT_MS))
        finally:
            service.close_all()
    except PlatformError as exc:
        raise RequestFailed(exc.code, str(exc), message=str(exc)) from exc
    except OSError as exc:
        text = f"창 {hwnd:#x}을(를) 캡처할 수 없다: {exc}"
        raise RequestFailed("capture_failed", text, message=text) from exc
    finally:
        tracker.stop()


METHODS: Final = {"windows.list": MethodSpec(_list)}
