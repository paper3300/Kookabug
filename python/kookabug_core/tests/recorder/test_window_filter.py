"""대상 창 거르기 (M4 계획 2.4, T5): 관측과 이벤트 시각의 기하 세대로만."""

from __future__ import annotations

from helpers.recorder_script import (
    APP,
    MS,
    OTHER,
    POPUP,
    TARGET,
    FakeTimeline,
    Script,
    kinds,
    texts,
)

from kookabug_core.recorder.actions import ClickAction, KeyAction, TextAction


def test_outside_client_click_ignored_and_counted() -> None:
    s = Script()
    s.at(0).click(100, 100)
    s.point = OTHER
    s.at(1000).click(100, 100)  # 다른 창 위
    s.point = TARGET
    s.at(2000).click(100, -10)  # 대상 창의 제목 표시줄 (클라이언트 밖)
    s.point = APP
    s.at(3000).click(5, 5)  # 우리 앱
    conv = s.converter()
    actions = conv.finish()
    assert kinds(actions) == ["click"]
    assert conv.counts.ignored_outside == 3


def test_keys_when_not_foreground_ignored() -> None:
    s = Script()
    s.at(0).click(10, 10).type("ab")
    s.fg = OTHER
    s.type("zz").tap("enter")
    s.fg = TARGET
    s.type("c")
    conv = s.converter()
    actions = conv.finish()
    # 다른 창이 앞이면 버리고, 게임 창을 떠났으므로 구간도 끝난다
    assert texts(actions) == ["ab", "c"]
    assert not [a for a in actions if isinstance(a, KeyAction)]
    assert conv.counts.ignored_outside >= 3


def test_owned_popup_click_ignored() -> None:
    s = Script()
    s.point = POPUP
    s.at(0).click(50, 50)
    conv = s.converter()
    assert conv.finish() == []
    assert conv.counts.ignored_popup == 1


def test_owned_popup_foreground_keys_text_enter_tab_ignored() -> None:
    # 검수 M8: 팝업에서 친 글자·Enter·Tab이 기본 창 사슬로 들어가지 않는다
    s = Script()
    s.at(0).click(500, 230).type("id")
    s.fg = POPUP
    s.type("popup text").tap("enter").tap("tab")
    s.fg = TARGET
    s.at(9000).click(500, 300).type("x")
    conv = s.converter()
    actions = conv.finish()
    assert texts(actions) == ["id", "x"]
    assert not [a for a in actions if isinstance(a, KeyAction)]
    assert conv.counts.ignored_popup >= 12


def test_key_held_across_focus_loss_not_emitted() -> None:
    s = Script()
    s.at(0).key_down(0x25, extended=True)  # 왼쪽 방향키를 누른 채
    s.fg = OTHER
    s.wait(500).key_up(0x25, extended=True)  # 다른 창에서 뗌
    s.fg = TARGET
    s.wait(100).tap("f5")
    conv = s.converter()
    actions = conv.finish()
    assert [a.keys for a in actions if isinstance(a, KeyAction)] == ["f5"]
    assert [w.code for w in conv.warnings] == ["key_held_across_focus_loss"]


def test_coords_use_event_generation_not_current() -> None:
    # 1초에 창이 (400, 300)으로 옮겨졌다. 처리하는 지금은 새 자리지만 0.5초 클릭은 옛 세대 좌표
    timeline = FakeTimeline([(0, 900 * MS, (100, 80)), (1000 * MS, 10**15, (400, 300))])
    s = Script()
    s.at(500).click(50, 60)
    s.origin = (400, 300)
    s.at(2000).click(70, 80)
    clicks = [a for a in s.run(timeline) if isinstance(a, ClickAction)]
    assert [c.point for c in clicks] == [(50, 60), (70, 80)]
    assert [c.needs_review for c in clicks] == [(), ()]


def test_click_in_uncertain_geometry_marked() -> None:
    timeline = FakeTimeline([(0, 900 * MS, (100, 80)), (1000 * MS, 10**15, (100, 80))])
    s = Script()
    s.at(950).click(50, 60)  # 불확실 구간
    (click,) = [a for a in s.run(timeline) if isinstance(a, ClickAction)]
    assert "geometry_unresolved" in click.needs_review


def test_undetermined_observation_needs_review() -> None:
    s = Script()
    s.obs_delay_ms = 80  # 50 ms 밖 → 판정 불가
    s.at(0).click(500, 230).type("ab").tap("f5")
    actions = s.run()
    click = next(a for a in actions if isinstance(a, ClickAction))
    text = next(a for a in actions if isinstance(a, TextAction))
    key = next(a for a in actions if isinstance(a, KeyAction))
    assert "window_undetermined" in click.needs_review  # 버리지 않고 확인 필요
    assert "window_undetermined" in text.needs_review
    assert "window_undetermined" in key.needs_review
