"""두벌식 한글 조합 (순수, M4 계획 2.7 "한글 IME", U7).

녹화는 키 이벤트만 받는다. 한글 입력기 모드였던 키는 자판 글쇠 → 자모 → 음절로 여기서 다시 짠다.
실제 입력기와 다를 수 있으므로 결과에는 "한글 조합 추정" 배지가 붙는다.

- 글쇠 → 자모는 두벌식 표준 (Shift: ㅃㅉㄸㄲㅆㅒㅖ)
- 겹모음(ㅘㅙㅚㅝㅞㅟㅢ)·겹받침(ㄳㄵㄶㄺㄻㄼㄽㄾㄿㅀㅄ)을 만들고, 받침 뒤에 모음이 오면 받침
  (겹받침이면 뒤 자음)이 다음 음절 첫소리로 넘어간다
- Backspace는 조합 중인 음절에서 자모 한 타씩 지운다(값 → 갑 → 가 → ㄱ). 조합 중이 아니면 글자
  하나를 지운다
"""

from __future__ import annotations

from typing import Final

__all__ = ["DUBEOLSIK", "TextBuffer", "jamo_for_key"]

_INITIALS: Final = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_MEDIALS: Final = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_FINALS: Final = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"
_VOWEL_PAIRS: Final = {
    ("ㅗ", "ㅏ"): "ㅘ",
    ("ㅗ", "ㅐ"): "ㅙ",
    ("ㅗ", "ㅣ"): "ㅚ",
    ("ㅜ", "ㅓ"): "ㅝ",
    ("ㅜ", "ㅔ"): "ㅞ",
    ("ㅜ", "ㅣ"): "ㅟ",
    ("ㅡ", "ㅣ"): "ㅢ",
}
_FINAL_PAIRS: Final = {
    ("ㄱ", "ㅅ"): "ㄳ",
    ("ㄴ", "ㅈ"): "ㄵ",
    ("ㄴ", "ㅎ"): "ㄶ",
    ("ㄹ", "ㄱ"): "ㄺ",
    ("ㄹ", "ㅁ"): "ㄻ",
    ("ㄹ", "ㅂ"): "ㄼ",
    ("ㄹ", "ㅅ"): "ㄽ",
    ("ㄹ", "ㅌ"): "ㄾ",
    ("ㄹ", "ㅍ"): "ㄿ",
    ("ㄹ", "ㅎ"): "ㅀ",
    ("ㅂ", "ㅅ"): "ㅄ",
}

DUBEOLSIK: Final = {
    "q": "ㅂ", "w": "ㅈ", "e": "ㄷ", "r": "ㄱ", "t": "ㅅ", "y": "ㅛ", "u": "ㅕ", "i": "ㅑ",
    "o": "ㅐ", "p": "ㅔ", "a": "ㅁ", "s": "ㄴ", "d": "ㅇ", "f": "ㄹ", "g": "ㅎ", "h": "ㅗ",
    "j": "ㅓ", "k": "ㅏ", "l": "ㅣ", "z": "ㅋ", "x": "ㅌ", "c": "ㅊ", "v": "ㅍ", "b": "ㅠ",
    "n": "ㅜ", "m": "ㅡ",
}  # fmt: skip
_SHIFTED: Final = {"q": "ㅃ", "w": "ㅉ", "e": "ㄸ", "r": "ㄲ", "t": "ㅆ", "o": "ㅒ", "p": "ㅖ"}


def jamo_for_key(letter: str, shift: bool) -> str | None:
    """영문 글쇠(a~z) → 두벌식 자모. 글쇠가 아니면 None."""
    key = letter.lower()
    if shift and key in _SHIFTED:
        return _SHIFTED[key]
    return DUBEOLSIK.get(key)


def _is_vowel(j: str) -> bool:
    return j in _MEDIALS


def _parse(strokes: list[str]) -> tuple[str | None, str | None, str | None] | None:
    """자모 타들이 음절 하나가 되면 (초성, 중성, 종성), 아니면 None."""
    if not strokes:
        return (None, None, None)
    i, n = 0, len(strokes)
    cho = jung = jong = None
    if not _is_vowel(strokes[0]):
        cho = strokes[0]
        i = 1
    if i < n and _is_vowel(strokes[i]):
        jung = strokes[i]
        i += 1
        if i < n and (jung, strokes[i]) in _VOWEL_PAIRS:
            jung = _VOWEL_PAIRS[(jung, strokes[i])]
            i += 1
    if jung is None:
        return (cho, None, None) if n == 1 else None
    if i < n:
        if cho is None or strokes[i] not in _FINALS or _is_vowel(strokes[i]):
            return None
        jong = strokes[i]
        i += 1
        if i < n and (jong, strokes[i]) in _FINAL_PAIRS:
            jong = _FINAL_PAIRS[(jong, strokes[i])]
            i += 1
    if i < n:
        return None
    return (cho, jung, jong)


def _render(strokes: list[str]) -> str:
    parsed = _parse(strokes)
    if parsed is None or not strokes:
        return ""
    cho, jung, jong = parsed
    if cho is not None and jung is not None:
        code = (_INITIALS.index(cho) * 21 + _MEDIALS.index(jung)) * 28
        code += _FINALS.index(jong) if jong else 0
        return chr(0xAC00 + code)
    return cho or jung or ""


class TextBuffer:
    """칸에 쳐진 글자를 다시 짠다: 일반 글자, 두벌식 자모(조합), Backspace."""

    def __init__(self) -> None:
        self._done: list[str] = []
        self._strokes: list[str] = []

    def _flush(self) -> None:
        if self._strokes:
            self._done.append(_render(self._strokes))
            self._strokes = []

    def type_char(self, ch: str) -> None:
        self._flush()
        self._done.append(ch)

    def type_jamo(self, j: str) -> None:
        if _parse([*self._strokes, j]) is not None:
            self._strokes.append(j)
            return
        if _is_vowel(j) and len(self._strokes) >= 2 and not _is_vowel(self._strokes[-1]):
            # 받침이 다음 음절 첫소리로 넘어간다
            moved = self._strokes.pop()
            self._flush()
            self._strokes = [moved, j]
            return
        self._flush()
        self._strokes = [j]

    def commit(self) -> None:
        """조합을 끝낸다 (커서 이동·칸 떠남)."""
        self._flush()

    def backspace(self) -> bool:
        """한 타 지운다. 지울 것이 없으면(칸에 원래 있던 글자를 지움) False."""
        if self._strokes:
            self._strokes.pop()
            return True
        if self._done:
            self._done.pop()
            return True
        return False

    def clear(self) -> None:
        self._done = []
        self._strokes = []

    def text(self) -> str:
        return "".join(self._done) + _render(self._strokes)
