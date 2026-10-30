"""입력 노드 (MVP 노드 목록 6장, 구현 계획 M1 T10).

노드는 `ctx.input`만 부른다. 가짜 ctx로 노드가 넘기는 요청을 보고, 실행기 + 예제 게임 장면 표
(`FakeScenario`, 실제 매칭 엔진)로 공용 입력 서비스를 거쳐 게임 장면에 닿는 점·글자를 본다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import check, make_workspace, secret, target
from helpers.m1 import ScenePlatform, clicks, kinds
from helpers.run import tk
from testkit import registry_with_testkit

from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.engine import ExecOptions, Executor, FakeClock, MemoryArtifacts, RunResult
from kookabug_core.engine.scenario import FakeScenario
from kookabug_core.loader import load_program
from kookabug_core.workspace import MemorySecrets
from kookabug_nodes.app import launch
from kookabug_nodes.input import click, drag, key, scroll, type_text
from kookabug_platform.engines import RunEngines
from kookabug_platform.frames import FrameStore, decode_image
from kookabug_sdk import Secret
from kookabug_sdk.testing import FakeContext, InputCall, fake_context, load_target
from kookabug_sdk.types import Match, Point, Rect

SCENARIO = FRAMES_DIR / "scenario.json"
START = Point(512, 412)
"""타이틀 화면 "게임 시작" 버튼 가운데."""
ACCOUNT_FIELD = (560, 230)
PASSWORD_FIELD = (560, 310)
PASSWORD = "sample-pass-01"


def scene_ctx() -> tuple[FakeContext, FakeScenario]:
    """예제 게임을 띄운 가짜 ctx (타이틀 화면)."""
    scenario = FakeScenario.load(SCENARIO)
    ctx = fake_context(scenario=scenario)
    assert launch(ctx, path="game.exe").exit == "attached"
    return ctx, scenario


def login_values(scenario: FakeScenario) -> dict[str, str]:
    return dict(scenario.latest().state.forms["login"]["values"])


# ---------------------------------------------------------------- core.input.click


def test_click_match_uses_click_point() -> None:
    ctx, scenario = scene_ctx()
    # target의 클릭 지점(`click`)이 상자 가운데보다 먼저다
    match = Match(Rect(0, 0, 40, 40), 0.99, click=START)
    assert click(ctx, match=match).exit == "done"
    assert ctx.input.calls == [InputCall("click", (match,), {"button": "left", "count": 1})]
    hwnd = scenario.latest().window.handle
    assert scenario.inputs == [(hwnd, "click", (512, 412, "left"))]
    assert scenario.latest().state.scene == "login"


def test_click_point_input() -> None:
    ctx = fake_context()
    # 그래프 상수 [x, y]는 실행기가 Point로 바꿔 준다 (test_point_constant_coerced_by_executor)
    assert click(ctx, point=Point(512, 412)).exit == "done"
    assert click(ctx, point=Point(5, 6), button="right").exit == "done"
    assert [(c.args, c.kwargs) for c in ctx.input.calls] == [
        ((Point(512, 412),), {"button": "left", "count": 1}),
        ((Point(5, 6),), {"button": "right", "count": 1}),
    ]


def test_click_count_double() -> None:
    ctx, scenario = scene_ctx()
    assert click(ctx, point=Point(100, 100), count=2).exit == "done"
    assert ctx.input.calls[-1].kwargs == {"button": "left", "count": 2}
    assert [k for _, k, _ in scenario.inputs] == ["click", "click"]


@pytest.mark.parametrize(
    "inputs",
    [
        {},
        {"match": Match(Rect(0, 0, 4, 4), 1.0), "point": Point(1, 2)},
    ],
)
def test_click_needs_exactly_one_of_match_or_point(inputs: dict[str, Any]) -> None:
    ctx = fake_context()
    with pytest.raises(ValueError, match="하나만"):
        click(ctx, **inputs)
    assert ctx.input.calls == []


@pytest.mark.parametrize("bad", [[1], [1, 2, 3], [1.5, 2], ["1", "2"], [True, 2], {"x": 1}])
def test_click_bad_point_constant_is_validation_error(tmp_path: Path, bad: Any) -> None:
    """점 상수 모양은 노드가 아니라 실행 전 검증이 본다 (검증기의 일반 규칙)."""
    ws = make_workspace(tmp_path)
    g = (
        tk()
        .entry("n_click")
        .node("n_click", "core.input.click", inputs={"point": bad}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    g.write(ws, "tests/t.graph.json")
    (problem,) = [d for d in check(ws, "tests/t.graph.json") if d.severity == "error"]
    assert problem.code == "type_mismatch" and problem.pointer == "/nodes/n_click/in/point"
    assert "[x, y]" in problem.message


# ---------------------------------------------------------------- core.input.drag·scroll


def test_drag_duration_moves() -> None:
    ctx = fake_context()
    start = Match(Rect(10, 10, 20, 20), 0.95)
    assert drag(ctx, start=start, end=Point(300, 40), duration_ms=500).exit == "done"
    assert drag(ctx, start=Point(1, 2), end=Point(3, 4)).exit == "done"
    assert ctx.input.calls == [
        InputCall("drag", (start, Point(300, 40)), {"duration_ms": 500, "button": "left"}),
        InputCall("drag", (Point(1, 2), Point(3, 4)), {"duration_ms": 300, "button": "left"}),
    ]


def test_scroll_amount() -> None:
    ctx = fake_context()
    assert scroll(ctx, point=Point(200, 300), amount=-3).exit == "done"
    assert scroll(ctx, point=Point(1, 1), amount=2).exit == "done"
    assert ctx.input.calls == [
        InputCall("scroll", (Point(200, 300), -3)),
        InputCall("scroll", (Point(1, 1), 2)),
    ]


# ---------------------------------------------------------------- core.input.key


def test_key_combo_and_hold() -> None:
    ctx, scenario = scene_ctx()
    assert key(ctx, keys="ctrl+a").exit == "done"
    assert key(ctx, keys="shift", hold_ms=250).exit == "done"
    assert ctx.input.calls == [
        InputCall("key", ("ctrl+a",), {"hold_ms": 0}),
        InputCall("key", ("shift",), {"hold_ms": 250}),
    ]
    assert [args for _, k, args in scenario.inputs if k == "key"] == [("ctrl+a",), ("shift",)]


# ---------------------------------------------------------------- core.input.type_text


def test_type_text_without_target_types_into_focus() -> None:
    ctx = fake_context()
    assert type_text(ctx, text="안녕 abc").exit == "done"
    assert ctx.input.calls == [InputCall("type_text", ("안녕 abc",))]
    assert ctx.captured == 0  # target이 없으면 화면을 보지 않는다


def test_type_text_secret_not_logged() -> None:
    ctx = fake_context()
    result = type_text(ctx, text=Secret("hunter2"), clear=True)
    assert result.exit == "done" and result.outputs == {} and result.message is None
    # 비밀값은 감싼 채로 입력 백엔드까지 간다 (원문은 백엔드만 꺼낸다)
    (*clears, typed) = ctx.input.calls
    assert [c.args for c in clears] == [("ctrl+a",), ("backspace",)]
    assert typed.args == (Secret("hunter2"),) and isinstance(typed.args[0], Secret)
    assert "hunter2" not in repr(ctx.input.calls)
    assert all("hunter2" not in message for _, message in ctx.log.records)


def test_type_text_target_clicks_first_and_clear(targets: Any, tmp_path: Path) -> None:
    targets.login(tmp_path)
    ctx, scenario = scene_ctx()
    click(ctx, point=START)
    account = load_target(tmp_path / targets.ACCOUNT)
    password = load_target(tmp_path / targets.PASSWORD)
    # 두 칸에 여러 글자가 이미 있다 (재시도 흉내)
    assert type_text(ctx, text="old-account", target=account).exit == "done"
    assert type_text(ctx, text="old-password", target=password).exit == "done"
    assert login_values(scenario) == {"account": "old-account", "password": "old-password"}
    calls = len(ctx.input.calls)

    # 같은 칸에 다시: clear가 칸 전체를 지우고 새로 입력한다
    assert type_text(ctx, text="qa_tester_01", target=account, clear=True).exit == "done"
    assert type_text(ctx, text=Secret(PASSWORD), target=password, clear=True).exit == "done"

    methods = [(c.method, c.args[0] if c.method != "click" else None) for c in ctx.input.calls]
    assert methods[calls:] == [
        ("click", None),
        ("key", "ctrl+a"),
        ("key", "backspace"),
        ("type_text", "qa_tester_01"),
        ("click", None),
        ("key", "ctrl+a"),
        ("key", "backspace"),
        ("type_text", Secret(PASSWORD)),
    ]
    # 찾은 칸의 클릭 지점(이름표 상자 가운데 + offset = 칸 가운데)을 눌렀다
    clicked = [args[:2] for _, kind, args in scenario.inputs[1:] if kind == "click"]
    assert clicked == [ACCOUNT_FIELD, PASSWORD_FIELD, ACCOUNT_FIELD, PASSWORD_FIELD]
    assert login_values(scenario) == {"account": "qa_tester_01", "password": PASSWORD}
    assert ctx.captured == 4  # 칸 찾기마다 한 번


def test_type_text_without_clear_appends_to_existing_text(targets: Any, tmp_path: Path) -> None:
    """대조군: `clear` 없이 같은 칸에 다시 입력하면 덧붙는다 (clear 검사가 공짜로 통과하지 않게)."""
    targets.login(tmp_path)
    ctx, scenario = scene_ctx()
    click(ctx, point=START)
    password = load_target(tmp_path / targets.PASSWORD)
    type_text(ctx, text="old-password", target=password)
    type_text(ctx, text="new", target=password)
    assert login_values(scenario)["password"] == "old-passwordnew"


def test_type_text_target_missing_is_error(targets: Any, tmp_path: Path) -> None:
    targets.login(tmp_path)
    ctx, _ = scene_ctx()  # 타이틀 화면: 로그인 칸이 없다
    before = list(ctx.input.calls)
    with pytest.raises(LookupError, match="account_field"):
        type_text(ctx, text="abc", target=load_target(tmp_path / targets.ACCOUNT), clear=True)
    assert ctx.input.calls == before  # 아무것도 누르지 않았다


# ---------------------------------------------------------------- 실행기 (공용 입력 서비스)


def run_scene(tmp_path: Path, graph: Any, targets: Any) -> tuple[RunResult, ScenePlatform]:
    """예제 게임 장면 표 + 실제 매칭 엔진(프레임 저장소)으로 그래프를 실행기에서 돌린다."""
    ws = make_workspace(tmp_path / "ws")
    targets.login(ws.root)
    graph.write(ws, "tests/t.graph.json")
    program = load_program(
        ws, "tests/t.graph.json", secrets=MemorySecrets({"accounts.pw": PASSWORD})
    )
    store = FrameStore()
    platform = ScenePlatform(
        FakeScenario.load(SCENARIO), decode=decode_image, engines=RunEngines(store)
    )
    result = Executor(
        registry_with_testkit(),
        platform=platform,
        clock=FakeClock(),
        artifacts=MemoryArtifacts(),
        frames=store,
    ).run(program, ExecOptions(run_id="r1"))
    return result, platform


def login_graph(targets: Any) -> Any:
    return (
        tk()
        .entry("n_launch")
        .node(
            "n_launch",
            "core.app.launch",
            inputs={"path": "game.exe", "window_title": "SampleRPG"},
            next={"attached": "n_start"},
        )
        .node("n_start", "core.input.click", inputs={"point": [512, 412]}, next={"done": "n_acc"})
        .node(
            "n_acc",
            "core.input.type_text",
            inputs={"target": target(targets.ACCOUNT), "text": "qa_tester_01", "clear": True},
            next={"done": "n_pw"},
        )
        .node(
            "n_pw",
            "core.input.type_text",
            inputs={"target": target(targets.PASSWORD), "text": secret("accounts.pw")},
            next={"done": "n_enter"},
        )
        .node("n_enter", "core.input.key", inputs={"keys": "enter"}, next={"done": "n_ok"})
        .node(
            "n_ok",
            "core.assert.compare",
            inputs={"a": 1, "op": "==", "b": 1},
            next={"ok": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


def test_login_form_through_input_service(tmp_path: Path, targets: Any) -> None:
    result, platform = run_scene(tmp_path, login_graph(targets), targets)
    assert result.verdict == "pass", result.reason
    game = platform.scenario.latest()
    assert game.state.scene == "lobby"
    hwnd = game.window.handle
    # Match는 서비스가 클릭 지점으로 줄였다 (칸 가운데)
    assert clicks(platform) == [(hwnd, 512, 412), (hwnd, *ACCOUNT_FIELD), (hwnd, *PASSWORD_FIELD)]
    assert [args for _, args in kinds(platform, "key")] == [
        ("ctrl+a",),
        ("backspace",),
        ("enter",),
    ]
    # 비밀값 원문은 게임에만 닿고 실행 기록에는 없다
    assert [args for _, args in kinds(platform, "text")] == [("qa_tester_01",), (PASSWORD,)]
    assert PASSWORD not in json.dumps(result.events, ensure_ascii=False)


@pytest.mark.parametrize(
    ("old", "clear", "expected"),
    [
        ("x", True, "replacement"),
        ("old-password", True, "replacement"),
        (PASSWORD + "-" + PASSWORD, True, "replacement"),  # 칸이 가득 찬 뒤에도
        ("old-password", False, "old-passwordreplacement"),
    ],
)
def test_clear_replaces_existing_text_through_input_service(
    tmp_path: Path, targets: Any, old: str, clear: bool, expected: str
) -> None:
    """검수 반례: 공용 입력 서비스를 거친 `clear`가 여러 글자가 남은 칸을 전부 지운다."""
    g = (
        tk()
        .entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_start"}
        )
        .node("n_start", "core.input.click", inputs={"point": [512, 412]}, next={"done": "n_old"})
        .node(
            "n_old",
            "core.input.type_text",
            inputs={"target": target(targets.PASSWORD), "text": old},
            next={"done": "n_again"},
        )
        .node(
            "n_again",
            "core.input.type_text",
            inputs={"target": target(targets.PASSWORD), "text": "replacement", "clear": clear},
            next={"done": "n_ok"},
        )
        .node(
            "n_ok",
            "core.assert.compare",
            inputs={"a": 1, "op": "==", "b": 1},
            next={"ok": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    result, platform = run_scene(tmp_path, g, targets)
    assert result.verdict == "pass", result.reason
    values = platform.scenario.latest().state.forms["login"]["values"]
    assert values["password"] == expected[:24]  # 칸 최대 글자 수


def test_drag_and_scroll_through_input_service(tmp_path: Path, targets: Any) -> None:
    g = (
        tk()
        .entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_drag"}
        )
        .node(
            "n_drag",
            "core.input.drag",
            inputs={"start": [10, 20], "end": [300, 40], "duration_ms": 0},
            next={"done": "n_wheel"},
        )
        .node(
            "n_wheel",
            "core.input.scroll",
            inputs={"point": [50, 60], "amount": 3},
            next={"done": "n_ok"},
        )
        .node(
            "n_ok",
            "core.assert.compare",
            inputs={"a": 1, "op": "==", "b": 1},
            next={"ok": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    result, platform = run_scene(tmp_path, g, targets)
    assert result.verdict == "pass", result.reason
    (drag_args,) = [args for _, args in kinds(platform, "drag")]
    (scroll_args,) = [args for _, args in kinds(platform, "scroll")]
    assert [(p.x, p.y) for p in drag_args] == [(10, 20), (300, 40)]
    assert ((scroll_args[0].x, scroll_args[0].y), scroll_args[1]) == ((50, 60), 3)
