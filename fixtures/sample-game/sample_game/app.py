"""창 껍데기: tkinter 창·입력 수신 기록·DPI 인식·보조 창.

입력 수신 기록(`--event-log`)은 JSONL이고 줄마다 바로 `flush`한다. 테스트는 이 기록을 "게임이
실제로 받았다"의 증거로 쓴다. 줄 공통 필드: `seq`(1부터), `ms`(시작 뒤 밀리초), `event`.

| event | 필드 |
|---|---|
| `ready` | `pid`, `hwnd`, `title`, `client_size`, `dpi`, `dpi_awareness`, `font`, `windows`, |
| | `recreated` — `windows`는 보조 창 이름(`second`·`popup`) → hwnd |
| `screen` | `scene`, `screen`, `popup` — 그 장면을 다 그린 뒤 |
| `key_down`·`key_up` | `window`, `key`(kookabug 키 이름), `keysym`, `vk`, `repeat`(down만) |
| `char` | `window`, `text`(글자 하나 — 한 키 이벤트에 여러 글자면 글자마다 한 줄) |
| `mouse_down`·`mouse_up` | `window`, `button`(left·middle·right), `x`, `y`(클라이언트 좌표) |
| `wheel` | `window`, `delta`, `x`, `y` |
| `focus` | `window`, `focused` |
| `resize` | `client_size` |
| `recreate` | `old_hwnd` |
| `window_closed` | `window` |
| `signal` | `command` — 검사용 신호 파일(`--signal-file`)의 명령을 처리한 뒤 |
| `fatal` | `reason`, `detail` |
| `exit` | `code` |
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Sequence
from ctypes import wintypes
from pathlib import Path
from typing import IO, Any, Final

from sample_game import EXIT_FONT_MISSING
from sample_game.flow import Game, Scene, apply, scene_state
from sample_game.layout import Viewport, hit
from sample_game.options import Options, parse_args
from sample_game.render import BG, MUTED, PANEL, TEXT, draw

__all__ = ["App", "EventLog", "key_name", "main", "printable_chars"]

# SetProcessDpiAwarenessContext 값 (DPI_AWARENESS_CONTEXT_*)
_CONTEXTS: Final = {"unaware": -1, "system": -2, "pmv2": -4}
_BUTTON_NAMES: Final = {1: "left", 2: "middle", 3: "right"}
# Tk keysym → kookabug 키 이름 (글자 하나짜리는 소문자로)
_KEYSYMS: Final = {
    "Return": "enter",
    "KP_Enter": "enter",
    "Escape": "esc",
    "Tab": "tab",
    "BackSpace": "backspace",
    "Delete": "delete",
    "space": "space",
    "Shift_L": "lshift",
    "Shift_R": "rshift",
    "Control_L": "lctrl",
    "Control_R": "rctrl",
    "Alt_L": "lalt",
    "Alt_R": "ralt",
    "Win_L": "lwin",
    "Win_R": "rwin",
    "Up": "up",
    "Down": "down",
    "Left": "left",
    "Right": "right",
    "Home": "home",
    "End": "end",
    "Prior": "pageup",
    "Next": "pagedown",
    "Insert": "insert",
}
_MISSING_FONT: Final = "kookabug-no-such-font"
SIGNAL_POLL_MS: Final = 50
"""검사용 신호 파일을 보는 간격."""

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SetProcessDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
_user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
_user32.SetThreadDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
_user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
_user32.GetWindowDpiAwarenessContext.argtypes = (wintypes.HWND,)
_user32.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
_user32.AreDpiAwarenessContextsEqual.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
_user32.AreDpiAwarenessContextsEqual.restype = wintypes.BOOL
_user32.GetDpiForWindow.argtypes = (wintypes.HWND,)
_user32.GetDpiForWindow.restype = wintypes.UINT
_user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_user32.GetClientRect.restype = wintypes.BOOL


def set_dpi_awareness(mode: str) -> None:
    """창을 만들기 전에 부른다. 프로세스 수준이 이미 정해져 있으면 이 스레드 수준으로 정한다."""
    context = ctypes.c_void_p(_CONTEXTS[mode])
    if not _user32.SetProcessDpiAwarenessContext(context):
        _user32.SetThreadDpiAwarenessContext(context)


def window_awareness(hwnd: int) -> str:
    context = _user32.GetWindowDpiAwarenessContext(hwnd)
    for name, value in _CONTEXTS.items():
        if _user32.AreDpiAwarenessContextsEqual(context, ctypes.c_void_p(value)):
            return name
    return "other"


def client_size(hwnd: int) -> list[int]:
    rect = wintypes.RECT()
    _user32.GetClientRect(hwnd, ctypes.byref(rect))
    return [rect.right - rect.left, rect.bottom - rect.top]


def frame_hwnd(top: tk.Misc) -> int:
    """Tk 최상위 창의 실제 Win32 창(감싸는 창). `winfo_id`는 그 안의 자식 창이다."""
    return int(top.tk.call("wm", "frame", str(top)), 16)


def printable_chars(text: str) -> str:
    """키 이벤트 문자열에서 글자 입력으로 볼 것만 (Tab·Enter·Backspace 같은 제어 문자 제외)."""
    return "".join(ch for ch in text if ch.isprintable())


def key_name(keysym: str) -> str:
    if keysym in _KEYSYMS:
        return _KEYSYMS[keysym]
    return keysym.lower()


_MODIFIERS: Final = frozenset(
    {"lctrl", "rctrl", "lshift", "rshift", "lalt", "ralt", "lwin", "rwin"}
)
# Tk 이벤트 `state`의 Ctrl 비트 (ControlMask)
CONTROL_MASK: Final = 0x4


def game_key(name: str, state: int) -> str:
    """게임 상태 기계에 넘길 키 이름: Ctrl을 누른 채 누른 키는 `ctrl+<이름>`.

    이 이벤트의 modifier 상태(`state`)로 정한다. 창마다 모은 누른 키 기록은 포커스가 옮겨 가면
    맞지 않는다(다른 창에서 뗀 Ctrl이 남거나, 다른 창에서 누른 채 들어온 Ctrl이 없다).
    """
    if name not in _MODIFIERS and state & CONTROL_MASK:
        return f"ctrl+{name}"
    return name


class EventLog:
    """입력 수신 기록. 경로가 없으면 아무것도 쓰지 않는다."""

    def __init__(self, path: Path | None) -> None:
        self._file: IO[str] | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("a", encoding="utf-8", newline="\n")
        self._seq = 0
        self._start = time.perf_counter()

    def write(self, event: str, **fields: Any) -> None:
        if self._file is None:
            return
        self._seq += 1
        ms = round((time.perf_counter() - self._start) * 1000, 1)
        record = {"seq": self._seq, "ms": ms, "event": event, **fields}
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


class App:
    def __init__(self, options: Options, game: Game, log: EventLog) -> None:
        self.o = options
        self.game = game
        self.log = log
        self.size = options.size
        self.root: tk.Tk | None = None
        self.canvas: tk.Canvas | None = None
        self.font = options.font
        self.ready = False
        self.recreated = False
        self._recreate_pending = False
        self._scheduled: int | None = None
        self._held: dict[str, set[str]] = {}
        self._focused: dict[str, bool] = {}
        self._last_scene: Scene | None = None
        self.pressed: str | None = None
        """`--press-feedback`: 왼쪽 버튼을 누르고 있는 단추 id."""

    # ------------------------------------------------------------ 수명

    def run(self) -> int:
        while True:
            code = self._build()
            if code is not None:
                return code
            assert self.root is not None
            self.root.mainloop()
            if not self._recreate_pending:
                self.log.write("exit", code=0)
                return 0
            self._recreate_pending = False
            self.recreated = True

    def _build(self) -> int | None:
        root = tk.Tk()
        self.root = root
        root.report_callback_exception = self._callback_error  # type: ignore[method-assign]
        if not self.recreated:
            actual = self._resolve_font(root)
            if actual is None:
                detail = f"글꼴 {self.o.font!r}가 없다"
                self.log.write("fatal", reason="font_missing", detail=detail)
                print(f"sample_game: {detail}", file=sys.stderr)
                root.destroy()
                return EXIT_FONT_MISSING
            self.font = actual
        root.title(self.o.title)
        w, h = self.size
        root.geometry(f"{w}x{h}")
        root.configure(bg=BG)
        canvas = tk.Canvas(root, width=w, height=h, highlightthickness=0, bd=0, bg=BG)
        canvas.pack(fill="both", expand=True)
        self.canvas = canvas
        canvas.bind("<Configure>", self._on_configure)
        self._bind_input(root, "main")
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        windows: dict[str, int] = {}
        root.update()
        if self.o.second_window:
            windows["second"] = self._second_window(root)
        if self.o.owned_popup:
            windows["popup"] = self._owned_popup(root)
        root.update()
        self._redraw()
        hwnd = frame_hwnd(root)
        self.log.write(
            "ready",
            pid=os.getpid(),
            hwnd=hwnd,
            title=self.o.title,
            client_size=client_size(hwnd),
            dpi=_user32.GetDpiForWindow(hwnd),
            dpi_awareness=window_awareness(hwnd),
            font=self.font,
            windows=windows,
            recreated=self.recreated,
        )
        self.ready = True
        # 새 창: 장면을 다시 기록하고, 옛 창에 걸었던 타이머는 사라졌으므로 다시 건다
        self._last_scene = None
        self._scheduled = None
        self._after_change()
        if self.o.recreate_after is not None and not self.recreated:
            root.after(self.o.recreate_after, self._recreate)
        if self.o.signal_file is not None:
            root.after(SIGNAL_POLL_MS, self._poll_signal)
        return None

    def _poll_signal(self) -> None:
        """검사용 신호 파일을 본다 (최소화 중에도 돈다 — 입력 없이 장면을 바꾸는 데 쓴다)."""
        if self.root is None or self.o.signal_file is None:
            return
        path = self.o.signal_file
        try:
            text = path.read_text(encoding="utf-8")
            path.unlink()
        except OSError:
            text = ""
        for command in text.split():
            if command == "fire":
                apply(self.game, ("fire", ""))
                self._after_change()
            self.log.write("signal", command=command)
        self.root.after(SIGNAL_POLL_MS, self._poll_signal)

    def _resolve_font(self, root: tk.Tk) -> str | None:
        actual = tkfont.Font(root=root, family=self.o.font, size=-12).actual("family")
        fallback = tkfont.Font(root=root, family=_MISSING_FONT, size=-12).actual("family")
        return None if actual == fallback else str(actual)

    def _on_close(self) -> None:
        if self.root is not None:
            self.root.destroy()

    def _recreate(self) -> None:
        if self.root is None:
            return
        self.log.write("recreate", old_hwnd=frame_hwnd(self.root))
        self._recreate_pending = True
        self.ready = False
        self.root.destroy()

    def _callback_error(self, exc: type[BaseException], value: BaseException, tb: Any) -> None:
        import traceback

        traceback.print_exception(exc, value, tb, file=sys.stderr)

    # ------------------------------------------------------------ 그리기·장면

    def _redraw(self) -> None:
        if self.canvas is not None:
            draw(self.canvas, self.game, self.size, self.font, self.pressed)
            self.canvas.update_idletasks()

    def _after_change(self) -> None:
        """상태가 바뀌었을 수 있는 입력 뒤: 다시 그리고, 장면이 바뀌었으면 기록한다."""
        self._redraw()
        scene = self.game.scene
        if scene is not self._last_scene:
            self._last_scene = scene
            self.log.write(
                "screen", scene=scene.value, screen=self.game.screen, popup=self.game.popup
            )
        self._schedule_timer()

    def _schedule_timer(self) -> None:
        timer = self.game.timer
        if timer is None or timer.token == self._scheduled or self.root is None:
            return
        self._scheduled = timer.token
        self.root.after(timer.ms, lambda token=timer.token: self._fire(token))

    def _fire(self, token: int) -> None:
        self.game.fire(token)
        self._after_change()

    def _on_configure(self, event: tk.Event) -> None:
        size = (event.width, event.height)
        if size == self.size:
            return
        self.size = size
        self._redraw()
        if self.ready:
            self.log.write("resize", client_size=list(size))

    # ------------------------------------------------------------ 입력

    def _bind_input(self, top: tk.Misc, window: str) -> None:
        self._held[window] = set()
        top.bind("<KeyPress>", lambda e: self._key_down(e, window))
        top.bind("<KeyRelease>", lambda e: self._key_up(e, window))
        top.bind("<ButtonPress>", lambda e: self._mouse(e, window, "mouse_down"))
        top.bind("<ButtonRelease>", lambda e: self._mouse(e, window, "mouse_up"))
        top.bind("<MouseWheel>", lambda e: self._wheel(e, window))
        top.bind("<FocusIn>", lambda e: self._focus(e, top, window, True))
        top.bind("<FocusOut>", lambda e: self._focus(e, top, window, False))

    def _key_down(self, event: tk.Event, window: str) -> str:
        name = key_name(event.keysym)
        held = self._held[window]
        repeat = name in held
        held.add(name)
        self.log.write(
            "key_down",
            window=window,
            key=name,
            keysym=event.keysym,
            vk=event.keycode,
            repeat=repeat,
        )
        # Tk는 대기 중인 WM_CHAR 여러 개를 한 키 이벤트의 문자열로 합친다 — 글자마다 기록한다
        chars = printable_chars(event.char)
        for ch in chars:
            self.log.write("char", window=window, text=ch)
        if window == "main":
            # 키 동작은 이벤트 하나에 한 번. Tk가 state를 수로 못 바꾸면 문자열로 준다(조합 없음)
            state = event.state if isinstance(event.state, int) else 0
            self.game.key(game_key(name, state))
            if chars:
                self.game.text(chars)
            self._after_change()
        # Tk 기본 묶음(Tab 포커스 이동·Alt 메뉴)이 돌지 않게 여기서 끝낸다
        return "break"

    def _key_up(self, event: tk.Event, window: str) -> str:
        name = key_name(event.keysym)
        self._held[window].discard(name)
        self.log.write("key_up", window=window, key=name, keysym=event.keysym, vk=event.keycode)
        return "break"

    def _mouse(self, event: tk.Event, window: str, kind: str) -> None:
        button = _BUTTON_NAMES.get(int(event.num), str(event.num))
        x, y = int(event.x), int(event.y)
        self.log.write(kind, window=window, button=button, x=x, y=y)
        if self.o.press_feedback and window == "main" and button == "left":
            pressed = hit(self.game.scene, Viewport(*self.size), x, y)
            pressed = pressed if kind == "mouse_down" else None
            if pressed != self.pressed:
                self.pressed = pressed
                self._redraw()
        # 클릭은 왼쪽 버튼을 뗄 때 그 자리의 버튼으로 판정한다
        if window == "main" and kind == "mouse_up" and button == "left":
            pressed = hit(self.game.scene, Viewport(*self.size), x, y)
            if pressed is not None:
                self.game.press(pressed)
                self._after_change()

    def _wheel(self, event: tk.Event, window: str) -> None:
        self.log.write("wheel", window=window, delta=int(event.delta), x=event.x, y=event.y)

    def _focus(self, event: tk.Event, top: tk.Misc, window: str, focused: bool) -> None:
        if event.widget is not top or self._focused.get(window) is focused:
            return
        self._focused[window] = focused
        self.log.write("focus", window=window, focused=focused)

    # ------------------------------------------------------------ 보조 창

    def _second_window(self, root: tk.Tk) -> int:
        """같은 프로세스의 독립 최상위 창 (소유자 없음)."""
        top = tk.Toplevel(root)
        top.title(f"{self.o.title} Chat")
        x = root.winfo_rootx() + self.size[0] + 40
        top.geometry(f"360x240+{x}+{root.winfo_rooty()}")
        self._small_canvas(top, "채팅", ("[공지] 예제 서버입니다", "모험가: 안녕하세요"))
        self._bind_input(top, "second")
        top.protocol("WM_DELETE_WINDOW", lambda: self._close_window(top, "second"))
        top.update()
        return frame_hwnd(top)

    def _owned_popup(self, root: tk.Tk) -> int:
        """메인 창이 소유한 팝업. 메인 클라이언트 왼쪽 위 (40, 40)에 겹쳐 놓는다."""
        top = tk.Toplevel(root)
        top.title(f"{self.o.title} Notice")
        top.transient(root)
        top.geometry(f"320x160+{root.winfo_rootx() + 40}+{root.winfo_rooty() + 40}")
        self._small_canvas(top, "알림", ("이벤트 보상이 도착했습니다",))
        self._bind_input(top, "popup")
        top.protocol("WM_DELETE_WINDOW", lambda: self._close_window(top, "popup"))
        top.update()
        return frame_hwnd(top)

    def _small_canvas(self, top: tk.Toplevel, title: str, lines: Sequence[str]) -> None:
        canvas = tk.Canvas(top, highlightthickness=0, bd=0, bg=PANEL)
        canvas.pack(fill="both", expand=True)
        canvas.create_text(16, 20, text=title, font=(self.font, -20, "bold"), fill=TEXT, anchor="w")
        for i, line in enumerate(lines):
            canvas.create_text(
                16, 60 + i * 30, text=line, font=(self.font, -16), fill=MUTED, anchor="w"
            )

    def _close_window(self, top: tk.Toplevel, window: str) -> None:
        top.destroy()
        self.log.write("window_closed", window=window)


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_args(argv)
    # 창을 만들기 전에 정해야 한다
    set_dpi_awareness(options.dpi_awareness)
    if options.start_scene is not None:
        game = scene_state(options.start_scene, options.config)
    else:
        game = Game(options.config)
    log = EventLog(options.event_log)
    try:
        return App(options, game, log).run()
    finally:
        log.close()
