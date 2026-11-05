"""변환기 보충 (M4 T8 인계): 구간 열림 알림(`on_span_open`)과 창 전환 조합(Alt+Tab 등) 지우기.

- 구간 열림: 녹화 세션이 칸 상자를 정하고 보호 영역·칸 존재·판정을 그 구간 시작 시각으로 연다.
  클릭마다 구간 후보가 열리지만 편집이 없는 구간(단추 클릭)은 알리지 않는다
- 창 전환: Tab을 누르는 순간 포그라운드는 아직 대상이라 `alt+tab`이 남는다 — 다음 이벤트에서
  포그라운드가 대상이 아니면 그 조합을 지운다 (M4 계획 2.15 사람 확인 3)
"""

from __future__ import annotations

from helpers.recorder_script import MS, OTHER, TARGET, FakeTimeline, Script, kinds, texts

from kookabug_core.recorder.actions import Converter, KeyAction
from kookabug_core.recorder.fields import FieldSpan


def converter(s: Script, opened: list[tuple[int, str, int, int | None]]) -> Converter:
    def on_open(span: FieldSpan) -> None:
        opened.append((span.span_id, span.start_kind, span.t_start, span.t_first))

    conv = Converter(TARGET, FakeTimeline(), on_span_open=on_open)
    conv.feed_ime(s.samples)
    for event in s.events:
        conv.feed(event, s.obs.get(event["event_id"]))
    return conv


def test_span_open_once_at_first_edit_with_start_time() -> None:
    s = Script()
    s.at(0).click(500, 400)  # 단추 클릭: 편집 없음 → 알리지 않는다
    s.at(1000).click(560, 230)  # 칸 클릭 → 3초 쉼 → 글자
    s.at(4000).type("abc")
    s.wait(3000).type("def")  # 쉼으로 끝나지 않는다: 다시 알리지 않는다
    s.tap("tab").type("x")  # Tab 구간
    opened: list[tuple[int, str, int, int | None]] = []
    conv = converter(s, opened)
    actions = conv.finish()
    assert texts(actions) == ["abcdef", "x"]
    assert (opened[0][1], opened[0][2]) == ("click", 1000 * MS)
    assert [kind for _, kind, _, _ in opened] == ["click", "tab"]
    assert opened[0][3] == 4000 * MS  # 첫 글자 시각도 알 수 있다


def test_span_opened_even_if_closed_in_same_event() -> None:
    s = Script()
    s.at(0).click(560, 230).type("a")
    s.tap("enter")  # 첫 글자 확정과 구간 끝이 같은 입력
    opened: list[tuple[int, str, int, int | None]] = []
    converter(s, opened).finish()
    assert [kind for _, kind, _, _ in opened] == ["click"]


def test_alt_tab_removed_when_foreground_leaves() -> None:
    s = Script()
    s.at(0).click(100, 100)
    s.at(500).combo("alt", "tab")  # Tab down 순간에는 아직 게임이 앞
    s.fg = OTHER
    s.wait(50).click(5, 5)  # 다음 이벤트에서 다른 창이 앞
    s.fg = TARGET
    s.wait(500).tap("f5")
    conv = converter(s, [])
    actions = conv.finish()
    keys = [a.keys for a in actions if isinstance(a, KeyAction)]
    assert keys == ["f5"]
    assert conv.counts_switch == 1


def test_alt_tab_kept_when_game_stays_in_front() -> None:
    s = Script()
    s.at(0).combo("alt", "tab")
    s.wait(100).tap("f5")
    actions = converter(s, []).finish()
    assert [a.keys for a in actions if isinstance(a, KeyAction)] == ["alt+tab", "f5"]
    assert kinds(actions) == ["key", "key"]
