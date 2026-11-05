"""녹화 대상 창의 기하 세대 시간표 (M4 계획 2.5 "기하 세대 시간표", 검수 H3).

캡처 링의 버퍼는 창 프레임 경계 전체(제목 표시줄·테두리 포함)이고, 훅 이벤트는 화면 좌표다.
둘을 클라이언트 좌표로 바꾸려면 **그 시각의** 창 기하가 필요하다. 처리하는 순간의 창 정보를 쓰면
그 사이 창이 옮겨졌을 때 틀린다.

- 세대 = 같은 기하가 이어진 구간. 확정 구간 = [처음 확인, 마지막 확인]
- 바뀐 것을 안 순간은 실제로 바뀐 순간보다 늦을 수 있다. 그래서 앞 세대 마지막 확인 ~ 새 세대
  처음 확인은 **불확실 구간**이고, 그 구간의 입력·프레임은 어느 세대인지 정하지 않는다
- 관측(폴링·창 이벤트)이 시각 차례를 어기고 와서 앞의 확인과 다른 기하를 말하면, 그 관측 시각 ~
  앞 확인 시각도 불확실 구간으로 둔다(어느 쪽이 맞는지 모른다)
- 프레임은 도착 시각이 확정 구간 안이고 버퍼 크기 = 프레임 경계 크기일 때만 그 세대로 검증된다
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from kookabug_platform.windows import WindowInfo

__all__ = [
    "POLL_INTERVAL_NS",
    "Generation",
    "Geometry",
    "GeometryPoller",
    "GeometryTimeline",
    "mono_clock",
]

POLL_INTERVAL_NS: Final = 100_000_000
"""녹화 세션의 기하 폴링 간격 (100 ms)."""
_MAX_GENERATIONS: Final = 4096


@dataclass(frozen=True, slots=True)
class Geometry:
    """대상 창 기하 (물리 화면 좌표, `recorder-script` `Geometry`와 같은 모양).

    `frame_bounds` = DWM 확장 프레임 경계 `(x, y, 너비, 높이)` — WGC 버퍼가 이 크기다.
    """

    frame_bounds: tuple[int, int, int, int]
    client_origin: tuple[int, int]
    client_size: tuple[int, int]
    dpi: int

    @property
    def frame_size(self) -> tuple[int, int]:
        return self.frame_bounds[2], self.frame_bounds[3]

    @property
    def client_offset(self) -> tuple[int, int]:
        """버퍼 안 클라이언트 (0, 0)의 자리."""
        return (
            self.client_origin[0] - self.frame_bounds[0],
            self.client_origin[1] - self.frame_bounds[1],
        )

    def same_layout(self, other: Geometry) -> bool:
        """버퍼 안 배치가 같다 (프레임 크기·클라이언트 자리·크기·DPI). 창을 옮기기만 한 두 세대는
        버퍼 내용이 창 기준이라 같은 자르기를 쓴다."""
        return (
            self.frame_size == other.frame_size
            and self.client_offset == other.client_offset
            and self.client_size == other.client_size
            and self.dpi == other.dpi
        )

    def to_client(self, point: Sequence[int]) -> tuple[int, int]:
        return int(point[0]) - self.client_origin[0], int(point[1]) - self.client_origin[1]

    def to_screen(self, point: Sequence[int]) -> tuple[int, int]:
        return int(point[0]) + self.client_origin[0], int(point[1]) + self.client_origin[1]

    def in_client(self, point: Sequence[int]) -> bool:
        """화면 점이 클라이언트 영역 안인가."""
        x, y = self.to_client(point)
        return 0 <= x < self.client_size[0] and 0 <= y < self.client_size[1]

    def crop_client(self, buffer: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """버퍼(프레임 경계 전체) → 클라이언트 영역 뷰. 버퍼 크기가 이 기하와 다르면 ValueError."""
        h, w = int(buffer.shape[0]), int(buffer.shape[1])
        if (w, h) != self.frame_size:
            raise ValueError(f"버퍼 크기 {w}x{h}가 프레임 경계 {self.frame_size}와 다르다")
        ox, oy = self.client_offset
        cw, ch = self.client_size
        if ox < 0 or oy < 0 or ox + cw > w or oy + ch > h:
            raise ValueError(f"클라이언트 {self.client_offset}+{self.client_size}가 버퍼 밖이다")
        return buffer[oy : oy + ch, ox : ox + cw]

    @classmethod
    def of_info(cls, info: WindowInfo) -> Geometry:
        left, top, right, bottom = info.frame_bounds
        return cls(
            (left, top, right - left, bottom - top),
            (int(info.client_origin[0]), int(info.client_origin[1])),
            (int(info.client_size[0]), int(info.client_size[1])),
            int(info.dpi),
        )

    @classmethod
    def of_json(cls, data: Mapping[str, Any]) -> Geometry:
        fb, co, cs = data["frame_bounds"], data["client_origin"], data["client_size"]
        return cls(
            (int(fb[0]), int(fb[1]), int(fb[2]), int(fb[3])),
            (int(co[0]), int(co[1])),
            (int(cs[0]), int(cs[1])),
            int(data["dpi"]),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "frame_bounds": list(self.frame_bounds),
            "client_origin": list(self.client_origin),
            "client_size": list(self.client_size),
            "dpi": self.dpi,
        }


@dataclass(frozen=True, slots=True)
class Generation:
    """기하 세대 하나 (`recorder-script` `GeometryGeneration`)."""

    gen: int
    geometry: Geometry
    from_ns: int
    confirmed_at_ns: int

    def covers(self, t_ns: int) -> bool:
        return self.from_ns <= t_ns <= self.confirmed_at_ns

    def to_json(self) -> dict[str, Any]:
        return {
            "gen": self.gen,
            **self.geometry.to_json(),
            "from_ns": self.from_ns,
            "confirmed_at_ns": self.confirmed_at_ns,
        }


class GeometryTimeline:
    """기하 관측을 받아 세대 시간표를 만든다. 여러 스레드(폴링·창 이벤트·판정)가 같이 쓴다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gens: list[Generation] = []
        self._doubt: list[tuple[int, int]] = []

    def observe(self, geometry: Geometry, at_ns: int) -> None:
        """`at_ns`에 창 기하가 `geometry`였음을 확인했다."""
        with self._lock:
            if not self._gens:
                self._gens.append(Generation(1, geometry, at_ns, at_ns))
                return
            last = self._gens[-1]
            if at_ns < last.confirmed_at_ns:
                # 늦게 온 관측: 같으면 이미 더 늦게 확인했다. 다르면 그 사이를 믿지 않는다
                if not (last.geometry == geometry and last.from_ns <= at_ns):
                    self._doubt.append((at_ns, last.confirmed_at_ns))
                return
            if last.geometry == geometry:
                self._gens[-1] = replace(last, confirmed_at_ns=at_ns)
                return
            self._gens.append(Generation(last.gen + 1, geometry, at_ns, at_ns))
            if len(self._gens) > _MAX_GENERATIONS:
                del self._gens[0]

    def generations(self) -> list[Generation]:
        with self._lock:
            return list(self._gens)

    def settled(self, t_ns: int) -> bool:
        """`t_ns` 뒤에 한 번이라도 확인했다 — 그 시각의 세대 판정이 더 바뀌지 않는다."""
        with self._lock:
            return bool(self._gens) and self._gens[-1].confirmed_at_ns >= t_ns

    def generation_at(self, t_ns: int) -> Generation | None:
        """`t_ns`가 확정 구간 안인 세대. 불확실 구간·모르는 시각이면 None."""
        with self._lock:
            if any(lo <= t_ns <= hi for lo, hi in self._doubt):
                return None
            for gen in reversed(self._gens):
                if gen.covers(t_ns):
                    return gen
                if gen.confirmed_at_ns < t_ns:
                    return None
        return None

    def frame_generation(self, arrival_ns: int, buffer_size: tuple[int, int]) -> Generation | None:
        """프레임이 검증된 세대: 도착 시각이 확정 구간 안이고 버퍼 크기 = 프레임 경계 크기.
        아니면 None (`unverified`)."""
        gen = self.generation_at(arrival_ns)
        if gen is None or gen.geometry.frame_size != tuple(buffer_size):
            return None
        return gen


class GeometryPoller:
    """녹화 세션의 100 ms 기하 폴링 (메시지 없는 API만 — `window_info`).

    읽기가 끝난 시각으로 확인한다. 읽는 데 오래 걸렸으면(20 ms 넘게) 그 관측은 버린다 — 언제의
    기하인지 좁힐 수 없다.
    """

    def __init__(
        self,
        timeline: GeometryTimeline,
        read: Callable[[], Geometry],
        *,
        clock_ns: Callable[[], int],
        interval_ns: int = POLL_INTERVAL_NS,
    ) -> None:
        self._timeline = timeline
        self._read = read
        self._clock_ns = clock_ns
        self._interval_s = interval_ns / 1e9
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.errors = 0

    def poll_once(self) -> bool:
        start = self._clock_ns()
        try:
            geometry = self._read()
        except Exception:
            self.errors += 1
            return False
        end = self._clock_ns()
        if end - start > 20_000_000:
            return False
        self._timeline.observe(geometry, end)
        return True

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="kb-geometry-poll", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self._interval_s)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)


def mono_clock(base_ns: int) -> Callable[[], int]:
    """녹화 기준 시각부터 잰 단조 ns 시계 (훅 이벤트 `t_ns`와 같은 원점)."""

    def now() -> int:
        return time.monotonic_ns() - base_ns

    return now
