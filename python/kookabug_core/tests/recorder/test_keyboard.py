"""키 이름·글자 해석 (M4 계획 2.7, T5): 관측 `hkl` 기준 표, 한국어 IME 모드, 다른 IME."""

from __future__ import annotations

import sys

import pytest
from helpers.recorder_script import JA, KO, US, Script, kinds, texts

from kookabug_core.recorder.actions import KeyAction, TextAction
from kookabug_core.recorder.keyboard import UsLayout, layout_kind, vk_name

CASES = [
    # (vk, shift, 글자)
    (0x41, False, "a"),
    (0x41, True, "A"),
    (0x31, False, "1"),
    (0x31, True, "!"),
    (0xBD, False, "-"),
    (0xBD, True, "_"),
    (0xBA, True, ":"),
    (0xDE, True, '"'),
    (0x20, False, " "),
    (0x0D, False, None),
    (0x25, False, None),
]


@pytest.mark.parametrize("hkl", [US, KO])
@pytest.mark.parametrize(("vk", "shift", "expected"), CASES)
def test_us_and_korean_alnum_table(hkl: str, vk: int, shift: bool, expected: str | None) -> None:
    assert UsLayout().char(vk, shift=shift, caps=False, hkl=hkl) == expected


def _installed(hkl: str) -> bool:
    import ctypes

    user32 = ctypes.WinDLL("user32")
    n = user32.GetKeyboardLayoutList(0, None)
    buf = (ctypes.c_void_p * max(n, 1))()
    user32.GetKeyboardLayoutList(n, buf)
    return any((v or 0) & 0xFFFFFFFF == int(hkl, 16) for v in buf)


@pytest.mark.skipif(sys.platform != "win32", reason="ToUnicodeEx는 Windows 전용")
@pytest.mark.parametrize("hkl", ["04090409", "04120412"])
def test_win32_to_unicode_matches_table(hkl: str) -> None:
    from kookabug_core.recorder.keyboard import Win32Layout

    if not _installed(hkl):
        pytest.skip(f"자판 {hkl}가 이 PC에 없다")
    layout = Win32Layout()
    for vk, shift, expected in CASES:
        assert layout.char(vk, shift=shift, caps=False, hkl=hkl) == expected, (vk, shift)


def test_vk_names_and_layout_kind() -> None:
    assert vk_name(0x0D) == "enter" and vk_name(0x25, True) == "left" and vk_name(0xA2) == "ctrl"
    assert vk_name(0x5B, True) == "win" and vk_name(0x41) == "a" and vk_name(0xE7) is None
    assert layout_kind(KO) == "korean" and layout_kind("e0010412") == "korean"
    assert (
        layout_kind(JA) == "cjk_ime" and layout_kind(US) == "other" and layout_kind(None) == "other"
    )


def test_korean_native_mode_composes_hangul_with_badge() -> None:
    s = Script()
    s.hkl = KO
    s.at(10).click(500, 230).type("dkssudgktpdy")  # 안녕하세요
    for ms in range(0, s.t // 1_000_000 + 250, 250):  # 대상이 앞에 있는 동안 250 ms마다 표본
        s.ime("native", at_ms=ms)
    (text,) = [a for a in s.run() if isinstance(a, TextAction)]
    assert text.text.reveal() == "안녕하세요"
    assert "hangul_guess" in text.badges and text.needs_review == ()


def test_korean_alnum_mode_is_latin() -> None:
    s = Script()
    s.hkl = KO
    s.at(0).ime("alphanumeric").at(10).click(500, 230).type("abc")
    s.ime("alphanumeric")
    (text,) = [a for a in s.run() if isinstance(a, TextAction)]
    assert text.text.reveal() == "abc" and text.badges == () and text.needs_review == ()


def test_ime_unknown_needs_review() -> None:
    s = Script()
    s.hkl = KO
    s.at(0).click(500, 230).type("abc")  # 300 ms 안 표본 없음
    (text,) = [a for a in s.run() if isinstance(a, TextAction)]
    assert text.text.reveal() == "abc" and "ime_unknown" in text.needs_review


def test_valid_prior_sample_plus_new_failed_sample_is_ime_unknown() -> None:
    # 3차 검수 N6: 앞의 정상 한글 표본이 유효해도 그 뒤 조회가 실패하면 그 키는 판정 불가
    s = Script()
    s.hkl = KO
    s.at(0).ime("native")
    s.at(100).click(500, 230)
    s.at(200).type("r")  # 120 ms 앞 정상 표본
    s.at(250).ime("native", status="timeout")
    good = Script()
    good.hkl = KO
    good.at(0).ime("native").at(100).click(500, 230).at(200).type("r")
    (ok,) = [a for a in good.run() if isinstance(a, TextAction)]
    assert ok.text.reveal() == "ㄱ" and ok.needs_review == ()  # 대조: 실패 표본 없으면 한글
    (text,) = [a for a in s.run() if isinstance(a, TextAction)]
    assert "ime_unknown" in text.needs_review
    assert text.text.reveal() == "r"  # 영문으로 해석하되 확인 필요


def test_non_korean_ime_falls_back_to_key_chain() -> None:
    s = Script()
    s.hkl = JA
    s.at(0).click(500, 230).type("ka")
    actions = s.run()
    assert texts(actions) == []
    keys = [a for a in actions if isinstance(a, KeyAction)]
    assert [k.keys for k in keys] == ["k", "a"]
    assert all("ime_other" in k.badges for k in keys)
    assert kinds(actions) == ["click", "key", "key"]
