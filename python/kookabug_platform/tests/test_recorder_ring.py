"""녹화 캡처 링·기하 세대·프레임 고르기 (M4 계획 2.5, T4). 가짜 원천 테두리는 `(1, 30, 1, 1)`."""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from kb_testing.fake_capture import FakeCaptureBackend, FakeScreen
from kb_testing.sample_game import FRAMES_DIR
from kookabug_platform.capture import CaptureService
from kookabug_platform.recorder.frames import (
    CaptureRing,
    ClickFrame,
    FrameHolds,
    RingPolicy,
    TransitionLog,
    Unresolved,
    pre_click,
    pre_hover,
)
from kookabug_platform.recorder.geometry import Geometry, GeometryTimeline
from kookabug_platform.recorder.scripted_frames import ScriptFrameSource, png_scenes
from kookabug_platform.vision import FrameMeta, Vision, load_target_file

MS = 1_000_000
S = 1_000_000_000
BORDER = (1, 30, 1, 1)
CLIENT = (1024, 640)
START_BUTTON = (412, 380, 200, 64)


def geometry(origin: tuple[int, int] = (100, 50), client: tuple[int, int] = CLIENT, dpi: int = 96):
    left, top, right, bottom = BORDER
    fw, fh = client[0] + left + right, client[1] + top + bottom
    return Geometry(
        (origin[0], origin[1], fw, fh), (origin[0] + left, origin[1] + top), client, dpi
    )


def solid_scenes(size_hint: tuple[int, int] = CLIENT):
    """장면 이름 → 단색 그림. "hover"는 START 단추 자리만 밝다 (올린 모양)."""
    colors = {"a": 40, "b": 200, "c": 120}

    def render(scene: str, size: tuple[int, int]) -> np.ndarray:
        image = np.full((size[1], size[0], 3), colors.get(scene, 80), dtype=np.uint8)
        if scene == "hover":
            x, y, w, h = START_BUTTON
            image[y : y + h, x : x + w] = 250
        if scene == "plain":
            x, y, w, h = START_BUTTON
            image[y : y + h, x : x + w] = 150
        return image

    return render


def source(scene: str = "a", **kwargs) -> ScriptFrameSource:
    return ScriptFrameSource(geometry(), scene, solid_scenes(), **kwargs)


def screen(g: Geometry, client_point: tuple[int, int]) -> tuple[int, int]:
    return g.to_screen(client_point)


# ---------------------------------------------------------------- 링 상한


def buf(value: int = 0, size: tuple[int, int] = (8, 6)) -> np.ndarray:
    return np.full((size[1], size[0], 3), value, dtype=np.uint8)


def test_ring_bounds_keep_newest_always() -> None:
    ring = CaptureRing(RingPolicy(max_age_ns=int(2.5 * S), max_frames=60, max_bytes=1 << 30))
    for i in range(100):
        ring.push(i + 1, i * 10 * MS, buf(i % 255))
    assert len(ring) == 60  # 최대 장수
    # 시간: 다음 프레임이 온 지 2.5초가 지난 프레임은 버린다
    ring.push(1000, 10 * S, buf(9))
    entries = ring.entries()
    assert entries[-1].seq == 1000
    assert entries[0].seq == 100  # 바로 앞 프레임은 막 화면이 아니게 됐으므로 남는다
    ring.trim(30 * S)
    assert [e.seq for e in ring.entries()] == [1000]  # 10초 넘게 지나도 가장 새 프레임은 남음
    kept = ring.before(25 * S)
    assert kept is not None and kept.seq == 1000
    # 바이트 상한
    small = CaptureRing(RingPolicy(max_bytes=3 * buf().nbytes))
    for i in range(10):
        small.push(i + 1, i * MS, buf(i))
    assert len(small) == 3 and small.nbytes <= 3 * buf().nbytes
    newest = small.latest()
    assert newest is not None and newest.seq == 10


def test_ring_rejects_time_going_backwards() -> None:
    ring = CaptureRing()
    ring.push(1, 10 * MS, buf())
    with pytest.raises(ValueError):
        ring.push(2, 5 * MS, buf())


# ---------------------------------------------------------------- 클릭 직전 프레임


@pytest.mark.parametrize(("b_offset_ns", "expected"), [(500_000, "a"), (-500_000, "b")])
def test_pre_click_is_last_arrival_before_down(b_offset_ns: int, expected: str) -> None:
    src = source("a", frame_lag_ns=0)
    t_down = 1 * S
    src.schedule_scene(t_down + b_offset_ns, "b")
    src.advance_to(2 * S)
    g = src.actual_geometry
    got = pre_click(src.ring, src.geometry, t_down, screen(g, (10, 10)))
    assert isinstance(got, ClickFrame)
    value = int(got.client_pixels()[0, 0, 0])
    assert value == {"a": 40, "b": 200}[expected]


def test_no_frame_before_first_frame() -> None:
    src = ScriptFrameSource(geometry(), "a", solid_scenes(), start_ns=1 * S)
    src.advance_to(2 * S)
    got = pre_click(src.ring, src.geometry, 1 * S, screen(src.actual_geometry, (5, 5)))
    assert got == Unresolved("no_frame")  # 도착 시각이 클릭과 같으면 앞 프레임이 아니다
    assert pre_click(src.ring, src.geometry, 0, (0, 0)) == Unresolved("no_frame")


def test_pre_frame_evicted_is_no_frame_not_later_frame() -> None:
    # 처리가 늦어 클릭 앞 프레임이 링에서 밀려남 → no_frame. 뒤 프레임(장면 b·c)으로 대신하지 않는다
    src = source("a", policy=RingPolicy(max_age_ns=int(2.5 * S)))
    src.schedule_scene(1 * S, "b")
    for i in range(2, 8):
        src.schedule_scene(i * S, "c" if i % 2 else "b")
    src.advance_to(8 * S)
    got = pre_click(src.ring, src.geometry, int(0.5 * S), screen(src.actual_geometry, (5, 5)))
    assert got == Unresolved("no_frame")


def test_down_event_hold_keeps_frame_after_eviction() -> None:
    src = source("a")
    holds = FrameHolds()
    src.advance_to(int(0.4 * S))
    held = holds.hold_before(src.ring, int(0.5 * S))  # down을 받는 즉시 붙잡음
    assert held is not None
    for i in range(1, 10):
        src.schedule_scene(i * S, "b" if i % 2 else "c")
    src.advance_to(10 * S)
    assert src.ring.before(int(0.5 * S)) is None
    assert holds.get(held.seq) is held and int(held.buffer[40, 40, 0]) == 40
    holds.release(held.seq)
    assert holds.get(held.seq) is None


def test_monotonic_not_wall_clock_used(monkeypatch: pytest.MonkeyPatch) -> None:
    # 링 도착 시각은 단조 ns 시계에서 온다. 벽시계가 크게 뛰어도 순서·값이 그대로다
    screen_ = FakeScreen(hwnd=0x10, pid=1)
    backend = FakeCaptureBackend()
    ticks = iter([5 * MS, 6 * MS])
    tracker = _FakeTracker()
    service = CaptureService(
        tracker,  # pyright: ignore[reportArgumentType]
        backend=backend,
        info=screen_.info,
        dpi_of=lambda _h: 96,
        ring=RingPolicy(),
        ring_clock_ns=lambda: next(ticks),
    )
    binding = tracker.binding(0x10)
    ring = service.open_ring(binding)  # pyright: ignore[reportArgumentType]
    monkeypatch.setattr(time, "time", lambda: 1e12)
    backend.last.push(screen_.bgra(10))
    monkeypatch.setattr(time, "time", lambda: 1.0)
    backend.last.push(screen_.bgra(20))
    assert [e.arrival_ns for e in ring.entries()] == [5 * MS, 6 * MS]


class _Binding:
    def __init__(self, hwnd: int) -> None:
        self.hwnd = hwnd
        self.binding_id = f"b{hwnd}"


class _FakeTracker:
    def on_death(self, _cb) -> None:
        pass

    def notify_capture_closed(self, _binding_id: str) -> None:
        pass

    def check(self, _binding) -> None:
        pass

    def binding(self, hwnd: int) -> _Binding:
        return _Binding(hwnd)


def test_capture_service_ring_off_by_default_and_full_buffer() -> None:
    screen_ = FakeScreen(hwnd=0x20, pid=1)
    backend = FakeCaptureBackend()
    tracker = _FakeTracker()
    plain = CaptureService(tracker, backend=backend, info=screen_.info, dpi_of=lambda _h: 96)  # pyright: ignore[reportArgumentType]
    with pytest.raises(ValueError):
        plain.open_ring(tracker.binding(0x20))  # pyright: ignore[reportArgumentType]
    assert plain.ring("b32") is None
    recording = CaptureService(
        tracker,  # pyright: ignore[reportArgumentType]
        backend=backend,
        info=screen_.info,
        dpi_of=lambda _h: 96,
        ring=RingPolicy(),
    )
    ring = recording.open_ring(tracker.binding(0x20))  # pyright: ignore[reportArgumentType]
    backend.last.push(screen_.bgra(77))
    entry = ring.latest()
    assert entry is not None
    assert entry.buffer_size == screen_.frame_size  # 프레임 경계 전체, 클라이언트 아님
    assert int(entry.buffer[0, 0, 0]) == 0 and int(entry.buffer[40, 10, 0]) == 77
    assert recording.close_all()
    assert len(ring) == 0


# ---------------------------------------------------------------- 테두리 있는 버퍼·기하 세대


def test_ring_stores_full_buffer_not_client() -> None:
    src = source("b")
    entry = src.ring.latest()
    assert entry is not None
    g = src.actual_geometry
    assert entry.buffer_size == g.frame_size == (CLIENT[0] + 2, CLIENT[1] + 31)
    assert int(entry.buffer[5, 5, 0]) != 200  # 제목 표시줄
    assert int(entry.buffer[30, 1, 0]) == 200  # 클라이언트 (0, 0)


def test_client_crop_uses_frame_generation_offsets() -> None:
    title = png_scenes(FRAMES_DIR)("title", CLIENT)
    src = ScriptFrameSource(geometry(), "title", png_scenes(FRAMES_DIR))
    src.advance_to(int(0.3 * S))
    point = (512, 412)
    got = pre_click(src.ring, src.geometry, int(0.25 * S), screen(src.actual_geometry, point))
    assert isinstance(got, ClickFrame)
    assert got.client_point == point
    crop = got.client_pixels()
    assert crop.shape[:2] == (CLIENT[1], CLIENT[0])
    assert np.array_equal(crop, title)
    assert np.array_equal(crop[point[1], point[0]], title[point[1], point[0]])


def test_click_point_to_saved_png_to_replay_point_roundtrip(tmp_path: Path) -> None:
    # 화면 점 → 클라이언트 → target PNG → Vision.find·click_point → 같은 클라이언트 점·화면 점
    src = ScriptFrameSource(geometry(origin=(300, 120)), "title", png_scenes(FRAMES_DIR))
    src.advance_to(int(0.3 * S))
    g = src.actual_geometry
    client_click = (470, 401)  # 단추 왼쪽 위 쪽 (가운데가 아님)
    screen_click = g.to_screen(client_click)
    got = pre_click(src.ring, src.geometry, int(0.25 * S), screen_click)
    assert isinstance(got, ClickFrame)
    pixels = got.client_pixels()
    x, y, w, h = START_BUTTON
    ok, data = cv2.imencode(".png", np.ascontiguousarray(pixels[y : y + h, x : x + w]))
    assert ok
    (tmp_path / "start.png").write_bytes(data.tobytes())
    center = (x + (w - 1) / 2, y + (h - 1) / 2)
    offset = [got.client_point[0] - center[0], got.client_point[1] - center[1]]
    body = {
        "format": "kookabug.target/0",
        "image": "start.png",
        "click": {"anchor": "center", "offset": offset},
        "recorded": {"client_size": list(g.client_size), "dpi": g.dpi},
    }
    (tmp_path / "start.target.json").write_text(json.dumps(body), encoding="utf-8")
    target = load_target_file(tmp_path / "start.target.json")
    # 재생: 창이 다른 자리에 뜸 (클라이언트 그림은 같다)
    replay = ScriptFrameSource(geometry(origin=(10, 700)), "title", png_scenes(FRAMES_DIR))
    replay_g = replay.actual_geometry
    entry = replay.ring.latest()
    assert entry is not None
    client = replay_g.crop_client(entry.buffer)
    result = Vision().find(np.ascontiguousarray(client), FrameMeta.of_image(client), target)
    assert result.match is not None
    assert result.match.click == client_click
    assert g.to_screen(result.match.click) == screen_click
    assert replay_g.to_screen(result.match.click) == (client_click[0] + 11, client_click[1] + 730)


def test_late_location_event_makes_uncertain_interval() -> None:
    # 창이 1.0초에 옮겨졌는데 알림·폴링이 1.2초에야 봄 → 그 사이 클릭은 geometry_unresolved
    src = source("a", poll_ns=300 * MS)
    moved = geometry(origin=(400, 300))
    src.schedule_geometry(1 * S, moved, notify_ns=1200 * MS)
    src.advance_to(2 * S)
    timeline = src.geometry
    old = geometry()
    assert timeline.generation_at(int(1.1 * S)) is None
    assert timeline.generation_at(int(0.95 * S)) is None  # 앞 세대 마지막 확인(0.9) 뒤도 불확실
    late = pre_click(src.ring, timeline, int(1.1 * S), moved.to_screen((5, 5)))
    assert late == Unresolved("geometry_unresolved")
    early = pre_click(src.ring, timeline, int(0.5 * S), old.to_screen((5, 5)))
    assert isinstance(early, ClickFrame) and early.client_point == (5, 5)
    # 옮기기만 했으므로(버퍼 배치 같음) 새 세대의 클릭은 앞 프레임으로 자를 수 있다 — 좌표는 새 세대
    after = pre_click(src.ring, timeline, int(1.4 * S), moved.to_screen((7, 9)))
    assert isinstance(after, ClickFrame) and after.client_point == (7, 9)
    # 아직 확인하지 못한 시각은 판정을 미룬다
    assert pre_click(src.ring, timeline, 5 * S, moved.to_screen((1, 1))) == Unresolved("pending")


@pytest.mark.parametrize("change", ["resize", "dpi"])
def test_resize_or_dpi_race_with_click_not_backfilled(change: str) -> None:
    # 크기·DPI가 바뀐 직후의 클릭: 앞 세대 프레임으로 새 좌표를 자르지 않고, 30 ms 뒤 온 새 세대
    # 프레임으로 소급하지도 않는다
    src = source("a", frame_lag_ns=30 * MS)
    new = geometry(client=(800, 500)) if change == "resize" else geometry(dpi=144)
    src.schedule_geometry(1 * S, new, notify_ns=1 * S)
    src.schedule_frame(1030 * MS)
    src.advance_to(2 * S)
    got = pre_click(src.ring, src.geometry, 1010 * MS, new.to_screen((10, 10)))
    assert got == Unresolved("geometry_unresolved")
    # 새 프레임이 온 뒤의 클릭은 새 세대로 잘린다
    later = pre_click(src.ring, src.geometry, 1500 * MS, new.to_screen((10, 10)))
    assert isinstance(later, ClickFrame)
    assert later.client_pixels().shape[:2] == (new.client_size[1], new.client_size[0])


def test_buffer_size_mismatch_unverified() -> None:
    src = source("a")
    g = src.actual_geometry
    src.schedule_frame(500 * MS, buffer_size=(g.frame_size[0] + 2, g.frame_size[1]))
    src.advance_to(1 * S)
    entry = src.ring.latest()
    assert (
        entry is not None
        and src.geometry.frame_generation(entry.arrival_ns, entry.buffer_size) is None
    )
    got = pre_click(src.ring, src.geometry, 700 * MS, g.to_screen((3, 3)))
    assert got == Unresolved("geometry_unresolved")


def test_out_of_order_conflicting_observation_is_doubt() -> None:
    timeline = GeometryTimeline()
    a, b = geometry(), geometry(origin=(0, 0))
    timeline.observe(a, 0)
    timeline.observe(a, 500 * MS)
    timeline.observe(b, 300 * MS)  # 늦게 온 다른 관측
    assert timeline.generation_at(400 * MS) is None
    assert timeline.generation_at(100 * MS) is not None


# ---------------------------------------------------------------- 커서 들어오기 전


def _hover_setup(enter_ns: int, *, hover_scene: str = "hover"):
    src = source("plain")
    src.schedule_scene(enter_ns + 5 * MS, hover_scene)  # 커서가 들어오자 단추가 바뀜
    t_down = enter_ns + 400 * MS
    src.advance_to(t_down + 100 * MS)
    g = src.actual_geometry
    outside, inside = g.to_screen((300, 300)), g.to_screen((470, 401))
    moves = [(enter_ns - 50 * MS, *outside), (enter_ns, *inside), (enter_ns + 100 * MS, *inside)]
    click = pre_click(src.ring, src.geometry, t_down, inside)
    assert isinstance(click, ClickFrame)
    return src, click, moves


def test_pre_hover_frame_selected_when_box_pixels_differ() -> None:
    src, click, moves = _hover_setup(1 * S)
    choice = pre_hover(src.ring, src.geometry, click, START_BUTTON, moves)
    assert choice.source == "pre_hover" and choice.badge is None
    x, y = START_BUTTON[:2]
    assert int(choice.frame.client_pixels()[y + 1, x + 1, 0]) == 150  # 올리기 전 모양
    assert int(click.client_pixels()[y + 1, x + 1, 0]) == 250
    # 상자 픽셀이 같으면 클릭 직전 그대로
    src2, click2, moves2 = _hover_setup(1 * S, hover_scene="plain")
    same = pre_hover(src2.ring, src2.geometry, click2, START_BUTTON, moves2)
    assert same.source == "pre_click" and same.badge is None


def test_pre_hover_missing_falls_back_with_badge() -> None:
    # 커서가 상자에 들어온 뒤 링에서 그 앞 프레임이 밀려남(오래 머묾) → 클릭 직전 + 배지
    src = source("plain", policy=RingPolicy(max_age_ns=int(2.5 * S)))
    src.schedule_scene(1 * S, "hover")
    for i in range(2, 7):
        src.schedule_scene(i * S + 1, "hover")  # 같은 장면 — 프레임 없음
        src.schedule_frame(i * S)
    t_down = 7 * S
    src.advance_to(t_down + 100 * MS)
    g = src.actual_geometry
    inside = g.to_screen((470, 401))
    moves = [(990 * MS, *g.to_screen((300, 300))), (995 * MS, *inside)]
    click = pre_click(src.ring, src.geometry, t_down, inside)
    assert isinstance(click, ClickFrame)
    choice = pre_hover(src.ring, src.geometry, click, START_BUTTON, moves)
    assert choice.source == "pre_click" and choice.badge == "hover_maybe"
    # 이동 이력이 아예 없어도(들어온 시각 모름) 같은 처리
    none = pre_hover(src.ring, src.geometry, click, START_BUTTON, [])
    assert none.badge == "hover_maybe"


# ---------------------------------------------------------------- 전이 기록


def test_transition_log_records_changes_and_keeps_first_and_last() -> None:
    src = source("a")
    base = src.ring.latest()
    assert base is not None
    src.schedule_scene(200 * MS, "b")
    src.schedule_scene(900 * MS, "c")
    src.advance_to(1 * S)
    log = TransitionLog(base, after_ns=100 * MS)
    for entry in src.ring.between(100 * MS, 1 * S):
        log.feed(entry)
    transition = log.close()
    assert [c.arrival_ns for c in transition.changes] == [200 * MS, 900 * MS]
    assert transition.first_changed is not None and transition.first_changed.arrival_ns == 200 * MS
    assert transition.last is not None and transition.last.arrival_ns == 900 * MS
    assert transition.last_change_ns == 900 * MS
