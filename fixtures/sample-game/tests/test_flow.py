"""상태 기계 단위 검사 (창 없음)."""

from __future__ import annotations

import pytest

from sample_game import BASE_SIZE, DEFAULT_ACCOUNT, DEFAULT_PASSWORD
from sample_game.flow import CANONICAL_STEPS, Game, GameConfig, Scene, scene_state
from sample_game.layout import BUTTONS, Viewport, hit


def login(game: Game, account: str = DEFAULT_ACCOUNT, password: str = DEFAULT_PASSWORD) -> None:
    game.press("account_field")
    game.text(account)
    game.key("tab")
    game.text(password)
    game.press("login")


def to_lobby(game: Game) -> None:
    game.press("start")
    login(game)
    assert game.scene is Scene.LOBBY


def finish_loading(game: Game) -> None:
    assert game.timer is not None
    game.fire(game.timer.token)


def test_title_to_world_happy_path() -> None:
    game = Game()
    assert game.scene is Scene.TITLE
    game.press("start")
    assert game.scene is Scene.LOGIN
    login(game)
    assert game.scene is Scene.LOBBY
    game.press("enter_world")  # 서버를 고르기 전에는 입장하지 않는다
    assert game.scene is Scene.LOBBY
    game.press("server_1")
    assert (game.scene, game.server) == (Scene.LOBBY_SERVER1, 1)
    game.press("enter_world")
    assert game.scene is Scene.LOADING
    finish_loading(game)
    assert game.scene is Scene.WORLD
    assert game.config.gold == 12345


def test_maintenance_popup_first() -> None:
    game = Game(GameConfig(maintenance=True))
    game.press("start")
    assert game.scene is Scene.MAINTENANCE
    # 팝업이 떠 있으면 아래 화면 버튼은 눌리지 않는다
    game.press("start")
    assert game.scene is Scene.MAINTENANCE
    game.press("maintenance_ok")
    assert game.scene is Scene.TITLE
    game.press("start")
    assert game.scene is Scene.MAINTENANCE
    game.key("enter")
    assert game.scene is Scene.TITLE


def test_login_fail_shows_error_popup() -> None:
    game = Game(GameConfig(login_fail=True))
    game.press("start")
    login(game)
    assert game.scene is Scene.LOGIN_ERROR
    # 계정은 남고 비밀번호는 비운다
    assert (game.account, game.password, game.focus) == (DEFAULT_ACCOUNT, "", "password")
    game.press("error_ok")
    assert game.scene is Scene.LOGIN
    game.text(DEFAULT_PASSWORD)
    game.key("enter")
    assert game.scene is Scene.LOGIN_ERROR  # 옵션이 켜져 있으면 맞는 값이어도 실패
    game.key("esc")
    assert game.scene is Scene.LOGIN


def test_wrong_password_fails_even_without_option() -> None:
    game = Game()
    game.press("start")
    login(game, password="wrong")
    assert game.scene is Scene.LOGIN_ERROR
    game.key("enter")
    game.press("password_field")
    game.text(DEFAULT_PASSWORD)
    game.press("login")
    assert game.scene is Scene.LOBBY


def test_wrong_account_and_text_editing() -> None:
    game = Game(GameConfig(account="user", password="pw"))
    game.press("start")
    game.text("usex")
    game.key("backspace")
    game.text("r")
    game.key("tab")
    game.text("pw\t\n")  # 제어 문자는 들어가지 않는다
    assert (game.account, game.password) == ("user", "pw")
    game.key("enter")
    assert game.scene is Scene.LOBBY


def test_select_all_clears_or_replaces_field() -> None:
    game = Game(GameConfig(account="user", password="pw"))
    game.press("start")
    game.text("old-name")
    game.key("ctrl+a")
    assert game.selected and game.account == "old-name"  # 고르기만 하고 지우지 않는다
    game.key("backspace")
    assert (game.account, game.selected) == ("", False)
    game.text("old")
    game.key("ctrl+a")
    game.text("user")  # 골라 둔 칸은 갈아 끼운다
    assert game.account == "user"
    game.text("x")  # 고르기는 한 번만: 다음 글자는 붙는다
    game.key("backspace")
    game.key("tab")
    game.text("pw")
    game.key("ctrl+a")
    game.press("password_field")  # 칸 클릭은 고르기를 푼다
    game.key("backspace")
    assert (game.account, game.password) == ("user", "p")
    game.text("w")
    game.key("enter")
    assert game.scene is Scene.LOBBY and not game.selected
    game.key("ctrl+a")  # 로그인 화면 밖에서는 아무 일도 없다
    assert not game.selected


def test_inventory_toggles_with_i_and_esc() -> None:
    game = Game()
    to_lobby(game)
    game.press("server_2")
    game.press("enter_world")
    finish_loading(game)
    game.key("i")
    assert game.scene is Scene.INVENTORY
    game.key("i")
    assert game.scene is Scene.WORLD
    game.key("i")
    game.key("esc")
    assert game.scene is Scene.WORLD
    game.key("esc")  # 월드에서 Esc는 아무 일도 없다
    assert game.scene is Scene.WORLD


def test_slow_loading_holds_loading_screen() -> None:
    game = Game(GameConfig(loading_ms=5000))
    to_lobby(game)
    game.press("server_1")
    game.press("enter_world")
    assert game.scene is Scene.LOADING
    assert game.timer is not None and game.timer.ms == 5000
    stale = game.timer.token - 1
    game.fire(stale)  # 옛 타이머는 무시
    assert game.scene is Scene.LOADING
    game.key("i")
    assert game.scene is Scene.LOADING
    finish_loading(game)
    assert game.scene is Scene.WORLD
    assert game.timer is None


@pytest.mark.parametrize("scene", list(Scene))
def test_canonical_state_reaches_scene(scene: Scene) -> None:
    assert scene in CANONICAL_STEPS
    assert scene_state(scene).scene is scene


def test_click_hits_scaled_buttons() -> None:
    # 기준 크기의 두 배 너비: 비율을 지키고 가운데 놓인다
    viewport = Viewport(BASE_SIZE[0] * 2, BASE_SIZE[1])
    x, y, w, h = viewport.rect(BUTTONS[Scene.TITLE][0].rect)
    assert x > BUTTONS[Scene.TITLE][0].rect[0]
    assert hit(Scene.TITLE, viewport, x + w // 2, y + h // 2) == "start"
    assert hit(Scene.TITLE, viewport, x - 1, y) is None
    big = Viewport(BASE_SIZE[0] * 2, BASE_SIZE[1] * 2)
    assert big.rect((10, 20, 30, 40)) == (20, 40, 60, 80)


def test_seed_changes_gold() -> None:
    assert GameConfig(seed=0).gold == 12345
    assert GameConfig(seed=7).gold == GameConfig(seed=7).gold != 12345
