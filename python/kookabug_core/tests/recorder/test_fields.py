"""입력 칸 구간 (M4 계획 2.7, 검수 H2, T5): 쉬어도 한 구간, 편집 키 흡수, 끝 조건."""

from __future__ import annotations

from helpers.recorder_script import VK, Script, kinds, texts

from kookabug_core.recorder.actions import KeyAction, TextAction
from kookabug_core.recorder.fields import FieldSpan


def text_actions(actions: list) -> list[TextAction]:
    return [a for a in actions if isinstance(a, TextAction)]


def test_field_span_survives_long_pause() -> None:
    s = Script()
    s.at(0).click(500, 230).type("abc").wait(3000).type("def")
    actions = s.run()
    assert kinds(actions) == ["click", "text"]  # 구간 하나 = type_text 하나
    (text,) = text_actions(actions)
    assert text.text.reveal() == "abcdef"
    assert text.in_field and text.start_kind == "click" and text.anchor == (500, 230)
    assert text.clear is False and text.needs_review == ()


def test_span_starts_long_after_click() -> None:
    s = Script()
    s.at(0).click(500, 230).wait(5000).type("qa_tester")
    actions = s.run()
    (text,) = text_actions(actions)
    assert text.text.reveal() == "qa_tester" and text.span_id == 1 and text.in_field


def test_tab_starts_new_span() -> None:
    s = Script()
    s.at(0).click(500, 230).type("id01").tap("tab").type("pw").tap("enter")
    actions = s.run()
    assert kinds(actions) == ["click", "text", "key", "text", "key"]
    first, second = text_actions(actions)
    assert (first.text.reveal(), second.text.reveal()) == ("id01", "pw")
    assert second.start_kind == "tab" and second.span_id != first.span_id
    assert [a.keys for a in actions if isinstance(a, KeyAction)] == ["tab", "enter"]


def test_backspace_and_ctrl_a_retype_absorbed() -> None:
    s = Script()
    s.at(0).click(500, 230).type("abx").tap("backspace").type("c")
    s.at(3000).click(500, 310).type("old").combo("ctrl", "a").type("new")
    s.at(6000).click(500, 400).type("zz").combo("ctrl", "a").tap("backspace")
    actions = s.run()
    a, b, c = text_actions(actions)
    assert (a.text.reveal(), a.clear) == ("abc", False)
    assert (b.text.reveal(), b.clear) == ("new", True)  # 전체 바꿈
    assert (c.text.reveal(), c.clear) == ("", True)  # 비움
    assert not [x for x in actions if isinstance(x, KeyAction)]  # 편집 키는 동작이 아니다


def test_backspace_past_start_sets_clear() -> None:
    s = Script()
    s.at(0).click(500, 230).tap("backspace").tap("backspace").type("hi")
    (text,) = text_actions(s.run())
    assert (text.text.reveal(), text.clear) == ("hi", True)  # 기존 내용이 있었다


def test_cursor_move_in_field_needs_review() -> None:
    s = Script()
    s.at(0).click(500, 230).type("abc").tap("left").type("x")
    (text,) = text_actions(s.run())
    assert "cursor_moved_in_field" in text.needs_review
    # 칸 상자를 알면 칸 안 클릭도 커서 이동이다 (구간은 이어진다)
    s2 = Script()
    s2.at(0).click(500, 230).type("abc").click(520, 232).type("d")
    actions = s2.run(field_box=lambda span: (400, 205, 320, 50))
    assert kinds(actions) == ["click", "text"]
    (text2,) = text_actions(actions)
    assert text2.text.reveal() == "abcd" and "cursor_moved_in_field" in text2.needs_review


def test_enter_or_click_ends_span() -> None:
    s = Script()
    s.at(0).click(500, 230).type("abc").tap("enter").type("x")
    s.at(3000).click(500, 230).type("def").click(800, 500).type("y")
    actions = s.run()
    assert texts(actions) == ["abc", "x", "def", "y"]
    loose = text_actions(actions)[1]
    assert loose.in_field is False and loose.start_kind == "none"
    assert kinds(actions) == ["click", "text", "key", "text", "click", "text", "click", "text"]


def test_loose_text_groups_by_one_second_gap() -> None:
    s = Script()
    s.at(0).type("ab").wait(1500).type("c")
    assert texts(s.run()) == ["ab", "c"]


class Gone:
    """칸 없음 확정 시각 (가짜 칸 존재 판정)."""

    def __init__(self, at_ns: int) -> None:
        self.at_ns = at_ns

    def gone(self, span: FieldSpan, t_ns: int) -> bool:
        return span.t_start < self.at_ns <= t_ns


def test_field_absence_confirmed_ends_span_value_change_does_not() -> None:
    s = Script()
    s.at(0).click(500, 230).type("abc").wait(2000).type("def")
    one = s.run(presence=Gone(10**15))  # 칸 값·포커스만 바뀜 → 확정 안 함
    assert texts(one) == ["abcdef"]
    two = s.run(presence=Gone(1_500_000_000))  # 장면 전환으로 없음 확정
    assert texts(two) == ["abc", "def"]
    assert [t.in_field for t in text_actions(two)] == [True, False]


def test_password_hint_from_first_key_obs() -> None:
    s = Script()
    s.at(0).click(500, 300)
    s.type("p")
    first_key = next(e for e in s.events if e["kind"] == "key_down")
    s.obs[first_key["event_id"]]["focus_password"] = True
    s.type("w")
    (text,) = text_actions(s.run())
    assert text.password_hint is True


def test_shift_letters_and_symbols() -> None:
    s = Script()
    s.at(0).click(10, 10).type("Pass-01!")
    assert texts(s.run()) == ["Pass-01!"]


def test_capslock_toggles_case() -> None:
    s = Script()
    s.at(0).click(10, 10).tap(VK["capslock"]).type("ab").tap(VK["capslock"]).type("c")
    actions = s.run()
    assert texts(actions) == ["ABc"]
