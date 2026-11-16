"""UX10 B: `core.app.launch`의 `path`를 비우면 워크스페이스 게임 설정(`game.executable`·`game.args`·
`game.cwd`)으로 띄운다. 설정이 없으면 분명한 오류, 경로를 준 그래프는 지금 그대로."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import make_workspace
from helpers.m1 import ScenePlatform
from helpers.run import tk
from testkit import registry_with_testkit

from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.engine import ExecOptions, Executor, FakeClock, MemoryArtifacts
from kookabug_core.engine.scenario import FakeScenario
from kookabug_core.loader import load_program
from kookabug_nodes.app import launch
from kookabug_sdk.errors import RunnerError
from kookabug_sdk.testing import FakeContext, fake_context

GAME_SETTINGS = {
    "game.executable": "D:/games/sample/game.exe",
    "game.args": ["--windowed"],
    "game.cwd": "D:/games/sample",
}


def scene_ctx(settings: dict[str, Any] | None = None) -> FakeContext:
    return fake_context(scenario=FakeScenario.load(FRAMES_DIR / "scenario.json"), settings=settings)


def test_empty_path_uses_game_setting() -> None:
    ctx = scene_ctx(GAME_SETTINGS)
    result = launch(ctx)
    assert result.exit == "attached"
    expected = ("D:/games/sample/game.exe", ("--windowed",), "D:/games/sample")
    assert ctx.process.launched == [expected]
    # 빈 글자도 비운 것으로 본다 (편집기에서 지운 칸)
    ctx = scene_ctx(GAME_SETTINGS)
    assert launch(ctx, path="").exit == "attached"
    assert ctx.process.launched[0][0] == "D:/games/sample/game.exe"


def test_node_args_and_cwd_win_over_setting() -> None:
    ctx = scene_ctx(GAME_SETTINGS)
    launch(ctx, args=["--log"], cwd="D:/other")
    assert ctx.process.launched == [("D:/games/sample/game.exe", ("--log",), "D:/other")]
    ctx = scene_ctx({"game.executable": "game.exe"})  # args·cwd 설정 없음
    launch(ctx)
    assert ctx.process.launched == [("game.exe", (), None)]


def test_empty_cwd_uses_setting_like_empty_path() -> None:
    ctx = scene_ctx(GAME_SETTINGS)
    launch(ctx, path="", cwd="")
    assert ctx.process.launched[0][2] == "D:/games/sample"
    ctx = scene_ctx(GAME_SETTINGS)
    launch(ctx, args=[])  # 빈 목록은 그 값 (설정 인자를 쓰지 않음)
    assert ctx.process.launched[0][1] == ()


def test_explicit_path_ignores_setting() -> None:
    ctx = scene_ctx(GAME_SETTINGS)
    launch(ctx, path="old.exe")
    assert ctx.process.launched == [("old.exe", (), None)]
    ctx = scene_ctx(GAME_SETTINGS)
    launch(ctx, path="old.exe", cwd="")
    assert ctx.process.launched == [("old.exe", (), "")]  # 경로를 준 노드는 지금 그대로


def test_missing_setting_is_clear_error() -> None:
    with pytest.raises(RunnerError) as caught:
        launch(scene_ctx())
    assert caught.value.code == "setting_missing"
    assert "게임 설정이 없다" in str(caught.value) and "설정 도우미" in str(caught.value)
    with pytest.raises(RunnerError) as caught:
        launch(scene_ctx({"game.executable": "game.exe", "game.args": "--bad"}))
    assert caught.value.code == "setting_invalid"


def run_graph(tmp_path: Path, local: dict[str, Any] | None) -> tuple[Any, list[tuple[str, ...]]]:
    g = (
        tk()
        .entry("n_launch")
        .node("n_launch", "core.app.launch", inputs={}, next={"attached": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    ws = make_workspace(tmp_path / "ws", local=local)
    g.write(ws, "tests/t.graph.json")
    platform = ScenePlatform.sample()
    calls: list[tuple[str, ...]] = []
    inner = platform.launch

    def recording(path: str, args: Sequence[str], cwd: str | None) -> Any:
        calls.append((path, *args, str(cwd)))
        return inner(path, args, cwd)

    platform.launch = recording  # type: ignore[method-assign]
    result = Executor(
        registry_with_testkit(), platform=platform, clock=FakeClock(), artifacts=MemoryArtifacts()
    ).run(load_program(ws, "tests/t.graph.json"), ExecOptions(run_id="r1"))
    return result, calls


def test_graph_without_path_runs_with_workspace_setting(tmp_path: Path) -> None:
    result, calls = run_graph(tmp_path, GAME_SETTINGS)
    assert result.verdict == "pass", result.reason
    assert calls == [("D:/games/sample/game.exe", "--windowed", "D:/games/sample")]


def test_graph_without_path_and_setting_errors(tmp_path: Path) -> None:
    result, calls = run_graph(tmp_path, None)
    assert result.verdict == "error" and calls == []
    ends = [e for e in result.events if e["event"] == "step.end" and e.get("error")]
    assert ends and ends[0]["error"]["code"] == "setting_missing"
