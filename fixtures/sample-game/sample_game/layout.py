"""버튼 배치. 기준 크기(1024x640) 좌표로 적고, 실제 클라이언트 크기로는 `Viewport`가 바꾼다.

클릭 판정(`hit`)과 그리기(`render`)와 장면 표(`scenario`)가 모두 이 표를 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sample_game import BASE_SIZE
from sample_game.flow import Scene

__all__ = ["BUTTONS", "Button", "Rect", "Viewport", "buttons_for", "hit"]

type Rect = tuple[int, int, int, int]  # x, y, w, h


@dataclass(frozen=True, slots=True)
class Button:
    id: str
    rect: Rect  # 기준 좌표
    label: str


# 공통 위치
_POPUP_OK: Final = (442, 392, 140, 52)
_START: Final = Button("start", (412, 380, 200, 64), "게임 시작")
_ACCOUNT: Final = Button("account_field", (400, 205, 320, 50), "")
_PASSWORD: Final = Button("password_field", (400, 285, 320, 50), "")
_LOGIN: Final = Button("login", (432, 380, 160, 56), "로그인")
_SERVER_1: Final = Button("server_1", (262, 200, 500, 64), "Server 1")
_SERVER_2: Final = Button("server_2", (262, 280, 500, 64), "Server 2")
_ENTER: Final = Button("enter_world", (412, 420, 200, 60), "입장")
_LOBBY: Final = (_SERVER_1, _SERVER_2, _ENTER)

# 장면마다 눌리는 버튼. 팝업이 떠 있으면 팝업 버튼만 눌린다
BUTTONS: Final[dict[Scene, tuple[Button, ...]]] = {
    Scene.TITLE: (_START,),
    Scene.MAINTENANCE: (Button("maintenance_ok", _POPUP_OK, "확인"),),
    Scene.LOGIN: (_ACCOUNT, _PASSWORD, _LOGIN),
    Scene.LOGIN_ERROR: (Button("error_ok", _POPUP_OK, "확인"),),
    Scene.LOBBY: _LOBBY,
    Scene.LOBBY_SERVER1: _LOBBY,
    Scene.LOBBY_SERVER2: _LOBBY,
    Scene.LOADING: (),
    Scene.WORLD: (),
    Scene.INVENTORY: (),
}


def buttons_for(scene: Scene) -> tuple[Button, ...]:
    return BUTTONS[scene]


@dataclass(frozen=True, slots=True)
class Viewport:
    """기준 좌표 → 클라이언트 픽셀. 비율을 지켜 늘리고 가운데 둔다."""

    width: int
    height: int

    @property
    def scale(self) -> float:
        return min(self.width / BASE_SIZE[0], self.height / BASE_SIZE[1])

    @property
    def origin(self) -> tuple[float, float]:
        s = self.scale
        return (self.width - BASE_SIZE[0] * s) / 2, (self.height - BASE_SIZE[1] * s) / 2

    def x(self, value: float) -> float:
        return self.origin[0] + value * self.scale

    def y(self, value: float) -> float:
        return self.origin[1] + value * self.scale

    def px(self, value: float) -> float:
        """길이 (글자 크기·선 두께)."""
        return value * self.scale

    def rect(self, rect: Rect) -> Rect:
        """기준 사각형 → 클라이언트 정수 사각형 (모서리를 반올림)."""
        x, y, w, h = rect
        left, top = round(self.x(x)), round(self.y(y))
        right, bottom = round(self.x(x + w)), round(self.y(y + h))
        return left, top, right - left, bottom - top

    def to_base(self, cx: float, cy: float) -> tuple[float, float]:
        ox, oy = self.origin
        return (cx - ox) / self.scale, (cy - oy) / self.scale


def hit(scene: Scene, viewport: Viewport, cx: float, cy: float) -> str | None:
    """클라이언트 좌표의 클릭이 누른 버튼."""
    for button in BUTTONS[scene]:
        x, y, w, h = viewport.rect(button.rect)
        if x <= cx < x + w and y <= cy < y + h:
            return button.id
    return None
