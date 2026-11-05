"""B1 검수 반례 회귀 (review_B1_1 N1~N4): 창 떠남 눌림 무효화, 판정 불가 클릭 보존, 오른쪽 클릭 구간
닫기, 구간 밖 글자 묶음과 키 동작 경계."""

from __future__ import annotations

from helpers.recorder_script import MS, OTHER, TARGET, FakeTimeline, Script, kinds, texts

from kookabug_core.recorder.actions import ClickAction, KeyAction, ScrollAction, TextAction

VK_LCTRL = 0xA2


def test_modifier_held_across_focus_loss_is_invalidated() -> None:
    # N1: 대상 창 Ctrl down → 다른 창 F5 → 복귀 뒤 A → Ctrl up. Ctrl은 떠날 때 떼어진 것으로 본다
    s = Script()
    s.key_down(VK_LCTRL).wait(100)
    s.fg = OTHER
    s.tap("f5")
    s.fg = TARGET
    s.type("a").key_up(VK_LCTRL)
    conv = s.converter()
    actions = conv.finish()
    assert not [a for a in actions if isinstance(a, KeyAction)]
    assert texts(actions) == ["a"]
    assert "key_held_across_focus_loss" in [w.code for w in conv.warnings]


def test_printable_held_across_focus_loss_is_dropped() -> None:
    # N1: 대상 창에서 W를 1초 누른 뒤 다른 창에서 뗌 → 글자로 확정하지 않고 버림 + 경고
    s = Script()
    s.key_down(ord("W")).wait(1000)
    s.fg = OTHER
    s.key_up(ord("W"))
    conv = s.converter()
    assert conv.finish() == []
    assert [w.code for w in conv.warnings] == ["key_held_across_focus_loss"]


def test_click_with_unknown_window_and_geometry_is_kept_for_review() -> None:
    # N2: 관측(80 ms 지연)도 기하(불확실 구간)도 판정 불가 → 버리지 않고 point 없는 클릭 + 확인 필요
    s = Script()
    s.obs_delay_ms = 80
    s.at(950).click(50, 60)
    timeline = FakeTimeline([(0, 900 * MS, (100, 80)), (1000 * MS, 10**15, (100, 80))])
    actions = s.run(timeline)
    assert len(actions) == 1
    (click,) = actions
    assert isinstance(click, ClickAction)
    assert click.point is None and click.screen == (150, 140)
    assert {"window_undetermined", "geometry_unresolved"} <= set(click.needs_review)
    assert click.event_id == s.events[0]["event_id"]


def test_undetermined_click_confirmed_outside_client_is_dropped() -> None:
    # 확인된 기하로 클라이언트 밖이면 관측이 없어도 제외 (창 밖 입력만 제외하는 규칙)
    s = Script()
    s.obs_delay_ms = 80
    s.at(100).click(100, -10).wheel(100, -10)
    conv = s.converter()
    assert conv.finish() == []
    assert conv.counts.undetermined == 2


def test_undetermined_wheel_with_unknown_geometry_kept() -> None:
    s = Script()
    s.obs_delay_ms = 80
    s.at(950).wheel(50, 60)
    timeline = FakeTimeline([(0, 900 * MS, (100, 80)), (1000 * MS, 10**15, (100, 80))])
    (scroll,) = s.run(timeline)
    assert isinstance(scroll, ScrollAction) and scroll.point is None
    assert {"window_undetermined", "geometry_unresolved"} <= set(scroll.needs_review)


def test_right_click_outside_field_ends_span() -> None:
    # N3: 칸 클릭 → a → 다른 자리 오른쪽 클릭 → b. 오른쪽 클릭도 칸 밖 클릭이라 구간을 닫는다
    s = Script()
    s.click(50, 60).type("a").click(500, 400, button="right").type("b")
    actions = s.run()
    assert kinds(actions) == ["click", "text", "click", "text"]
    assert texts(actions) == ["a", "b"]
    assert isinstance(actions[2], ClickAction) and actions[2].button == "right"
    second = actions[3]
    assert isinstance(second, TextAction) and not second.in_field


def test_right_click_inside_known_field_box_keeps_span() -> None:
    s = Script()
    s.click(500, 230).type("a").click(520, 232, button="right").type("b")
    actions = s.run(field_box=lambda span: (400, 205, 320, 50))
    assert texts(actions) == ["ab"]


def test_loose_text_split_by_key_action() -> None:
    # N4: 구간 밖 a → F5 → b (1초 안). F5 앞뒤 글자를 합치면 b가 장면 바뀌기 전에 재생된다
    s = Script()
    s.type("a").tap("f5").type("b")
    actions = s.run()
    assert kinds(actions) == ["text", "key", "text"]
    assert texts(actions) == ["a", "b"]
    assert isinstance(actions[1], KeyAction) and actions[1].keys == "f5"


def test_loose_text_split_by_lone_modifier_tap() -> None:
    s = Script()
    s.type("a").tap(0xA0).type("b")  # 혼자 누른 Shift
    actions = s.run()
    assert kinds(actions) == ["text", "key", "text"]


def test_field_span_not_split_by_key_inside_field() -> None:
    # 대조: 실제 입력 칸 구간은 Backspace 같은 편집 키로 나뉘지 않는다 (장시간 유지 정책 그대로)
    s = Script()
    s.click(500, 230).type("ab").tap("backspace").wait(2000).type("c")
    assert texts(s.run()) == ["ac"]
