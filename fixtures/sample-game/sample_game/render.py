"""장면 그리기. `Canvas` 하나에 평면 도형과 글자만 그린다 (애니메이션 없음, 같은 상태 = 같은 그림).

팝업도 같은 Canvas 안에 그린다 — 창 캡처에 찍혀야 하기 때문이다.
"""

from __future__ import annotations

import random
import tkinter as tk
from typing import Any, Final

from sample_game.flow import Game, Scene
from sample_game.layout import BUTTONS, Button, Rect, Viewport

__all__ = ["draw"]

BG: Final = "#1c2433"
PANEL: Final = "#2b3548"
PANEL_EDGE: Final = "#4a5875"
TEXT: Final = "#f2f4f8"
MUTED: Final = "#9aa6bd"
ACCENT: Final = "#f0a830"
ACCENT_TEXT: Final = "#1c2433"
FIELD: Final = "#11161f"
FOCUS: Final = "#5fb0ff"
ERROR: Final = "#ff6b6b"
SELECT: Final = "#36507a"
DIM: Final = "#0b0f16"
PRESSED: Final = "#3a7a3a"
"""`--press-feedback`의 눌린 단추 색 (어떤 단추 색과도 뚜렷이 다르게)."""

INVENTORY_ITEMS: Final = ("포션", "검", "방패", "Key", "지도", "Gem", "활", "빵")


class _Painter:
    def __init__(
        self, canvas: tk.Canvas, viewport: Viewport, font: str, pressed: str | None = None
    ) -> None:
        self.c = canvas
        self.v = viewport
        self.font = font
        self.pressed = pressed

    def _font(self, size: int, bold: bool = False) -> tuple[str, int] | tuple[str, int, str]:
        # 음수 = 픽셀 크기. 포인트로 주면 DPI에 따라 글자 크기가 바뀌어 화면 PNG가 어긋난다
        px = -max(1, round(self.v.px(size)))
        return (self.font, px, "bold") if bold else (self.font, px)

    def rect(self, rect: Rect, fill: str, outline: str = "", width: float = 0) -> None:
        x, y, w, h = self.v.rect(rect)
        self.c.create_rectangle(
            x,
            y,
            x + w,
            y + h,
            fill=fill,
            outline=outline,
            width=self.v.px(width) if outline else 0,
        )

    def oval(self, rect: Rect, fill: str, outline: str = "", width: float = 0) -> None:
        x, y, w, h = self.v.rect(rect)
        self.c.create_oval(
            x, y, x + w, y + h, fill=fill, outline=outline, width=self.v.px(width) if outline else 0
        )

    def text(
        self,
        x: float,
        y: float,
        text: str,
        size: int,
        *,
        fill: str = TEXT,
        bold: bool = False,
        anchor: Any = "center",
    ) -> None:
        self.c.create_text(
            round(self.v.x(x)),
            round(self.v.y(y)),
            text=text,
            font=self._font(size, bold),
            fill=fill,
            anchor=anchor,
        )

    def button(self, button: Button, *, primary: bool = True) -> None:
        fill, color = (ACCENT, ACCENT_TEXT) if primary else (PANEL, TEXT)
        if button.id == self.pressed:
            fill = PRESSED
        self.rect(button.rect, fill, PANEL_EDGE if not primary else "", 2)
        x, y, w, h = button.rect
        self.text(x + w / 2, y + h / 2, button.label, 24, fill=color, bold=True)

    def panel(self, rect: Rect, title: str) -> None:
        x, y, w, _h = rect
        self.rect(rect, PANEL, PANEL_EDGE, 3)
        self.rect((x, y, w, 56), PANEL_EDGE)
        self.text(x + w / 2, y + 28, title, 24, bold=True)


def draw(
    canvas: tk.Canvas, game: Game, size: tuple[int, int], font: str, pressed: str | None = None
) -> None:
    """`pressed`(검사 옵션 `--press-feedback`)면 그 id의 단추를 눌린 색으로 그린다."""
    canvas.delete("all")
    viewport = Viewport(*size)
    canvas.create_rectangle(0, 0, size[0], size[1], fill=BG, outline="")
    p = _Painter(canvas, viewport, font, pressed)
    scene = game.scene
    if scene in (Scene.TITLE, Scene.MAINTENANCE):
        _title(p)
    elif scene in (Scene.LOGIN, Scene.LOGIN_ERROR):
        _login(p, game)
    elif scene in (Scene.LOBBY, Scene.LOBBY_SERVER1, Scene.LOBBY_SERVER2):
        _lobby(p, game)
    elif scene is Scene.LOADING:
        _loading(p)
    else:
        _world(p, game)
    if scene is Scene.MAINTENANCE:
        _popup(p, "점검 안내", ("서버 점검 중입니다", "잠시 후 다시 접속해 주세요"), scene)
    elif scene is Scene.LOGIN_ERROR:
        _popup(p, "로그인 실패", ("계정 또는 비밀번호가", "올바르지 않습니다"), scene, ERROR)
    elif scene is Scene.INVENTORY:
        _inventory(p, game)


def _title(p: _Painter) -> None:
    p.oval((362, 70, 300, 300), "#24314a")
    p.text(512, 190, "SampleRPG", 64, bold=True)
    p.text(512, 262, "샘플 RPG · 연습용 예제 게임", 24, fill=MUTED)
    p.button(BUTTONS[Scene.TITLE][0])
    p.text(512, 600, "v0.1  Kookabug 예제", 16, fill=MUTED)


def _login(p: _Painter, game: Game) -> None:
    p.text(512, 120, "로그인", 40, bold=True)
    account, password, login = BUTTONS[Scene.LOGIN]
    for button, label, value, name in (
        (account, "계정", game.account, "account"),
        (password, "비밀번호", "●" * len(game.password), "password"),
    ):
        x, y, _w, h = button.rect
        p.text(x - 24, y + h / 2, label, 22, fill=MUTED, anchor="e")
        focused = game.focus == name and game.scene is Scene.LOGIN
        p.rect(button.rect, FIELD, FOCUS if focused else PANEL_EDGE, 2)
        p.text(x + 14, y + h / 2, value, 22, anchor="w")
    p.button(login)
    p.text(512, 590, "Tab: 다음 칸   Enter: 로그인", 16, fill=MUTED)


def _lobby(p: _Painter, game: Game) -> None:
    p.text(512, 120, "서버 선택", 40, bold=True)
    s1, s2, enter = BUTTONS[Scene.LOBBY]
    for number, button, state, color in ((1, s1, "원활", "#6bd68a"), (2, s2, "혼잡", ACCENT)):
        selected = game.server == number
        p.rect(button.rect, SELECT if selected else PANEL, FOCUS if selected else PANEL_EDGE, 2)
        x, y, w, h = button.rect
        p.text(x + 28, y + h / 2, button.label, 26, bold=True, anchor="w")
        p.text(x + w - 28, y + h / 2, state, 22, fill=color, anchor="e")
    p.button(enter)


def _loading(p: _Painter) -> None:
    p.text(512, 290, "불러오는 중...", 32, bold=True)
    p.rect((312, 350, 400, 20), FIELD, PANEL_EDGE, 2)
    p.rect((314, 352, 236, 16), FOCUS)


def _world(p: _Painter, game: Game) -> None:
    p.rect((0, 0, 1024, 640), "#2f5d3a")
    p.rect((0, 380, 1024, 90), "#a08458")
    for x, y in ((120, 120), (260, 230), (90, 500), (700, 520), (880, 300), (520, 160)):
        p.oval((x, y, 70, 70), "#1f4429")
    p.oval((492, 400, 40, 40), FOCUS, TEXT, 2)
    # 미니맵 (오른쪽 위)
    p.rect((824, 20, 180, 180), "#16201a", TEXT, 3)
    p.rect((824, 120, 180, 20), "#6e5c3e")
    p.oval((906, 124, 12, 12), FOCUS)
    p.text(914, 186, "MAP", 14, fill=MUTED)
    # 골드 (왼쪽 위)
    p.rect((20, 20, 240, 52), DIM, PANEL_EDGE, 2)
    p.oval((34, 32, 28, 28), ACCENT)
    p.text(76, 46, f"Gold {game.config.gold:,}", 24, bold=True, anchor="w")
    p.rect((362, 590, 300, 36), DIM)
    p.text(512, 608, "I: 인벤토리", 18, fill=MUTED)


def _popup(
    p: _Painter, title: str, lines: tuple[str, ...], scene: Scene, color: str = TEXT
) -> None:
    p.rect((0, 0, 1024, 640), DIM)
    p.panel((262, 170, 500, 300), title)
    for i, line in enumerate(lines):
        p.text(512, 280 + i * 40, line, 24, fill=color)
    p.button(BUTTONS[scene][0])


def _inventory(p: _Painter, game: Game) -> None:
    p.panel((212, 90, 600, 460), "인벤토리")
    items = list(INVENTORY_ITEMS)
    if game.config.seed:
        random.Random(game.config.seed).shuffle(items)
    for i in range(15):
        row, col = divmod(i, 5)
        x, y = 252 + col * 108, 170 + row * 108
        p.rect((x, y, 92, 92), FIELD, PANEL_EDGE, 2)
        if i < len(items):
            p.text(x + 46, y + 46, items[i], 20)
    p.text(512, 522, "I · Esc: 닫기", 18, fill=MUTED)
