"""키 이름표와 조합 나누기 (구현 계획 M1 2.4 "키").

이름은 대소문자를 가리지 않고, 조합은 `+`로 잇는다(`ctrl+shift+a`). 이름표는 순수 자료다 — 가짜
백엔드(`fake`)에서도 모르는 이름은 `key_unknown`이고, 실제 SendInput 변환(스캔 코드)은
`kookabug_platform.keys`가 이 표 위에서 한다.

정식 이름은 예제 게임 입력 기록의 키 이름과 같다(`lshift`·`rctrl`). 좌우를 가리지 않는 `shift`·
`ctrl`·`alt`는 왼쪽 키로 눌린다. 구두점 이름은 그 글자가 아니라 **그 글자가 찍힌 키**다(`+`는 `=+`
키, 대문자·윗글자가 필요하면 `shift+=`처럼 조합).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from kookabug_core.engine.errors import EngineError

__all__ = [
    "KEYS",
    "KEY_UNKNOWN",
    "MOUSE_BUTTONS",
    "KeyDef",
    "KeyUnknown",
    "canonical_button",
    "canonical_key",
    "key_def",
    "split_combo",
]

KEY_UNKNOWN: Final = "key_unknown"


class KeyUnknown(EngineError):
    """모르는 키 이름이나 마우스 버튼."""

    def __init__(self, message: str) -> None:
        super().__init__(KEY_UNKNOWN, message)


@dataclass(frozen=True, slots=True)
class KeyDef:
    """정식 이름, 가상 키 코드(`VK_*`), 확장 키 여부(스캔 코드 앞에 E0가 붙는 키)."""

    name: str
    vk: int
    extended: bool = False


def _table() -> dict[str, KeyDef]:
    keys: dict[str, KeyDef] = {}

    def add(name: str, vk: int, extended: bool = False) -> None:
        keys[name] = KeyDef(name, vk, extended)

    for i in range(26):
        add(chr(ord("a") + i), 0x41 + i)
    for i in range(10):
        add(str(i), 0x30 + i)
        add(f"numpad{i}", 0x60 + i)
    for i in range(1, 25):
        add(f"f{i}", 0x6F + i)
    for name, vk in (
        ("enter", 0x0D),
        ("esc", 0x1B),
        ("tab", 0x09),
        ("space", 0x20),
        ("backspace", 0x08),
        ("capslock", 0x14),
        ("scrolllock", 0x91),
        ("pause", 0x13),
        ("shift", 0x10),
        ("ctrl", 0x11),
        ("alt", 0x12),
        ("lshift", 0xA0),
        ("rshift", 0xA1),
        ("lctrl", 0xA2),
        ("lalt", 0xA4),
        ("multiply", 0x6A),
        ("add", 0x6B),
        ("subtract", 0x6D),
        ("decimal", 0x6E),
        (";", 0xBA),
        ("=", 0xBB),
        (",", 0xBC),
        ("-", 0xBD),
        (".", 0xBE),
        ("/", 0xBF),
        ("`", 0xC0),
        ("[", 0xDB),
        ("\\", 0xDC),
        ("]", 0xDD),
        ("'", 0xDE),
    ):
        add(name, vk)
    for name, vk in (
        ("delete", 0x2E),
        ("insert", 0x2D),
        ("home", 0x24),
        ("end", 0x23),
        ("pageup", 0x21),
        ("pagedown", 0x22),
        ("left", 0x25),
        ("up", 0x26),
        ("right", 0x27),
        ("down", 0x28),
        ("rctrl", 0xA3),
        ("ralt", 0xA5),
        ("win", 0x5B),
        ("lwin", 0x5B),
        ("rwin", 0x5C),
        ("apps", 0x5D),
        ("divide", 0x6F),
        ("numlock", 0x90),
        ("printscreen", 0x2C),
        ("numpad_enter", 0x0D),
    ):
        add(name, vk, extended=True)
    return keys


KEYS: Final[Mapping[str, KeyDef]] = _table()

_ALIASES: Final[Mapping[str, str]] = {
    "return": "enter",
    "escape": "esc",
    "del": "delete",
    "ins": "insert",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "control": "ctrl",
    "menu": "alt",
    "left_shift": "lshift",
    "right_shift": "rshift",
    "left_ctrl": "lctrl",
    "right_ctrl": "rctrl",
    "left_alt": "lalt",
    "right_alt": "ralt",
    "left_win": "lwin",
    "right_win": "rwin",
    "num0": "numpad0",
    "num1": "numpad1",
    "num2": "numpad2",
    "num3": "numpad3",
    "num4": "numpad4",
    "num5": "numpad5",
    "num6": "numpad6",
    "num7": "numpad7",
    "num8": "numpad8",
    "num9": "numpad9",
    "plus": "=",
    "+": "=",
    "minus": "-",
    "equals": "=",
    "comma": ",",
    "period": ".",
    "slash": "/",
    "backslash": "\\",
    "semicolon": ";",
    "quote": "'",
    "backquote": "`",
    "lbracket": "[",
    "rbracket": "]",
}

MOUSE_BUTTONS: Final = ("left", "right", "middle", "x1", "x2")

# "ctrl+shift+a" → ctrl, shift, a. 끝의 "+"는 키 이름이다 ("ctrl++" → ctrl, +)
_COMBO_SPLIT: Final = re.compile(r"\+(?=.)")


def split_combo(text: str) -> list[str]:
    """조합 문자열을 누르는 차례의 이름들로. 비었거나 빈 이름이 있으면(`+a`, `ctrl++a`)
    `key_unknown` — 잘못 쓴 조합도 모르는 키와 같은 사유로 끝난다."""
    names = _COMBO_SPLIT.split(text)
    if not text or any(not n for n in names):
        raise KeyUnknown(f"키 조합이 잘못됐다: {text!r}")
    return names


def canonical_key(name: str) -> str:
    """정식 키 이름 (대소문자 무시, 별칭 풀기). 모르면 `key_unknown`."""
    lowered = name.casefold()
    found = _ALIASES.get(lowered, lowered)
    if found not in KEYS:
        raise KeyUnknown(f"모르는 키 이름 {name!r}")
    return found


def key_def(name: str) -> KeyDef:
    return KEYS[canonical_key(name)]


def canonical_button(name: str) -> str:
    """정식 마우스 버튼 이름. 모르면 `key_unknown`."""
    lowered = name.casefold()
    if lowered not in MOUSE_BUTTONS:
        raise KeyUnknown(f"모르는 마우스 버튼 {name!r} (가능한 값: {', '.join(MOUSE_BUTTONS)})")
    return lowered
