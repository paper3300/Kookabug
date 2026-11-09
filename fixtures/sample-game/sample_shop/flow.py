"""상점 상태 기계와 단추 배치 (클라이언트 1024x640 픽셀 고정).

- 갈래: `default`, `moved`(`--buy-moved`, 구매 단추가 오른쪽 아래로 — 같은 그림), `missing`
  (`--buy-missing`, 구매 단추 없음)
- 한 번 방문에 거래는 하나: 구매(골드 -100, 물약 +1) · 판매(낡은 칼, 골드 +50) · 치트(콘솔
  `give_gold 1000`, 골드 +1000). 거래 뒤 구매·판매·콘솔은 반응하지 않는다(상태 수를 작게)
- 콘솔: ` 키로 열고 한 줄 입력, Enter = 실행(맞는 명령이면 치트, 아니면 닫힘), Esc = 닫기
- 다이아 충전(기본 갈래): "결제" 확인 팝업 — 결제·취소 모두 상점으로 (금지 동작 검사용, 실제
  결제 없음 — 입력 기록에 `purchase_attempt`만)
- 닫기: 상점을 나간다 (`shop_closed`)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final, Literal

__all__ = [
    "BUTTONS",
    "CHEAT_COMMAND",
    "CONSOLE_FIELD",
    "CONSOLE_KEY",
    "CONSOLE_MAX",
    "LAYOUTS",
    "Rect",
    "Shop",
    "buttons_for",
]

type Rect = tuple[int, int, int, int]
type Layout = Literal["default", "moved", "missing"]

LAYOUTS: Final[tuple[Layout, ...]] = ("default", "moved", "missing")
GOLD_START: Final = 12345
POTION_PRICE: Final = 100
BLADE_PRICE: Final = 50
CHEAT_COMMAND: Final = "give_gold 1000"
CHEAT_GOLD: Final = 1000
CONSOLE_KEY: Final = "`"
CONSOLE_MAX: Final = 40
CONSOLE_FIELD: Final[Rect] = (24, 572, 976, 48)

BUTTONS: Final[dict[str, Rect]] = {
    "buy": (120, 452, 180, 60),
    "buy_moved": (700, 556, 180, 60),
    "sell": (360, 452, 180, 60),
    "close": (40, 560, 140, 52),
    "charge": (820, 28, 164, 48),
    "pay": (352, 372, 140, 52),
    "cancel": (532, 372, 140, 52),
}


@dataclass(frozen=True, slots=True)
class Shop:
    layout: Layout = "default"
    gold: int = GOLD_START
    potions: int = 0
    blade: bool = True
    done: Literal["bought", "sold", "cheat"] | None = None
    overlay: Literal["console", "confirm"] | None = None
    closed: bool = False
    command: str = ""
    """콘솔 입력 칸 (장면 이름에는 들지 않는다 — 헤드리스 표는 `forms`로 따라간다)."""

    @property
    def scene(self) -> str:
        if self.closed:
            return "shop_closed"
        if self.overlay == "console":
            return "console"
        if self.overlay == "confirm":
            return "shop_purchase_confirm"
        if self.done == "cheat":
            return "shop_rich"
        prefix = {"default": "shop", "moved": "shop_moved", "missing": "shop_missing"}[self.layout]
        return prefix if self.done is None else f"{prefix}_{self.done}"

    def press(self, button: str) -> Shop:
        """그 단추를 눌렀다 (지금 보이는 단추만 반응)."""
        if button not in buttons_for(self):
            return self
        if button in ("buy", "buy_moved"):
            return replace(
                self, gold=self.gold - POTION_PRICE, potions=self.potions + 1, done="bought"
            )
        if button == "sell":
            return replace(self, gold=self.gold + BLADE_PRICE, blade=False, done="sold")
        if button == "close":
            return replace(self, closed=True)
        if button == "charge":
            return replace(self, overlay="confirm")
        if button in ("pay", "cancel"):
            return replace(self, overlay=None)
        return self

    def key(self, name: str) -> Shop:
        if self.closed:
            return self
        if self.overlay == "console":
            if name == "enter":
                if self.command == CHEAT_COMMAND:
                    return replace(
                        self, gold=self.gold + CHEAT_GOLD, done="cheat", overlay=None, command=""
                    )
                return replace(self, overlay=None, command="")
            if name == "esc":
                return replace(self, overlay=None, command="")
            if name == "backspace":
                return replace(self, command=self.command[:-1])
            return self
        if (
            name == CONSOLE_KEY
            and self.overlay is None
            and self.layout == "default"
            and self.done is None
        ):
            return replace(self, overlay="console", command="")
        return self

    def type(self, text: str) -> Shop:
        if self.overlay != "console":
            return self
        command = self.command
        for ch in text:
            if ch.isprintable() and len(command) < CONSOLE_MAX:
                command += ch
        return replace(self, command=command)


def buttons_for(shop: Shop) -> list[str]:
    """지금 화면에서 누를 수 있는 단추 (그려진 단추 중 반응하는 것)."""
    if shop.closed or shop.overlay == "console":
        return []
    if shop.overlay == "confirm":
        return ["pay", "cancel"]
    out = ["close"]
    if shop.done is None:
        if shop.layout == "default":
            out += ["buy", "charge"]
        elif shop.layout == "moved":
            out.append("buy_moved")
        out.append("sell")
    return out


def keys_for(shop: Shop) -> list[str]:
    """그 화면에서 상태를 바꾸는 키 (콘솔 칸 조작 키 제외)."""
    if shop.overlay == "console":
        return ["enter", "esc"]
    if shop.layout == "default" and shop.done is None and shop.overlay is None and not shop.closed:
        return [CONSOLE_KEY]
    return []
