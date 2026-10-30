"""가짜 캡처 백엔드와 가짜 창 기하 (`kookabug_platform.capture`를 실제 WGC 없이 검사).

- `FakeCaptureBackend`: 세션마다 `FakeCaptureSession`. 검사가 프레임을 넣고(`push`), 창 닫힘
  (`close`), 스레드 종료(`die`)를 일으킨다. `on_start`가 있으면 세션을 띄울 때 부른다(첫 프레임 등)
- `FakeScreen`: 창 하나의 확장 프레임·클라이언트 기하·DPI·최소화. `info`가 `WindowInfo`를 주고,
  `bgra(value)`가 지금 크기의 프레임(테두리 0, 클라이언트 `value`)을 만든다
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kookabug_platform.windows import WindowInfo

__all__ = ["FakeCaptureBackend", "FakeCaptureSession", "FakeScreen"]


class FakeCaptureSession:
    def __init__(
        self, hwnd: int, on_frame: Callable[[Any], None], on_closed: Callable[[], None]
    ) -> None:
        self.hwnd = hwnd
        self.on_frame = on_frame
        self.on_closed = on_closed
        self.finished = False
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True
        self.finished = True

    def is_finished(self) -> bool:
        return self.finished

    def push(self, frame: Any) -> None:
        """콜백 스레드가 프레임을 넘긴 것처럼."""
        self.on_frame(frame)

    def close(self) -> None:
        """창이 닫혀 `on_closed`가 왔다."""
        self.on_closed()
        self.finished = True

    def die(self) -> None:
        """멈추라고 하지 않았는데 세션 스레드가 끝났다."""
        self.finished = True


@dataclass
class FakeCaptureBackend:
    sessions: list[FakeCaptureSession] = field(default_factory=list[FakeCaptureSession])
    fail: BaseException | None = None
    on_start: Callable[[FakeCaptureSession], None] | None = None

    def start(
        self, hwnd: int, on_frame: Callable[[Any], None], on_closed: Callable[[], None]
    ) -> FakeCaptureSession:
        if self.fail is not None:
            raise self.fail
        session = FakeCaptureSession(hwnd, on_frame, on_closed)
        self.sessions.append(session)
        if self.on_start is not None:
            self.on_start(session)
        return session

    @property
    def last(self) -> FakeCaptureSession:
        return self.sessions[-1]


@dataclass
class FakeScreen:
    """창 하나. 확장 프레임 원점 `origin`, 테두리 `(왼, 위, 오른, 아래)`, 클라이언트 크기."""

    hwnd: int
    pid: int
    origin: tuple[int, int] = (100, 50)
    border: tuple[int, int, int, int] = (1, 30, 1, 1)
    client_size: tuple[int, int] = (64, 40)
    dpi: int = 96
    minimized: bool = False

    @property
    def frame_size(self) -> tuple[int, int]:
        left, top, right, bottom = self.border
        return self.client_size[0] + left + right, self.client_size[1] + top + bottom

    def info(self, hwnd: int) -> WindowInfo:
        assert hwnd == self.hwnd
        ox, oy = self.origin
        fw, fh = self.frame_size
        client_origin = (ox + self.border[0], oy + self.border[1])
        bounds = (ox, oy, ox + fw, oy + fh)
        return WindowInfo(
            hwnd=hwnd,
            pid=self.pid,
            process_created=0,
            process_name="game.exe",
            title="Game",
            class_name="FakeWindow",
            client_size=self.client_size,
            client_origin=client_origin,
            frame_bounds=bounds,
            window_rect=bounds,
            dpi=self.dpi,
            monitor_dpi=self.dpi,
            monitor=(0, 0, 1920, 1080),
            minimized=self.minimized,
            visible=True,
            cloaked=False,
            fullscreen=False,
            integrity=None,
        )

    def bgra(self, value: int, *, size: tuple[int, int] | None = None) -> Any:
        """지금(또는 `size`) 프레임 크기의 BGRA 프레임. 테두리는 0, 클라이언트는 `value`."""
        fw, fh = size or self.frame_size
        frame = np.zeros((fh, fw, 4), dtype=np.uint8)
        left, top, right, bottom = self.border
        frame[top : fh - bottom, left : fw - right, :3] = value
        frame[..., 3] = 255
        return frame
