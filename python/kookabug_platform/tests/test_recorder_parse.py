"""저수준 훅 구조체 → 훅 이벤트 해석 (M4 계획 2.1 "이벤트 모양", T3 CI)."""

from __future__ import annotations

import ctypes
from typing import Any

import pytest

from kookabug_core.schema.shape import validator
from kookabug_platform.inputmark import KOOKABUG_INPUT_MARK
from kookabug_platform.recorder.hookproc import HookCore
from kookabug_platform.recorder.parse import (
    MAX_SAFE,
    is_marker,
    key_event_from_bytes,
    mouse_event_from_bytes,
    wire_extra_info,
)
from kookabug_platform.win32 import user32
from kookabug_platform.win32.user32 import KBDLLHOOKSTRUCT, MSLLHOOKSTRUCT


def mouse_bytes(x: int, y: int, data: int = 0, flags: int = 0, extra: int = 0) -> bytes:
    s = MSLLHOOKSTRUCT()
    s.pt.x, s.pt.y = x, y
    s.mouseData, s.flags, s.time, s.dwExtraInfo = data, flags, 1234, extra
    return bytes(memoryview(s).cast("B"))


def key_bytes(vk: int, scan: int, flags: int = 0, extra: int = 0) -> bytes:
    s = KBDLLHOOKSTRUCT()
    s.vkCode, s.scanCode, s.flags, s.time, s.dwExtraInfo = vk, scan, flags, 1234, extra
    return bytes(memoryview(s).cast("B"))


def hook_event_errors(event: dict[str, Any]) -> list[str]:
    return [e.message for e in validator("recorder-hook", "#/$defs/HookEvent").iter_errors(event)]


@pytest.mark.parametrize(
    ("msg", "data", "expected"),
    [
        (user32.WM_MOUSEMOVE, 0, {"kind": "mouse_move"}),
        (user32.WM_LBUTTONDOWN, 0, {"kind": "mouse_down", "button": "left"}),
        (user32.WM_LBUTTONUP, 0, {"kind": "mouse_up", "button": "left"}),
        (user32.WM_RBUTTONDOWN, 0, {"kind": "mouse_down", "button": "right"}),
        (user32.WM_MBUTTONUP, 0, {"kind": "mouse_up", "button": "middle"}),
        (user32.WM_XBUTTONDOWN, 1 << 16, {"kind": "mouse_down", "button": "x1"}),
        (user32.WM_XBUTTONUP, 2 << 16, {"kind": "mouse_up", "button": "x2"}),
        (user32.WM_MOUSEWHEEL, 120 << 16, {"kind": "wheel", "delta": 120}),
        (user32.WM_MOUSEWHEEL, 0xFF88 << 16, {"kind": "wheel", "delta": -120}),
        (user32.WM_MOUSEHWHEEL, 240 << 16, {"kind": "wheel", "delta": 240, "horizontal": True}),
    ],
)
def test_mouse_struct_bytes_to_event(msg: int, data: int, expected: dict[str, Any]) -> None:
    event = mouse_event_from_bytes(msg, mouse_bytes(-1500, 300, data))
    assert event is not None
    assert {k: event[k] for k in expected} == expected
    assert (event["x"], event["y"]) == (-1500, 300)  # 왼쪽 모니터 음수 좌표 그대로
    assert event["injected"] is False and event["injected_lower_il"] is False
    assert event["extra_info"] == 0
    if expected["kind"] != "wheel":
        assert "horizontal" not in event


def test_unknown_messages_are_ignored() -> None:
    assert mouse_event_from_bytes(0x0203, mouse_bytes(0, 0)) is None  # WM_LBUTTONDBLCLK
    assert mouse_event_from_bytes(user32.WM_XBUTTONDOWN, mouse_bytes(0, 0, 3 << 16)) is None
    assert key_event_from_bytes(0x0102, key_bytes(0x41, 0x1E)) is None  # WM_CHAR


def test_mouse_injected_flags() -> None:
    injected = mouse_event_from_bytes(
        user32.WM_LBUTTONDOWN, mouse_bytes(1, 2, flags=user32.LLMHF_INJECTED, extra=77)
    )
    assert injected is not None
    assert (injected["injected"], injected["injected_lower_il"], injected["extra_info"]) == (
        True,
        False,
        77,
    )
    lower = mouse_event_from_bytes(
        user32.WM_LBUTTONUP,
        mouse_bytes(1, 2, flags=user32.LLMHF_INJECTED | user32.LLMHF_LOWER_IL_INJECTED),
    )
    assert lower is not None
    assert (lower["injected"], lower["injected_lower_il"]) == (True, True)


@pytest.mark.parametrize(
    ("msg", "kind"),
    [
        (user32.WM_KEYDOWN, "key_down"),
        (user32.WM_KEYUP, "key_up"),
        (user32.WM_SYSKEYDOWN, "key_down"),
        (user32.WM_SYSKEYUP, "key_up"),
    ],
)
def test_key_struct_bytes_to_event(msg: int, kind: str) -> None:
    event = key_event_from_bytes(msg, key_bytes(0x41, 0x1E))
    assert event == {
        "kind": kind,
        "vk": 0x41,
        "scan": 0x1E,
        "extended": False,
        "injected": False,
        "injected_lower_il": False,
        "extra_info": 0,
    }


def test_key_flags_extended_injected_lower_il() -> None:
    flags = user32.LLKHF_EXTENDED | user32.LLKHF_INJECTED | user32.LLKHF_LOWER_IL_INJECTED
    event = key_event_from_bytes(user32.WM_KEYDOWN, key_bytes(0x26, 0x48, flags, extra=5))
    assert event is not None
    assert (event["extended"], event["injected"], event["injected_lower_il"]) == (True, True, True)
    assert event["extra_info"] == 5
    only_injected = key_event_from_bytes(
        user32.WM_KEYUP, key_bytes(0x26, 0x48, user32.LLKHF_INJECTED)
    )
    assert only_injected is not None
    assert (only_injected["extended"], only_injected["injected_lower_il"]) == (False, False)


def test_marker_and_large_extra_info() -> None:
    assert is_marker(KOOKABUG_INPUT_MARK)
    assert not is_marker(KOOKABUG_INPUT_MARK + 1)
    assert not is_marker(0)
    # ULONG_PTR는 64비트 — 2^53-1을 넘으면 10진 문자열 (JSON 정수 정밀도)
    big = 2**60 + 3
    assert wire_extra_info(MAX_SAFE) == MAX_SAFE
    assert wire_extra_info(MAX_SAFE + 1) == str(MAX_SAFE + 1)
    event = key_event_from_bytes(user32.WM_KEYDOWN, key_bytes(0x41, 0x1E, extra=big))
    assert event is not None
    assert event["extra_info"] == str(big)
    assert ctypes.sizeof(MSLLHOOKSTRUCT) >= 24 and ctypes.sizeof(KBDLLHOOKSTRUCT) >= 24


def test_numbered_events_match_hook_event_schema() -> None:
    """훅 콜백 경로로 번호를 매긴 이벤트가 `recorder-hook` `HookEvent` 모양이다."""
    now = [0]
    core = HookCore(clock=lambda: now[0])
    core.on_mouse(user32.WM_MOUSEMOVE, 10, 20, 0, 0, 0)
    now[0] = 1_000_000
    core.on_mouse(user32.WM_LBUTTONDOWN, 10, 20, 0, user32.LLMHF_INJECTED, 2**60)
    core.on_mouse(user32.WM_MOUSEWHEEL, 10, 20, 0xFF88 << 16, 0, 0)
    core.on_mouse(user32.WM_MOUSEHWHEEL, 10, 20, 120 << 16, 0, 0)
    core.on_key(user32.WM_KEYDOWN, 0x41, 0x1E, user32.LLKHF_EXTENDED, 0)
    batch = core.take_batch(now[0])
    assert batch is not None
    assert [e["kind"] for e in batch["events"]] == [
        "mouse_move",
        "mouse_down",
        "wheel",
        "wheel",
        "key_down",
    ]
    for event in batch["events"]:
        assert hook_event_errors(event) == [], event
