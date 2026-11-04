"""실제 입력 검사의 안전장치 (구현 계획 M1 2.13 `kb_testing.keys`).

검사가 실제 키보드·마우스 상태를 확인하고 정리하는 도구다. 제품 코드(`kookabug_platform`)와 따로
구현한다(그 코드를 검사하는 데 쓰므로):

- `is_down(name)`: `GetAsyncKeyState`의 최상위 비트 (주입된 입력도 반영된다)
- `assert_no_keys_held()`: 검사 시작 전에 지켜보는 키·버튼이 눌려 있지 않은지
- `release_all_for_test()`: 끝에 지켜보는 키·버튼 중 **눌린 것만** 뗀다(가상 키 코드 SendInput).
  눌리지 않은 마우스 버튼을 떼면 그 자리에 클릭이 생기므로 보내지 않는다

이 도구가 보내는 입력은 기본으로 제품과 같은 표식(`KOOKABUG_INPUT_MARK`, `dwExtraInfo`)을 싣는다 —
녹화 검사에서 정리용 떼기가 사람 입력으로 녹화되지 않게(M4 계획 2.2 C19). 녹화 검사의 "사람" 입력은
`extra_info`로 검사 표식을 준다.
"""

from __future__ import annotations

import ctypes
import time
from collections.abc import Iterable
from ctypes import wintypes
from typing import Final

__all__ = [
    "KOOKABUG_INPUT_MARK",
    "VK",
    "WATCHED",
    "assert_no_keys_held",
    "cursor_pos",
    "held",
    "is_down",
    "release_all_for_test",
    "release_input",
]

VK: Final = {
    "shift": 0x10,
    "ctrl": 0x11,
    "alt": 0x12,
    "lshift": 0xA0,
    "rshift": 0xA1,
    "lctrl": 0xA2,
    "rctrl": 0xA3,
    "lalt": 0xA4,
    "ralt": 0xA5,
    "lwin": 0x5B,
    "rwin": 0x5C,
    "a": 0x41,
    "b": 0x42,
    "x": 0x58,
    "up": 0x26,
    "mouse:left": 0x01,
    "mouse:right": 0x02,
    "mouse:middle": 0x04,
}
"""이름 → 가상 키 코드 (마우스는 `mouse:<버튼>`)."""

WATCHED: Final = tuple(VK)

KOOKABUG_INPUT_MARK: Final = 0x4B4F4F4B
"""제품 `kookabug_platform.sendinput.KOOKABUG_INPUT_MARK`와 같은 값 (제품 코드를 import하지 않고
따로 둔다 — 검사가 둘이 같은지 본다)."""

_INPUT_MOUSE, _INPUT_KEYBOARD = 0, 1
_KEYEVENTF_EXTENDEDKEY, _KEYEVENTF_KEYUP = 0x0001, 0x0002
_MOUSE_UP: Final = {"mouse:left": 0x0004, "mouse:right": 0x0010, "mouse:middle": 0x0040}
_EXTENDED: Final = frozenset({"rctrl", "ralt", "lwin", "rwin", "up"})


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _UNION(ctypes.Union):
    _fields_ = (("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32))


class _INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("u", _UNION))


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_GetAsyncKeyState = _user32.GetAsyncKeyState
_GetAsyncKeyState.restype = ctypes.c_short
_GetAsyncKeyState.argtypes = (ctypes.c_int,)
_SendInput = _user32.SendInput
_SendInput.restype = wintypes.UINT
_SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
_GetCursorPos = _user32.GetCursorPos
_GetCursorPos.restype = wintypes.BOOL
_GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)


def is_down(name: str) -> bool:
    return bool(_GetAsyncKeyState(VK[name]) & 0x8000)


def held(names: Iterable[str] = WATCHED) -> list[str]:
    return [n for n in names if is_down(n)]


def assert_no_keys_held(names: Iterable[str] = WATCHED, *, timeout: float = 10.0) -> None:
    """눌린 키·버튼이 없을 때까지 `timeout`초 기다린다 (사람이 PC를 쓰는 중이면 잠깐 누른 것은
    지나간다). 그래도 눌려 있으면 실패."""
    watched = tuple(names)
    deadline = time.monotonic() + timeout
    while down := held(watched):
        if time.monotonic() >= deadline:
            raise AssertionError(f"검사 시작 전에 눌린 키·버튼이 있다: {down} (손을 떼고 다시)")
        time.sleep(0.05)


def cursor_pos() -> tuple[int, int]:
    """마우스 커서 화면 좌표 (이 스레드의 DPI 인식 기준)."""
    pt = wintypes.POINT()
    _GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def release_input(name: str, *, extra_info: int = KOOKABUG_INPUT_MARK) -> _INPUT:
    """`name`을 떼는 `INPUT` 하나 (보내지 않는다). `extra_info`는 `dwExtraInfo` 값."""
    item = _INPUT()
    if name in _MOUSE_UP:
        item.type = _INPUT_MOUSE
        item.u.mi.dwFlags = _MOUSE_UP[name]
        item.u.mi.dwExtraInfo = extra_info
    else:
        item.type = _INPUT_KEYBOARD
        item.u.ki.wVk = VK[name]
        item.u.ki.dwFlags = _KEYEVENTF_KEYUP | (_KEYEVENTF_EXTENDEDKEY if name in _EXTENDED else 0)
        item.u.ki.dwExtraInfo = extra_info
    return item


def release_all_for_test(
    names: Iterable[str] = WATCHED, *, extra_info: int = KOOKABUG_INPUT_MARK
) -> list[str]:
    """눌린 것만 뗀다. 뗀 이름들을 돌려준다. 기본은 제품 표식을 싣는다."""
    released: list[str] = []
    for name in held(names):
        item = release_input(name, extra_info=extra_info)
        _SendInput(1, ctypes.byref(item), ctypes.sizeof(_INPUT))
        released.append(name)
    return released
