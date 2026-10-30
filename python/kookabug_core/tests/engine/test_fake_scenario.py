"""장면 전이 가짜 플랫폼 `FakeScenario` (구현 계획 M1 2.7, 계획 검수 8). 예제 게임의 장면 표
(`fixtures/sample-game/frames/scenario.json`)로 본다. 기준 해석(`sample_game.scenario.Simulator`)과
무작위 입력으로 대조한다."""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import make_workspace
from helpers.m1 import SCENARIO, START, ScenePlatform, run_on
from helpers.run import tk

from kookabug_core.engine.errors import EngineError
from kookabug_core.engine.scenario import FakeScenario, ScenarioError, ScenarioState
from kookabug_sdk.testing import InputCall, fake_context
from kookabug_sdk.types import Point, ProcessRef
from sample_game.scenario import Simulator

LOGIN_BUTTON = (512, 408)
ACCOUNT, PASSWORD = "qa_tester_01", "sample-pass-01"


def spec() -> dict[str, Any]:
    return json.loads(SCENARIO.read_text(encoding="utf-8"))


def scene_of(image_path: Path | None) -> str:
    assert image_path is not None
    return image_path.stem


def test_launch_rule_gives_fake_process_and_window() -> None:
    scenario = FakeScenario.load(SCENARIO)
    a = scenario.launch_game("C:/games/sample.exe", ["--maintenance"])
    b = scenario.launch_game("C:/games/sample.exe", [])
    assert (a.process.pid, b.process.pid) == (4001, 4002)
    assert a.window.handle != b.window.handle and a.window.pid == a.process.pid
    assert (a.state.variant, b.state.variant) == ("maintenance", "default")
    assert a.process.name == "python.exe"
    info = scenario.info(a.window)
    assert (info.title, info.class_name, info.client_size, info.dpi) == (
        "SampleRPG",
        "TkTopLevel",
        (1024, 640),
        96,
    )
    # 나중에 띄운 창이 앞, 프로세스 이름으로도 찾는다
    assert scenario.find("sample") == b.window
    assert scenario.find(process_name="PYTHON.EXE") == b.window
    assert scenario.close_process(ProcessRef(b.process.pid))
    assert scenario.find("sample") == a.window
    with pytest.raises(EngineError) as caught:
        scenario.game_of(b.window)
    assert caught.value.code == "window_gone"


def test_click_in_rect_transitions_scene() -> None:
    scenario = FakeScenario.load(SCENARIO)
    game = scenario.launch_game("game.exe")
    assert scene_of(scenario.frame(game).path) == "title"
    scenario.apply(game, "click", START.x - 1, START.y, "left")  # 버튼 밖
    assert scene_of(scenario.frame(game).path) == "title"
    scenario.apply(game, "click", START.center.x, START.center.y, "right")  # 왼쪽 버튼만
    assert scene_of(scenario.frame(game).path) == "title"
    scenario.apply(game, "click", START.center.x, START.center.y, "left")
    assert scene_of(scenario.frame(game).path) == "login"


def test_key_transitions_scene_and_form_typing() -> None:
    scenario = FakeScenario.load(SCENARIO)
    game = scenario.launch_game("game.exe")
    scenario.apply(game, "click", START.center.x, START.center.y, "left")
    scenario.apply(game, "text", ACCOUNT)
    scenario.apply(game, "key", "Tab")  # 키 이름은 대소문자 무시
    scenario.apply(game, "text", PASSWORD)
    scenario.apply(game, "key", "enter")
    assert game.state.scene == "lobby"

    wrong = scenario.launch_game("game.exe")
    scenario.apply(wrong, "click", START.center.x, START.center.y, "left")
    scenario.apply(wrong, "text", ACCOUNT)
    scenario.apply(wrong, "key", "enter")
    assert wrong.state.scene == "login_error"
    assert wrong.state.forms["login"]["focus"] == "password"


def test_after_frames_delay() -> None:
    state = ScenarioState(spec())
    state.scene = "loading"
    shown = [state.capture() for _ in range(5)]
    assert shown == ["loading", "loading", "loading", "world", "world"]


def test_spec_shape_validated(tmp_path: Path) -> None:
    def broken(edit: Any) -> str:
        data = copy.deepcopy(spec())
        edit(data)
        path = tmp_path / "frames" / "s.json"
        path.parent.mkdir(exist_ok=True)
        for png in Path(SCENARIO).parent.glob("*.png"):
            (path.parent / png.name).write_bytes(png.read_bytes())
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ScenarioError) as caught:
            FakeScenario.load(path)
        return str(caught.value)

    assert "/format" in broken(lambda d: d.update(format="other/0"))
    assert "/start" in broken(lambda d: d.update(start="nowhere"))
    assert "/scenes/title" in broken(lambda d: d["scenes"].update(title="missing.png"))
    assert "/transitions/0/to" in broken(lambda d: d["transitions"][0].update(to="nowhere"))
    assert "/transitions/0/on/kind" in broken(lambda d: d["transitions"][0]["on"].update(kind="x"))
    assert "/launch" in broken(
        lambda d: d.update(launch=[{"args_contains": "-x", "variant": "default"}])
    )
    assert "모르는 키" in broken(lambda d: d.update(extra=1))
    assert "/window/client_size" in broken(lambda d: d["window"].update(client_size=[0, 1]))


@pytest.mark.parametrize("seed", range(6))
def test_matches_reference_simulator_on_random_inputs(seed: int) -> None:
    """기준 해석(예제 게임 `Simulator`)과 같은 입력에 같은 장면·폼 상태."""
    rng = random.Random(seed)
    data = spec()
    rects = [t["on"]["rect"] for t in data["transitions"] if t.get("on", {}).get("kind") == "click"]
    rects += [f["rect"] for f in data["forms"]["login"]["fields"]]
    keys = sorted(
        {t["on"]["key"] for t in data["transitions"] if t.get("on", {}).get("kind") == "key"}
    )
    keys += ["tab", "backspace", "a", "ctrl+a", "ctrl+a"]
    args = rng.choice([[], ["--login-fail"], ["--maintenance"]])
    ours = ScenarioState(data, args)
    ref = Simulator(data, args)
    for _ in range(300):
        roll = rng.random()
        if roll < 0.4:
            x, y, w, h = rng.choice(rects)
            point = (x + rng.randrange(w), y + rng.randrange(h))
            ours.click(*point)
            ref.click(*point)
        elif roll < 0.65:
            k = rng.choice(keys)
            ours.key(k)
            ref.key(k)
        elif roll < 0.8:
            text = rng.choice([ACCOUNT, PASSWORD, "x", "한"])
            ours.text(text)
            ref.text(text)
        else:
            assert ours.capture() == ref.capture()
        assert (ours.scene, ours.forms) == (ref.scene, ref.forms)


def test_fake_context_scenario_protocol() -> None:
    """SDK `fake_context(scenario=)`에 그대로 넣는다 (가장 나중에 띄운 게임이 화면·입력을
    받는다)."""
    scenario = FakeScenario.load(SCENARIO)
    ctx = fake_context(scenario=scenario)
    process = ctx.process.launch("game.exe")
    window = ctx.process.find_window(process)
    assert window is not None and window.title == "SampleRPG"
    assert scene_of(ctx.capture().path) == "title"
    ctx.input.click(Point(START.center.x, START.center.y))
    assert scene_of(ctx.capture().path) == "login"
    assert ctx.input.calls[-1] == InputCall(
        "click", (Point(512, 412),), {"button": "left", "count": 1}
    )


def test_platform_runs_launch_click_and_key_graph(tmp_path: Path) -> None:
    """실행기 + `ScenarioPlatform`: 띄우기 → 클릭(타이틀 → 로그인) → 글자·키 → 로비."""
    ws = make_workspace(tmp_path)
    platform = ScenePlatform.sample()
    g = (
        tk()
        .entry("n_launch")
        .node(
            "n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_start"}
        )
        .node("n_start", "testkit.input.tap", inputs={"x": 512, "y": 412}, next={"done": "n_acc"})
        .node("n_acc", "testkit.m1.type", inputs={"text": ACCOUNT}, next={"done": "n_tab"})
        .node("n_tab", "testkit.m1.key", inputs={"key": "tab"}, next={"done": "n_pw"})
        .node("n_pw", "testkit.m1.type", inputs={"text": PASSWORD}, next={"done": "n_enter"})
        .node(
            "n_enter",
            "testkit.m1.key",
            inputs={"key": "enter", "hold_ms": 50},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run_on(ws, g, platform)
    assert ran.result.verdict == "pass", ran.result.reason
    assert platform.scenario.latest().state.scene == "lobby"
    assert ran.clock.now_ms() >= 50  # 누르고 있기 = 취소로 깨는 기다림
