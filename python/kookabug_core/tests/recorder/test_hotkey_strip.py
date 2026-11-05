"""녹화 단축키 지우기 (M4 계획 2.4, C13, T5)."""

from __future__ import annotations

from helpers.recorder_script import VK, Script, kinds, texts

from kookabug_core.recorder.actions import KeyAction, TextAction


def test_stop_and_secret_hotkeys_removed_including_lone_modifiers() -> None:
    s = Script()
    s.at(0).click(500, 230).type("pw")
    s.combo("ctrl", "shift", "p")  # 비밀값 표시
    s.type("x")
    s.at(3000).combo("ctrl", "shift", "r")  # 정지
    conv = s.converter()
    actions = conv.finish()
    assert kinds(actions) == ["click", "text"]  # 단축키와 그 때문에만 눌린 수정 키는 없다
    (text,) = [a for a in actions if isinstance(a, TextAction)]
    assert text.text.reveal() == "pwx" and text.marked_secret
    assert conv.counts.hotkeys == 2


def test_modifier_used_by_other_key_kept() -> None:
    # Ctrl을 누른 채 S(조합) 뒤 Shift+R(단축키): 그 사이 다른 키가 있었던 Ctrl의 ctrl+s는 남는다
    s = Script()
    s.at(0).key_down(VK["ctrl"]).wait(10).tap(0x53)  # S
    s.key_down(VK["shift"]).wait(10).tap(0x52).key_up(VK["shift"]).wait(10).key_up(VK["ctrl"])
    actions = s.run()
    assert [a.keys for a in actions if isinstance(a, KeyAction)] == ["ctrl+s"]


def test_secret_hotkey_without_span_marks_next_span() -> None:
    s = Script()
    s.at(0).combo("ctrl", "shift", "p")
    s.at(1000).click(500, 300).type("abc")
    (text,) = [a for a in s.run() if isinstance(a, TextAction)]
    assert text.marked_secret
    assert texts(s.run()) == ["abc"]
