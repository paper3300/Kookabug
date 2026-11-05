"""녹화 키 해석: 가상 키 → 키 이름(M1 `inputs.keys`), 글쇠 → 글자 (M4 계획 2.7 "글자 해석").

- 키 이름은 재생 `core.input.key`가 받는 이름이다. 수정 키는 좌우를 가리지 않는 `ctrl`·`shift`·
  `alt`·`win`으로 쓴다(조합 `ctrl+a`)
- 글자는 이벤트에 붙은 관측의 자판(`hkl`)으로 정한다. 기본은 순수 표(`UsLayout` — US 배열, 한국어
  자판의 영문 모드도 같다)다. daemon은 `ToUnicodeEx`(`Win32Layout`, `wFlags` 4 — 사용자 자판
  상태를 바꾸지 않음)를 쓸 수 있다. 자판 상태(Shift·CapsLock)는 키 이벤트로 다시 짠다
- 한국어 자판(언어 0x0412)은 한글 모드면 글쇠를 두벌식 자모로(`hangul`), 일본어·중국어 입력기는
  글자가 아니라 키 사슬로 남긴다
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Mapping
from typing import Final, Literal, Protocol

from kookabug_core.inputs.keys import KEYS

__all__ = [
    "CURSOR_KEYS",
    "EDIT_KEYS",
    "MODIFIER_NAMES",
    "KeyLayout",
    "LayoutKind",
    "UsLayout",
    "Win32Layout",
    "combo_name",
    "is_modifier",
    "layout_kind",
    "vk_name",
]

VK_BACK: Final = 0x08
VK_TAB: Final = 0x09
VK_RETURN: Final = 0x0D
VK_ESCAPE: Final = 0x1B
VK_CAPITAL: Final = 0x14
VK_A: Final = 0x41

MODIFIER_NAMES: Final[Mapping[int, str]] = {
    0x10: "shift", 0xA0: "shift", 0xA1: "shift",
    0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
    0x12: "alt", 0xA4: "alt", 0xA5: "alt",
    0x5B: "win", 0x5C: "win",
}  # fmt: skip
_MODIFIER_ORDER: Final = ("ctrl", "alt", "shift", "win")

CURSOR_KEYS: Final = frozenset({0x25, 0x26, 0x27, 0x28, 0x24, 0x23, 0x2E, 0x21, 0x22})
"""칸 안 커서를 옮기거나 커서 뒤를 지우는 키 (방향키·Home·End·Delete·PageUp/Down)."""
EDIT_KEYS: Final = frozenset({VK_BACK})

_NAMES: Final[dict[tuple[int, bool], str]] = {}
for _key in KEYS.values():
    if _key.vk in MODIFIER_NAMES or _key.name == "numpad_enter":
        continue
    _NAMES.setdefault((_key.vk, _key.extended), _key.name)


def is_modifier(vk: int) -> bool:
    return vk in MODIFIER_NAMES


def vk_name(vk: int, extended: bool = False) -> str | None:
    """가상 키 → 재생 키 이름. 표에 없으면 None (그 키는 녹화하지 않고 센다)."""
    if vk in MODIFIER_NAMES:
        return MODIFIER_NAMES[vk]
    return _NAMES.get((vk, extended)) or _NAMES.get((vk, not extended))


def combo_name(modifiers: set[str], key: str) -> str:
    """`{"shift","ctrl"}`, `a` → `ctrl+shift+a`."""
    return "+".join([m for m in _MODIFIER_ORDER if m in modifiers and m != key] + [key])


type LayoutKind = Literal["korean", "cjk_ime", "other"]


def layout_kind(hkl: str | None) -> LayoutKind:
    """자판 핸들(16진 문자열)의 언어 → 한국어·다른 동아시아 입력기·그 밖."""
    if not hkl:
        return "other"
    try:
        lang = int(hkl, 16) & 0xFFFF
    except ValueError:
        return "other"
    if lang == 0x0412:
        return "korean"
    if lang in (0x0411, 0x0404, 0x0804, 0x0C04, 0x1004, 0x1404):
        return "cjk_ime"
    return "other"


class KeyLayout(Protocol):
    def char(self, vk: int, *, shift: bool, caps: bool, hkl: str | None) -> str | None:
        """그 글쇠가 찍는 글자 하나 (인쇄 가능한 글자가 아니면 None)."""
        ...


_US_PLAIN: Final = {
    0x20: " ", 0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
    0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
    0x6A: "*", 0x6B: "+", 0x6D: "-", 0x6E: ".", 0x6F: "/",
}  # fmt: skip
_US_SHIFT: Final = {
    0xBA: ":", 0xBB: "+", 0xBC: "<", 0xBD: "_", 0xBE: ">", 0xBF: "?", 0xC0: "~",
    0xDB: "{", 0xDC: "|", 0xDD: "}", 0xDE: '"',
}  # fmt: skip
_DIGIT_SHIFT: Final = ")!@#$%^&*("


class UsLayout:
    """US 배열 순수 표 (한국어 자판 영문 모드도 같은 글자)."""

    def char(self, vk: int, *, shift: bool, caps: bool, hkl: str | None) -> str | None:
        if 0x41 <= vk <= 0x5A:
            letter = chr(vk + 32)
            return letter.upper() if shift != caps else letter
        if 0x30 <= vk <= 0x39:
            return _DIGIT_SHIFT[vk - 0x30] if shift else chr(vk)
        if 0x60 <= vk <= 0x69:
            return chr(vk - 0x60 + 0x30)
        if shift and vk in _US_SHIFT:
            return _US_SHIFT[vk]
        return _US_PLAIN.get(vk)


class Win32Layout:
    """`ToUnicodeEx`로 그 자판의 글자를 읽는다 (`wFlags` 4: 커널 자판 상태를 바꾸지 않음).

    자판이 이 PC에 없거나 데드 키·여러 글자면 `UsLayout`으로 돌아간다.
    """

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Windows 전용")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._to_unicode = user32.ToUnicodeEx
        self._to_unicode.restype = ctypes.c_int
        self._to_unicode.argtypes = [
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_char_p,
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_void_p,
        ]
        self._map = user32.MapVirtualKeyExW
        self._map.restype = ctypes.c_uint
        self._map.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
        self._fallback = UsLayout()

    def char(self, vk: int, *, shift: bool, caps: bool, hkl: str | None) -> str | None:
        if not hkl:
            return self._fallback.char(vk, shift=shift, caps=caps, hkl=hkl)
        handle = ctypes.c_void_p(int(hkl, 16))
        state = (ctypes.c_ubyte * 256)()
        if shift:
            state[0x10] = 0x80
        if caps:
            state[VK_CAPITAL] = 0x01
        buf = ctypes.create_unicode_buffer(8)
        scan = self._map(vk, 0, handle)  # MAPVK_VK_TO_VSC
        n = self._to_unicode(vk, scan, ctypes.cast(state, ctypes.c_char_p), buf, 8, 4, handle)
        if n == 1 and buf.value and buf.value.isprintable():
            return buf.value
        if n == 0:
            return None
        return self._fallback.char(vk, shift=shift, caps=caps, hkl=hkl)
