"""검사 창을 띄울 모니터 고르기 (`KOOKABUG_TEST_DISPLAY`).

사람이 주 모니터로 일하는 동안 데스크톱 검사가 띄우는 창(예제 게임, 탐지용 임시 창, 검사의 tkinter
창)이 업무를 가리지 않게 한다. 값이 없거나 빈 값이면 지금처럼 아무것도 하지 않는다(CI 영향 없음).

    KOOKABUG_TEST_DISPLAY=left      # 가장 왼쪽 모니터 (right: 가장 오른쪽, primary: 주 모니터)
    KOOKABUG_TEST_DISPLAY=-500,300  # 그 점이 든 모니터

이름은 실행할 때의 모니터 목록에서 찾는다(좌표를 박지 않는다). 창은 그 모니터 **작업 영역** 안에
놓는다. 창이 작업 영역보다 크면 주 모니터 반대쪽으로 넘치게 놓는다(왼쪽 모니터면 오른쪽 끝을 맞춤 —
넘친 부분이 주 모니터를 가리지 않게).

- 이 프로세스의 창: `place(width, height)` → 왼쪽 위 좌표 (탐지용 임시 창)
- tkinter 창(예제 게임·검사가 띄운 `tk.Tk()`): 제품·게임 코드를 고치지 않고, `tkinter.Tk()`가
  만들 때 읽는 프로필(`$HOME/.Tk.py`)로 처리한다. `tk_env(env)`가 `HOME`을 `tk_home/`로 두면 그
  환경으로 띄운 파이썬의 모든 `tk.Tk()`가 이 모듈의 `install_tk()`를 부른다 — 크기만 주는
  `geometry("WxH")`에 그 모니터 안 위치를 붙이고, 위치를 주는 창(보조 창·팝업)은 그 모니터 작업
  영역 안으로 옮긴다. 다시 만든 창도 같다
- 좌표는 부르는 스레드의 DPI 인식 기준(예제 게임은 Per-Monitor V2 → 물리 픽셀)이라 창 좌표와 맞다

이 모듈은 표준 라이브러리만 쓴다(예제 게임 프로세스가 파일 경로로 불러 쓴다).
"""

from __future__ import annotations

import ctypes
import os
import re
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "DISPLAY_ENV",
    "RESERVE_ENV",
    "TK_HOME",
    "Monitor",
    "install_tk",
    "install_tk_hook",
    "monitors",
    "offscreen_position",
    "outer_edge",
    "pair_layout",
    "pick",
    "place",
    "place_in",
    "reserve_env",
    "shift_within",
    "target",
    "tk_env",
]

DISPLAY_ENV: Final = "KOOKABUG_TEST_DISPLAY"
RESERVE_ENV: Final = "KOOKABUG_TEST_DISPLAY_RESERVE"
"""검사가 띄울 tkinter 창을 나중에 키울 클라이언트 크기 `WxH` (`reserve_env`)."""
TK_HOME: Final = Path(__file__).resolve().parent / "tk_home"
"""`tkinter.Tk.readprofile`이 읽는 `.Tk.py`가 있는 폴더 (`HOME`으로 넘긴다)."""

type Rect = tuple[int, int, int, int]
"""(left, top, right, bottom)."""


@dataclass(frozen=True, slots=True)
class Monitor:
    name: str
    bounds: Rect
    work: Rect
    primary: bool


def monitors() -> list[Monitor]:
    """모니터 목록 (부르는 스레드의 DPI 인식 좌표)."""

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = (
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        )

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )
    found: list[Monitor] = []

    def collect(handle: int, _hdc: int, _rect: Any, _data: int) -> bool:
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(wintypes.HMONITOR(handle), ctypes.byref(info)):
            m, w = info.rcMonitor, info.rcWork
            found.append(
                Monitor(
                    info.szDevice,
                    (m.left, m.top, m.right, m.bottom),
                    (w.left, w.top, w.right, w.bottom),
                    bool(info.dwFlags & 1),
                )
            )
        return True

    user32.EnumDisplayMonitors(None, None, callback_type(collect), 0)
    return found


def pick(spec: str, found: Sequence[Monitor]) -> Monitor:
    """값 → 모니터. 모르는 값·없는 모니터면 `ValueError`."""
    value = spec.strip().casefold()
    if not found:
        raise ValueError("모니터가 없다")
    if value == "left":
        return min(found, key=lambda m: (m.bounds[0], not m.primary))
    if value == "right":
        return max(found, key=lambda m: (m.bounds[2], m.primary))
    if value == "primary":
        return next((m for m in found if m.primary), found[0])
    point = re.fullmatch(r"\s*(-?\d+)\s*,\s*(-?\d+)\s*", value)
    if point is None:
        raise ValueError(f"{DISPLAY_ENV}={spec!r}: left·right·primary 또는 'x,y'여야 한다")
    x, y = int(point[1]), int(point[2])
    for m in found:
        left, top, right, bottom = m.bounds
        if left <= x < right and top <= y < bottom:
            return m
    raise ValueError(f"{DISPLAY_ENV}={spec!r}: 그 점이 든 모니터가 없다")


def target(
    environ: Mapping[str, str] | None = None,
    found: Callable[[], Sequence[Monitor]] | None = None,
) -> tuple[Monitor, Sequence[Monitor]] | None:
    """환경이 고른 모니터와 전체 목록. 값이 없으면 None."""
    spec = (os.environ if environ is None else environ).get(DISPLAY_ENV, "").strip()
    if not spec:
        return None
    every = (found or monitors)()  # 기본은 부를 때 이 모듈의 monitors (검사가 대역으로 바꾼다)
    return pick(spec, every), every


def place_in(
    monitor: Monitor, every: Sequence[Monitor], width: int, height: int
) -> tuple[int, int]:
    """그 모니터 작업 영역 안 왼쪽 위 좌표 (가운데). 넘치면 주 모니터 반대쪽으로 넘긴다."""
    left, top, right, bottom = monitor.work
    primary = next((m for m in every if m.primary), monitor)
    if width <= right - left:
        x = left + (right - left - width) // 2
    elif monitor.bounds[2] <= primary.bounds[0]:
        x = right - width  # 주 모니터 왼쪽: 왼쪽으로 넘친다
    else:
        x = left  # 주 모니터이거나 오른쪽: 오른쪽으로 넘친다
    y = top + max(0, (bottom - top - height) // 2)
    return x, y


def place(
    width: int, height: int, environ: Mapping[str, str] | None = None
) -> tuple[int, int] | None:
    """이 크기의 창을 놓을 왼쪽 위 좌표. 값이 없으면 None (지금 동작 그대로)."""
    chosen = target(environ)
    if chosen is None:
        return None
    return place_in(chosen[0], chosen[1], width, height)


def _fits(rect: Rect, work: Rect) -> bool:
    return work[0] <= rect[0] and work[1] <= rect[1] and rect[2] <= work[2] and rect[3] <= work[3]


def shift_within(
    rect: Rect, dx: int, dy: int, environ: Mapping[str, str] | None = None
) -> tuple[int, int]:
    """창 사각형 `rect`를 `(dx, dy)`만큼 옮기는 검사가 쓸 이동량.

    값이 없으면 그대로. 있으면 옮긴 창이 고른 모니터 작업 영역 안에 남게: 그 방향에 자리가 없으면
    반대 방향으로(거리 같음), 양쪽 다 모자라면 자리가 더 큰 쪽으로 들어가는 만큼만 옮긴다. 검사는
    돌려받은 이동량으로 기대값을 셈한다("옮겼다"는 검사 의미는 같다). 창이 이미 작업 영역 밖이면
    그 축은 원래 값.
    """
    chosen = target(environ)
    if chosen is None:
        return dx, dy
    work = chosen[0].work
    out = []
    for axis, delta in ((0, dx), (1, dy)):
        below = rect[axis] - work[axis]  # 음의 방향으로 옮길 수 있는 거리
        above = work[axis + 2] - rect[axis + 2]  # 양의 방향
        if below < 0 or above < 0 or delta == 0:
            out.append(delta)
            continue
        ahead, behind = (above, below) if delta > 0 else (below, above)
        sign = 1 if delta > 0 else -1
        if abs(delta) <= ahead:
            out.append(delta)
        elif abs(delta) <= behind:
            out.append(-delta)
        elif ahead >= behind:
            out.append(sign * ahead)
        else:
            out.append(-sign * behind)
    return out[0], out[1]


def pair_layout(
    first: Rect, other: Rect, gap: int = 20, environ: Mapping[str, str] | None = None
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """두 창이 겹치지 않게 놓을 왼쪽 위 좌표 `(first, other)`. 값이 없으면 None (검사 원래 배치).

    고른 모니터 작업 영역에 가로로 나란히 들어가면 가로, 아니면 세로로 쌓는다(1080 폭 세로
    모니터에 1040 폭 게임 둘). 둘 다 안 들어가면 `ValueError`.
    """
    chosen = target(environ)
    if chosen is None:
        return None
    left, top, right, bottom = chosen[0].work
    w1, h1 = first[2] - first[0], first[3] - first[1]
    w2, h2 = other[2] - other[0], other[3] - other[1]
    if w1 + gap + w2 <= right - left and max(h1, h2) <= bottom - top:
        return (left, top), (left + w1 + gap, top)
    if h1 + gap + h2 <= bottom - top and max(w1, w2) <= right - left:
        return (left, top), (left, top + h1 + gap)
    raise ValueError(f"{DISPLAY_ENV}: 창 둘({w1}x{h1}, {w2}x{h2})이 작업 영역에 안 들어간다")


def outer_edge(
    environ: Mapping[str, str] | None = None,
    found: Callable[[], Sequence[Monitor]] | None = None,
) -> tuple[str, Monitor] | None:
    """창을 화면 밖에 걸쳐 놓는 검사가 쓸 경계: 고른 모니터가 가장 왼쪽이면 `("left", 그 모니터)`
    (왼쪽 바깥 — 주 모니터 반대편), 가장 오른쪽이면 `("right", 그 모니터)`. 양옆에 모니터가 있는
    모니터를 골랐으면 가장 오른쪽 모니터의 오른쪽 경계(고른 모니터가 아니어도 주 모니터는 가리지
    않는다). 값이 없으면 None (검사 원래 배치)."""
    chosen = target(environ, found)
    if chosen is None:
        return None
    monitor, every = chosen
    if monitor.bounds[0] == min(m.bounds[0] for m in every) and len(every) > 1:
        return "left", monitor
    rightmost = max(every, key=lambda m: m.bounds[2])
    return "right", rightmost


def offscreen_position(
    client: tuple[int, int, int, int],
    window: Rect,
    monitor_bounds: Sequence[Rect],
    columns: int,
    environ: Mapping[str, str] | None = None,
    found: Callable[[], Sequence[Monitor]] | None = None,
) -> tuple[int, int]:
    """창을 화면 밖에 걸쳐 놓을 왼쪽 위 (`client` = 클라이언트 `(x, y, w, h)`, `window` = 창).

    기본은 가장 오른쪽 모니터의 오른쪽 경계에 클라이언트 오른쪽 `columns`열을 걸친다. 검사 창
    모니터가 가장 왼쪽 모니터면 그 왼쪽 경계에 클라이언트 왼쪽 `columns`열을 걸친다(주 모니터
    반대편 — 넘친 부분이 다른 모니터에 가지 않는다). 그 밖은 `outer_edge`."""
    x, _y, w, _h = client
    edge = outer_edge(environ, found)
    if edge is not None and edge[0] == "left":
        left, top, _right, _bottom = edge[1].bounds
        return window[0] + (left - columns - x), top + 50
    _left, top, right, _bottom = (
        edge[1].bounds if edge is not None else max(monitor_bounds, key=lambda r: r[2])
    )
    return window[0] + (right + columns - (x + w)), top + 50


def reserve_env(
    width: int, height: int, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """검사가 띄울 tkinter 창(예제 게임)을 나중에 이 클라이언트 크기로 **키울** 때 그 환경에 더할
    값. 그 창은 이 크기가 들어갈 자리에 처음부터 놓인다 — 고른 모니터보다 넓으면 주 모니터 반대쪽
    으로 넘치게(왼쪽 모니터면 오른쪽 끝을 맞춤) 놓아, 왼쪽 위를 그대로 두고 키워도 주 모니터를
    가리지 않는다. 검사 창 모니터 값이 없으면 빈 사전 (지금 동작 그대로)."""
    if not (os.environ if environ is None else environ).get(DISPLAY_ENV, "").strip():
        return {}
    return {RESERVE_ENV: f"{width}x{height}"}


def tk_env(env: MutableMapping[str, str]) -> MutableMapping[str, str]:
    """`env`로 띄운 파이썬의 tkinter 창이 고른 모니터에 뜨게 `HOME`을 둔다 (값이 없으면 그대로)."""
    if env.get(DISPLAY_ENV, "").strip():
        env["HOME"] = str(TK_HOME)
    return env


_FRAME: Final = (16, 40)
"""창 틀이 클라이언트보다 큰 정도 (Windows 10·11 기본 테두리·제목 표시줄, 100% 배율 넉넉히)."""
_SIZE_ONLY = re.compile(r"^(\d+)x(\d+)$")
_WITH_POSITION = re.compile(r"^(?:(\d+)x(\d+))?([+-]-?\d+)([+-]-?\d+)$")


def _signed(text: str) -> int:
    # Tk 위치 "+-1080"은 -1080, "-20"은 오른쪽·아래 끝에서 20 (여기서는 그대로 음수로 다룬다)
    return int(text[1:]) if text[0] == "+" else -int(text[1:])


def install_tk_hook(
    environ: Mapping[str, str] | None = None,
) -> tuple[Monitor, Sequence[Monitor]] | None:
    """이 프로세스의 tkinter `Wm.geometry`를 보정한다(여러 번 불러도 한 번). 값이 없으면 None.

    자식 프로세스는 `tk_env`의 프로필이 부르고, 검사 프로세스 자신(pytest 안에서 직접 만드는
    tkinter 창 — 예: doctor 점검 창)은 검사 플러그인이 세션 시작 때 부른다."""
    chosen = target(environ)
    if chosen is None:
        return None
    import tkinter

    monitor, every = chosen
    wm: Any = tkinter.Wm
    if not getattr(wm, "_kb_test_display", False):
        original = wm.wm_geometry

        def wm_geometry(self: Any, new_geometry: str | None = None) -> Any:
            if isinstance(new_geometry, str):
                new_geometry = _adjust(self, new_geometry, monitor, every)
            return original(self, new_geometry)

        wm.wm_geometry = wm_geometry
        wm.geometry = wm_geometry
        wm._kb_test_display = True
        # 감싸기 전 원래 메서드 (검사가 세션 훅을 걷어 내고 새 훅을 시험할 때 쓴다)
        wm._kb_original_wm_geometry = original
    return chosen


def install_tk(root: Any, environ: Mapping[str, str] | None = None) -> None:
    """`tkinter.Tk()` 프로필에서 부른다: 이 프로세스의 tkinter 창을 고른 모니터에 놓는다."""
    chosen = install_tk_hook(environ)
    if chosen is None:
        return
    # 크기를 주지 않는 창(검사의 작은 tk 창)도 그 모니터에 뜨게 처음 위치를 준다
    x, y = place_in(chosen[0], chosen[1], 200, 200)
    root.wm_geometry(f"+{x}+{y}")


def _reserved(environ: Mapping[str, str] | None = None) -> tuple[int, int] | None:
    value = (os.environ if environ is None else environ).get(RESERVE_ENV, "")
    found = _SIZE_ONLY.match(value.strip())
    return None if found is None else (int(found[1]), int(found[2]))


def _adjust(
    window: Any,
    geometry: str,
    monitor: Monitor,
    every: Sequence[Monitor],
    environ: Mapping[str, str] | None = None,
) -> str:
    size = _SIZE_ONLY.match(geometry)
    if size is not None:
        w, h = int(size[1]), int(size[2])
        # 검사가 나중에 키울 크기를 알려 줬으면(RESERVE_ENV) 그 크기로 자리를 잡는다: 왼쪽 위를
        # 그대로 두고 키우는 크기 바꾸기(SetWindowPos SWP_NOMOVE)가 주 모니터로 넘치지 않게
        reserve = _reserved(environ)
        pw, ph = (w, h) if reserve is None else (max(w, reserve[0]), max(h, reserve[1]))
        x, y = place_in(monitor, every, pw + _FRAME[0], ph + _FRAME[1])
        return f"{w}x{h}+{x}+{y}"
    moved = _WITH_POSITION.match(geometry)
    if moved is None:
        return geometry
    # Tk 크기는 클라이언트 영역이고 위치는 창 틀 기준이다: 틀(테두리·제목 표시줄)만큼 여유를 둔다
    w = (int(moved[1]) if moved[1] else int(window.winfo_reqwidth())) + _FRAME[0]
    h = (int(moved[2]) if moved[2] else int(window.winfo_reqheight())) + _FRAME[1]
    x, y = _signed(moved[3]), _signed(moved[4])
    left, top, right, bottom = monitor.work
    x = min(max(x, left), max(left, right - w))
    y = min(max(y, top), max(top, bottom - h))
    prefix = f"{moved[1]}x{moved[2]}" if moved[1] else ""
    return f"{prefix}+{x}+{y}"
