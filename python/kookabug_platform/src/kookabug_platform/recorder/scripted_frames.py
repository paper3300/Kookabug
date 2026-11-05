"""가짜 프레임 원천: 각본대로 테두리 있는 버퍼와 기하 시간표를 낸다 (M4 계획 2.5 "프레임 원천").

실제 WGC처럼 버퍼는 창 프레임 경계 전체(제목 표시줄·테두리 포함)이고 클라이언트 그림은 그 안
`client_origin - frame_bounds` 자리에 있다. 검사는 시각을 정해 `advance_to`로 흘린다(실시간 아님).

- 장면(`schedule_scene`)이 바뀌면 그 시각에 프레임이 온다 (`frame_lag_ns` 뒤)
- 기하(`schedule_geometry`)는 `t_ns`에 실제로 바뀌고, 원천은 `notify_ns`에 알게 된다(늦은 알림).
  실제 기하가 바뀌면 새 크기 프레임이 온다. 폴링(`poll_ns`, None이면 끔)은 실제 기하를 읽는다
- `schedule_frame`은 그 시각 장면으로 프레임 하나 (`buffer_size`를 주면 그 크기 — 검증 안 됨)
- 폼 값·포커스·가림 글자를 그리는 동적 장면은 T8의 부품 합성 원천이 이 위에 얹는다
"""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np

from kookabug_platform.recorder.frames import CaptureRing, Pixels, RingPolicy
from kookabug_platform.recorder.geometry import POLL_INTERVAL_NS, Geometry, GeometryTimeline

__all__ = ["BORDER_COLOR", "TITLE_COLOR", "ScriptFrameSource", "png_scenes"]

TITLE_COLOR: Final = (90, 60, 30)
BORDER_COLOR: Final = (40, 40, 40)

type SceneRenderer = Callable[[str, tuple[int, int]], Pixels]
"""장면 이름·클라이언트 크기 → 클라이언트 BGR 그림."""


def png_scenes(folder: Path) -> SceneRenderer:
    """`<folder>/<장면>.png`을 읽어 클라이언트 크기로 맞춘다 (예제 게임 `frames/`)."""
    cache: dict[str, Pixels] = {}

    def render(scene: str, size: tuple[int, int]) -> Pixels:
        image = cache.get(scene)
        if image is None:
            data = np.frombuffer((folder / f"{scene}.png").read_bytes(), np.uint8)
            image = np.asarray(cv2.imdecode(data, cv2.IMREAD_COLOR), dtype=np.uint8)
            cache[scene] = image
        if (int(image.shape[1]), int(image.shape[0])) != size:
            image = np.asarray(cv2.resize(image, size, interpolation=cv2.INTER_AREA), np.uint8)
        return image

    return render


class ScriptFrameSource:
    """각본 시각표 → 링 + 기하 시간표 (`FrameSource`)."""

    def __init__(
        self,
        geometry: Geometry,
        scene: str,
        render: SceneRenderer,
        *,
        start_ns: int = 0,
        poll_ns: int | None = POLL_INTERVAL_NS,
        frame_lag_ns: int = 0,
        policy: RingPolicy | None = None,
    ) -> None:
        self._ring = CaptureRing(policy)
        self._timeline = GeometryTimeline()
        self._render = render
        self._geometry = geometry
        self._scene = scene
        self._poll_ns = poll_ns
        self._lag = frame_lag_ns
        self._now = start_ns
        self._seq = itertools.count(1)
        self._order = itertools.count()
        self._queue: list[tuple[int, int, str, Any]] = []
        self._timeline.observe(geometry, start_ns)
        self._next_poll = None if poll_ns is None else start_ns + poll_ns
        self._push(start_ns + frame_lag_ns, None)

    # ------------------------------------------------------------ FrameSource

    @property
    def ring(self) -> CaptureRing:
        return self._ring

    @property
    def geometry(self) -> GeometryTimeline:
        return self._timeline

    def start(self) -> None:
        pass

    def close(self) -> None:
        self._ring.clear()

    # ------------------------------------------------------------ 각본

    @property
    def now_ns(self) -> int:
        return self._now

    @property
    def scene(self) -> str:
        return self._scene

    @property
    def actual_geometry(self) -> Geometry:
        return self._geometry

    def _at(self, t_ns: int, kind: str, value: Any) -> None:
        if t_ns < self._now:
            raise ValueError(f"이미 지난 시각이다: {t_ns} < {self._now}")
        heapq.heappush(self._queue, (t_ns, next(self._order), kind, value))

    def schedule_scene(self, t_ns: int, scene: str) -> None:
        self._at(t_ns, "scene", scene)

    def schedule_geometry(
        self, t_ns: int, geometry: Geometry, notify_ns: int | None = None
    ) -> None:
        self._at(t_ns, "geometry", geometry)
        self._at(t_ns if notify_ns is None else notify_ns, "notify", None)

    def schedule_frame(self, arrival_ns: int, buffer_size: tuple[int, int] | None = None) -> None:
        self._at(arrival_ns, "frame", buffer_size)

    def load_lines(self, lines: Iterable[Mapping[str, Any]]) -> None:
        """각본 줄(`recorder-script`) 중 scene·geometry·frame을 시각표에 넣는다."""
        for line in lines:
            match line.get("kind"):
                case "scene":
                    self.schedule_scene(int(line["t_ns"]), str(line["scene"]))
                case "geometry":
                    notify = line.get("notify_ns")
                    self.schedule_geometry(
                        int(line["t_ns"]),
                        Geometry.of_json(line["geometry"]),
                        None if notify is None else int(notify),
                    )
                case "frame":
                    size = line.get("buffer_size")
                    self.schedule_frame(
                        int(line["arrival_ns"]),
                        None if size is None else (int(size[0]), int(size[1])),
                    )
                case _:
                    pass

    def advance_to(self, t_ns: int) -> None:
        """`t_ns`까지(포함) 정해 둔 일과 폴링을 시각 차례로 처리한다."""
        while True:
            next_event = self._queue[0][0] if self._queue else None
            poll = self._next_poll
            candidates = [t for t in (next_event, poll) if t is not None and t <= t_ns]
            if not candidates:
                break
            at = min(candidates)
            self._now = at
            if next_event is not None and next_event == at:
                _, _, kind, value = heapq.heappop(self._queue)
                self._apply(at, kind, value)
                continue
            assert self._poll_ns is not None
            self._timeline.observe(self._geometry, at)
            self._next_poll = at + self._poll_ns
        self._now = max(self._now, t_ns)

    def _apply(self, at: int, kind: str, value: Any) -> None:
        match kind:
            case "scene":
                if value != self._scene:
                    self._scene = value
                    self._at(at + self._lag, "frame", None)
            case "geometry":
                changed = value.frame_size != self._geometry.frame_size or (
                    value.client_size != self._geometry.client_size
                )
                self._geometry = value
                if changed:
                    self._at(at + self._lag, "frame", None)
            case "notify":
                self._timeline.observe(self._geometry, at)
            case "frame":
                self._push(at, value)
            case _:
                raise ValueError(kind)

    # ------------------------------------------------------------ 버퍼

    def buffer(self, buffer_size: tuple[int, int] | None = None) -> Pixels:
        """지금 장면·실제 기하의 원본 버퍼 (테두리 있음)."""
        g = self._geometry
        fw, fh = buffer_size or g.frame_size
        frame = np.empty((fh, fw, 3), dtype=np.uint8)
        frame[:] = BORDER_COLOR
        ox, oy = g.client_offset
        frame[: max(0, oy), :] = TITLE_COLOR
        client = self._render(self._scene, g.client_size)
        cw, ch = g.client_size
        w, h = max(0, min(cw, fw - ox)), max(0, min(ch, fh - oy))
        frame[oy : oy + h, ox : ox + w] = client[:h, :w]
        frame.setflags(write=False)
        return frame

    def _push(self, arrival_ns: int, buffer_size: tuple[int, int] | None) -> None:
        self._ring.push(next(self._seq), arrival_ns, self.buffer(buffer_size))
