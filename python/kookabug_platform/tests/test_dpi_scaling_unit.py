"""배율로 확대되는 창의 좌표·크기 계산 (M1 D7 화면 배율 결함).

실제 배율을 바꾸지 않고 가짜 DPI 값으로 본다. 가짜 창은 Windows의 DPI 가상화를 흉내 낸다:
창 좌표(창 DPI 기준)로 크기를 갖고, 물리 값은 창·클라이언트의 각 경계를 따로 배율로 바꿔 반올림한
차이다. 실제 배율 검사(`test_windows.py`의 unaware·system 창)는 조율자가 150·200%에서 돌린다.
"""

from __future__ import annotations

from ctypes import wintypes
from typing import Any

import pytest

from kookabug_platform import dpi
from kookabug_platform.dpi import round_half_up, scale_length
from kookabug_platform.windows import fit_client_size

SCALES = (96, 120, 144, 192)  # 100·125·150·200%


def test_scale_length_rounds_like_muldiv() -> None:
    assert scale_length(960, 144, 96) == 640
    assert scale_length(640, 96, 144) == 960
    assert scale_length(961, 144, 96) == 641  # 640.67
    assert scale_length(1, 192, 96) == 1  # 0.5는 0에서 먼 쪽
    assert scale_length(-1, 192, 96) == -1
    assert scale_length(3, 144, 96) == 2
    assert scale_length(800, 96, 96) == 800
    with pytest.raises(ValueError):
        scale_length(1, 0, 96)


class FakeScaledWindow:
    """DPI 가상화된 창 하나 (`ClientSizeOps`). 크기는 창 좌표, `physical_client`만 물리 픽셀."""

    def __init__(
        self,
        window_dpi: int,
        monitor_dpi: int,
        *,
        position: tuple[int, int] = (0, 0),
        border: tuple[int, int, int, int] = (8, 31, 8, 8),
        menu_wrap: int = 0,
        fixed: bool = False,
    ) -> None:
        self.window_dpi = window_dpi
        self.monitor_dpi = monitor_dpi
        self.position = position
        self.border = border
        self.menu_wrap = menu_wrap
        """크기를 바꾸면 메뉴 줄이 늘어 클라이언트 높이가 이만큼 줄어든다 (계산으로는 모른다)."""
        self.fixed = fixed
        self.size = (500, 400)
        self.sets: list[tuple[int, int]] = []

    def _physical(self, value: int) -> int:
        return round_half_up(value * self.monitor_dpi / self.window_dpi)

    def frame_for(self, width: int, height: int) -> tuple[int, int] | None:
        left, top, right, bottom = self.border
        return width + left + right, height + top + bottom

    def set_outer(self, width: int, height: int) -> bool:
        self.sets.append((width, height))
        if not self.fixed:
            self.size = (width, height)
        return True

    def outer(self) -> tuple[int, int] | None:
        return self.size

    def client(self) -> tuple[int, int] | None:
        left, top, right, bottom = self.border
        wrap = self.menu_wrap if self.sets else 0
        return self.size[0] - left - right, self.size[1] - top - bottom - wrap

    def physical_client(self) -> tuple[int, int] | None:
        width, height = self.client() or (0, 0)
        x = self.position[0] + self.border[0]
        y = self.position[1] + self.border[1]
        return (
            self._physical(x + width) - self._physical(x),
            self._physical(y + height) - self._physical(y),
        )


@pytest.mark.parametrize("monitor_dpi", SCALES)
@pytest.mark.parametrize("window_dpi", [96, 144])
def test_fit_client_size_in_window_coordinates(window_dpi: int, monitor_dpi: int) -> None:
    # window_dpi 96: unaware 창, 또는 로그아웃 없이 배율을 바꾼(시스템 DPI 96) system-aware 창.
    # window_dpi 144: 로그온 때부터 150%인 system-aware 창 (그 모니터에서는 확대 없음)
    if 960 * window_dpi % monitor_dpi or 600 * window_dpi % monitor_dpi:
        pytest.skip("창 좌표로 정수가 아닌 조합")
    logical = (960 * window_dpi // monitor_dpi, 600 * window_dpi // monitor_dpi)
    for position in [(x, y) for x in range(4) for y in range(4)]:
        window = FakeScaledWindow(window_dpi, monitor_dpi, position=position)
        assert fit_client_size((960, 600), window_dpi, monitor_dpi, window), position
        # 창 DPI 기준 테두리로 계산한 바깥 크기 한 번으로 맞는다 (흔들림 없음)
        assert window.sets == [(logical[0] + 16, logical[1] + 39)]
        assert window.physical_client() == (960, 600)


def test_fit_client_size_odd_window_position_at_150() -> None:
    # 150%: 창 좌표 경계가 홀수면 물리 경계가 .5 — 640x400의 1.5배는 정수라 그래도 정확
    window = FakeScaledWindow(96, 144, position=(1, 3), border=(7, 30, 7, 7))
    assert fit_client_size((960, 600), 96, 144, window)
    assert window.client() == (640, 400)


def test_fit_client_size_corrects_measured_difference() -> None:
    window = FakeScaledWindow(96, 144, menu_wrap=20)
    assert fit_client_size((960, 600), 96, 144, window)
    assert window.sets == [(656, 439), (656, 459)]
    assert window.physical_client() == (960, 600)


def test_fit_client_size_refusals_are_false() -> None:
    # 고정 크기 창: 크기가 안 바뀐다
    assert not fit_client_size((960, 600), 96, 144, FakeScaledWindow(96, 144, fixed=True))
    # 150%에서 961 px는 창 좌표 정수 크기가 없다 (640.67) — 어느 위치에서도 거짓 성공은 없다
    for x in range(4):
        window = FakeScaledWindow(96, 144, position=(x, 0))
        assert fit_client_size((961, 600), 96, 144, window) == (
            window.physical_client() == (961, 600)
        )


def test_fit_client_size_identity_at_same_dpi() -> None:
    # PMv2 창(창 DPI = 모니터 DPI): 물리 크기가 곧 창 좌표
    window = FakeScaledWindow(144, 144)
    assert fit_client_size((961, 601), 144, 144, window)
    assert window.sets == [(977, 640)]


def test_client_to_screen_adds_point_to_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    # 확대되는 창의 ClientToScreen처럼 점을 논리 좌표로 바꿨다 되돌리며 잃는 가짜(150%: 10 → 9)
    seen: list[tuple[int, int]] = []

    def lossy(hwnd: int, point: Any) -> bool:
        pt: wintypes.POINT = point._obj  # ctypes.byref 인자
        seen.append((pt.x, pt.y))
        pt.x = 100 + int(int(pt.x / 1.5) * 1.5)
        pt.y = 200 + int(int(pt.y / 1.5) * 1.5)
        return True

    monkeypatch.setattr(dpi.user32, "ClientToScreen", lossy)
    assert dpi.client_to_screen(0x1234, (10, 20)) == (110, 220)
    assert seen == [(0, 0)]  # 점은 넣지 않고 원점만 읽는다


def test_client_to_screen_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dpi.user32, "ClientToScreen", lambda hwnd, point: False)
    with pytest.raises(OSError):
        dpi.client_to_screen(0x1234, (1, 2))
