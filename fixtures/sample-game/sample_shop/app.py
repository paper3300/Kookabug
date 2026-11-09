"""상점 창: 상태 기계 + 그 상태의 PNG(`render.render`)를 Canvas 하나에 그대로 보인다.

클릭은 왼쪽 버튼을 **뗄 때** 그 자리의 단추로 판정한다 (예제 게임과 같다). 키: ` 콘솔 열기,
콘솔에서 글자·Backspace·Enter·Esc. Per-Monitor V2 DPI 인식으로 띄워 클라이언트 1024x640 픽셀이
PNG와 1:1이다.

`--event-log FILE`: 한 줄 JSON(`seq`·`ms`·`event`) — `ready`, `screen{scene, gold, potions}`,
`mouse_up{x, y}`, `key{key}`, `char{text}`, `purchase_attempt`(다이아 충전 팝업의 결제 단추 — 실제
결제 없음), `exit`.
"""

from __future__ import annotations

import base64
import contextlib
import ctypes
import json
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from sample_shop import CLIENT_SIZE, TITLE
from sample_shop.flow import BUTTONS, CONSOLE_KEY, Shop, buttons_for
from sample_shop.render import render

__all__ = ["Options", "run"]

_KEYSYMS = {
    "grave": CONSOLE_KEY,
    "Return": "enter",
    "Escape": "esc",
    "BackSpace": "backspace",
}


@dataclass(frozen=True, slots=True)
class Options:
    layout: str = "default"
    title: str = TITLE
    event_log: Path | None = None


class _App:
    def __init__(self, options: Options) -> None:
        self.state = Shop(layout=options.layout)  # type: ignore[arg-type]
        self.started = time.monotonic()
        self.seq = 0
        self.log: TextIO | None = (
            options.event_log.open("a", encoding="utf-8") if options.event_log else None
        )
        self.root = tk.Tk()
        self.root.title(options.title)
        self.root.resizable(False, False)
        w, h = CLIENT_SIZE
        self.canvas = tk.Canvas(self.root, width=w, height=h, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.image: tk.PhotoImage | None = None
        self.canvas.bind("<ButtonRelease-1>", self._up)
        self.root.bind("<Key>", self._key)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self._draw()
        self.emit("ready", title=options.title, client_size=[w, h])

    def emit(self, event: str, **fields: Any) -> None:
        if self.log is None:
            return
        self.seq += 1
        ms = round((time.monotonic() - self.started) * 1000)
        line = {"seq": self.seq, "ms": ms, "event": event, **fields}
        self.log.write(json.dumps(line, ensure_ascii=False) + "\n")
        self.log.flush()

    def _draw(self) -> None:
        data = base64.b64encode(render(self.state)).decode("ascii")
        self.image = tk.PhotoImage(data=data, format="png")
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.image, anchor="nw")
        self.emit(
            "screen", scene=self.state.scene, gold=self.state.gold, potions=self.state.potions
        )

    def _set(self, state: Shop) -> None:
        if state != self.state:
            changed = state.scene != self.state.scene or state.command != self.state.command
            self.state = state
            if changed:
                self._draw()

    def _up(self, event: tk.Event[Any]) -> None:
        x, y = int(event.x), int(event.y)
        self.emit("mouse_up", button="left", x=x, y=y)
        for button in buttons_for(self.state):
            bx, by, bw, bh = BUTTONS[button]
            if bx <= x < bx + bw and by <= y < by + bh:
                if button == "pay":
                    self.emit("purchase_attempt")
                self._set(self.state.press(button))
                return

    def _key(self, event: tk.Event[Any]) -> None:
        name = _KEYSYMS.get(str(event.keysym))
        if name is not None:
            self.emit("key", key=name)
            self._set(self.state.key(name))
            return
        char = str(event.char)
        if char and char.isprintable():
            self.emit("char", text=char)
            self._set(self.state.type(char))

    def _quit(self) -> None:
        self.emit("exit")
        if self.log is not None:
            self.log.close()
        self.root.destroy()


def run(options: Options) -> int:
    with contextlib.suppress(AttributeError, OSError):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    app = _App(options)
    app.root.mainloop()
    return 0
