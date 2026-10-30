"""SendInput 백엔드의 입력 값과 입력 직전 확인 (실제 입력 없이 `SendInput` 바꿔 끼움)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from kb_testing.fake_win32 import FakeWindowApi
from kookabug_core.inputs import ClientPoint, PlatformUnavailable
from kookabug_platform.errors import (
    INPUT_DESKTOP_UNAVAILABLE,
    KEY_UNKNOWN,
    POINT_OBSCURED,
    TARGET_ELEVATED,
    WINDOW_GONE,
    WINDOW_MINIMIZED,
    WINDOW_NOT_FOREGROUND,
    PlatformError,
)
from kookabug_platform.sendinput import (
    SendInputBackend,
    VirtualScreen,
    WindowInputGuard,
    normalize,
)
from kookabug_platform.tracker import WindowTracker
from kookabug_platform.win32 import user32
from kookabug_sdk.types import Point

SCREEN = VirtualScreen(-1920, 0, 3840, 1080)
"""왼쪽에 모니터가 하나 더 있는 가상 데스크톱."""


class Sent:
    """`SendInput` 자리: 받은 입력을 값으로 남기고 `result`(기본 = 다 넣음)를 돌려준다."""

    def __init__(self, result: int | None = None) -> None:
        self.result = result
        self.batches: list[list[dict[str, int]]] = []

    def __call__(self, inputs: Sequence[user32.INPUT]) -> int:
        batch: list[dict[str, int]] = []
        for item in inputs:
            if item.type == user32.INPUT_KEYBOARD:
                ki = item.ki
                batch.append({"vk": ki.wVk, "scan": ki.wScan, "flags": ki.dwFlags})
            else:
                mi = item.mi
                data = mi.mouseData
                batch.append({"dx": mi.dx, "dy": mi.dy, "data": data, "flags": mi.dwFlags})
        self.batches.append(batch)
        return len(inputs) if self.result is None else self.result

    @property
    def flat(self) -> list[dict[str, int]]:
        return [item for batch in self.batches for item in batch]


def backend(sent: Sent) -> SendInputBackend:
    return SendInputBackend(send=sent, screen=lambda: SCREEN)


def test_key_uses_scancode_flag() -> None:
    sent = Sent()
    b = backend(sent)
    b.down("a")
    b.up("a")
    b.down("up")
    down, up, arrow = sent.flat
    assert down == {"vk": 0x41, "scan": 0x1E, "flags": user32.KEYEVENTF_SCANCODE}
    assert up == {
        "vk": 0x41,
        "scan": 0x1E,
        "flags": user32.KEYEVENTF_SCANCODE | user32.KEYEVENTF_KEYUP,
    }
    # 화살표 = E0 48 (확장 플래그가 없으면 숫자패드 8이 된다)
    assert arrow == {
        "vk": 0x26,
        "scan": 0x48,
        "flags": user32.KEYEVENTF_SCANCODE | user32.KEYEVENTF_EXTENDEDKEY,
    }
    with pytest.raises(PlatformError) as caught:
        b.down("nosuchkey")
    assert caught.value.code == KEY_UNKNOWN


def test_text_unicode_per_utf16_unit() -> None:
    sent = Sent()
    backend(sent).text("가a😀")  # 😀은 UTF-16 대리 쌍 둘
    units = [0xAC00, 0x61, 0xD83D, 0xDE00]
    unicode, keyup = user32.KEYEVENTF_UNICODE, user32.KEYEVENTF_KEYUP
    assert sent.batches == [
        [
            {"vk": 0, "scan": unit, "flags": unicode},
            {"vk": 0, "scan": unit, "flags": unicode | keyup},
        ]
        for unit in units
    ]


def test_mouse_absolute_virtual_desk_normalization() -> None:
    # 정규화 값을 Windows 식(floor(n·크기/65536))으로 되돌리면 정확히 그 픽셀이다
    for x in (-1920, -1919, -1, 0, 1, 1000, 1918, 1919):
        nx, _ = normalize(Point(x, 0), SCREEN)
        assert 0 <= nx <= 65535
        assert SCREEN.left + nx * SCREEN.width // 65536 == x
    for y in (0, 1, 539, 1079):
        _, ny = normalize(Point(0, y), SCREEN)
        assert SCREEN.top + ny * SCREEN.height // 65536 == y

    sent = Sent()
    b = backend(sent)
    b.move(Point(100, 200))
    b.mouse_down("left", Point(100, 200))
    b.mouse_up("left")
    b.mouse_down("x2")
    absolute = (
        user32.MOUSEEVENTF_MOVE | user32.MOUSEEVENTF_ABSOLUTE | user32.MOUSEEVENTF_VIRTUALDESK
    )
    nx, ny = normalize(Point(100, 200), SCREEN)
    move, down, up, x2 = sent.flat
    assert move == {"dx": nx, "dy": ny, "data": 0, "flags": absolute}
    assert down == {"dx": nx, "dy": ny, "data": 0, "flags": absolute | user32.MOUSEEVENTF_LEFTDOWN}
    # 떼기는 좌표 없이 지금 자리에서
    assert up == {"dx": 0, "dy": 0, "data": 0, "flags": user32.MOUSEEVENTF_LEFTUP}
    assert x2 == {"dx": 0, "dy": 0, "data": user32.XBUTTON2, "flags": user32.MOUSEEVENTF_XDOWN}
    with pytest.raises(PlatformError) as caught:
        b.mouse_down("thumb")
    assert caught.value.code == KEY_UNKNOWN


def test_wheel_delta() -> None:
    sent = Sent()
    b = backend(sent)
    b.wheel(2, Point(10, 10))
    b.wheel(-1)
    first, second = sent.batches
    assert [i["flags"] & user32.MOUSEEVENTF_MOVE for i in first] == [user32.MOUSEEVENTF_MOVE, 0]
    assert first[1] == {"dx": 0, "dy": 0, "data": 240, "flags": user32.MOUSEEVENTF_WHEEL}
    # 음수(뒤로·아래)는 DWORD 2의 보수
    assert second == [
        {"dx": 0, "dy": 0, "data": -120 & 0xFFFFFFFF, "flags": user32.MOUSEEVENTF_WHEEL}
    ]


def test_sendinput_zero_return_raises() -> None:
    b = backend(Sent(result=0))
    with pytest.raises(OSError, match="0개만"):
        b.down("a")
    with pytest.raises(OSError):
        b.move(Point(0, 0))
    short = backend(Sent(result=1))
    with pytest.raises(OSError, match="2개 중 1개만"):
        short.wheel(1, Point(0, 0))


# ── 입력 직전 확인 (가짜 Win32 표) ───────────────────────────────────


MAIN, POPUP, OTHER = 0x100, 0x200, 0x300


@pytest.fixture
def api() -> FakeWindowApi:
    fake = FakeWindowApi()
    fake.add(MAIN, 10, title="Game", client_origin=(1000, 500))
    fake.add(POPUP, 10, title="Notice", owner=MAIN)
    fake.add(OTHER, 20, title="Other")
    fake.foreground = MAIN
    fake.under_point[(1005, 507)] = MAIN
    fake.under_point[(1040, 540)] = POPUP
    return fake


def guard_for(api: FakeWindowApi) -> tuple[WindowInputGuard, object]:
    tracker = WindowTracker(api)
    return WindowInputGuard(tracker, api), tracker.bind(MAIN)


def code_of(guard: WindowInputGuard, target: object, at: ClientPoint | None) -> str:
    with pytest.raises(PlatformError) as caught:
        guard.check("down", target, at)
    return caught.value.code


def test_guard_passes_and_returns_screen_point(api: FakeWindowApi) -> None:
    guard, target = guard_for(api)
    assert guard.check("down", target, None) is None
    assert guard.check("move", target, ClientPoint(5, 7)) == Point(1005, 507)
    api.foreground = POPUP  # 소유 팝업이 포그라운드여도 키보드는 대상으로 통과
    assert guard.check("text", target, None) is None


def test_guard_codes_in_order(api: FakeWindowApi) -> None:
    guard, target = guard_for(api)
    with pytest.raises(PlatformUnavailable):
        guard.check("down", None, None)
    assert code_of(guard, target, ClientPoint(40, 40)) == POINT_OBSCURED  # 소유 팝업이 덮음
    api.foreground = OTHER
    assert code_of(guard, target, None) == WINDOW_NOT_FOREGROUND
    # 잠금 화면·권한 상승은 포그라운드보다 먼저 정확한 사유로
    api.integrity[10] = 0x3000
    assert code_of(guard, target, None) == TARGET_ELEVATED
    api.locked = True
    assert code_of(guard, target, None) == INPUT_DESKTOP_UNAVAILABLE
    api.windows[MAIN].minimized = True
    assert code_of(guard, target, None) == WINDOW_MINIMIZED
    api.destroy(MAIN)
    assert code_of(guard, target, None) == WINDOW_GONE
