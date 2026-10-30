"""SendInput 입력 백엔드와 입력 직전 확인 (구현 계획 M1 2.4).

**백엔드** (`SendInputBackend`, `kookabug_core.inputs.InputBackend`): 입력 액터 스레드와 복구 경로의
떼기만 부른다. 좌표는 화면 물리 픽셀이다.

- 키: `keys.stroke`(가상 키 + 스캔 코드 + `KEYEVENTF_SCANCODE`, 확장 키 플래그)
- 글자: UTF-16 코드 단위마다 `KEYEVENTF_UNICODE` 누르기·떼기. 비밀값도 여기까지만 온다
- 마우스: `MOUSEEVENTF_ABSOLUTE|VIRTUALDESK` 정규화 좌표(가상 데스크톱 전체 0~65535). 누르기는 그
  점으로 옮기며 누른다. 휠은 한 칸 = `WHEEL_DELTA`(120), 양수 = 앞으로(위)
- `SendInput`이 넣은 개수가 모자라면(0 포함) `OSError`. UIPI가 막은 입력은 개수가 줄지 않는다 —
  그래서 무결성 확인(`target_elevated`)을 입력 직전 확인에서 한다

좌표·가상 데스크톱 크기를 다루는 호출은 그 스레드만 Per-Monitor V2로 두고 한다(물리 픽셀).

**입력 직전 확인** (`WindowInputGuard`, `kookabug_core.inputs.InputGuard`): 액터 스레드에서
`down`·`text`·`move`·`wheel` 직전마다. 떼기·`RELEASE_ALL`·복구에는 하지 않는다. 차례:

1. 대상 창 바인딩이 살아 있음 (`window_gone`) — 추적기의 대기 중인 파괴 이벤트를 먼저 처리한다
2. 최소화 아님 (`window_minimized`)
3. 입력 데스크톱을 열 수 있음 (`input_desktop_unavailable`)
4. 대상 무결성 ≤ runner (`target_elevated`)
5. 키보드·글자: 포그라운드가 대상·대상의 소유 팝업 (`window_not_foreground`)
6. 마우스: `ClientToScreen` 뒤 점 아래 최상위 창이 정확히 대상 (`point_obscured`), 그리고 5

입력 데스크톱·무결성을 포그라운드보다 먼저 보는 이유: 잠금 화면·권한 상승 게임에서는 포그라운드
판정도 실패하는데, 정확한 사유는 앞의 것이다.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable, Sequence
from typing import Final, NamedTuple

from kookabug_core.inputs import ClientPoint, GuardedOp, InputDevice, PlatformUnavailable
from kookabug_platform.dpi import per_monitor_v2_thread
from kookabug_platform.errors import KEY_UNKNOWN, PlatformError
from kookabug_platform.keys import KeyStroke, stroke
from kookabug_platform.tracker import WindowBinding, WindowTracker
from kookabug_platform.win32 import user32
from kookabug_platform.win32._ffi import last_error_text
from kookabug_platform.win32.api import DEFAULT_API, WindowApi
from kookabug_platform.windows import (
    check_foreground,
    check_input_desktop,
    check_integrity,
    check_not_minimized,
    check_point,
)
from kookabug_sdk.types import Point

__all__ = [
    "SendInputBackend",
    "VirtualScreen",
    "WindowInputGuard",
    "key_input",
    "mouse_input",
    "normalize",
    "send_inputs",
    "unicode_inputs",
    "virtual_screen",
]

_ABSOLUTE: Final = (
    user32.MOUSEEVENTF_MOVE | user32.MOUSEEVENTF_ABSOLUTE | user32.MOUSEEVENTF_VIRTUALDESK
)
# 버튼 → (누르기, 떼기, mouseData)
_BUTTONS: Final = {
    "left": (user32.MOUSEEVENTF_LEFTDOWN, user32.MOUSEEVENTF_LEFTUP, 0),
    "right": (user32.MOUSEEVENTF_RIGHTDOWN, user32.MOUSEEVENTF_RIGHTUP, 0),
    "middle": (user32.MOUSEEVENTF_MIDDLEDOWN, user32.MOUSEEVENTF_MIDDLEUP, 0),
    "x1": (user32.MOUSEEVENTF_XDOWN, user32.MOUSEEVENTF_XUP, user32.XBUTTON1),
    "x2": (user32.MOUSEEVENTF_XDOWN, user32.MOUSEEVENTF_XUP, user32.XBUTTON2),
}


class VirtualScreen(NamedTuple):
    """가상 데스크톱(모든 모니터를 덮는 사각형), 물리 픽셀."""

    left: int
    top: int
    width: int
    height: int


def virtual_screen() -> VirtualScreen:
    with per_monitor_v2_thread():
        return VirtualScreen(
            int(user32.GetSystemMetrics(user32.SM_XVIRTUALSCREEN)),
            int(user32.GetSystemMetrics(user32.SM_YVIRTUALSCREEN)),
            int(user32.GetSystemMetrics(user32.SM_CXVIRTUALSCREEN)),
            int(user32.GetSystemMetrics(user32.SM_CYVIRTUALSCREEN)),
        )


def _axis(value: int, origin: int, size: int) -> int:
    # Windows는 정규화 값 n을 픽셀 floor(n·size / 65536)로 되돌린다. 그 식으로 정확히 value가
    # 나오는 가장 작은 n (올림)
    size = max(1, size)
    n = ((value - origin) * 65536 + size - 1) // size
    return min(max(n, 0), 65535)


def normalize(at: Point, screen: VirtualScreen) -> tuple[int, int]:
    """화면 물리 픽셀 → `ABSOLUTE|VIRTUALDESK` 정규화 좌표 (0~65535)."""
    return _axis(at.x, screen.left, screen.width), _axis(at.y, screen.top, screen.height)


def key_input(key: KeyStroke, *, up: bool) -> user32.INPUT:
    item = user32.INPUT(type=user32.INPUT_KEYBOARD)
    item.ki.wVk = key.vk
    item.ki.wScan = key.scan
    item.ki.dwFlags = key.flags | (user32.KEYEVENTF_KEYUP if up else 0)
    return item


def unicode_inputs(text: str) -> list[list[user32.INPUT]]:
    """UTF-16 코드 단위마다 [누르기, 떼기] (`KEYEVENTF_UNICODE`). 보충 문자는 대리 쌍 둘이다."""
    data = text.encode("utf-16-le")
    pairs: list[list[user32.INPUT]] = []
    for i in range(0, len(data), 2):
        unit = int.from_bytes(data[i : i + 2], "little")
        pair: list[user32.INPUT] = []
        for flags in (user32.KEYEVENTF_UNICODE, user32.KEYEVENTF_UNICODE | user32.KEYEVENTF_KEYUP):
            item = user32.INPUT(type=user32.INPUT_KEYBOARD)
            item.ki.wScan = unit
            item.ki.dwFlags = flags
            pair.append(item)
        pairs.append(pair)
    return pairs


def mouse_input(
    flags: int, *, at: Point | None = None, data: int = 0, screen: VirtualScreen | None = None
) -> user32.INPUT:
    """마우스 입력 하나. `at`을 주면 그 화면 점으로 옮기는 절대 좌표를 함께 싣는다."""
    item = user32.INPUT(type=user32.INPUT_MOUSE)
    if at is not None:
        assert screen is not None
        item.mi.dx, item.mi.dy = normalize(at, screen)
        flags |= _ABSOLUTE
    item.mi.mouseData = data & 0xFFFFFFFF
    item.mi.dwFlags = flags
    return item


def send_inputs(inputs: Sequence[user32.INPUT]) -> int:
    """`SendInput` (이 스레드만 PMv2). 넣은 개수를 돌려준다."""
    array = (user32.INPUT * len(inputs))(*inputs)
    with per_monitor_v2_thread():
        return int(user32.SendInput(len(inputs), array, ctypes.sizeof(user32.INPUT)))


type SendFn = Callable[[Sequence[user32.INPUT]], int]


class SendInputBackend:
    """SendInput 백엔드. `send`·`screen`은 검사가 바꿔 끼운다."""

    device: Final = InputDevice("windows")

    def __init__(
        self,
        *,
        send: SendFn = send_inputs,
        screen: Callable[[], VirtualScreen] = virtual_screen,
    ) -> None:
        self._send_fn = send
        self._screen = screen

    @property
    def available(self) -> bool:
        return True

    def down(self, key: str) -> None:
        self._send([key_input(stroke(key), up=False)])

    def up(self, key: str) -> None:
        self._send([key_input(stroke(key), up=True)])

    def mouse_down(self, button: str, at: Point | None = None) -> None:
        down, _, data = _button(button)
        screen = None if at is None else self._screen()
        self._send([mouse_input(down, at=at, data=data, screen=screen)])

    def mouse_up(self, button: str) -> None:
        _, up, data = _button(button)
        self._send([mouse_input(up, data=data)])

    def move(self, at: Point) -> None:
        self._send([mouse_input(0, at=at, screen=self._screen())])

    def wheel(self, amount: int, at: Point | None = None) -> None:
        inputs = [] if at is None else [mouse_input(0, at=at, screen=self._screen())]
        inputs.append(mouse_input(user32.MOUSEEVENTF_WHEEL, data=amount * user32.WHEEL_DELTA))
        self._send(inputs)

    def text(self, text: str) -> None:
        for pair in unicode_inputs(text):
            self._send(pair)

    def _send(self, inputs: Sequence[user32.INPUT]) -> None:
        sent = self._send_fn(inputs)
        if sent != len(inputs):
            raise OSError(
                f"SendInput이 입력 {len(inputs)}개 중 {sent}개만 넣었다 ({last_error_text()})"
            )


def _button(button: str) -> tuple[int, int, int]:
    found = _BUTTONS.get(button)
    if found is None:
        raise PlatformError(KEY_UNKNOWN, f"모르는 마우스 버튼 {button!r}")
    return found


class WindowInputGuard:
    """입력 직전 확인. 요청의 대상은 이 실행의 창 바인딩(`WindowBinding`)이다."""

    def __init__(self, tracker: WindowTracker, api: WindowApi = DEFAULT_API) -> None:
        self.tracker = tracker
        self._api = api

    def check(self, op: GuardedOp, target: object | None, at: ClientPoint | None) -> Point | None:
        if not isinstance(target, WindowBinding):
            raise PlatformUnavailable(
                "입력 대상 창이 정해지지 않았다 (앱 실행·창 붙기로 대상 창을 먼저 정한다)"
            )
        api = self._api
        hwnd = target.hwnd
        self.tracker.sync()
        self.tracker.check(target)
        check_not_minimized(hwnd, api)
        check_input_desktop(api)
        check_integrity(hwnd, api)
        if at is None:
            check_foreground(hwnd, api)
            return None
        screen = api.client_to_screen(hwnd, at.x, at.y)
        check_point(hwnd, screen, api)
        check_foreground(hwnd, api)
        return Point(*screen)
