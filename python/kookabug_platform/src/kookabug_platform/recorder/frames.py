"""녹화의 클릭 이전 프레임: 캡처 링·프레임 고르기·붙잡기·전이 기록 (M4 계획 2.5).

- **링**: WGC 원본 버퍼(창 프레임 경계 전체, 제목 표시줄·테두리 포함)의 BGR 복사본 + 단조 ns 도착
  시각. 링은 자르지 않는다 — 기하는 `GeometryTimeline`이 따로 정한다
- **상한**: 화면이 아니게 된 지(다음 프레임이 온 지) 2.5초가 지난 프레임을 버린다. WGC는 바뀔 때만
  프레임을 주므로 10초 전 프레임도 다음 프레임이 오기 전까지는 지금 화면이다 — 가장 새 프레임은
  늘 남는다. 최대 60장·256 MiB, 넘치면 오래된 것부터
- **클릭 직전 프레임** = `arrival < t_down`인 가장 새 프레임. 링 앞쪽부터 버리므로 링에 그런
  프레임이 있으면 그것이 맞는 프레임이다. 없으면 `no_frame` — **뒤 프레임으로 대신하지 않는다**
- **자르기 조건**: 클릭과 그 프레임이 같은 확정 세대일 때만. 아니면 `geometry_unresolved` — 새
  프레임을 소급해 쓰지 않는다
- **커서 들어오기 전 프레임**: 이동 이력에서 커서가 상자에 마지막으로 들어온 시각 앞 프레임.
  상자 픽셀이 클릭 직전과 다르면(평균 채널 차 > 8) 그것으로 자른다. 없으면 클릭 직전 + 배지
- 시각은 모두 녹화 기준 단조 ns(훅 이벤트 `t_ns`와 같은 원점). 벽시계는 쓰지 않는다
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal, Protocol

import numpy as np

from kookabug_platform.recorder.geometry import Generation, GeometryTimeline

if TYPE_CHECKING:
    from numpy.typing import NDArray

__all__ = [
    "HOVER_DIFF",
    "CaptureRing",
    "ClickFrame",
    "FrameHolds",
    "FrameSource",
    "HoverChoice",
    "RingEntry",
    "RingPolicy",
    "Transition",
    "TransitionLog",
    "Unresolved",
    "box_diff",
    "click_frame",
    "pre_click",
    "pre_hover",
]

type Pixels = NDArray[np.uint8]

HOVER_DIFF: Final = 8.0
"""클릭 직전과 커서 들어오기 전 프레임의 상자 평균 채널 차가 이보다 크면 들어오기 전으로 자른다."""
_CHANGE_LEVEL: Final = 24
"""전이 기록: 채널 차가 이보다 큰 픽셀을 바뀐 픽셀로 센다."""


@dataclass(frozen=True, slots=True)
class RingPolicy:
    max_age_ns: int = 2_500_000_000
    max_frames: int = 60
    max_bytes: int = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True, eq=False)
class RingEntry:
    """링 항목: 원본 버퍼(읽기 전용 BGR)와 도착 시각."""

    seq: int
    arrival_ns: int
    buffer: Pixels

    @property
    def buffer_size(self) -> tuple[int, int]:
        return int(self.buffer.shape[1]), int(self.buffer.shape[0])

    @property
    def nbytes(self) -> int:
        return int(self.buffer.nbytes)

    def meta(self) -> dict[str, object]:
        """`recorder-script` `RingFrame` 모양 (버퍼 크기·도착 시각만)."""
        return {
            "seq": self.seq,
            "arrival_ns": self.arrival_ns,
            "buffer_size": list(self.buffer_size),
        }


class CaptureRing:
    """녹화 세션 하나의 프레임 링. 캡처 콜백 스레드가 넣고 판정 스레드가 읽는다."""

    def __init__(self, policy: RingPolicy | None = None) -> None:
        self.policy = policy or RingPolicy()
        self._lock = threading.Lock()
        self._items: deque[RingEntry] = deque()
        self._bytes = 0
        self.evicted = 0

    def push(self, seq: int, arrival_ns: int, buffer: Pixels) -> RingEntry:
        if buffer.flags.writeable:
            buffer = np.array(buffer, dtype=np.uint8, copy=True)
            buffer.setflags(write=False)
        entry = RingEntry(seq, arrival_ns, buffer)
        with self._lock:
            if self._items and arrival_ns < self._items[-1].arrival_ns:
                raise ValueError("링 도착 시각이 거꾸로 간다")
            self._items.append(entry)
            self._bytes += entry.nbytes
            self._evict(arrival_ns)
        return entry

    def _evict(self, now_ns: int) -> None:
        p = self.policy
        items = self._items
        while len(items) > 1:
            successor = items[1]
            too_old = successor.arrival_ns < now_ns - p.max_age_ns
            if not (too_old or len(items) > p.max_frames or self._bytes > p.max_bytes):
                break
            gone = items.popleft()
            self._bytes -= gone.nbytes
            self.evicted += 1

    def trim(self, now_ns: int) -> None:
        """새 프레임 없이 시간만 흘렀을 때의 정리 (넣을 때도 한다)."""
        with self._lock:
            self._evict(now_ns)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def nbytes(self) -> int:
        with self._lock:
            return self._bytes

    def entries(self) -> list[RingEntry]:
        with self._lock:
            return list(self._items)

    def latest(self) -> RingEntry | None:
        with self._lock:
            return self._items[-1] if self._items else None

    def before(self, t_ns: int) -> RingEntry | None:
        """`arrival < t_ns`인 가장 새 프레임. 없으면 None (뒤 프레임으로 대신하지 않는다)."""
        with self._lock:
            found = None
            for entry in self._items:
                if entry.arrival_ns >= t_ns:
                    break
                found = entry
            return found

    def between(self, after_ns: int, before_ns: int) -> list[RingEntry]:
        """`after < arrival < before`인 프레임들 (도착 차례)."""
        with self._lock:
            return [e for e in self._items if after_ns < e.arrival_ns < before_ns]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0


class FrameHolds:
    """붙잡은 프레임 (링에서 밀려나도 남는다, 참조 수). 세션 저장소로 옮기는 것은 T8."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: dict[int, tuple[RingEntry, int]] = {}

    def hold(self, entry: RingEntry) -> RingEntry:
        with self._lock:
            _, count = self._held.get(entry.seq, (entry, 0))
            self._held[entry.seq] = (entry, count + 1)
        return entry

    def hold_before(self, ring: CaptureRing, t_ns: int) -> RingEntry | None:
        """버튼 down을 받는 즉시: 그 시각 앞 프레임을 링에서 밀려나기 전에 붙잡는다."""
        entry = ring.before(t_ns)
        return None if entry is None else self.hold(entry)

    def release(self, seq: int) -> None:
        with self._lock:
            item = self._held.get(seq)
            if item is None:
                return
            entry, count = item
            if count <= 1:
                del self._held[seq]
            else:
                self._held[seq] = (entry, count - 1)

    def get(self, seq: int) -> RingEntry | None:
        with self._lock:
            item = self._held.get(seq)
            return None if item is None else item[0]

    def __iter__(self) -> Iterator[RingEntry]:
        with self._lock:
            return iter([entry for entry, _ in self._held.values()])

    def __len__(self) -> int:
        with self._lock:
            return len(self._held)

    def clear(self) -> None:
        with self._lock:
            self._held.clear()


# ---------------------------------------------------------------- 프레임 고르기


type UnresolvedReason = Literal["no_frame", "geometry_unresolved", "pending"]


@dataclass(frozen=True, slots=True)
class Unresolved:
    """프레임을 정하지 못함. `pending`은 기하를 아직 그 시각 뒤로 확인하지 못함(다시 물을 것)."""

    reason: UnresolvedReason


@dataclass(frozen=True, slots=True)
class ClickFrame:
    """클릭과 같은 확정 세대로 검증된 프레임."""

    entry: RingEntry
    generation: Generation
    t_ns: int
    client_point: tuple[int, int]

    def client_pixels(self) -> Pixels:
        return self.generation.geometry.crop_client(self.entry.buffer)


def pre_click(
    ring: CaptureRing, timeline: GeometryTimeline, t_down_ns: int, screen_point: Sequence[int]
) -> ClickFrame | Unresolved:
    """클릭 직전 프레임과 그 클릭의 클라이언트 점. 규칙은 모듈 설명."""
    entry = ring.before(t_down_ns)
    if entry is None:
        return Unresolved("no_frame")
    return _same_generation(entry, timeline, t_down_ns, screen_point)


def click_frame(
    entry: RingEntry | None, timeline: GeometryTimeline, t_ns: int, screen_point: Sequence[int]
) -> ClickFrame | Unresolved:
    """붙잡아 둔 프레임(`FrameHolds.hold_before`)과 입력의 세대 검사 — `pre_click`과 같은 규칙.
    프레임이 없으면 `no_frame`."""
    if entry is None:
        return Unresolved("no_frame")
    return _same_generation(entry, timeline, t_ns, screen_point)


def _same_generation(
    entry: RingEntry, timeline: GeometryTimeline, t_ns: int, screen_point: Sequence[int]
) -> ClickFrame | Unresolved:
    if not timeline.settled(t_ns):
        return Unresolved("pending")
    at_input = timeline.generation_at(t_ns)
    at_frame = timeline.frame_generation(entry.arrival_ns, entry.buffer_size)
    if at_input is None or at_frame is None or not _compatible(at_input, at_frame):
        return Unresolved("geometry_unresolved")
    return ClickFrame(entry, at_input, t_ns, at_input.geometry.to_client(screen_point))


def _compatible(a: Generation, b: Generation) -> bool:
    """같은 확정 세대이거나, 창을 옮기기만 해 버퍼 배치가 같은 두 확정 세대."""
    return a.gen == b.gen or a.geometry.same_layout(b.geometry)


@dataclass(frozen=True, slots=True)
class HoverChoice:
    """자를 프레임: 클릭 직전(`pre_click`) 또는 커서 들어오기 전(`pre_hover`).
    `badge`가 `hover_maybe`면 올린 모양일 수 있다(들어오기 전 프레임이 없음)."""

    frame: ClickFrame
    source: Literal["pre_click", "pre_hover"]
    badge: Literal["hover_maybe"] | None = None


def box_diff(a: Pixels, b: Pixels, box: Sequence[int]) -> float:
    """두 클라이언트 그림의 상자 `(x, y, w, h)` 평균 채널 차."""
    x, y, w, h = (int(v) for v in box)
    pa = a[y : y + h, x : x + w].astype(np.int16)
    pb = b[y : y + h, x : x + w].astype(np.int16)
    if pa.size == 0 or pa.shape != pb.shape:
        return 0.0
    return float(np.abs(pa - pb).mean())


def _inside(point: tuple[int, int], box: Sequence[int]) -> bool:
    x, y, w, h = box
    return x <= point[0] < x + w and y <= point[1] < y + h


def pre_hover(
    ring: CaptureRing,
    timeline: GeometryTimeline,
    click: ClickFrame,
    box: Sequence[int],
    moves: Sequence[tuple[int, int, int]],
) -> HoverChoice:
    """`box`(클라이언트 좌표)를 자를 프레임을 고른다. `moves` = `(t_ns, 화면 x, 화면 y)` 이동 이력.

    이동은 그 시각 세대로 클라이언트 좌표가 된다(불확실 구간의 이동이면 거기서 멈춘다 — 들어온
    시각을 모름).
    """
    fallback = HoverChoice(click, "pre_click", "hover_maybe")
    gen = click.generation
    t_enter: int | None = None
    inside_since = click.t_ns
    for t, x, y in sorted((m for m in moves if m[0] <= click.t_ns), reverse=True):
        at = timeline.generation_at(t)
        if at is None or not _compatible(at, gen):
            break
        if not _inside(at.geometry.to_client((x, y)), box):
            t_enter = inside_since
            break
        inside_since = t
    if t_enter is None:
        return fallback
    entry = ring.before(t_enter)
    if entry is None:
        return fallback
    if entry is click.entry:
        return HoverChoice(click, "pre_click")
    at_frame = timeline.frame_generation(entry.arrival_ns, entry.buffer_size)
    if at_frame is None or not _compatible(at_frame, gen):
        return fallback
    hover = ClickFrame(entry, gen, click.t_ns, click.client_point)
    if box_diff(click.client_pixels(), hover.client_pixels(), box) > HOVER_DIFF:
        return HoverChoice(hover, "pre_hover")
    return HoverChoice(click, "pre_click")


# ---------------------------------------------------------------- 전이 기록


@dataclass(frozen=True, slots=True)
class Change:
    """앞 프레임과 달라진 프레임의 도착 시각과 바뀐 영역(버퍼 좌표 `(x, y, w, h)`)."""

    arrival_ns: int
    region: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class Transition:
    """앞 동작 입력 뒤 ~ 다음 동작 입력 전 사이의 변화 (대기 추론 재료, M4 계획 2.7)."""

    base: RingEntry
    changes: tuple[Change, ...]
    first_changed: RingEntry | None
    """기준 프레임과 처음 달라진 프레임."""
    last: RingEntry | None
    """마지막으로 받은 프레임 (없으면 기준 그대로)."""

    @property
    def last_change_ns(self) -> int | None:
        return self.changes[-1].arrival_ns if self.changes else None


def _changed_region(a: Pixels, b: Pixels) -> tuple[int, int, int, int] | None:
    if a.shape != b.shape:
        return (0, 0, int(b.shape[1]), int(b.shape[0]))
    mask = (np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2)) > _CHANGE_LEVEL
    if not mask.any():
        return None
    ys, xs = np.nonzero(mask)
    x0, y0 = int(xs.min()), int(ys.min())
    return (x0, y0, int(xs.max()) - x0 + 1, int(ys.max()) - y0 + 1)


@dataclass
class TransitionLog:
    """동작 사이 전이 기록. 프레임이 도착할 때마다 `feed` — 링이 짧아도 변화 시각이 남는다.

    프레임은 처음 달라진 것과 마지막 것만 붙잡는다.
    """

    base: RingEntry
    after_ns: int
    _previous: RingEntry | None = None
    _changes: list[Change] = field(default_factory=list[Change])
    _first: RingEntry | None = None

    def feed(self, entry: RingEntry) -> None:
        if entry.arrival_ns <= self.after_ns or entry is self.base:
            return
        previous = self._previous or self.base
        region = _changed_region(previous.buffer, entry.buffer)
        if region is not None:
            self._changes.append(Change(entry.arrival_ns, region))
            if self._first is None and _changed_region(self.base.buffer, entry.buffer):
                self._first = entry
        self._previous = entry

    def close(self) -> Transition:
        return Transition(self.base, tuple(self._changes), self._first, self._previous)


# ---------------------------------------------------------------- 원천


class FrameSource(Protocol):
    """녹화 세션의 프레임 원천: 실제(`CaptureService` 링 + 기하 폴링) 또는 가짜(각본)."""

    @property
    def ring(self) -> CaptureRing: ...
    @property
    def geometry(self) -> GeometryTimeline: ...
    def start(self) -> None: ...
    def close(self) -> None: ...


class CaptureFrameSource:
    """실제 원천: 링을 켠 `CaptureService` 세션과 기하 폴링.

    `open_ring`은 그 창의 캡처 세션을 띄우고 링을 준다(`CaptureService.open_ring`), `close_ring`은
    세션을 닫는다. 첫 검증된 프레임을 기다리는 것은 녹화 세션(T8)이 한다.
    """

    def __init__(
        self,
        open_ring: Callable[[], CaptureRing],
        close_ring: Callable[[], object],
        timeline: GeometryTimeline,
        poller: _Poller,
    ) -> None:
        self._open_ring = open_ring
        self._close_ring = close_ring
        self._timeline = timeline
        self._poller = poller
        self._ring: CaptureRing | None = None

    @property
    def ring(self) -> CaptureRing:
        if self._ring is None:
            raise RuntimeError("프레임 원천을 아직 시작하지 않았다")
        return self._ring

    @property
    def geometry(self) -> GeometryTimeline:
        return self._timeline

    def start(self) -> None:
        self._poller.poll_once()
        self._poller.start()
        self._ring = self._open_ring()

    def close(self) -> None:
        self._poller.stop()
        self._close_ring()
        if self._ring is not None:
            self._ring.clear()


class _Poller(Protocol):
    def poll_once(self) -> bool: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
