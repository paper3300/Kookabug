"""두벌식 조합 (M4 계획 2.7, U7, T5)."""

from __future__ import annotations

import pytest

from kookabug_core.recorder.hangul import TextBuffer, jamo_for_key


def compose(keys: str) -> str:
    """영문 글쇠 열(대문자 = Shift, `<` = Backspace) → 조합 결과."""
    buf = TextBuffer()
    for k in keys:
        if k == "<":
            buf.backspace()
            continue
        jamo = jamo_for_key(k, k.isupper())
        assert jamo is not None
        buf.type_jamo(jamo)
    return buf.text()


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ("gksrmf", "한글"),
        ("dkssudgktpdy", "안녕하세요"),
        ("rkqt", "값"),  # 겹받침 ㅄ
        ("rkqtk", "갑사"),  # 겹받침 뒤 모음: 뒤 자음이 넘어감
        ("ekfr", "닭"),  # ㄺ
        ("Rk", "까"),  # 쌍자음 (Shift)
        ("Tkd", "쌍"),
        ("ghk", "화"),  # 겹모음 ㅘ
        ("dnl", "위"),  # ㅟ
        ("dml", "의"),  # ㅢ
        ("rkr", "각"),
        ("rkrk", "가가"),  # 받침이 다음 음절로
        ("O", "ㅒ"),
        ("rr", "ㄱㄱ"),
        ("Ekf", "딸"),
        ("rkE", "가ㄸ"),  # ㄸ은 받침이 될 수 없다
    ],
)
def test_dubeolsik_table(keys: str, expected: str) -> None:
    assert compose(keys) == expected


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ("rkqt<", "갑"),  # 자모 한 타씩
        ("rkqt<<", "가"),
        ("rkqt<<<", "ㄱ"),
        ("rkqt<<<<", ""),
        ("ghk<", "호"),  # 겹모음도 한 타
        ("gksrmf<", "한그"),
        ("gksrmf<<<", "한"),  # 조합 중인 음절이 다 지워지면 앞 글자
    ],
)
def test_backspace_units(keys: str, expected: str) -> None:
    assert compose(keys) == expected


def test_mixed_latin_and_backspace_before_start() -> None:
    buf = TextBuffer()
    buf.type_char("a")
    buf.type_jamo("ㄱ")
    buf.type_jamo("ㅏ")
    buf.type_char("1")
    assert buf.text() == "a가1"
    assert buf.backspace() and buf.backspace() and buf.backspace()
    assert not buf.backspace()  # 지울 것이 없다 (구간 시작 전 내용)
