"""`WindowsPlatform`·추적기·공용 입력 서비스의 창 정체성 (구현 계획 M1 2.2 창 수명, T9 검수 1·2차).

- 캡처 메타데이터·`Match.window`는 캡처한 실제 바인딩으로 정규화한다
- 같은 살아 있는 창은 참조 표현(부분 참조 `WindowRef(hwnd)`·완전한 참조)이 달라도 바인딩 하나다
- 재검증은 관측 창과 요청 창을 둘 다 바인딩으로 확정해 비교한다: 관측한 창이 닫혔으면
  `window_gone`(요청이 부분 참조여도), 다른 살아 있는 창이면 `window_mismatch` — 입력 0회

WGC·Win32 창 정보·입력 싱크는 대역, 추적기·메타데이터 변환·공용 입력 서비스는 제품 코드다.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from kookabug_core.engine.context import ObservationLimits
from kookabug_core.engine.errors import EngineError
from kookabug_platform.capture import CapturedFrame, FrameInfo
from kookabug_platform.platform import WindowsPlatform
from kookabug_platform.tracker import WindowBinding, WindowTracker
from kookabug_sdk.types import FrameRef, Match, Rect, WindowRef

HWND = 0x100
OTHER = 0x200


class Sink:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def click(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


def platform_with(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[WindowsPlatform, WindowTracker, Sink]:
    api = SimpleNamespace(
        is_window=lambda hwnd: True, window_pid=lambda hwnd: 7, process_created=lambda pid: 123
    )
    tracker = WindowTracker(api, run_id="t9")  # pyright: ignore[reportArgumentType]

    def capture(binding: WindowBinding, region: Any, *, deadline: Any) -> CapturedFrame:
        info = FrameInfo("wgc", binding, (30, 20), (0, 0), 96, None, 10.0, 9.0, 1, False, False)
        return CapturedFrame(np.zeros((20, 30, 3), dtype=np.uint8), info, ("t9", 1))

    service = SimpleNamespace(capture=capture)
    platform = WindowsPlatform(tracker=tracker, capture=service)  # pyright: ignore[reportArgumentType]
    sink = Sink()
    platform.attach_input(sink)  # pyright: ignore[reportArgumentType]
    monkeypatch.setattr(
        "kookabug_platform.platform.wins.window_info",
        lambda hwnd: SimpleNamespace(
            client_size=(30, 20), dpi=96, title="Game", pid=7, process_created=123
        ),
    )
    monkeypatch.setattr("kookabug_platform.platform.wins.find_window", lambda **kw: HWND)
    return platform, tracker, sink


def observed(platform: WindowsPlatform, window: WindowRef) -> Match:
    _, staged = platform.capture_staged(window, None, ObservationLimits(2000))
    assert staged.meta is not None and staged.meta.window is not None
    return Match(
        Rect(1, 1, 4, 4),
        1.0,
        window=staged.meta.window,
        frame_info=FrameRef("wgc", (30, 20), 96, 1),
    )


def send(platform: WindowsPlatform, window: WindowRef, match: Match) -> str | None:
    observer = SimpleNamespace(
        rematch=lambda m: None,
        note=lambda message: None,
        observation_stale=lambda m: None,  # 멈춘 적 없는 실행 (관측 세대 M3)
        coordinate_stale=lambda at: None,
    )
    try:
        platform.service.for_step("s2", window, observer, sleep=lambda ms: None).click(match)  # pyright: ignore[reportArgumentType]
    except EngineError as exc:
        return exc.code
    return None


def test_capture_meta_window_is_resolved_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    platform, _, _ = platform_with(monkeypatch)
    match = observed(platform, WindowRef(HWND, "Game"))
    # 바인딩 없는 참조로 캡처해도 메타데이터에는 이 실행의 바인딩 전체가 실린다
    assert match.window == WindowRef(HWND, "Game", pid=7, process_created="123", binding="t9.w1")


@pytest.mark.parametrize(
    "capture_first", [True, False], ids=["partial_then_find", "find_then_partial"]
)
def test_live_window_aliases_share_binding(
    monkeypatch: pytest.MonkeyPatch, capture_first: bool
) -> None:
    """같은 살아 있는 창의 부분 참조·완전한 참조는 같은 바인딩이라 서로의 관측으로 입력된다."""
    platform, _, sink = platform_with(monkeypatch)
    if capture_first:
        match = observed(platform, WindowRef(HWND))
        found = platform.find_window("Game", None, False)
        assert found is not None
        request = found
    else:
        found = platform.find_window("Game", None, False)
        assert found is not None
        match = observed(platform, found)
        request = WindowRef(HWND)
    assert match.window is not None and match.window.binding == found.binding
    assert send(platform, request, match) is None
    assert send(platform, request, replace(match, window=WindowRef(HWND))) is None
    assert len(sink.calls) == 2


def test_destroyed_observation_rejected_for_new_partial_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform, tracker, sink = platform_with(monkeypatch)
    original = platform.find_window("Game", None, False)
    assert original is not None
    match = observed(platform, original)
    tracker.notify_destroyed(HWND)
    # 같은 HWND에 새 창이 있고 요청은 바인딩 없는 부분 참조 (처음 쓰므로 새 창에 바인딩된다)
    assert send(platform, WindowRef(HWND), match) == "window_gone"
    assert sink.calls == []


def test_destroyed_observation_rejected_for_new_full_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform, tracker, sink = platform_with(monkeypatch)
    match = observed(platform, WindowRef(HWND, "Game"))
    tracker.notify_destroyed(HWND)
    new = tracker.bind(HWND)
    current = WindowRef(HWND, pid=7, process_created="123", binding=new.binding_id)
    assert send(platform, current, match) == "window_gone"
    assert sink.calls == []


def test_old_window_request_after_destroy_is_window_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    platform, tracker, sink = platform_with(monkeypatch)
    match = observed(platform, WindowRef(HWND, "Game"))
    assert match.window is not None
    tracker.notify_destroyed(HWND)
    tracker.bind(HWND)  # 같은 HWND에 새 창
    assert send(platform, match.window, match) == "window_gone"
    assert sink.calls == []


def test_refinding_recreated_window_keeps_live_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    """창 탐색 → 파괴 → 같은 HWND로 다시 만든 창을 두 번 찾음: 두 참조가 같은 바인딩이라 서로의
    관측으로 입력된다. 옛 창의 참조·관측은 `window_gone` 그대로 (T9 3차 검수)."""
    platform, tracker, sink = platform_with(monkeypatch)
    original = platform.find_window("Game", None, False)
    assert original is not None
    old_match = observed(platform, original)
    tracker.notify_destroyed(HWND)
    first = platform.find_window("Game", None, False)
    match = observed(platform, first) if first is not None else None
    second = platform.find_window("Game", None, False)
    assert first is not None and second is not None and match is not None
    assert first.binding == second.binding != original.binding
    assert send(platform, first, match) is None
    assert send(platform, second, match) is None
    assert len(sink.calls) == 2
    # 옛 창: 참조로 요청해도, 옛 관측을 새 창에 넣어도 window_gone, 입력 없음
    assert send(platform, original, old_match) == "window_gone"
    assert send(platform, second, old_match) == "window_gone"
    assert len(sink.calls) == 2


def test_other_live_window_is_window_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    platform, _, sink = platform_with(monkeypatch)
    match = observed(platform, WindowRef(HWND, "Game"))
    assert send(platform, WindowRef(OTHER, "Other"), match) == "window_mismatch"
    assert sink.calls == []
