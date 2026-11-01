"""공용 입력 서비스 (구현 계획 M1 2.4, 계획 검수 4): 창 고정 요청, `Match` 재검증·재매칭,
`window_mismatch`, `StaleObservation` → 처리되지 않은 fail.

실행기 검사는 예제 게임 장면 표(`FakeScenario`)와 정해 둔 답을 주는 찾기 엔진(`StubEngines`)으로
한다. 창 크기 바뀜은 `ScenePlatform.resize`로 흉내 낸다(재검증이 보는 "지금 창").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import link, make_workspace, target
from helpers.m1 import START, ScenePlatform, StubEngines, clicks, run_on, write_target
from helpers.run import tk

from kookabug_core.engine.errors import EngineError
from kookabug_core.inputs.actor import ClientPoint
from kookabug_core.inputs.service import InputService, same_window
from kookabug_sdk.errors import StaleObservation
from kookabug_sdk.types import FrameRef, Match, Point, Rect, WindowRef

A = WindowRef(0x100, "A", pid=11, process_created="1", binding="r.w1")
B = WindowRef(0x200, "B", pid=11, process_created="1", binding="r.w2")
TARGET = "targets/start.target.json"


# ---------------------------------------------------------------- 단위 (가짜 싱크·창)


class Sink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, Any]] = []

    def click(
        self,
        at: ClientPoint,
        *,
        button: str = "left",
        count: int = 1,
        target: Any = None,
        step: Any = None,
    ) -> None:
        self.calls.append(("click", at, target))

    def drag(self, start: ClientPoint, end: ClientPoint, **kw: Any) -> None:
        self.calls.append(("drag", (start, end), kw["target"]))

    def scroll(self, at: ClientPoint, amount: int, **kw: Any) -> None:
        self.calls.append(("scroll", at, kw["target"]))

    def key(self, key: str, **kw: Any) -> None:
        self.calls.append(("key", key, kw["target"]))

    def press(self, key: str, **kw: Any) -> None:
        self.calls.append(("press", key, kw["target"]))

    def release(self, key: str, **kw: Any) -> None:
        self.calls.append(("release", key, kw["target"]))

    def type_text(self, text: Any, **kw: Any) -> None:
        self.calls.append(("text", text, kw["target"]))


class View:
    def __init__(self, backend: str, client_size: tuple[int, int], dpi: int) -> None:
        self.backend, self.client_size, self.dpi = backend, client_size, dpi


class Windows:
    def __init__(self) -> None:
        self.size: tuple[int, int] = (1024, 640)

    def bind(self, window: WindowRef) -> object:
        return ("bound", window.handle)

    def identify(self, window: WindowRef) -> WindowRef:
        return window

    def state(self, window: WindowRef) -> View:
        return View("wgc", self.size, 96)


class Observer:
    def __init__(self, found: Match | None = None) -> None:
        self.found = found
        self.rematched: list[Match] = []
        self.notes: list[str] = []

    def rematch(self, match: Match) -> Match | None:
        self.rematched.append(match)
        return self.found

    def note(self, message: str) -> None:
        self.notes.append(message)

    def observation_stale(self, match: Match) -> str | None:
        return None  # 멈춘 적 없는 실행 (관측 세대는 test_revalidate_epoch.py)

    def coordinate_stale(self, at: Point | Rect) -> str | None:
        return None


def match_at(rect: Rect, *, window: WindowRef | None = A, target: str | None = TARGET) -> Match:
    return Match(
        rect, 0.99, window=window, frame_info=FrameRef("wgc", (1024, 640), 96, 1), target=target
    )


def service() -> tuple[InputService, Sink, Windows]:
    sink, windows = Sink(), Windows()
    return InputService(sink, windows, sleep=lambda ms: None), sink, windows


def test_rect_and_point_no_revalidation() -> None:
    svc, sink, windows = service()
    windows.size = (2048, 1280)  # 창이 바뀌었어도 출처 없는 위치는 그대로
    observer = Observer()
    ctx_input = svc.for_step("s1", A, observer)
    ctx_input.click(Rect(10, 20, 30, 40))
    ctx_input.click(Point(5, 6))
    assert [c[1] for c in sink.calls] == [ClientPoint(25, 40), ClientPoint(5, 6)]
    assert observer.rematched == []
    assert all(c[2] == ("bound", A.handle) for c in sink.calls)


def test_match_window_mismatch_error() -> None:
    svc, sink, _ = service()
    with pytest.raises(EngineError) as caught:
        svc.for_step("s1", B, Observer()).click(match_at(START, window=A))
    assert caught.value.code == "window_mismatch"
    assert sink.calls == []


def test_same_window_ignores_missing_parts() -> None:
    assert same_window(WindowRef(0x100), A)
    assert not same_window(A, B)
    assert not same_window(A, WindowRef(0x100, pid=12))


def test_size_change_rematch_unit_uses_new_point() -> None:
    svc, sink, windows = service()
    windows.size = (2048, 1280)
    new = Match(Rect(824, 760, 400, 128), 0.98, window=A, target=TARGET)
    observer = Observer(found=new)
    svc.for_step("s1", A, observer).click(match_at(START))
    assert sink.calls == [("click", ClientPoint(1024, 824), ("bound", A.handle))]
    assert len(observer.rematched) == 1 and observer.notes


def test_match_without_target_unit_is_stale() -> None:
    svc, sink, windows = service()
    windows.size = (800, 500)
    with pytest.raises(StaleObservation):
        svc.for_step("s1", A, Observer()).click(match_at(START, target=None))
    assert sink.calls == []


def test_move_only_unit_no_rematch() -> None:
    svc, sink, _ = service()
    observer = Observer()
    svc.for_step("s1", A, observer).click(match_at(START))
    assert observer.rematched == []
    assert sink.calls == [("click", ClientPoint(512, 412), ("bound", A.handle))]


def test_hold_key_press_sleep_release() -> None:
    slept: list[int] = []
    sink = Sink()
    svc = InputService(sink, Windows(), sleep=slept.append)
    svc.for_step("s1", A, Observer()).key("shift", hold_ms=300)
    assert [c[0] for c in sink.calls] == ["press", "release"] and slept == [300]


# ---------------------------------------------------------------- 실행기 (장면 + 정해 둔 찾기)


def find_then_click(**click_inputs: Any) -> Any:
    return (
        tk()
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_find"})
        .node(
            "n_find",
            "testkit.m1.find",
            inputs={"target": target(TARGET)},
            next={"found": "n_click"},
        )
        .node(
            "n_click",
            "testkit.m1.click",
            inputs={"at": link("n_find.match"), **click_inputs},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


def setup(
    tmp_path: Path, answers: list[Rect | None], *, with_target: bool = True
) -> tuple[Any, ScenePlatform, StubEngines]:
    ws = make_workspace(tmp_path)
    write_target(ws, TARGET)
    engines = StubEngines({TARGET: answers}, with_target=with_target)
    return ws, ScenePlatform.sample(engines), engines


def test_request_window_fixed_at_creation(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    platform = ScenePlatform.sample()
    g = (
        tk()
        .entry("n_a")
        .node("n_a", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_b"})
        .node("n_b", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_switch"})
        .node(
            "n_switch",
            "testkit.m1.switch_click",
            inputs={"to": link("n_a.window"), "x": 1, "y": 2},
            next={"done": "n_after"},
        )
        .node(
            "n_after",
            "testkit.m1.switch_click",
            inputs={"to": link("n_a.window"), "x": 3, "y": 4},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run_on(ws, g, platform)
    assert ran.result.verdict == "pass", ran.result.reason
    a = ran.end("n_a")["outputs"]["handle"]
    b = ran.end("n_b")["outputs"]["handle"]
    assert a != b
    # n_switch는 창을 A로 바꾼 뒤 클릭했지만 그 요청의 창은 스텝 시작 때의 B, 다음 스텝부터 A
    assert clicks(platform) == [(b, 1, 2), (a, 3, 4)]


def test_size_change_rematch_uses_new_point(tmp_path: Path) -> None:
    new = Rect(824, 760, 400, 128)
    ws, platform, engines = setup(tmp_path, [START, new])
    engines.after_find.append(lambda: platform.resize((2048, 1280)))
    ran = run_on(ws, find_then_click(), platform)
    assert ran.result.verdict == "pass", ran.result.reason
    assert clicks(platform)[-1][1:] == (new.center.x, new.center.y)
    # 다시 찾기는 클릭 스텝에서 (캡처 하나 + 찾기 하나), 원래 출력은 그대로
    assert engines.calls_of(TARGET) == [TARGET, TARGET]
    assert ran.end("n_find")["outputs"]["match"]["rect"] == {
        "x": 412,
        "y": 380,
        "width": 200,
        "height": 64,
    }
    assert any("다시 찾아" in m for m in ran.logs("n_click"))


def test_rematch_fails_unhandled_fail_stale_observation(tmp_path: Path) -> None:
    ws, platform, engines = setup(tmp_path, [START, None])
    engines.after_find.append(lambda: platform.resize((2048, 1280)))
    ran = run_on(ws, find_then_click(), platform)
    r = ran.result
    assert (r.verdict, r.code) == ("fail", "unhandled_fail")
    assert r.failure_path == ("n_click",)
    end = ran.end("n_click")
    assert (end["status"], end["exit"]) == ("fail", None)
    assert end["message"].startswith("stale_observation:")
    assert clicks(platform) == []


def test_match_without_target_after_change_is_stale(tmp_path: Path) -> None:
    ws, platform, engines = setup(tmp_path, [START], with_target=False)
    engines.after_find.append(lambda: platform.resize((800, 500)))
    ran = run_on(ws, find_then_click(), platform)
    assert (ran.result.verdict, ran.result.failure_path) == ("fail", ("n_click",))
    assert ran.end("n_click")["message"].startswith("stale_observation:")
    assert engines.calls_of(TARGET) == [TARGET]  # 다시 찾지 않았다


def test_stale_swallowed_by_node_still_unhandled_fail(tmp_path: Path) -> None:
    ws, platform, engines = setup(tmp_path, [START, None])
    engines.after_find.append(lambda: platform.resize((2048, 1280)))
    g = (
        tk()
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_fc"})
        .node(
            "n_fc",
            "testkit.m1.find_click",
            inputs={"target": target(TARGET), "swallow": True},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run_on(ws, g, platform)
    assert (ran.result.verdict, ran.result.failure_path) == ("fail", ("n_fc",))
    assert ran.end("n_fc")["exit"] is None


def test_move_only_no_rematch(tmp_path: Path) -> None:
    ws, platform, engines = setup(tmp_path, [START])
    ran = run_on(ws, find_then_click(), platform)
    assert ran.result.verdict == "pass", ran.result.reason
    assert engines.calls_of(TARGET) == [TARGET]
    assert clicks(platform)[-1][1:] == (START.center.x, START.center.y)


def test_image_click_path_goes_through_service(tmp_path: Path) -> None:
    # 찾은 창(A)과 다른 창(B)을 in.window로 준 클릭 노드: 출력 핀으로 넘어온 Match도 서비스가
    # 점으로 줄이기 전에 막는다 (코어 노드·워커 노드가 같은 경로)
    ws, platform, _ = setup(tmp_path, [START])
    g = (
        tk()
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_find"})
        .node("n_find", "testkit.m1.find", inputs={"target": target(TARGET)}, next={"found": "n_b"})
        .node("n_b", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_click"})
        .node(
            "n_click",
            "testkit.m1.click",
            inputs={"at": link("n_find.match"), "window": link("n_b.window")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run_on(ws, g, platform)
    assert (ran.result.verdict, ran.result.code) == ("error", "window_mismatch")
    assert clicks(platform) == []


def test_double_click_count_reaches_sink(tmp_path: Path) -> None:
    ws, platform, _ = setup(tmp_path, [START])
    ran = run_on(ws, find_then_click(count=2), platform)
    assert ran.result.verdict == "pass", ran.result.reason
    assert len(clicks(platform)) == 2
