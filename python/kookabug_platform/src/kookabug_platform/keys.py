"""키 이름 → SendInput 키 입력 (구현 계획 M1 2.4 "키").

이름표 자체(정식 이름·별칭·가상 키 코드·확장 키)는 `kookabug_core.inputs.keys`에 있다 — 가짜
백엔드에서도 같은 이름이 같은 오류(`key_unknown`)를 내야 해서다. 여기서는 그 표로 실제 입력을
만든다: `wVk` + `wScan`(`MapVirtualKeyW(MAPVK_VK_TO_VSC_EX)`) + `KEYEVENTF_SCANCODE`, 확장 키는
`KEYEVENTF_EXTENDEDKEY`. 스캔 코드로 보내는 이유: DirectInput·Raw Input을 읽는 게임은 가상 키
코드만 든 입력을 무시한다. 스캔 코드가 없는 키(지금 자판에 없음)는 가상 키 코드로만 보낸다.
"""

from __future__ import annotations

from dataclasses import dataclass

from kookabug_core.inputs.keys import KeyDef, KeyUnknown, canonical_key, key_def, split_combo
from kookabug_platform.errors import KEY_UNKNOWN, PlatformError
from kookabug_platform.win32 import user32

__all__ = ["KeyStroke", "combo", "key_def", "stroke"]


@dataclass(frozen=True, slots=True)
class KeyStroke:
    """키 하나의 SendInput 값 (누르기 기준; 떼기는 `KEYEVENTF_KEYUP`을 더한다)."""

    name: str
    vk: int
    scan: int
    flags: int


def stroke(name: str) -> KeyStroke:
    """키 이름 → 입력 값. 모르는 이름은 `key_unknown`(`PlatformError`)."""
    try:
        key = key_def(name)
    except KeyUnknown as exc:
        raise PlatformError(KEY_UNKNOWN, exc.message) from exc
    return _stroke(key)


def _stroke(key: KeyDef) -> KeyStroke:
    mapped = int(user32.MapVirtualKeyW(key.vk, user32.MAPVK_VK_TO_VSC_EX))
    scan = mapped & 0xFF
    extended = key.extended or (mapped >> 8) in (0xE0, 0xE1)
    flags = user32.KEYEVENTF_EXTENDEDKEY if extended else 0
    if scan:
        flags |= user32.KEYEVENTF_SCANCODE
    return KeyStroke(key.name, key.vk, scan, flags)


def combo(text: str) -> list[KeyStroke]:
    """조합 문자열(`ctrl+a`)을 누르는 차례의 입력 값들로. 나누는 규칙은 액터와 같다."""
    try:
        names = [canonical_key(n) for n in split_combo(text)]
    except KeyUnknown as exc:
        raise PlatformError(KEY_UNKNOWN, exc.message) from exc
    return [stroke(n) for n in names]
