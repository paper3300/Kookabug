"""헤드리스 장면 전이 표(`frames/scenario.json`)가 게임 코드와 맞는가."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

import pytest

from kookabug_core.canonical import is_canonical
from sample_game import BASE_SIZE, DEFAULT_ACCOUNT, DEFAULT_PASSWORD
from sample_game.flow import FIELD_MAX, FORM_FIELDS, Game, GameConfig, Scene
from sample_game.layout import BUTTONS, Viewport, hit
from sample_game.scenario import FORM, FORMAT, LOADING_FRAMES, Simulator, generate

FRAMES = Path(__file__).resolve().parents[1] / "frames"
SCENARIO = FRAMES / "scenario.json"
VIEWPORT = Viewport(*BASE_SIZE)
# 갈래별 실행 인수와 그 갈래의 게임 설정
VARIANT_RUNS = {
    "default": ([], GameConfig()),
    "login_fail": (["--login-fail"], GameConfig(login_fail=True)),
    "maintenance": (["--maintenance", "--login-fail"], GameConfig(maintenance=True)),
}


def committed() -> dict[str, Any]:
    return json.loads(SCENARIO.read_text(encoding="utf-8"))


def center(scene: str, button_id: str) -> tuple[int, int]:
    button = next(b for b in BUTTONS[Scene(scene)] if b.id == button_id)
    x, y, w, h = VIEWPORT.rect(button.rect)
    return x + w // 2, y + h // 2


def click(sim: Simulator, button_id: str) -> None:
    sim.click(*center(sim.scene, button_id))


def type_login(sim: Simulator, account: str, password: str) -> None:
    click(sim, "account_field")
    sim.text(account)
    sim.key("tab")
    sim.text(password)


def test_generated_scenario_matches_committed() -> None:
    assert committed() == generate(), "fixtures/sample-game/tools/gen_scenario.py로 다시 만든다"
    assert is_canonical(SCENARIO.read_text(encoding="utf-8"))
    data = committed()
    assert data["format"] == FORMAT
    assert set(data["scenes"]) == {s.value for s in Scene}
    for name, png in data["scenes"].items():
        assert (FRAMES / png).is_file(), f"{name}: {png} 없음 (tools/snap_frames.py)"


def test_committed_pngs_are_distinct() -> None:
    """장면마다 그림이 다르다 (한 장면을 다른 장면 이름으로 찍은 실수를 잡는다)."""
    seen: dict[str, str] = {}
    for scene in Scene:
        digest = hashlib.sha256((FRAMES / f"{scene.value}.png").read_bytes()).hexdigest()
        assert digest not in seen, f"{scene.value}와 {seen.get(digest)}가 같은 파일이다"
        seen[digest] = scene.value


def test_scenario_transitions_cover_happy_and_fail_paths() -> None:
    data = committed()
    seen: set[str] = set()

    happy = Simulator(data, ["-m", "sample_game"])
    assert happy.variant == "default"
    click(happy, "start")
    seen.add(happy.scene)
    type_login(happy, DEFAULT_ACCOUNT, DEFAULT_PASSWORD)
    for step in (
        lambda: click(happy, "login"),
        lambda: click(happy, "server_1"),
        lambda: click(happy, "enter_world"),
    ):
        step()
        seen.add(happy.scene)
    # 로딩은 정해진 캡처 수만큼 보인 뒤 월드
    shown = [happy.capture() for _ in range(LOADING_FRAMES + 1)]
    assert shown == ["loading"] * LOADING_FRAMES + ["world"]
    happy.key("i")
    seen |= {"world", happy.scene}
    assert happy.scene == "inventory"
    happy.key("esc")
    assert happy.scene == "world"

    fail = Simulator(data, ["-m", "sample_game", "--login-fail"])
    assert fail.variant == "login_fail"
    click(fail, "start")
    type_login(fail, DEFAULT_ACCOUNT, DEFAULT_PASSWORD)
    fail.key("enter")
    assert fail.scene == "login_error"
    seen.add(fail.scene)
    # 오류 뒤: 계정은 남고 비밀번호는 비고 비밀번호 칸
    assert fail.forms[FORM] == {
        "values": {"account": DEFAULT_ACCOUNT, "password": ""},
        "focus": "password",
        "selected": False,
    }
    click(fail, "error_ok")
    assert fail.scene == "login"

    maint = Simulator(data, ["--maintenance", "--login-fail"])
    assert maint.variant == "maintenance"
    click(maint, "start")
    assert maint.scene == "maintenance"
    seen.add(maint.scene)
    maint.key("enter")
    assert maint.scene == "title"

    lobby = Simulator(data, [])
    click(lobby, "start")
    type_login(lobby, DEFAULT_ACCOUNT, DEFAULT_PASSWORD)
    for button in ("login", "server_2"):
        click(lobby, button)
    seen |= {"title", "lobby", lobby.scene}
    assert lobby.scene == "lobby_server2"
    # 모든 장면에 갈 수 있다
    assert seen == {s.value for s in Scene}


@pytest.mark.parametrize(
    ("case", "steps"),
    [
        ("no_typing", []),
        ("password_only", [("text", DEFAULT_PASSWORD)]),
        ("swapped_fields", [("text", DEFAULT_PASSWORD), ("key", "tab"), ("text", DEFAULT_ACCOUNT)]),
        ("wrong_password", [("text", DEFAULT_ACCOUNT), ("key", "tab"), ("text", "nope")]),
        ("both_in_account", [("text", DEFAULT_ACCOUNT + DEFAULT_PASSWORD)]),
    ],
)
def test_login_without_correct_input_does_not_succeed(
    case: str, steps: list[tuple[str, str]]
) -> None:
    """검수 반례: 글자를 안 넣거나 칸이 틀리거나 값이 틀리면 표에서도 로그인이 실패한다."""
    sim = Simulator(committed(), [])
    game = Game()
    click(sim, "start")
    game.press("start")
    for kind, value in steps:
        getattr(sim, kind)(value)
        getattr(game, kind)(value)
    click(sim, "login")
    game.press("login")
    assert sim.scene == game.scene.value == "login_error", case


def test_select_all_then_erase_or_type_replaces_whole_field() -> None:
    """`select_key`(ctrl+a) 뒤 `erase_key`는 칸 전체를 지우고 글자는 칸을 갈아 끼운다."""
    sim, game = Simulator(committed(), []), Game()
    click(sim, "start")
    game.press("start")
    steps: list[tuple[str, str]] = [
        ("text", "old-account"),
        ("key", "ctrl+a"),
        ("key", "backspace"),
        ("text", DEFAULT_ACCOUNT),
        ("key", "tab"),
        ("text", "old-password"),
        ("key", "ctrl+a"),
        ("text", DEFAULT_PASSWORD),
    ]
    for kind, value in steps:
        getattr(sim, kind)(value)
        getattr(game, kind)(value)
        _check_same(sim, game, f"{kind} {value!r}")
    assert sim.forms[FORM]["values"] == {"account": DEFAULT_ACCOUNT, "password": DEFAULT_PASSWORD}
    # 고르기는 다음 칸으로 가면 풀린다: 그 뒤 backspace는 끝 글자 하나만
    for sm in (sim.key, game.key):
        sm("ctrl+a")
        sm("tab")
        sm("backspace")
    _check_same(sim, game, "tab 뒤 backspace")
    assert sim.forms[FORM]["values"]["account"] == DEFAULT_ACCOUNT[:-1]
    click(sim, "login")
    game.press("login")
    assert sim.scene == game.scene.value == "login_error"


def test_click_outside_buttons_does_nothing() -> None:
    sim = Simulator(committed(), [])
    sim.click(5, 5)
    assert sim.scene == "title"


def _random_steps(rng: random.Random, n: int) -> list[tuple[str, Any]]:
    texts = [DEFAULT_ACCOUNT, DEFAULT_PASSWORD, "x", "가나", "a" * (FIELD_MAX + 3), "\t", ""]
    keys = ["enter", "esc", "tab", "backspace", "i", "a", "ctrl+a", "ctrl+a"]
    steps: list[tuple[str, Any]] = []
    for _ in range(n):
        r = rng.random()
        if r < 0.45:
            steps.append(("click_button", rng.random()))  # 그 장면 버튼 중 하나 (실행 때 고름)
        elif r < 0.55:
            steps.append(
                ("click_point", (rng.randrange(BASE_SIZE[0]), rng.randrange(BASE_SIZE[1])))
            )
        elif r < 0.75:
            steps.append(("key", rng.choice(keys)))
        elif r < 0.95:
            steps.append(("text", rng.choice(texts)))
        else:
            steps.append(("wait", None))
    return steps


def _check_same(sim: Simulator, game: Game, where: str) -> None:
    assert sim.scene == game.scene.value, where
    if game.scene in (Scene.LOGIN, Scene.LOGIN_ERROR):
        values = {name: getattr(game, name) for name in FORM_FIELDS}
        state = {"values": values, "focus": game.focus, "selected": game.selected}
        assert sim.forms[FORM] == state, where


@pytest.mark.parametrize("variant", list(VARIANT_RUNS))
def test_scenario_simulator_matches_game_on_random_inputs(variant: str) -> None:
    """표의 기준 해석과 실제 상태 기계를 무작위 입력으로 대조한다 (장면·로그인 칸 상태)."""
    args, config = VARIANT_RUNS[variant]
    data = committed()
    rng = random.Random(f"kookabug-sample-game-{variant}")
    scenes: set[str] = set()
    for run in range(200):
        sim, game = Simulator(data, args), Game(config)
        # 정상 경로에 자주 닿게 반은 맞는 로그인으로 시작한다
        prefix: list[tuple[str, Any]] = []
        if run % 2:
            prefix = [
                ("click_button", "start"),
                ("text", DEFAULT_ACCOUNT),
                ("key", "tab"),
                ("text", DEFAULT_PASSWORD),
                ("click_button", "login"),
            ]
        for i, (kind, value) in enumerate([*prefix, *_random_steps(rng, 40)]):
            where = f"{variant} run {run} step {i} {kind} {value!r}"
            if kind in ("click_button", "click_point"):
                if kind == "click_button":
                    buttons = BUTTONS[game.scene]
                    if not buttons:
                        continue
                    if isinstance(value, str):
                        match = [b for b in buttons if b.id == value]
                        if not match:
                            continue
                        button = match[0]
                    else:
                        button = buttons[int(value * len(buttons))]
                    x, y, w, h = VIEWPORT.rect(button.rect)
                    point = (x + w // 2, y + h // 2)
                else:
                    point = value
                sim.click(*point)
                pressed = hit(game.scene, VIEWPORT, *point)
                if pressed is not None:
                    game.press(pressed)
            elif kind == "key":
                sim.key(value)
                game.key(value)
            elif kind == "text":
                sim.text(value)
                game.text(value)
            else:
                if game.timer is not None:
                    game.fire(game.timer.token)
                for _ in range(LOADING_FRAMES + 1):
                    sim.capture()
            _check_same(sim, game, where)
            scenes.add(game.scene.value)
    expected = {
        "default": {s.value for s in Scene} - {"maintenance"},
        "login_fail": {"title", "login", "login_error"},
        "maintenance": {"title", "maintenance"},
    }[variant]
    assert scenes == expected


@pytest.mark.parametrize("size", [BASE_SIZE, (800, 600), (1280, 720), (320, 200)])
def test_button_rects_inside_client(size: tuple[int, int]) -> None:
    viewport = Viewport(*size)
    for scene, buttons in BUTTONS.items():
        for button in buttons:
            x, y, w, h = viewport.rect(button.rect)
            assert w > 0 and h > 0, (scene, button.id)
            assert x >= 0 and x + w <= size[0], (scene, button.id, size)
            assert y >= 0 and y + h <= size[1], (scene, button.id, size)
    data = committed()
    rects = [t["on"]["rect"] for t in data["transitions"] if t.get("on", {}).get("kind") == "click"]
    rects += [f["rect"] for form in data["forms"].values() for f in form["fields"]]
    for x, y, w, h in rects:
        assert x >= 0 and x + w <= BASE_SIZE[0] and y >= 0 and y + h <= BASE_SIZE[1]
