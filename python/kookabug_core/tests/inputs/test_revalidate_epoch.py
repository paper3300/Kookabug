"""입력 직전 재검증의 관측 세대 (구현 계획 M3 2.4 "입력 서비스 재검증", T4).

디버거로 멈췄다 재개한 뒤 그 전 세대 관측(`Match`)으로 입력하려 하면, 창 크기·DPI가 같아도 공용
입력 서비스가 `Match.target`으로 새 캡처에서 다시 찾는다. 찾으면 새 클릭 지점으로 입력하고, 못
찾거나 target이 없으면 입력하지 않고 `stale_observation`이다. 이 실행이 준 적 없는 캡처 번호(출처
없음)도 오래된 것으로 본다. 워커 노드의 입력도 같은 서비스를 지나고, 워커가 캡처 번호를 새 것으로
바꿔 보내도 세탁되지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from helpers.epoch import Debugger, SceneEngines, platform_with, run_debug, scene
from helpers.graphs import GraphBuilder, link, make_workspace, target
from helpers.m1 import Ran, ScenePlatform, clicks, write_target
from helpers.run import tk
from helpers.worker import WorkerHarness

from kookabug_core.engine import RunResult
from kookabug_sdk.types import Point, Rect

A = "targets/a.target.json"
BOX = Rect(412, 380, 200, 64)
MOVED = Rect(700, 500, 100, 40)


def launch(first: str) -> GraphBuilder:
    return (
        tk()
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": first})
    )


def wait_then(click_type: str = "core.input.click", pin: str = "match") -> GraphBuilder:
    """띄우기 → `n_wait`(image.wait A) → `n_click`(그 Match로 클릭) → 통과."""
    return (
        launch("n_wait")
        .node("n_wait", "core.image.wait", inputs={"target": target(A)}, next={"found": "n_click"})
        .node("n_click", click_type, inputs={pin: link("n_wait.match")}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


class Scene:
    """장면 엔진과 플랫폼, 멈춘 동안 바꿀 장면."""

    def __init__(self, where: dict[str, Rect], texts: dict[str, str] | None = None) -> None:
        self.engines = SceneEngines(where={A: where}, texts=dict(texts or {}))
        self.platform: ScenePlatform = platform_with(self.engines)

    def to(self, name: str | None) -> Debugger:
        """`n_click` 경계에서 멈추고, 멈춘 동안 장면을 `name`으로 (None이면 그대로)."""

        def change(d: Debugger, point: object) -> None:
            if name is not None:
                scene(self.platform, name)

        return Debugger(at={"n_click"}, while_paused=change)

    @property
    def hwnd(self) -> int:
        return self.platform.scenario.latest().window.handle


def run(tmp_path: Path, graph: GraphBuilder, s: Scene, dbg: Debugger | None) -> Ran:
    ws = make_workspace(tmp_path)
    write_target(ws, A)
    return run_debug(ws, graph, s.platform, dbg)


def assert_stale_no_input(ran: Ran, s: Scene, node: str = "n_click") -> None:
    result = ran.result
    assert (result.verdict, result.code, result.failure_path) == (
        "fail",
        "unhandled_fail",
        (node,),
    ), result.reason
    end = ran.end(node)
    assert (end["status"], end["exit"]) == ("fail", None)
    assert str(end["message"]).startswith("stale_observation:")
    assert clicks(s.platform) == []


def test_resume_target_gone_no_input_sent(tmp_path: Path) -> None:
    s = Scene({"title": BOX})
    ran = run(tmp_path, wait_then(), s, s.to("lobby"))
    assert_stale_no_input(ran, s)
    assert "디버거 재개 전 관측" in ran.end("n_click")["message"]


def test_resume_target_moved_clicks_new_point(tmp_path: Path) -> None:
    s = Scene({"title": BOX, "lobby": MOVED})
    ran = run(tmp_path, wait_then(), s, s.to("lobby"))
    assert ran.result.verdict == "pass", ran.result.reason
    assert clicks(s.platform) == [(s.hwnd, MOVED.center.x, MOVED.center.y)]
    assert any("다시 찾아" in m for m in ran.logs("n_click"))
    # 원래 출력은 그대로다
    rect = ran.end("n_wait")["outputs"]["match"]["rect"]
    assert rect == {"x": BOX.x, "y": BOX.y, "width": BOX.width, "height": BOX.height}


def test_stale_match_rematched_even_if_same_size(tmp_path: Path) -> None:
    """창 크기·DPI·캡처 방식이 같아도(M1이면 그대로 입력) 재개 뒤에는 다시 찾는다."""
    s = Scene({"title": BOX})
    ran = run(tmp_path, wait_then(), s, s.to(None))
    assert ran.result.verdict == "pass", ran.result.reason
    assert s.engines.finds == [(A, "title"), (A, "title")]
    assert clicks(s.platform) == [(s.hwnd, BOX.center.x, BOX.center.y)]
    # 멈추지 않으면 M1 그대로: 다시 찾지 않는다
    plain = Scene({"title": BOX})
    run(tmp_path / "plain", wait_then(), plain, None)
    assert plain.engines.finds == [(A, "title")]


def unknown_graph() -> GraphBuilder:
    return (
        launch("n_um")
        .node(
            "n_um",
            "testkit.epoch.unknown_match",
            inputs={"target": target(A), "rect": [10, 10, 20, 20]},
            next={"done": "n_click"},
        )
        .node(
            "n_click",
            "core.input.click",
            inputs={"match": link("n_um.match")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


def test_unknown_capture_id_after_resume_treated_stale(tmp_path: Path) -> None:
    """이 실행이 준 적 없는 캡처 번호의 `Match`: 재개한 실행에서는 다시 찾아 그 자리로 입력한다."""
    s = Scene({"title": BOX})
    ran = run(tmp_path, unknown_graph(), s, s.to(None))
    assert ran.result.verdict == "pass", ran.result.reason
    assert clicks(s.platform) == [(s.hwnd, BOX.center.x, BOX.center.y)]
    assert any("출처를 알 수 없다" in m for m in ran.logs("n_click"))
    # 멈춘 적 없는 실행(세대 0)은 M1 그대로 그 상자로
    plain = Scene({"title": BOX})
    run(tmp_path / "plain", unknown_graph(), plain, None)
    assert clicks(plain.platform) == [(plain.hwnd, 20, 20)]


def test_ocr_match_without_target_stale_after_resume(tmp_path: Path) -> None:
    """OCR 줄 `Match`는 다시 찾을 target이 없다: 재개 뒤에는 입력하지 않는다 (보류 H2)."""
    g = (
        launch("n_wt")
        .node("n_wt", "core.ocr.wait_text", inputs={"contains": "START"}, next={"found": "n_click"})
        .node(
            "n_click",
            "core.input.click",
            inputs={"match": link("n_wt.match")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    s = Scene({}, texts={"title": "START"})
    ran = run(tmp_path, g, s, s.to(None))
    assert_stale_no_input(ran, s)
    assert "target이 없어" in ran.end("n_click")["message"]


def offset_graph(mode: str = "click") -> GraphBuilder:
    """띄우기 → `n_wait`(image.wait A) → `n_click`(받은 Match에서 뽑은 좌표로 입력) → 통과."""
    return (
        launch("n_wait")
        .node("n_wait", "core.image.wait", inputs={"target": target(A)}, next={"found": "n_click"})
        .node(
            "n_click",
            "testkit.epoch.offset_input",
            inputs={"at": link("n_wait.match"), "dx": 10, "mode": mode},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


def drags(platform: ScenePlatform) -> list[tuple[Any, ...]]:
    return [args for _, kind, args in platform.scenario.inputs if kind == "drag"]


@pytest.mark.parametrize("mode", ["click", "drag"])
def test_point_rect_from_stale_match_not_sent(tmp_path: Path, mode: str) -> None:
    """재개 전 `Match`를 받은 입력 노드(예외 ②)가 `Match`를 넘기지 않고 거기서 뽑은 좌표
    (`Point`·`Rect`)로 입력하면 다시 찾을 수 없으므로 입력하지 않는다 — 대상이 사라졌어도 재개 전
    좌표로 누르지 않는다 (검수 T4-1 High 1)."""
    s = Scene({"title": BOX})
    ran = run(tmp_path, offset_graph(mode), s, s.to("lobby"))
    assert_stale_no_input(ran, s)
    assert drags(s.platform) == []
    assert "좌표(point·rect)" in ran.end("n_click")["message"]


def drag_graph() -> GraphBuilder:
    """띄우기 → `n_wait`(image.wait A) → `n_drag`(core.input.drag: 찾은 Match → 상수 끝점)."""
    return (
        launch("n_wait")
        .node("n_wait", "core.image.wait", inputs={"target": target(A)}, next={"found": "n_drag"})
        .node(
            "n_drag",
            "core.input.drag",
            inputs={"start": link("n_wait.match"), "end": [50, 60]},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


def drag_points(platform: ScenePlatform) -> list[tuple[int, int, int, int]]:
    return [(a.x, a.y, b.x, b.y) for a, b, *_ in drags(platform)]


@pytest.mark.parametrize(
    ("to", "start"),
    [(None, BOX.center), ("lobby", MOVED.center)],
    ids=["same_place", "moved"],
)
def test_drag_rematched_start_to_constant_end_after_resume(
    tmp_path: Path, to: str | None, start: Point
) -> None:
    """재개 전 `Match`를 시작점으로 받은 `core.input.drag`: 시작점은 다시 찾고, 끝점은 관측과 무관한
    상수라 그대로 나간다 (검수 T4-2 Mid — 상수 좌표까지 거절하지 않는다)."""
    s = Scene({"title": BOX, "lobby": MOVED})
    ran = run(tmp_path, drag_graph(), s, Debugger(at={"n_drag"}) if to is None else _at_drag(s, to))
    assert ran.result.verdict == "pass", ran.result.reason
    assert drag_points(s.platform) == [(start.x, start.y, 50, 60)]


def test_drag_start_target_gone_no_drag(tmp_path: Path) -> None:
    s = Scene({"title": BOX})
    ran = run(tmp_path, drag_graph(), s, _at_drag(s, "lobby"))
    assert (ran.result.verdict, ran.result.failure_path) == ("fail", ("n_drag",)), ran.result.reason
    assert str(ran.end("n_drag")["message"]).startswith("stale_observation:")
    assert drags(s.platform) == []


def _at_drag(s: Scene, name: str) -> Debugger:
    def change(d: Debugger, point: object) -> None:
        scene(s.platform, name)

    return Debugger(at={"n_drag"}, while_paused=change)


def test_point_from_fresh_match_sent_as_is(tmp_path: Path) -> None:
    """같은 노드라도 받은 관측이 새것이면(멈춤 없음, 또는 찾기 전에 멈춤) 좌표 입력은 그대로
    나간다."""
    expected = (BOX.center.x + 10, BOX.center.y)
    plain = Scene({"title": BOX})
    run(tmp_path / "plain", offset_graph(), plain, None)
    assert clicks(plain.platform) == [(plain.hwnd, *expected)]
    early = Scene({"title": BOX})
    ran = run(tmp_path / "early", offset_graph(), early, Debugger(at={"n_wait"}))
    assert ran.result.verdict == "pass", ran.result.reason
    assert clicks(early.platform) == [(early.hwnd, *expected)]


# ---------------------------------------------------------------- 워커 노드


def worker_run(tmp_path: Path, graph: GraphBuilder, s: Scene, dbg: Debugger) -> RunResult:
    ws = make_workspace(tmp_path / "ws")
    write_target(ws, A)
    graph.write(ws, "tests/t.graph.json")
    h = WorkerHarness(ws, "tests/t.graph.json", tmp_path, platform=s.platform, debugger=dbg)
    return h.run_all()


@pytest.mark.process
def test_worker_node_stale_match_rematched_via_service(tmp_path: Path) -> None:
    """워커 노드(`testkit.m1.click`)가 재개 전 `Match`로 SDK 클릭 → runner 공용 입력 서비스가 다시
    찾아 옮겨 간 자리로 입력한다."""
    s = Scene({"title": BOX, "lobby": MOVED})
    result = worker_run(tmp_path, wait_then("testkit.m1.click", "at"), s, s.to("lobby"))
    assert result.verdict == "pass", result.reason
    assert clicks(s.platform) == [(s.hwnd, MOVED.center.x, MOVED.center.y)]


@pytest.mark.process
def test_worker_cannot_forge_fresh_epoch(tmp_path: Path) -> None:
    """워커가 재개 전 `Match`의 캡처 번호를 방금 캡처한 번호로 바꿔 클릭해도, 재개 전 관측을
    입력으로 받은 스텝이라 다시 찾는다 → 대상이 사라졌으면 입력하지 않는다."""
    g = (
        launch("n_wait")
        .node("n_wait", "core.image.wait", inputs={"target": target(A)}, next={"found": "n_click"})
        .node(
            "n_click",
            "testkit.epoch.forge",
            inputs={"at": link("n_wait.match")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    s = Scene({"title": BOX})
    result = worker_run(tmp_path, g, s, s.to("lobby"))
    assert (result.verdict, result.code, result.failure_path) == (
        "fail",
        "unhandled_fail",
        ("n_click",),
    ), result.reason
    assert clicks(s.platform) == []


@pytest.mark.process
@pytest.mark.parametrize("mode", ["click", "drag"])
def test_worker_point_rect_from_stale_match_not_sent(tmp_path: Path, mode: str) -> None:
    """워커 노드가 재개 전 `Match`에서 뽑은 좌표로 SDK `click(Point)`·`drag(Rect, Point)` → 입력
    없이 `stale_observation`."""
    s = Scene({"title": BOX})
    result = worker_run(tmp_path, offset_graph(mode), s, s.to("lobby"))
    assert (result.verdict, result.code, result.failure_path) == (
        "fail",
        "unhandled_fail",
        ("n_click",),
    ), result.reason
    assert clicks(s.platform) == [] and drags(s.platform) == []
