"""상태별 마무리 중 동작 쪽 (M4 계획 2.9 표, 검수 M3, T5)."""

from __future__ import annotations

from helpers.recorder_script import VK, Script, kinds, texts

from kookabug_core.recorder.actions import KeyAction, TextAction
from kookabug_core.recorder.continuity import ContinuityChecker
from kookabug_core.recorder.events import truncate_at_cut


def test_pause_with_key_held_then_released_during_pause() -> None:
    s = Script()
    s.at(0).click(500, 230).type("ab").key_down(VK["f5"])
    conv = Script.converter(s)
    conv.pause()
    later = Script()
    later.at(1000).key_up(VK["f5"]).type("zz")  # 일시정지 중: 버림
    for event in later.events:
        conv.feed(event, later.obs.get(event["event_id"]))
    conv.resume()
    after = Script()
    after._ids = iter(range(1000, 2000))  # pyright: ignore[reportAttributeAccessIssue]
    after._crit = iter(range(1000, 2000))  # pyright: ignore[reportAttributeAccessIssue]
    after.at(3000).type("c")
    for event in after.events:
        conv.feed(event, after.obs.get(event["event_id"]))
    actions = conv.finish()
    assert texts(actions) == ["abc"]  # 구간은 일시정지를 넘어 이어진다
    assert not [a for a in actions if isinstance(a, KeyAction)]
    assert [w.code for w in conv.warnings] == ["released_during_pause"]


def test_stop_with_key_and_drag_held() -> None:
    s = Script()
    s.at(0).click(500, 230).type("ab")
    s.key_down(VK["f5"]).wait(10).down(100, 100).wait(10).move(200, 200)
    conv = s.converter()
    actions = conv.finish()
    assert kinds(actions) == ["click", "text"]  # 떼지 않은 키·끌기는 동작이 아니다
    assert [w.code for w in conv.warnings] == ["held_at_stop", "held_at_stop"]
    (text,) = [a for a in actions if isinstance(a, TextAction)]
    assert text.needs_review == ()  # 정지: 구간은 닫고 판정을 이어감


def test_crit_seq_gap_truncates_actions_and_marks_open_span_review() -> None:
    s = Script()
    s.at(0).click(500, 230).type("ab")
    s.at(2000).tap("f5")
    events = list(s.events)
    gap_at = next(i for i, e in enumerate(events) if e.get("vk") == VK["f5"])
    lost = events.pop(gap_at)  # 키 하나를 잃음 → crit_seq 빈틈
    checker = ContinuityChecker()
    batch = {
        "batch_no": 1,
        "events": events,
        "crit_first": events[0]["crit_seq"],
        "crit_last": events[-1]["crit_seq"],
        "dropped_marker": 0,
        "coalesced_moves": 0,
        "overflow": 0,
    }
    violation = checker.feed_events(batch)
    assert violation is not None and violation.cut_crit_seq == lost["crit_seq"]
    kept = truncate_at_cut(events, violation.cut_crit_seq)
    script = Script()
    conv = script.converter()
    for event in kept:
        conv.feed(event, s.obs.get(event["event_id"]))
    actions = conv.finish("cut")
    assert kinds(actions) == ["click", "text"]  # 끊긴 곳 앞까지만, 뒤 키(f5)는 쓰지 않음
    (text,) = [a for a in actions if isinstance(a, TextAction)]
    assert text.text.reveal() == "ab" and "cut_by_stop" in text.needs_review
