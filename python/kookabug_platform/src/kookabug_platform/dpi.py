"""DPI 인식과 좌표 변환 (구현 계획 M1 2.2).

**좌표의 단일 기준은 대상 창 클라이언트 영역의 물리 픽셀**이다. 정규화 사각형은 그 순간의 클라이언트
크기를 곱하고, 화면 좌표는 입력 직전에만(액터 스레드) `client_to_screen`으로 만든다.

이 패키지의 창 함수는 좌표를 읽고 쓰는 동안 **그 스레드만** Per-Monitor V2로 둔다
(`per_monitor_v2_thread`). 그래서 프로세스 수준이 무엇이든(검사의 pytest 프로세스 포함) 물리 픽셀을
본다. runner는 진입점에서 프로세스 수준도 PMv2로 정한다(`kookabug_core.win.dpi`).
"""

from __future__ import annotations

import ctypes
import math
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes

from kookabug_core.win import dpi as _core_dpi
from kookabug_platform.errors import DPI_AWARENESS_UNAVAILABLE, PlatformError
from kookabug_platform.win32 import user32

__all__ = [
    "client_to_screen",
    "ensure_per_monitor_v2",
    "normalized_to_pixels",
    "offset_point",
    "per_monitor_v2_thread",
    "round_half_up",
]

type Rect = tuple[int, int, int, int]
"""`(x, y, w, h)` 클라이언트 물리 픽셀."""


def ensure_per_monitor_v2() -> None:
    """프로세스를 Per-Monitor V2로 정하고 확인한다. 안 되면 `dpi_awareness_unavailable`."""
    try:
        _core_dpi.ensure_per_monitor_v2()
    except _core_dpi.DpiAwarenessUnavailable as exc:
        raise PlatformError(DPI_AWARENESS_UNAVAILABLE, str(exc)) from exc


@contextmanager
def per_monitor_v2_thread() -> Iterator[None]:
    """이 스레드만 잠깐 PMv2로 둔다 (좌표를 물리 픽셀로 읽고 쓰려고). 끝나면 되돌린다."""
    previous = user32.SetThreadDpiAwarenessContext(
        user32.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    )
    try:
        yield
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(previous)


def round_half_up(value: float) -> int:
    # 파이썬 round()는 짝수 쪽으로 반올림한다. 좌표는 0.5를 늘 위로 올린다
    return math.floor(value + 0.5)


def normalized_to_pixels(
    rect: tuple[float, float, float, float], client_size: tuple[int, int]
) -> Rect:
    """정규화 사각형 `(x, y, w, h)`(0~1)를 그 순간 클라이언트 크기의 물리 픽셀로.

    네 변을 각각 반올림하고(`x0 = round(x·W)`, `x1 = round((x+w)·W)`) 클라이언트 안으로 자른다.
    그래서 이웃한 정규화 사각형은 픽셀에서도 겹치거나 틈이 생기지 않는다.
    """
    x, y, w, h = rect
    cw, ch = client_size
    x0 = min(max(round_half_up(x * cw), 0), cw)
    y0 = min(max(round_half_up(y * ch), 0), ch)
    x1 = min(max(round_half_up((x + w) * cw), x0), cw)
    y1 = min(max(round_half_up((y + h) * ch), y0), ch)
    return x0, y0, x1 - x0, y1 - y0


def offset_point(origin: tuple[int, int], point: tuple[int, int]) -> tuple[int, int]:
    """클라이언트 점 + 클라이언트 원점(화면) = 화면 점."""
    return origin[0] + point[0], origin[1] + point[1]


def client_to_screen(hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
    """클라이언트 물리 픽셀 점 → 화면 물리 픽셀 점 (`ClientToScreen`, PMv2 스레드)."""
    pt = wintypes.POINT(*point)
    with per_monitor_v2_thread():
        if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
            raise OSError(f"ClientToScreen 실패: hwnd={hwnd}")
    return pt.x, pt.y
