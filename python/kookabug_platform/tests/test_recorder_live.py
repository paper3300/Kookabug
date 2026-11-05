"""녹화 캡처 링을 실제 예제 게임 창으로 (M4 T4, `desktop`).

제목 표시줄 있는 실제 창에서 링 프레임 + 기하 세대로 자른 클라이언트가 `capture()` 결과와 같은지,
도착 시각이 단조인지, 창을 옮기는 동안 세대가 나뉘는지 본다. 장면은 신호 파일(`fire`)로 바꾼다.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from kb_testing.display import shift_within
from kb_testing.proc import wait_until
from kb_testing.sample_game import SampleGame, launch_sample_game
from kookabug_platform.capture import CaptureService
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.dpi import per_monitor_v2_thread
from kookabug_platform.recorder.frames import ClickFrame, RingPolicy, pre_click
from kookabug_platform.recorder.geometry import Geometry, GeometryPoller, GeometryTimeline
from kookabug_platform.tracker import WindowTracker
from kookabug_platform.win32 import user32
from kookabug_platform.windows import window_info

pytestmark = pytest.mark.desktop


@pytest.fixture
def game(tmp_path: Path) -> Iterator[SampleGame]:
    signal = tmp_path / "signal.txt"
    title = f"KBRing {uuid.uuid4().hex[:8]}"
    options = (
        *("--title", title, "--start-scene", "loading", "--slow-loading", "60000"),
        *("--signal-file", str(signal)),
    )
    with launch_sample_game(options, workdir=tmp_path) as g:
        yield g


class Rig:
    def __init__(self, game: SampleGame, *, ring: bool = True) -> None:
        self.base = time.monotonic_ns()
        self.tracker = WindowTracker(run_id=f"r{uuid.uuid4().hex[:6]}").start()
        self.service = CaptureService(
            self.tracker,
            ring=RingPolicy() if ring else None,
            ring_clock_ns=lambda: time.monotonic_ns() - self.base,
        )
        self.binding = self.tracker.bind(game.hwnd)
        self.timeline = GeometryTimeline()
        hwnd = game.hwnd

        def read() -> Geometry:
            with per_monitor_v2_thread():
                return Geometry.of_info(window_info(hwnd))

        self.poller = GeometryPoller(
            self.timeline, read, clock_ns=lambda: time.monotonic_ns() - self.base
        )

    def now(self) -> int:
        return time.monotonic_ns() - self.base

    def close(self) -> None:
        self.poller.stop()
        self.service.close_all()
        self.tracker.stop()


@pytest.fixture
def rig(game: SampleGame) -> Iterator[Rig]:
    r = Rig(game)
    yield r
    r.close()


def fire(game: SampleGame, tmp_path: Path) -> None:
    (tmp_path / "signal.txt").write_text("fire\n", encoding="utf-8")


def test_ring_on_real_window_arrival_monotonic(rig: Rig, game: SampleGame, tmp_path: Path) -> None:
    ring = rig.service.open_ring(rig.binding)
    wait_until(lambda: len(ring) >= 1, timeout=5.0)
    before_fire = rig.now()
    fire(game, tmp_path)  # 로딩 → 월드
    game.wait_screen("world")

    def arrived() -> bool:
        latest = ring.latest()
        return latest is not None and latest.arrival_ns > before_fire

    wait_until(arrived, timeout=5.0)
    arrivals = [e.arrival_ns for e in ring.entries()]
    assert arrivals == sorted(arrivals)
    assert all(a <= rig.now() for a in arrivals)


def test_ring_off_by_default_for_runs(game: SampleGame) -> None:
    rig = Rig(game, ring=False)
    try:
        frame = rig.service.capture(rig.binding, deadline=ObservationDeadline(3000))
        assert frame.size[0] > 0
        assert rig.service.ring(rig.binding.binding_id) is None
        with pytest.raises(ValueError):
            rig.service.open_ring(rig.binding)
    finally:
        rig.close()


def test_real_window_crop_matches_client_capture(rig: Rig) -> None:
    ring = rig.service.open_ring(rig.binding)
    rig.poller.poll_once()
    rig.poller.start()
    wait_until(lambda: len(ring) >= 1, timeout=5.0)
    time.sleep(0.3)  # 폴링이 프레임 도착 뒤로 확인하게
    captured = rig.service.capture(rig.binding, deadline=ObservationDeadline(3000))
    g = Geometry.of_info(window_info(rig.binding.hwnd))
    assert g.client_offset[1] > 0  # 제목 표시줄이 있는 창
    t = rig.now()
    wait_until(lambda: rig.timeline.settled(t), timeout=2.0)
    got = pre_click(ring, rig.timeline, t, g.to_screen((10, 10)))
    assert isinstance(got, ClickFrame), got
    assert np.array_equal(got.client_pixels(), captured.pixels)


def test_move_window_during_ring_generations(rig: Rig) -> None:
    ring = rig.service.open_ring(rig.binding)
    rig.poller.poll_once()
    rig.poller.start()
    wait_until(lambda: len(ring) >= 1, timeout=5.0)
    time.sleep(0.25)
    hwnd = rig.binding.hwnd
    with per_monitor_v2_thread():
        rect = window_info(hwnd).window_rect
        dx, dy = shift_within(rect, 60, 40)
        flags = user32.SWP_NOSIZE | user32.SWP_NOZORDER | user32.SWP_NOACTIVATE
        assert user32.SetWindowPos(hwnd, None, rect[0] + dx, rect[1] + dy, 0, 0, flags)
    time.sleep(0.35)
    gens = rig.timeline.generations()
    assert len(gens) >= 2
    old, new = gens[-2], gens[-1]
    assert new.geometry.client_origin == (
        old.geometry.client_origin[0] + dx,
        old.geometry.client_origin[1] + dy,
    )
    assert rig.timeline.generation_at((old.confirmed_at_ns + new.from_ns) // 2) is None
    # 옮기기만 했으므로 새 세대 클릭도 앞 프레임으로 잘린다 (좌표는 새 세대)
    t = rig.now()
    wait_until(lambda: rig.timeline.settled(t), timeout=2.0)
    got = pre_click(ring, rig.timeline, t, new.geometry.to_screen((5, 6)))
    assert isinstance(got, ClickFrame) and got.client_point == (5, 6)
