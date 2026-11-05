"""이벤트 → 동작: 동작 종류마다 (M4 계획 2.7, T5)."""

from __future__ import annotations

from helpers.recorder_script import VK, Script, kinds, texts

from kookabug_core.recorder.actions import (
    ClickAction,
    ConverterOptions,
    DragAction,
    KeyAction,
    ScrollAction,
)


def test_click_double_right() -> None:
    s = Script()
    s.at(100).click(200, 150)
    s.at(1000).click(300, 300).wait(100).click(301, 301)  # 시간·거리 안 두 번
    s.at(3000).click(50, 60, button="right")
    actions = [a for a in s.run() if isinstance(a, ClickAction)]
    assert [(a.button, a.point, a.count) for a in actions] == [
        ("left", (200, 150), 1),
        ("left", (300, 300), 2),
        ("right", (50, 60), 1),
    ]
    assert actions[0].screen == (300, 230)


def test_double_click_needs_system_time_and_distance() -> None:
    s = Script()
    s.at(0).click(10, 10).wait(600).click(10, 10)  # 이중 클릭 시간 밖
    s.at(3000).click(10, 10).wait(50).click(30, 30)  # 거리 밖
    opts = ConverterOptions(double_click_ns=500_000_000, double_click_px=4)
    clicks = [a for a in s.run(options=opts) if isinstance(a, ClickAction)]
    assert [c.count for c in clicks] == [1, 1, 1, 1]


def test_drag_vs_click_threshold() -> None:
    s = Script()
    s.at(0).down(100, 100).wait(50).up(104, 103)  # 4 px 이하 = 클릭
    s.at(1000).down(100, 100).wait(10).move(150, 120).wait(200).up(200, 140)
    s.at(2000).down(1000, 600).wait(100).up(1100, 700)  # 끝점이 클라이언트 밖 → 가장자리
    actions = s.run()
    assert kinds(actions) == ["click", "drag", "drag"]
    drag = actions[1]
    assert isinstance(drag, DragAction)
    assert (drag.start, drag.end, drag.duration_ms) == ((100, 100), (200, 140), 210)
    assert "end_point_pixels" in drag.badges
    clipped = actions[2]
    assert isinstance(clipped, DragAction)
    assert clipped.end == (1023, 639) and clipped.clipped and "end_clipped" in clipped.badges


def test_wheel_burst_merged() -> None:
    s = Script()
    s.at(0).wheel(500, 300, -120).wait(50).wheel(505, 302, -120).wait(50).wheel(500, 300, -120)
    s.wait(500).wheel(500, 300, 120)  # 300 ms 넘게 쉼 → 새 묶음
    s.wait(50).wheel(700, 300, 120)  # 16 px 밖 → 새 묶음
    scrolls = [a for a in s.run() if isinstance(a, ScrollAction)]
    assert [(a.point, a.delta, a.amount) for a in scrolls] == [
        ((500, 300), -360, -3),
        ((500, 300), 120, 1),
        ((700, 300), 120, 1),
    ]


def test_hold_key_hold_ms() -> None:
    s = Script()
    s.at(0).tap("f5", hold_ms=50)
    s.at(1000).tap(0x57, hold_ms=800)  # 글자 키(W)도 오래 누르면 누르고 있기
    s.at(3000).tap("left", hold_ms=450)
    s.at(4000).combo("ctrl", "s")
    actions = s.run()
    keys = [(a.keys, a.hold_ms) for a in actions if isinstance(a, KeyAction)]
    assert keys == [("f5", None), ("w", 800), ("left", 450), ("ctrl+s", None)]
    assert texts(actions) == []


def test_autorepeat_collapsed() -> None:
    s = Script()
    s.at(0).key_down(0x74)
    for _ in range(10):
        s.wait(33).key_down(0x74)  # 자동 반복
    s.wait(10).key_up(0x74)
    conv = s.converter()
    actions = conv.finish()
    assert [(a.keys, a.hold_ms) for a in actions if isinstance(a, KeyAction)] == [("f5", 340)]
    assert conv.counts.autorepeat == 10


def test_lone_modifier_tap_is_key() -> None:
    s = Script()
    s.at(0).tap(VK["shift"])
    actions = s.run()
    assert [(a.keys) for a in actions if isinstance(a, KeyAction)] == ["shift"]
