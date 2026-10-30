"""화면 상태 기계. 창·시간과 무관한 순수 코드라 단위 테스트와 장면 표 생성이 같은 규칙을 쓴다.

입력은 세 가지다: 버튼 누름(`press`, 클릭 좌표는 `layout`이 버튼으로 바꾼다), 이름 붙은 키(`key`),
글자(`text`). 시간은 `timer`(지금 걸린 타이머)와 `fire`(그 타이머가 끝남)로만 흐른다.

로그인 칸은 보통 입력 칸처럼 `ctrl+a`로 지금 칸 글자를 전부 고른다(`selected`). 고른 채로
`backspace`는 칸을 비우고, 글자는 칸을 갈아 끼운다. 버튼 누름·다른 처리되는 키는 고르기를
푼다. 고르기는 화면에 그리지 않는다(화면 PNG는 그대로).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Final

from sample_game import DEFAULT_ACCOUNT, DEFAULT_LOADING_MS, DEFAULT_PASSWORD

__all__ = [
    "CANONICAL_STEPS",
    "FIELD_MAX",
    "FORM_FIELDS",
    "SELECT_ALL_KEY",
    "Game",
    "GameConfig",
    "Scene",
    "Timer",
    "apply",
    "keys_for",
    "scene_state",
]

FIELD_MAX: Final = 24
# 로그인 칸 (Tab 순서). `Game`의 같은 이름 속성에 값이 있고, 버튼 ID는 `<이름>_field`
FORM_FIELDS: Final = ("account", "password")
# 지금 칸 글자를 전부 고르는 키 (창 껍데기가 Ctrl을 누른 채 A를 이 이름으로 넘긴다)
SELECT_ALL_KEY: Final = "ctrl+a"


class Scene(StrEnum):
    """화면에 보이는 장면. 헤드리스 화면 PNG 하나가 장면 하나다."""

    TITLE = "title"
    MAINTENANCE = "maintenance"
    LOGIN = "login"
    LOGIN_ERROR = "login_error"
    LOBBY = "lobby"
    LOBBY_SERVER1 = "lobby_server1"
    LOBBY_SERVER2 = "lobby_server2"
    LOADING = "loading"
    WORLD = "world"
    INVENTORY = "inventory"


@dataclass(frozen=True, slots=True)
class GameConfig:
    maintenance: bool = False
    login_fail: bool = False
    loading_ms: int = DEFAULT_LOADING_MS
    account: str = DEFAULT_ACCOUNT
    password: str = DEFAULT_PASSWORD
    seed: int = 0

    @property
    def gold(self) -> int:
        return 12345 if self.seed == 0 else random.Random(self.seed).randrange(1000, 100000)


@dataclass(frozen=True, slots=True)
class Timer:
    name: str
    ms: int
    token: int


@dataclass(slots=True)
class Game:
    config: GameConfig = field(default_factory=GameConfig)
    screen: str = "title"  # title | login | lobby | loading | world
    popup: str | None = None  # maintenance | login_error | inventory
    account: str = ""
    password: str = ""
    focus: str = "account"  # account | password
    selected: bool = False  # 지금 칸 글자를 전부 골랐다 (ctrl+a)
    server: int | None = None
    timer: Timer | None = None
    _tokens: int = 0

    @property
    def scene(self) -> Scene:
        if self.popup == "maintenance":
            return Scene.MAINTENANCE
        if self.popup == "login_error":
            return Scene.LOGIN_ERROR
        if self.popup == "inventory":
            return Scene.INVENTORY
        if self.screen == "lobby" and self.server is not None:
            return Scene(f"lobby_server{self.server}")
        return Scene(self.screen)

    # ------------------------------------------------------------ 입력

    def press(self, button: str) -> None:
        """버튼 누름. 지금 장면에 없는 버튼이면 아무 일도 없다."""
        handler = _BUTTONS.get((self.scene, button))
        if handler is not None:
            self.selected = False
            handler(self)

    def key(self, name: str) -> None:
        handler = _KEYS.get((self.scene, name))
        if handler is not None:
            handler(self)
            if name != SELECT_ALL_KEY:
                self.selected = False

    def text(self, chars: str) -> None:
        """글자 입력. 로그인 화면(팝업 없음)의 지금 칸에만 들어간다. 골라 둔 칸은 갈아 끼운다."""
        if self.scene is not Scene.LOGIN:
            return
        for ch in chars:
            if not ch.isprintable():
                continue
            if self.selected:
                setattr(self, self.focus, "")
                self.selected = False
            value = getattr(self, self.focus)
            if len(value) < FIELD_MAX:
                setattr(self, self.focus, value + ch)

    def fire(self, token: int) -> None:
        """타이머 끝. 이미 바뀐(옛) 타이머면 무시한다."""
        if self.timer is None or self.timer.token != token:
            return
        name, self.timer = self.timer.name, None
        if name == "loading_done" and self.screen == "loading":
            self.screen = "world"

    # ------------------------------------------------------------ 동작

    def _start(self) -> None:
        if self.config.maintenance:
            self.popup = "maintenance"
        else:
            # 로그인 화면에 새로 들어오면 칸은 비고 계정 칸부터
            self.screen, self.account, self.password = "login", "", ""
            self.focus = FORM_FIELDS[0]

    def _close_popup(self) -> None:
        self.popup = None

    def _focus(self, name: str) -> None:
        self.focus = name

    def _next_field(self) -> None:
        self.focus = FORM_FIELDS[(FORM_FIELDS.index(self.focus) + 1) % len(FORM_FIELDS)]

    def _backspace(self) -> None:
        value = getattr(self, self.focus)
        setattr(self, self.focus, "" if self.selected else value[:-1])

    def _select_all(self) -> None:
        self.selected = True

    def _login(self) -> None:
        ok = (
            not self.config.login_fail
            and self.account == self.config.account
            and self.password == self.config.password
        )
        if ok:
            self.screen, self.server = "lobby", None
        else:
            # 실패하면 비밀번호를 비우고 그 칸으로 간다 (계정은 그대로)
            self.popup, self.password, self.focus = "login_error", "", "password"

    def _select_server(self, number: int) -> None:
        self.server = number

    def _enter_world(self) -> None:
        if self.server is None:
            return
        self.screen = "loading"
        self._tokens += 1
        self.timer = Timer("loading_done", self.config.loading_ms, self._tokens)

    def _open_inventory(self) -> None:
        self.popup = "inventory"


type _Handler = Callable[[Game], None]

_LOBBY_SCENES: Final = (Scene.LOBBY, Scene.LOBBY_SERVER1, Scene.LOBBY_SERVER2)

_BUTTONS: Final[dict[tuple[Scene, str], _Handler]] = {
    (Scene.TITLE, "start"): Game._start,
    (Scene.MAINTENANCE, "maintenance_ok"): Game._close_popup,
    (Scene.LOGIN, "account_field"): lambda g: g._focus("account"),
    (Scene.LOGIN, "password_field"): lambda g: g._focus("password"),
    (Scene.LOGIN, "login"): Game._login,
    (Scene.LOGIN_ERROR, "error_ok"): Game._close_popup,
}
for _scene in _LOBBY_SCENES:
    _BUTTONS[_scene, "server_1"] = lambda g: g._select_server(1)
    _BUTTONS[_scene, "server_2"] = lambda g: g._select_server(2)
    _BUTTONS[_scene, "enter_world"] = Game._enter_world

# 키 이름은 kookabug 키 이름표와 같다 (소문자, `enter`·`esc`·`tab`·`backspace`)
_KEYS: Final[dict[tuple[Scene, str], _Handler]] = {
    (Scene.MAINTENANCE, "enter"): Game._close_popup,
    (Scene.LOGIN, "tab"): Game._next_field,
    (Scene.LOGIN, "backspace"): Game._backspace,
    (Scene.LOGIN, SELECT_ALL_KEY): Game._select_all,
    (Scene.LOGIN, "enter"): Game._login,
    (Scene.LOGIN_ERROR, "enter"): Game._close_popup,
    (Scene.LOGIN_ERROR, "esc"): Game._close_popup,
    (Scene.WORLD, "i"): Game._open_inventory,
    (Scene.INVENTORY, "i"): Game._close_popup,
    (Scene.INVENTORY, "esc"): Game._close_popup,
}


def keys_for(scene: Scene) -> list[str]:
    """그 장면에서 뜻이 있는 키 이름 (장면 표 생성용)."""
    return sorted(name for s, name in _KEYS if s is scene)


# ---------------------------------------------------------------- 장면별 대표 상태

type _Step = tuple[str, str]  # (press|key|text|fire, 값)

_LOGIN_OK: Final[tuple[_Step, ...]] = (
    ("press", "start"),
    ("text", "{account}"),
    ("key", "tab"),
    ("text", "{password}"),
    ("press", "login"),
)

# 장면마다 시작 상태에서 그 장면까지 가는 순서. 화면 PNG(`--start-scene`)가 이 상태를 그린다
CANONICAL_STEPS: Final[dict[Scene, tuple[_Step, ...]]] = {
    Scene.TITLE: (),
    Scene.MAINTENANCE: (("press", "start"),),
    Scene.LOGIN: (("press", "start"),),
    Scene.LOGIN_ERROR: _LOGIN_OK,
    Scene.LOBBY: _LOGIN_OK,
    Scene.LOBBY_SERVER1: (*_LOGIN_OK, ("press", "server_1")),
    Scene.LOBBY_SERVER2: (*_LOGIN_OK, ("press", "server_2")),
    Scene.LOADING: (*_LOGIN_OK, ("press", "server_1"), ("press", "enter_world")),
    Scene.WORLD: (*_LOGIN_OK, ("press", "server_1"), ("press", "enter_world"), ("fire", "")),
    Scene.INVENTORY: (
        *_LOGIN_OK,
        ("press", "server_1"),
        ("press", "enter_world"),
        ("fire", ""),
        ("key", "i"),
    ),
}


def apply(game: Game, step: _Step) -> None:
    kind, value = step
    if kind == "press":
        game.press(value)
    elif kind == "key":
        game.key(value)
    elif kind == "text":
        game.text(value.format(account=game.config.account, password=game.config.password))
    elif kind == "fire":
        if game.timer is not None:
            game.fire(game.timer.token)
    else:
        raise ValueError(f"모르는 단계: {kind}")


def scene_state(scene: Scene, config: GameConfig | None = None) -> Game:
    """그 장면의 대표 상태. 장면에 필요한 실행 옵션(점검·로그인 실패)은 여기서 켠다."""
    base = config or GameConfig()
    game = Game(
        replace(
            base,
            maintenance=scene is Scene.MAINTENANCE,
            login_fail=scene is Scene.LOGIN_ERROR,
        )
    )
    for step in CANONICAL_STEPS[scene]:
        apply(game, step)
    if game.scene is not scene:
        raise AssertionError(f"{scene} 대표 상태를 만들지 못했다 (도착: {game.scene})")
    return game
