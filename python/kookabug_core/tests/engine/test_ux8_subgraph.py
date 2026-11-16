"""UX8 D·E: 서브그래프가 잡은 창을 부른 쪽이 이어받기, 서브그래프 직접 실행 판정.

- D: `core.graph.call`이 ok 계열 출구로 돌아오면 서브그래프 안에서 마지막으로 정한 현재 대상 창이
  부른 쪽 현재 창이 된다 — 서브그래프 안 `core.app.launch` 다음의 부른 쪽 클릭 노드가 그 창에
  입력한다(보통·붙여 실행 둘 다). fail 출구면 넘기지 않는다. 서브그래프가 끝나도 띄운 게임은 살아
  있다(실행 Job은 실행 전체 끝에서만 정리)
- E: `kind: subgraph`를 직접 실행해 ok 출구에 닿으면 pass("출구 '<이름>'에 닿았다"), fail
  출구면 fail
"""

from __future__ import annotations

from pathlib import Path

from helpers.graphs import GraphBuilder, make_workspace, subgraph_interface
from helpers.m1 import ScenePlatform, clicks, run_on
from helpers.run import tk
from testkit import registry_with_testkit

from kookabug_core.engine import ExecOptions, Executor, FakeClock, MemoryArtifacts
from kookabug_core.engine.executor import AttachStart, RunResult
from kookabug_core.loader import load_program
from kookabug_core.workspace import Workspace
from kookabug_sdk.types import ProcessRef

SUB = "subgraphs/common/game_open.graph.json"
"""`게임 실행`과 같은 일을 하는 서브그래프 (붙여 실행이 통째로 건너뛰는 경로가 아니다)."""


def launch_sub(ws: Workspace, *, fail: bool = False) -> None:
    """안에서 `core.app.launch`로 게임을 띄워 창을 잡는 서브그래프. `fail`이면 fail 출구."""
    exit_name = "bad" if fail else "done"
    (
        tk("subgraph", interface=subgraph_interface(exits={"done": "ok", "bad": "fail"}))
        .entry("n_launch")
        .node(
            "n_launch",
            "core.app.launch",
            inputs={"path": "game.exe"},
            next={"attached": "n_x"},
        )
        .exit("n_x", exit_name)
        .write(ws, SUB)
    )


def caller(*, handle_fail: bool = False) -> GraphBuilder:
    builder = tk().entry("n_call")
    nexts = {"done": "n_click"}
    if handle_fail:
        nexts["bad"] = "n_click"
    return (
        builder.node("n_call", "core.graph.call", config={"graph": SUB}, next=nexts)
        .node("n_click", "core.input.click", inputs={"point": [30, 40]}, next={"done": "n_w"})
        .node("n_w", "testkit.m1.window", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def test_ok_exit_passes_window_to_caller(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    launch_sub(ws)
    platform = ScenePlatform.sample()
    ran = run_on(ws, caller(), platform)
    assert ran.result.verdict == "pass", ran.result.reason
    inner = ran.end("n_launch")["outputs"]["window"]["handle"]
    # 서브그래프가 잡은 창에 부른 쪽 클릭이 들어갔고, 다음 노드의 현재 창도 그 창이다
    assert clicks(platform) == [(inner, 30, 40)]
    assert ran.end("n_w")["outputs"]["handle"] == inner
    # 서브그래프가 끝나도 띄운 게임은 살아 있다 (실행 끝까지)
    assert [g.window.handle for g in platform.scenario.games()] == [inner]


def test_fail_exit_does_not_pass_window(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    launch_sub(ws, fail=True)
    platform = ScenePlatform.sample()
    ran = run_on(ws, caller(handle_fail=True), platform)
    # 부른 쪽에 정해진 창이 없다: 클릭이 대상 창 없음으로 실패한다 (서브그래프 창을 쓰지 않음)
    assert ran.result.verdict == "error", ran.result.reason
    assert "대상 창" in str(ran.result.reason)
    assert clicks(platform) == []


def test_unchanged_window_keeps_callers(tmp_path: Path) -> None:
    """서브그래프가 대상을 바꾸지 않았으면 부른 쪽 창 그대로."""
    ws = make_workspace(tmp_path)
    (
        tk("subgraph", interface=subgraph_interface())
        .entry("n_w2")
        .node("n_w2", "testkit.m1.window", next={"done": "n_x"})
        .exit("n_x", "done")
        .write(ws, SUB)
    )
    platform = ScenePlatform.sample()
    graph = (
        tk()
        .entry("n_a")
        .node("n_a", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_call"})
        .node("n_call", "core.graph.call", config={"graph": SUB}, next={"done": "n_w"})
        .node("n_w", "testkit.m1.window", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    ran = run_on(ws, graph, platform)
    assert ran.result.verdict == "pass", ran.result.reason
    a = ran.end("n_a")["outputs"]["handle"]
    assert ran.end("n_w2")["outputs"]["handle"] == a
    assert ran.end("n_w")["outputs"]["handle"] == a


def test_attach_run_passes_window_too(tmp_path: Path) -> None:
    """붙여 실행: 서브그래프 안 창 잡기 노드(게임 실행 아닌 것)가 정한 창도 같은 규칙."""
    ws = make_workspace(tmp_path)
    platform = ScenePlatform.sample()
    game = platform.scenario.launch_game("game.exe")  # 켜져 있는 게임
    other = platform.scenario.launch_game("game.exe")  # 서브그래프가 고를 창
    (
        tk("subgraph", interface=subgraph_interface())
        .entry("n_launch")
        .node("n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_s"})
        .node("n_s", "testkit.m1.set_window", inputs={"title": "Sample"}, next={"done": "n_x"})
        .exit("n_x", "done")
        .write(ws, SUB)
    )
    caller().write(ws, "tests/ux8.graph.json")
    program = load_program(ws, "tests/ux8.graph.json")
    executor = Executor(
        registry_with_testkit(), platform=platform, clock=FakeClock(), artifacts=MemoryArtifacts()
    )
    start = AttachStart(game.window, ProcessRef(game.window.pid))
    result = executor.run(program, ExecOptions(run_id="r1", attach=start))
    assert result.verdict == "pass", result.reason
    # 게임 실행 노드는 대신했고(새로 띄우지 않음), set_window가 고른 창(가장 앞 = 나중에 띄운 창)이
    # 부른 쪽 클릭을 받았다
    assert len(platform.scenario.games()) == 2
    assert clicks(platform) == [(other.window.handle, 30, 40)]


# ---------------------------------------------------------------- E 직접 실행 판정


def run_sub(ws: Workspace) -> RunResult:
    program = load_program(ws, SUB)
    executor = Executor(
        registry_with_testkit(),
        platform=ScenePlatform.sample(),
        clock=FakeClock(),
        artifacts=MemoryArtifacts(),
    )
    return executor.run(program, ExecOptions(run_id="r1"))


def test_direct_subgraph_ok_exit_passes(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    launch_sub(ws)
    result = run_sub(ws)
    assert result.verdict == "pass"
    assert result.reason == "출구 'done'에 닿았다"


def test_direct_subgraph_fail_exit_fails(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    launch_sub(ws, fail=True)
    result = run_sub(ws)
    assert result.verdict == "fail"
    assert "bad" in result.reason


def test_test_graph_without_assertion_still_fails(tmp_path: Path) -> None:
    """test 그래프 판정은 그대로 (검증 없이 끝나면 fail)."""
    ws = make_workspace(tmp_path)
    platform = ScenePlatform.sample()
    graph = (
        tk()
        .entry("n_a")
        .node("n_a", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_w"})
        .node("n_w", "testkit.m1.window")
    )
    ran = run_on(ws, graph, platform)
    assert ran.result.verdict == "fail" and ran.result.code == "no_assertion"
