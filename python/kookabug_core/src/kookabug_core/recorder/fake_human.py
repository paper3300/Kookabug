"""가짜 사람 (M4 계획 2.9 "가짜 원천", C18): 각본의 원시 입력을 가짜 게임 장면(`ScenarioState`)에
같은 시각에 적용한다. 실제 runner 입력 경로와 같은 장면 규칙(`forms`·`when.valid`)을 쓴다.

예제 게임과 같은 해석: 왼쪽 버튼은 **뗄 때** 클릭(누른 자리와 4 px 안), 키는 누를 때. 글자 키(수정
키 없음, Shift만)는 글자, Ctrl+A는 `ctrl+a`, 그 밖은 키 이름(`tab`·`enter`·`backspace`). 게임 창이
앞에 없거나(키) 점 아래 창이 게임이 아니면(마우스) 게임에 가지 않는다 — 각본의 관측 줄로 정한다.
우리 표식·다른 프로그램 입력도 게임에는 간다(녹화기가 거를 뿐이다).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from kookabug_core.engine.scenario import ScenarioState
from kookabug_core.recorder.keyboard import UsLayout, combo_name, is_modifier, vk_name

__all__ = ["FakeHuman"]

_CLICK_PX: Final = 4


class FakeHuman:
    """원시 입력 하나씩 `apply`. 화면 좌표는 그 순간의 클라이언트 원점으로 바꾼다."""

    def __init__(self, state: ScenarioState) -> None:
        self.state = state
        self.foreground = True
        """게임 창이 앞에 있다 (키가 게임에 간다)."""
        self.pointer_on_game = True
        """점 아래 창이 게임이다 (마우스가 게임에 간다)."""
        self._mods: set[str] = set()
        self._down: dict[str, tuple[int, int]] = {}
        self._layout = UsLayout()

    def apply(self, raw: Mapping[str, Any], origin: tuple[int, int]) -> bool:
        """입력 하나. 게임 상태가 바뀌었을 수 있으면 True (새 프레임을 낸다)."""
        kind = raw["kind"]
        if kind in ("mouse_down", "mouse_up"):
            point = (int(raw["x"]) - origin[0], int(raw["y"]) - origin[1])
            button = str(raw.get("button", "left"))
            if kind == "mouse_down":
                if self.pointer_on_game:
                    self._down[button] = point
                return False
            start = self._down.pop(button, None)
            if start is None or button != "left" or not self.pointer_on_game:
                return False
            if max(abs(point[0] - start[0]), abs(point[1] - start[1])) > _CLICK_PX:
                return False  # 끌기는 장면을 바꾸지 않는다
            self.state.click(*point)
            return True
        if kind not in ("key_down", "key_up"):
            return False
        vk = int(raw["vk"])
        if is_modifier(vk):
            name = vk_name(vk) or "shift"
            if kind == "key_down":
                self._mods.add(name)
            else:
                self._mods.discard(name)
            return False
        if kind == "key_up" or not self.foreground:
            return False
        name = vk_name(vk, bool(raw.get("extended", False)))
        if name is None:
            return False
        if self._mods - {"shift"}:
            self.state.key(combo_name(self._mods, name))
            return True
        ch = self._layout.char(vk, shift="shift" in self._mods, caps=False, hkl=None)
        if ch is not None:
            self.state.text(ch)
        else:
            self.state.key(name)
        return True
