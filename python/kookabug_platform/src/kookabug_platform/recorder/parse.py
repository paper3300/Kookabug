"""저수준 훅 구조체 → 훅 이벤트 (순수, M4 계획 2.1 "이벤트 모양").

훅 콜백은 `MSLLHOOKSTRUCT`·`KBDLLHOOKSTRUCT`의 필드를 복사해 여기 함수에 넘긴다. 결과는 번호
(`event_id`·`crit_seq`)·시각을 매기기 전의 원시 입력(`recorder-script` `RawInput`과 같은 모양)이다.
좌표 `x`·`y`는 `MSLLHOOKSTRUCT.pt` 그대로(물리 화면 좌표 — 훅 프로세스는 Per-Monitor V2).
"""

from __future__ import annotations

import ctypes
from typing import Any, Final

from kookabug_platform.inputmark import KOOKABUG_INPUT_MARK
from kookabug_platform.win32.user32 import (
    KBDLLHOOKSTRUCT,
    LLKHF_EXTENDED,
    LLKHF_INJECTED,
    LLKHF_LOWER_IL_INJECTED,
    LLMHF_INJECTED,
    LLMHF_LOWER_IL_INJECTED,
    MSLLHOOKSTRUCT,
    WM_KEYDOWN,
    WM_KEYUP,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MBUTTONDOWN,
    WM_MBUTTONUP,
    WM_MOUSEHWHEEL,
    WM_MOUSEMOVE,
    WM_MOUSEWHEEL,
    WM_RBUTTONDOWN,
    WM_RBUTTONUP,
    WM_SYSKEYDOWN,
    WM_SYSKEYUP,
    WM_XBUTTONDOWN,
    WM_XBUTTONUP,
)

__all__ = [
    "MAX_SAFE",
    "is_marker",
    "key_event",
    "key_event_from_bytes",
    "mouse_event",
    "mouse_event_from_bytes",
    "wire_extra_info",
]

MAX_SAFE: Final = 2**53 - 1

_BUTTONS: Final = {
    WM_LBUTTONDOWN: ("mouse_down", "left"),
    WM_LBUTTONUP: ("mouse_up", "left"),
    WM_RBUTTONDOWN: ("mouse_down", "right"),
    WM_RBUTTONUP: ("mouse_up", "right"),
    WM_MBUTTONDOWN: ("mouse_down", "middle"),
    WM_MBUTTONUP: ("mouse_up", "middle"),
}
_KEYS: Final = {
    WM_KEYDOWN: "key_down",
    WM_SYSKEYDOWN: "key_down",
    WM_KEYUP: "key_up",
    WM_SYSKEYUP: "key_up",
}


def is_marker(extra_info: int) -> bool:
    """우리 입력 표식 (훅 프로세스가 버린다 — `dropped_marker`)."""
    return extra_info == KOOKABUG_INPUT_MARK


def wire_extra_info(value: int) -> int | str:
    """`dwExtraInfo`(ULONG_PTR) → 메시지 값 (2^53-1 넘으면 10진 문자열, 스키마 `ExtraInfo`)."""
    return value if value <= MAX_SAFE else str(value)


def _signed_high_word(value: int) -> int:
    high = (value >> 16) & 0xFFFF
    return high - 0x10000 if high & 0x8000 else high


def mouse_event(
    msg: int, x: int, y: int, mouse_data: int, flags: int, extra_info: int
) -> dict[str, Any] | None:
    """마우스 훅 메시지 하나 → 원시 입력. 모르는 메시지면 None."""
    base: dict[str, Any] = {
        "x": int(x),
        "y": int(y),
        "injected": bool(flags & LLMHF_INJECTED),
        "injected_lower_il": bool(flags & LLMHF_LOWER_IL_INJECTED),
        "extra_info": wire_extra_info(extra_info),
    }
    if msg == WM_MOUSEMOVE:
        return {"kind": "mouse_move", **base}
    if msg in _BUTTONS:
        kind, button = _BUTTONS[msg]
        return {"kind": kind, "button": button, **base}
    if msg in (WM_XBUTTONDOWN, WM_XBUTTONUP):
        which = (mouse_data >> 16) & 0xFFFF
        button = {1: "x1", 2: "x2"}.get(which)
        if button is None:
            return None
        kind = "mouse_down" if msg == WM_XBUTTONDOWN else "mouse_up"
        return {"kind": kind, "button": button, **base}
    if msg in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
        event = {"kind": "wheel", "delta": _signed_high_word(mouse_data), **base}
        if msg == WM_MOUSEHWHEEL:
            event["horizontal"] = True
        return event
    return None


def key_event(msg: int, vk: int, scan: int, flags: int, extra_info: int) -> dict[str, Any] | None:
    """키보드 훅 메시지 하나 → 원시 입력. 모르는 메시지면 None."""
    kind = _KEYS.get(msg)
    if kind is None:
        return None
    return {
        "kind": kind,
        "vk": int(vk) & 0xFF,
        "scan": int(scan) & 0xFFFF,
        "extended": bool(flags & LLKHF_EXTENDED),
        "injected": bool(flags & LLKHF_INJECTED),
        "injected_lower_il": bool(flags & LLKHF_LOWER_IL_INJECTED),
        "extra_info": wire_extra_info(extra_info),
    }


def mouse_event_from_bytes(msg: int, data: bytes) -> dict[str, Any] | None:
    """`MSLLHOOKSTRUCT` 바이트 → 원시 입력 (검사·진단용, 콜백은 필드를 바로 넘긴다)."""
    s = MSLLHOOKSTRUCT.from_buffer_copy(data[: ctypes.sizeof(MSLLHOOKSTRUCT)])
    return mouse_event(msg, s.pt.x, s.pt.y, s.mouseData, s.flags, s.dwExtraInfo)


def key_event_from_bytes(msg: int, data: bytes) -> dict[str, Any] | None:
    """`KBDLLHOOKSTRUCT` 바이트 → 원시 입력."""
    s = KBDLLHOOKSTRUCT.from_buffer_copy(data[: ctypes.sizeof(KBDLLHOOKSTRUCT)])
    return key_event(msg, s.vkCode, s.scanCode, s.flags, s.dwExtraInfo)
