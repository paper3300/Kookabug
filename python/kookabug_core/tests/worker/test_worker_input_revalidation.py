"""워커 노드가 SDK로 직접 부른 입력도 공용 입력 서비스를 거친다 (구현 계획 M1 2.4, 계획 검수 4).

워커 노드(testkit)가 `ctx.vision.find` → `ctx.input.click(match)`을 RPC로 부르면 runner의
`CtxServer` → 스텝 ctx → 공용 입력 서비스에서 창 고정·재검증·재매칭을 한다. 장면은 예제 게임
`FakeScenario`, 찾기는 정해 둔 답(`StubEngines`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers.graphs import link, make_workspace, target
from helpers.m1 import START, ScenePlatform, StubEngines, clicks, write_target
from helpers.run import tk
from helpers.worker import WorkerHarness

from kookabug_core.engine import RunResult
from kookabug_sdk.types import Rect

pytestmark = pytest.mark.process

TARGET = "targets/start.target.json"
NEW = Rect(824, 760, 400, 128)


def harness(tmp_path: Path, graph: object, platform: ScenePlatform) -> WorkerHarness:
    ws = make_workspace(tmp_path / "ws")
    write_target(ws, TARGET)
    graph.write(ws, "tests/t.graph.json")  # type: ignore[attr-defined]
    return WorkerHarness(ws, "tests/t.graph.json", tmp_path, platform=platform)


def find_click_graph() -> object:
    return (
        tk()
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_fc"})
        .node(
            "n_fc",
            "testkit.m1.find_click",
            inputs={"target": target(TARGET)},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


def end_of(h: WorkerHarness, result: RunResult, node: str) -> dict[str, object]:
    del h
    steps = [e["step"] for e in result.events if e["event"] == "step.start" and e["node"] == node]
    (found,) = [e for e in result.events if e["event"] == "step.end" and e["step"] in steps]
    return found


def test_worker_direct_click_after_resize_rematched(tmp_path: Path) -> None:
    engines = StubEngines({TARGET: [START, NEW]})
    platform = ScenePlatform.sample(engines)
    engines.after_find.append(lambda: platform.resize((2048, 1280)))
    h = harness(tmp_path, find_click_graph(), platform)
    result = h.run_all()
    assert result.verdict == "pass", result.reason
    assert clicks(platform)[-1][1:] == (NEW.center.x, NEW.center.y)
    assert engines.calls_of(TARGET) == [TARGET, TARGET]  # 워커 찾기 한 번 + runner 다시 찾기 한 번


def test_worker_direct_click_stale_without_target(tmp_path: Path) -> None:
    engines = StubEngines({TARGET: [START]}, with_target=False)
    platform = ScenePlatform.sample(engines)
    engines.after_find.append(lambda: platform.resize((2048, 1280)))
    h = harness(tmp_path, find_click_graph(), platform)
    result = h.run_all()
    assert (result.verdict, result.code, result.failure_path) == (
        "fail",
        "unhandled_fail",
        ("n_fc",),
    )
    end = end_of(h, result, "n_fc")
    assert (end["status"], end["exit"]) == ("fail", None)
    assert str(end["message"]).startswith("stale_observation:")
    assert clicks(platform) == []


def test_worker_stale_swallowed_still_unhandled_fail(tmp_path: Path) -> None:
    engines = StubEngines({TARGET: [START, None]})
    platform = ScenePlatform.sample(engines)
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
    result = harness(tmp_path, g, platform).run_all()
    assert (result.verdict, result.failure_path) == ("fail", ("n_fc",))


def test_worker_common_window_input_applies_to_its_requests(tmp_path: Path) -> None:
    platform = ScenePlatform.sample()
    g = (
        tk()
        .entry("n_a")
        .node("n_a", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_b"})
        .node("n_b", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_t1"})
        .node(
            "n_t1",
            "testkit.input.tap",
            inputs={"x": 1, "y": 1, "window": link("n_a.window")},
            next={"done": "n_w"},
        )
        .node(
            "n_w", "testkit.m1.window", inputs={"window": link("n_a.window")}, next={"done": "n_t2"}
        )
        .node("n_t2", "testkit.input.tap", inputs={"x": 2, "y": 2}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = harness(tmp_path, g, platform)
    result = h.run_all()
    assert result.verdict == "pass", result.reason
    a = end_of(h, result, "n_a")["outputs"]["handle"]  # type: ignore[index]
    b = end_of(h, result, "n_b")["outputs"]["handle"]  # type: ignore[index]
    assert end_of(h, result, "n_w")["outputs"]["handle"] == a  # type: ignore[index]
    assert clicks(platform) == [(a, 1, 1), (b, 2, 2)]


def test_worker_set_window_frame_scoped(tmp_path: Path) -> None:
    platform = ScenePlatform.sample()
    g = (
        tk()
        .entry("n_a")
        .node("n_a", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_b"})
        .node("n_b", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_switch"})
        .node(
            "n_switch",
            "testkit.m1.switch_click",
            inputs={"to": link("n_a.window"), "x": 5, "y": 5},
            next={"done": "n_w"},
        )
        .node("n_w", "testkit.m1.window", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = harness(tmp_path, g, platform)
    result = h.run_all()
    assert result.verdict == "pass", result.reason
    a = end_of(h, result, "n_a")["outputs"]["handle"]  # type: ignore[index]
    b = end_of(h, result, "n_b")["outputs"]["handle"]  # type: ignore[index]
    # 워커 노드의 set_window: 그 노드의 클릭은 시작 때 창(B), 다음 스텝부터 A
    assert clicks(platform) == [(b, 5, 5)]
    assert end_of(h, result, "n_w")["outputs"]["handle"] == a  # type: ignore[index]
