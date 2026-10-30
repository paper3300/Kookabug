"""앱·창 노드 (MVP 노드 목록 3장, 구현 계획 M1 T10): 가짜 ctx + 예제 게임 장면 표(`FakeScenario`).

출구마다 한 번씩 지나고, 창을 정하는 노드가 호출 프레임의 현재 대상 창을 바꾸고 앞으로 가져오는지
본다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import link, make_workspace
from helpers.m1 import ScenePlatform
from helpers.run import tk
from testkit import registry_with_testkit

from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.engine import ExecOptions, Executor, FakeClock, MemoryArtifacts
from kookabug_core.engine.scenario import FakeScenario
from kookabug_core.loader import load_program
from kookabug_nodes.app import close, launch
from kookabug_nodes.window import attach, set_current, set_size
from kookabug_sdk.testing import FakeContext, FakeWindow, fake_context
from kookabug_sdk.types import ProcessRef, WindowRef

SCENARIO = FRAMES_DIR / "scenario.json"
GAME = "SampleRPG"

MAIN = WindowRef(0x100, "Main Game", pid=7, process_created="1", binding="b.main")
POPUP = WindowRef(0x200, "Confirm", pid=7, process_created="1", binding="b.popup")
OTHER = WindowRef(0x300, "Notepad", pid=9, process_created="2", binding="b.other")


def scene_ctx() -> FakeContext:
    return fake_context(scenario=FakeScenario.load(SCENARIO))


def desktop_ctx(window: WindowRef | None = None) -> FakeContext:
    return fake_context(
        window=window,
        windows=[
            FakeWindow(POPUP, process_name="game.exe", owned=True),
            FakeWindow(MAIN, process_name="game.exe", client_size=(1024, 640)),
            FakeWindow(OTHER, process_name="notepad.exe"),
        ],
    )


# ---------------------------------------------------------------- core.app.launch


def test_launch_sets_current_window() -> None:
    ctx = scene_ctx()
    assert ctx.window is None
    result = launch(ctx, path="game.exe", args=["--size", "1024x640"], cwd="D:/games")
    assert result.exit == "attached" and result.kind == "ok"
    window, process = result.outputs["window"], result.outputs["process"]
    assert isinstance(window, WindowRef) and window.title == GAME
    assert process == ProcessRef(window.pid, "game.exe")
    assert ctx.process.launched == [("game.exe", ("--size", "1024x640"), "D:/games")]
    # 호출 프레임의 현재 대상 창이 되고 한 번 앞으로 가져온다
    assert ctx.window == window
    assert ctx.windows.activated == [window]


def test_launch_window_title_filter() -> None:
    ctx = scene_ctx()
    ok = launch(ctx, path="game.exe", window_title="/^Sample/")
    assert ok.exit == "attached"
    # 제목이 맞는 창이 없으면 timeout_ms까지 기다리고 timeout (띄운 프로세스는 내보낸다)
    ctx = scene_ctx()
    before = ctx.clock.now_ms()
    missed = launch(ctx, path="game.exe", window_title="Launcher", timeout_ms=1500)
    assert missed.exit == "timeout" and missed.kind == "fail"
    assert ctx.clock.now_ms() - before == 1500
    assert isinstance(missed.outputs["process"], ProcessRef)
    assert ctx.windows.find(GAME) is not None  # 창은 떴지만 제목이 다르다
    assert ctx.window is None and ctx.windows.activated == []


def test_launch_without_window_is_timeout() -> None:
    ctx = fake_context()  # 장면 없음: 띄워도 창이 안 뜬다
    result = launch(ctx, path="tool.exe", timeout_ms=100)
    assert result.exit == "timeout"
    assert result.outputs["process"].name == "tool.exe"


# ---------------------------------------------------------------- core.app.close


def test_close_closed_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = scene_ctx()
    process = launch(ctx, path="game.exe").outputs["process"]
    assert close(ctx, process=process).exit == "closed"
    assert ctx.process.closed == [process]
    assert ctx.windows.find(GAME) is None
    # 정상 종료하지 않아 강제로 끝냈으면 timeout
    calls: list[tuple[ProcessRef, int]] = []

    def forced(p: ProcessRef, force_after_ms: int) -> bool:
        calls.append((p, force_after_ms))
        return False

    monkeypatch.setattr(ctx.process, "close", forced)
    result = close(ctx, process=process, force_after_ms=250)
    assert (result.exit, result.kind) == ("timeout", "fail")
    assert calls == [(process, 250)]


# ---------------------------------------------------------------- core.window.attach


def test_attach_found_and_not_found() -> None:
    ctx = desktop_ctx()
    found = attach(ctx, title="main game")
    assert found.exit == "found" and found.outputs == {"window": MAIN}
    assert ctx.window == MAIN and ctx.windows.activated == [MAIN]
    missed = attach(ctx, title="/^Nope$/")
    assert (missed.exit, missed.kind) == ("not_found", "fail")
    assert ctx.window == MAIN  # 못 찾으면 현재 창은 그대로


def test_attach_by_process_name() -> None:
    ctx = desktop_ctx()
    result = attach(ctx, process_name="NOTEPAD.EXE")
    assert result.exit == "found" and result.outputs["window"] == OTHER
    # 제목과 프로세스 이름을 같이 주면 둘 다 맞아야 한다
    assert attach(ctx, title="Notepad", process_name="game.exe").exit == "not_found"
    # 장면 표의 게임 창도 프로세스 이름으로 찾는다
    scene = scene_ctx()
    window = launch(scene, path="game.exe").outputs["window"]
    other = scene_ctx()
    assert attach(scene, process_name="python.exe").outputs["window"] == window
    assert attach(other, process_name="python.exe").exit == "not_found"


def test_attach_owned_popup_needs_flag() -> None:
    ctx = desktop_ctx()
    # 소유 팝업은 기본으로는 찾지 않는다 (Z 순서 앞이어도)
    assert attach(ctx, title="Confirm").exit == "not_found"
    assert attach(ctx, process_name="game.exe").outputs["window"] == MAIN
    owned = attach(ctx, title="Confirm", owned=True)
    assert owned.exit == "found" and owned.outputs["window"] == POPUP
    assert ctx.window == POPUP


def test_attach_needs_title_or_process() -> None:
    with pytest.raises(ValueError, match="title"):
        attach(desktop_ctx())


# ---------------------------------------------------------------- core.window.set_current


def test_set_current_changes_frame_window_and_activates() -> None:
    ctx = desktop_ctx(MAIN)
    result = set_current(ctx, window=OTHER)
    assert result.exit == "done" and result.kind == "ok"
    assert ctx.window == OTHER and ctx.windows.activated == [OTHER]
    assert set_current(ctx, window=MAIN).exit == "done"
    assert ctx.window == MAIN and ctx.windows.activated == [OTHER, MAIN]


# ---------------------------------------------------------------- core.window.set_size


def test_set_size_done_and_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = desktop_ctx(MAIN)
    assert set_size(ctx, client_size=[1280, 720]).exit == "done"
    assert ctx.windows.info(MAIN).client_size == (1280, 720)

    monkeypatch.setattr(ctx.windows, "set_client_size", lambda window, w, h: False)
    result = set_size(ctx, client_size=[800, 600])
    assert (result.exit, result.kind) == ("fail", "fail")
    assert result.message is not None and "800x600" in result.message


def test_set_size_uses_step_window_and_rejects_bad_size() -> None:
    ctx = desktop_ctx(OTHER)
    assert set_size(ctx, client_size=[640, 480]).exit == "done"
    assert ctx.windows.info(OTHER).client_size == (640, 480)
    assert ctx.windows.info(MAIN).client_size == (1024, 640)
    for bad in ([640], [640, 480, 1], [0, 480], [640, -1]):
        with pytest.raises(ValueError, match="client_size"):
            set_size(ctx, client_size=bad)
    with pytest.raises(ValueError, match="대상 창"):
        set_size(desktop_ctx(None), client_size=[640, 480])


# ---------------------------------------------------------------- 실행기 (장면 표 플랫폼)


def test_app_window_nodes_in_executor(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_a")
        .node("n_a", "core.app.launch", inputs={"path": "a.exe"}, next={"attached": "n_b"})
        .node("n_b", "core.app.launch", inputs={"path": "b.exe"}, next={"attached": "n_set"})
        .node(
            "n_set",
            "core.window.set_current",
            inputs={"window": link("n_a.window")},
            next={"done": "n_click"},
        )
        .node("n_click", "core.input.click", inputs={"point": [5, 6]}, next={"done": "n_size"})
        .node(
            "n_size",
            "core.window.set_size",
            inputs={"client_size": [1024, 640], "window": link("n_b.window")},
            next={"done": "n_bad"},
        )
        .node(
            "n_bad",
            "core.window.set_size",
            inputs={"client_size": [800, 600]},
            next={"done": "n_close", "fail": "n_close"},
        )
        .node(
            "n_close",
            "core.app.close",
            inputs={"process": link("n_a.process")},
            next={"closed": "n_attach"},
        )
        .node(
            "n_attach",
            "core.window.attach",
            inputs={"title": GAME},
            next={"found": "n_ok"},
        )
        .node(
            "n_ok",
            "core.assert.compare",
            inputs={"a": 1, "op": "==", "b": 1},
            next={"ok": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ws = make_workspace(tmp_path / "ws")
    g.write(ws, "tests/t.graph.json")
    platform = ScenePlatform.sample()
    result = Executor(
        registry_with_testkit(), platform=platform, clock=FakeClock(), artifacts=MemoryArtifacts()
    ).run(load_program(ws, "tests/t.graph.json"), ExecOptions(run_id="r1"))
    assert result.verdict == "pass", result.reason

    starts = {e["step"]: e["node"] for e in result.events if e["event"] == "step.start"}
    ends: dict[str, dict[str, Any]] = {
        starts[e["step"]]: e for e in result.events if e["event"] == "step.end"
    }
    exits = {node: end["exit"] for node, end in ends.items()}
    assert exits["n_size"] == "done" and exits["n_bad"] == "fail"
    assert exits["n_close"] == "closed" and exits["n_attach"] == "found"
    first, second = (
        platform.scenario.game_of_process(ProcessRef(ends[n]["outputs"]["process"]["pid"]))
        for n in ("n_a", "n_b")
    )
    assert first is not None and second is not None
    # 나중에 띄운 B가 현재 창이었지만 set_current 뒤 입력은 A로 간다
    assert [hwnd for hwnd, kind, _ in platform.scenario.inputs if kind == "click"] == [
        first.window.handle
    ]
    # 닫은 A는 더 찾지 않는다
    assert not first.open and second.open
    assert ends["n_attach"]["outputs"]["window"]["handle"] == second.window.handle
