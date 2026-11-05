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
from typing import Final

from kookabug_core.win import dpi as _core_dpi
from kookabug_platform.errors import DPI_AWARENESS_UNAVAILABLE, PlatformError
from kookabug_platform.win32 import user32

__all__ = [
    "NORMALIZED_DIGITS",
    "client_to_screen",
    "ensure_per_monitor_v2",
    "normalized_to_pixels",
    "offset_point",
    "per_monitor_v2_thread",
    "pixels_to_normalized",
    "round_half_up",
    "scale_length",
    "window_dpi_thread",
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


@contextmanager
def window_dpi_thread(hwnd: int) -> Iterator[bool]:
    """이 스레드를 잠깐 그 창의 DPI 인식으로 둔다. 그동안 좌표·크기는 **창 자신의 좌표**(창 DPI
    기준, unaware 창이면 논리 픽셀)다. 창의 인식을 못 읽으면(창이 닫힘) 바꾸지 않고 False를 준다."""
    context = user32.GetWindowDpiAwarenessContext(hwnd) if hwnd else None
    previous = user32.SetThreadDpiAwarenessContext(context) if context else None
    try:
        yield bool(previous)
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(previous)


def scale_length(value: int, from_dpi: int, to_dpi: int) -> int:
    """정수 길이를 `from_dpi` 기준에서 `to_dpi` 기준으로 (`MulDiv`처럼 0.5는 0에서 먼 쪽으로)."""
    if from_dpi <= 0 or to_dpi <= 0:
        raise ValueError(f"DPI는 양수여야 한다: {from_dpi}, {to_dpi}")
    scaled = (abs(value) * to_dpi * 2 + from_dpi) // (2 * from_dpi)
    return scaled if value >= 0 else -scaled


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


NORMALIZED_DIGITS: Final = 6
"""정규화 좌표를 저장할 때의 소수 자릿수 (target `search.region`)."""
_STEP: Final = 10.0**-NORMALIZED_DIGITS
_MAX_STEPS: Final = 1000


def pixels_to_normalized(
    rect: Rect | tuple[int, int, int, int], client_size: tuple[int, int]
) -> tuple[float, float, float, float]:
    """`normalized_to_pixels`의 역: 클라이언트 물리 픽셀 사각형 → 정규화 `(x, y, w, h)`.

    소수 `NORMALIZED_DIGITS`자리에서 반올림하고, 그 값을 `normalized_to_pixels`로 다시 바꾼 사각형이
    `rect`와 다르면 그 변을 한 단계(`1e-6`)씩 바깥(왼쪽·위는 작게, 오른쪽·아래는 크게)부터 옮겨
    같아지는 값을 고른다. 그래서 저장한 검색 범위가 같은 클라이언트 크기에서 같은 픽셀이 된다.
    사각형은 클라이언트 안이어야 한다(아니면 `ValueError`).
    """
    x, y, w, h = (int(v) for v in rect)
    cw, ch = client_size
    if cw <= 0 or ch <= 0 or w < 0 or h < 0 or x < 0 or y < 0 or x + w > cw or y + h > ch:
        raise ValueError(f"사각형 {rect}이(가) 클라이언트 {client_size} 안이 아니다")
    nx = _edge(x, cw, outward=-1)
    ny = _edge(y, ch, outward=-1)
    nx1 = _edge(x + w, cw, outward=1)
    ny1 = _edge(y + h, ch, outward=1)
    nw = _length(nx, nx1, x + w, cw)
    nh = _length(ny, ny1, y + h, ch)
    result = (nx, ny, nw, nh)
    if normalized_to_pixels(result, client_size) != (x, y, w, h):
        raise ValueError(f"사각형 {rect}을(를) 정규화 좌표로 왕복할 수 없다 ({client_size})")
    return result


def _fits(value: float, pixel: int, size: int) -> bool:
    return min(max(round_half_up(value * size), 0), size) == pixel


def _edge(pixel: int, size: int, *, outward: int) -> float:
    """`round(v * size) == pixel`인 6자리 소수 v. 반올림한 값이 안 맞으면 바깥 방향부터 찾는다."""
    base = round(pixel / size, NORMALIZED_DIGITS)
    for k in range(_MAX_STEPS):
        for sign in (outward, -outward) if k else (0,):
            value = round(min(max(base + sign * k * _STEP, 0.0), 1.0), NORMALIZED_DIGITS)
            if _fits(value, pixel, size):
                return value
    raise ValueError(f"픽셀 {pixel}을(를) 크기 {size}의 정규화 좌표로 나타낼 수 없다")


def _length(start: float, end: float, pixel_end: int, size: int) -> float:
    """`start + w`가 `pixel_end`로 돌아오는 6자리 소수 w (덧셈 오차를 피해 한 단계씩 고친다)."""
    base = round(end - start, NORMALIZED_DIGITS)
    for k in range(_MAX_STEPS):
        for sign in (1, -1) if k else (0,):
            value = round(min(max(base + sign * k * _STEP, 0.0), 1.0), NORMALIZED_DIGITS)
            if _fits(start + value, pixel_end, size):
                return value
    raise ValueError(f"끝 픽셀 {pixel_end}을(를) 크기 {size}의 정규화 길이로 나타낼 수 없다")


def offset_point(origin: tuple[int, int], point: tuple[int, int]) -> tuple[int, int]:
    """클라이언트 점 + 클라이언트 원점(화면) = 화면 점."""
    return origin[0] + point[0], origin[1] + point[1]


def client_to_screen(hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
    """클라이언트 물리 픽셀 점 → 화면 물리 픽셀 점 = 클라이언트 원점 + 점.

    원점만 `ClientToScreen(0, 0)`(PMv2 스레드)으로 읽고 점은 더한다. 점을 `ClientToScreen`에 그대로
    넣으면 배율로 확대되는 창(DPI unaware 창, 로그온 뒤 배율을 바꾼 system-aware 창)에서
    Windows가 그 점을 창의 논리 좌표로 바꿨다 되돌리며 1~2 px 잃는다(150%에서 (10, 20) →
    원점 + (9, 19), 200%에서 원점 + (8, 19)). 캡처 자르기(`WindowInfo.client_origin`)도 같은
    원점을 쓰므로, 원점 + 점이 캡처 프레임의 그 픽셀 자리다.
    """
    origin = wintypes.POINT(0, 0)
    with per_monitor_v2_thread():
        if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            raise OSError(f"ClientToScreen 실패: hwnd={hwnd}")
    return offset_point((origin.x, origin.y), point)
