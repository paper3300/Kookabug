"""가짜 Win32 창 표 (`kookabug_platform.win32.api.WindowApi`를 바꿔 끼우는 검사용).

창마다 PID·소유자·부모·제목·최소화 등을 적어 두고, 포그라운드 창과 화면 점 아래 창을 정한다.
`root`는 부모 사슬(`GA_ROOT`)만 따라간다 — 소유자는 따라가지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["FakeWindow", "FakeWindowApi"]


@dataclass
class FakeWindow:
    pid: int
    title: str = ""
    owner: int = 0
    parent: int = 0
    visible: bool = True
    minimized: bool = False
    cloaked: bool = False
    class_name: str = "FakeWindow"
    client_origin: tuple[int, int] = (0, 0)


@dataclass
class FakeWindowApi:
    windows: dict[int, FakeWindow] = field(default_factory=dict[int, FakeWindow])
    created: dict[int, int] = field(default_factory=dict[int, int])
    """PID → 생성 시각 (없으면 1000 + PID)."""
    names: dict[int, str] = field(default_factory=dict[int, str])
    integrity: dict[int | None, int | None] = field(default_factory=dict[int | None, int | None])
    foreground: int = 0
    under_point: dict[tuple[int, int], int] = field(default_factory=dict[tuple[int, int], int])
    desktop: tuple[str | None, str] = ("Default", "")
    locked: bool | None = False

    def add(self, hwnd: int, pid: int, **kw: object) -> int:
        self.windows[hwnd] = FakeWindow(pid, **kw)  # type: ignore[arg-type]
        return hwnd

    def destroy(self, hwnd: int) -> None:
        self.windows.pop(hwnd, None)

    # ------------------------------------------------------------ WindowApi

    def is_window(self, hwnd: int) -> bool:
        return hwnd in self.windows

    def is_visible(self, hwnd: int) -> bool:
        return self.windows[hwnd].visible

    def is_minimized(self, hwnd: int) -> bool:
        return self.windows[hwnd].minimized

    def is_cloaked(self, hwnd: int) -> bool:
        return self.windows[hwnd].cloaked

    def owner(self, hwnd: int) -> int:
        w = self.windows.get(hwnd)
        return 0 if w is None else w.owner

    def root(self, hwnd: int) -> int:
        current = hwnd
        while current in self.windows and self.windows[current].parent:
            current = self.windows[current].parent
        return current if current in self.windows else 0

    def top_level_windows(self) -> list[int]:
        return [h for h, w in self.windows.items() if not w.parent]

    def foreground_window(self) -> int:
        return self.foreground

    def window_from_point(self, x: int, y: int) -> int:
        return self.under_point.get((x, y), 0)

    def client_to_screen(self, hwnd: int, x: int, y: int) -> tuple[int, int]:
        ox, oy = self.windows[hwnd].client_origin
        return ox + x, oy + y

    def window_pid(self, hwnd: int) -> int:
        w = self.windows.get(hwnd)
        return 0 if w is None else w.pid

    def window_title(self, hwnd: int) -> str:
        return self.windows[hwnd].title

    def window_class(self, hwnd: int) -> str:
        return self.windows[hwnd].class_name

    def process_created(self, pid: int) -> int | None:
        return self.created.get(pid, 1000 + pid)

    def process_name(self, pid: int) -> str:
        return self.names.get(pid, f"p{pid}.exe")

    def process_integrity(self, pid: int | None) -> int | None:
        return self.integrity.get(pid, 0x2000)

    def input_desktop(self) -> tuple[str | None, str]:
        return self.desktop

    def session_locked(self) -> bool | None:
        return self.locked
