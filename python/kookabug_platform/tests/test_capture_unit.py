"""캡처 규칙 단위 검사: 세션 시작 실패, 행 간격·BGRA→BGR, 최신 프레임 재사용 조건 ①~④, 장애 구분
(구현 계획 M1 2.3). 실제 WGC 대신 가짜 백엔드·가짜 창 기하를 쓴다."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import numpy as np
import pytest

from kb_testing.fake_capture import FakeCaptureBackend, FakeCaptureSession, FakeScreen
from kb_testing.fake_win32 import FakeWindowApi
from kookabug_platform.capture import CapturedFrame, CaptureService, bgra_to_bgr
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.errors import (
    CAPTURE_FAILED,
    CAPTURE_TIMEOUT,
    CAPTURE_UNSUPPORTED,
    WINDOW_GONE,
    WINDOW_MINIMIZED,
    PlatformError,
)
from kookabug_platform.tracker import WindowBinding, WindowTracker
from kookabug_sdk.types import Rect

HWND, PID = 0x2000, 41
SHORT_MS = 150


@dataclass
class Rig:
    api: FakeWindowApi
    tracker: WindowTracker
    screen: FakeScreen
    backend: FakeCaptureBackend
    service: CaptureService
    binding: WindowBinding

    def capture(self, ms: int = 1000, region: Rect | None = None) -> CapturedFrame:
        return self.service.capture(self.binding, region, deadline=ObservationDeadline(ms))

    def fails(self, code: str, ms: int = SHORT_MS) -> PlatformError:
        with pytest.raises(PlatformError) as info:
            self.capture(ms)
        assert info.value.code == code, info.value.message
        return info.value


@pytest.fixture
def rig() -> Iterator[Rig]:
    api = FakeWindowApi()
    api.add(HWND, PID, title="Game")
    tracker = WindowTracker(api)
    screen = FakeScreen(HWND, PID)
    backend = FakeCaptureBackend()
    # 세션을 띄우면 첫 프레임이 곧바로 온다 (화면을 한 번 그림)
    backend.on_start = lambda s: s.push(screen.bgra(10))
    service = CaptureService(
        tracker, backend=backend, info=screen.info, dpi_of=lambda _h: screen.dpi, fresh_wait_ms=20
    )
    yield Rig(api, tracker, screen, backend, service, tracker.bind(HWND))
    service.close_all()


def later(ms: int, fn: Callable[[], None]) -> threading.Timer:
    timer = threading.Timer(ms / 1000, fn)
    timer.start()
    return timer


def test_session_start_failure_is_capture_unsupported(rig: Rig) -> None:
    rig.backend.fail = OSError("GraphicsCaptureItem을 만들 수 없음")
    err = rig.fails(CAPTURE_UNSUPPORTED)
    assert "GraphicsCaptureItem" in err.message
    # 백엔드가 준 정확한 사유는 그대로
    rig.backend.fail = PlatformError(CAPTURE_UNSUPPORTED, "전용 사유")
    assert rig.fails(CAPTURE_UNSUPPORTED).message == "전용 사유"
    assert rig.service.sessions_started == 0


def test_row_pitch_and_bgra_to_bgr(rig: Rig) -> None:
    # windows-capture처럼: 행 간격(pitch)이 너비 x 4보다 큰 버퍼의 (높이, 너비, 4) 뷰
    width, height, pitch = 5, 3, 32
    raw = np.arange(height * pitch, dtype=np.uint32).astype(np.uint8).reshape(height, pitch)
    view = raw[:, : width * 4].reshape(height, width, 4)
    assert not view.flags.c_contiguous
    bgr = bgra_to_bgr(view)
    assert bgr.shape == (height, width, 3)
    assert bgr.flags.c_contiguous and not bgr.flags.writeable
    assert np.array_equal(bgr, view[:, :, :3])
    raw[:] = 0  # 콜백 버퍼가 바뀌어도 복사본은 그대로
    assert bgr.any()
    with pytest.raises(ValueError, match="BGRA"):
        bgra_to_bgr(np.zeros((2, 2, 3), dtype=np.uint8))
    # 세션 경로: 행 간격 있는 프레임 → 클라이언트만, 테두리 없이
    screen = rig.screen
    fw, fh = screen.frame_size
    padded = np.zeros((fh, fw * 4 + 24), dtype=np.uint8)
    frame = padded[:, : fw * 4].reshape(fh, fw, 4)
    frame[:] = screen.bgra(77)
    rig.backend.on_start = lambda s: s.push(frame)
    shot = rig.capture()
    assert shot.size == screen.client_size
    assert (shot.pixels == 77).all()


def test_client_crop_region_and_frame_info(rig: Rig) -> None:
    shot = rig.capture()
    left, top, _right, _bottom = rig.screen.border
    info = shot.info
    assert shot.size == info.client_size == rig.screen.client_size
    assert (shot.pixels == 10).all()  # 테두리(0)가 섞이지 않았다
    assert info.backend == "wgc" and info.window == rig.binding
    assert info.client_origin_screen == (100 + left, 50 + top)
    assert (info.dpi, info.region, info.reused, info.fullscreen) == (96, None, False, False)
    assert info.pixels_at <= info.observed_at
    part = rig.capture(region=Rect(2, 3, 10, 5))
    assert part.size == (10, 5) and part.info.region == (2, 3, 10, 5)
    assert part.info.frame_seq == info.frame_seq and part.key != shot.key
    with pytest.raises(ValueError, match="밖"):
        rig.capture(region=Rect(60, 0, 10, 5))


# ---------------------------------------------------------------- 재사용 조건 ①~④


def breaks_session_closed(rig: Rig) -> str:
    rig.backend.last.close()
    return WINDOW_GONE


def breaks_session_callback_error(rig: Rig) -> str:
    rig.backend.last.push(np.zeros((2, 2, 3), dtype=np.uint8))  # BGRA가 아님 → 콜백 예외
    return "recreated"


def breaks_session_thread_finished(rig: Rig) -> str:
    rig.backend.last.die()
    return "recreated"


def breaks_no_first_frame(rig: Rig) -> str:
    rig.service.close_all()
    rig.backend.on_start = None
    return CAPTURE_TIMEOUT


def breaks_binding_dead(rig: Rig) -> str:
    rig.tracker.notify_destroyed(HWND)
    return WINDOW_GONE


def breaks_minimized(rig: Rig) -> str:
    rig.screen.minimized = True
    return WINDOW_MINIMIZED


def breaks_size_changed(rig: Rig) -> str:
    rig.screen.client_size = (80, 50)
    rig.backend.on_start = None  # 다시 연 세션도 프레임을 주지 않는다
    return CAPTURE_TIMEOUT


def breaks_dpi_changed(rig: Rig) -> str:
    rig.screen.dpi = 144
    rig.backend.on_start = None
    return CAPTURE_TIMEOUT


@pytest.mark.parametrize(
    "breaks",
    [
        breaks_session_closed,
        breaks_session_callback_error,
        breaks_session_thread_finished,
        breaks_no_first_frame,
        breaks_binding_dead,
        breaks_minimized,
        breaks_size_changed,
        breaks_dpi_changed,
    ],
    ids=lambda f: f.__name__.removeprefix("breaks_"),
)
def test_reuse_conditions_table(rig: Rig, breaks: Callable[[Rig], str]) -> None:
    first = rig.capture()
    # 조건이 다 맞으면: 새 프레임이 없으니 최신 프레임을 이 관측으로 다시 쓴다
    again = rig.capture()
    assert again.info.reused and again.info.frame_seq == first.info.frame_seq
    assert again.info.pixels_at == first.info.pixels_at
    assert again.info.observed_at > first.info.observed_at
    # 조건 하나를 깨면 재사용하지 않는다
    expect = breaks(rig)
    if expect == "recreated":
        shot = rig.capture()
        assert not shot.info.reused and shot.info.frame_seq > first.info.frame_seq
        assert rig.service.sessions_started == 2
        assert rig.backend.sessions[0].stopped
    else:
        rig.fails(expect)


def test_size_change_waits_for_matching_frame(rig: Rig) -> None:
    first = rig.capture()
    screen = rig.screen
    screen.client_size = (80, 50)
    session = rig.backend.last
    # 옛 크기 프레임이 하나 더 와도 쓰지 않고, 새 크기 프레임을 기다린다
    later(30, lambda: session.push(screen.bgra(20, size=(70, 60))))
    later(80, lambda: session.push(screen.bgra(30)))
    shot = rig.capture()
    assert shot.size == (80, 50) and (shot.pixels == 30).all()
    assert not shot.info.reused and shot.info.frame_seq > first.info.frame_seq + 1


def test_size_change_without_frame_reopens_session_once(rig: Rig) -> None:
    first = rig.capture()
    # 크기가 바뀌었는데 지금 세션은 새 크기 프레임을 주지 않는다 (멈춘 화면)
    rig.screen.client_size = (80, 50)
    shot = rig.capture()
    assert shot.size == (80, 50) and not shot.info.reused
    assert rig.service.sessions_started == 2 and rig.backend.sessions[0].stopped
    assert shot.info.frame_seq > first.info.frame_seq
    # 다시 연 세션도 주지 않으면 그 뒤는 기한까지 기다려 capture_timeout (장애 재생성 아님)
    rig.screen.client_size = (90, 60)
    rig.backend.on_start = None
    err = rig.fails(CAPTURE_TIMEOUT, ms=600)
    assert "다시 연 뒤" in err.message
    assert rig.service.sessions_started == 3


def test_new_frame_after_request_is_not_reused(rig: Rig) -> None:
    # 새 프레임 대기를 넉넉히 둔 서비스 (타이머 지연과 무관하게 대기 안에 프레임이 온다)
    service = CaptureService(
        rig.tracker,
        backend=rig.backend,
        info=rig.screen.info,
        dpi_of=lambda _h: rig.screen.dpi,
        fresh_wait_ms=1000,
    )
    try:
        service.capture(rig.binding, deadline=ObservationDeadline(2000))
        session = rig.backend.last
        later(30, lambda: session.push(rig.screen.bgra(55)))
        start = time.monotonic()
        shot = service.capture(rig.binding, deadline=ObservationDeadline(2000))
        assert not shot.info.reused and (shot.pixels == 55).all()
        assert time.monotonic() - start < 0.9  # 프레임이 오면 대기를 끝까지 채우지 않는다
    finally:
        service.close_all()


def test_recreated_session_without_first_frame_is_capture_failed(rig: Rig) -> None:
    rig.capture()
    rig.backend.on_start = None  # 다시 만든 세션은 프레임을 주지 않는다
    rig.backend.last.die()
    err = rig.fails(CAPTURE_FAILED)
    assert "다시 만들었지만" in err.message
    assert rig.service.sessions_started == 2


def test_recreated_session_dying_again_is_capture_failed(rig: Rig) -> None:
    rig.capture()

    def die_at_start(session: FakeCaptureSession) -> None:
        session.die()

    rig.backend.on_start = die_at_start
    rig.backend.last.die()
    err = rig.fails(CAPTURE_FAILED)
    assert "다시 만든 캡처 세션도 죽었다" in err.message


def test_frameless_session_dropped_after_capture_timeout_kept_after_node_timeout(
    rig: Rig,
) -> None:
    from kookabug_platform.errors import ObservationTimeout

    rig.backend.on_start = None
    # 노드 기한으로 끝나면 세션을 그대로 둔다 (다음 폴링이 같은 세션의 첫 프레임을 기다림)
    with pytest.raises(ObservationTimeout):
        rig.service.capture(rig.binding, deadline=ObservationDeadline(2000, node_ms=60))
    assert rig.service.sessions_started == 1 and not rig.backend.last.stopped
    # 설정 기한까지 프레임이 없으면 그 세션을 버린다 → 다음 요청은 새 세션의 첫 프레임
    rig.fails(CAPTURE_TIMEOUT)
    assert rig.backend.last.stopped
    rig.backend.on_start = lambda s: s.push(rig.screen.bgra(40))
    shot = rig.capture()
    assert (shot.pixels == 40).all() and rig.service.sessions_started == 2


def test_on_closed_kills_binding_and_stop_does_not(rig: Rig) -> None:
    rig.capture()
    # 우리가 멈춘 세션의 on_closed는 바인딩을 죽이지 않는다
    session = rig.backend.last
    assert rig.service.close(rig.binding.binding_id)
    session.on_closed()
    rig.tracker.check(rig.binding)
    # 창이 닫혀 온 on_closed는 바인딩을 죽인다 (추적기 연결)
    rig.capture()
    before = rig.tracker.generation
    rig.backend.last.close()
    assert rig.tracker.generation == before + 1
    assert not rig.tracker.is_alive(rig.binding)
    rig.fails(WINDOW_GONE)


def root_array(a: np.ndarray) -> np.ndarray:
    while isinstance(a.base, np.ndarray):
        a = a.base
    return a


@pytest.mark.parametrize("region", [Rect(0, 0, 1, 1), Rect(0, 5, 1920, 2)], ids=["tiny", "rows"])
def test_region_crops_own_memory_and_fit_budget(rig: Rig, region: Rect) -> None:
    # 작은 영역·전체 너비 행 영역을 출력으로 남겨도 붙잡은 실제 할당이 예산 안 (검수 T4-1 High 2)
    from kookabug_platform.frames import FrameStore

    store = FrameStore(budget_bytes=1 << 20)
    rig.screen.client_size = (1920, 1080)
    rig.service.close_all()
    for i in range(1, 21):
        if i > 1:
            rig.backend.last.push(rig.screen.bgra(i))
        shot = rig.capture(region=region)
        assert shot.pixels.base is None and shot.pixels.flags.owndata
        store.register(i, shot.staged(), "s")
        store.mark_output(i)
    store.close_step("s")
    rig.service.close_all()
    with store.pinned(*sorted(store.held())) as arrays:
        roots = {id(root_array(a)): root_array(a) for a in arrays}
        held = sum(a.nbytes for a in roots.values())
    assert held == store.bytes_held <= store.budget_bytes


def test_closed_binding_releases_pixels_without_another_capture(rig: Rig) -> None:
    # 창이 닫히고 새 창으로 넘어가며 옛 바인딩을 다시 캡처하지 않아도 픽셀을 놓는다
    # (검수 T4-1 Mid 3: on_closed 경로)
    rig.screen.client_size = (1920, 1080)
    rig.service.close_all()
    for _ in range(20):
        binding = rig.tracker.bind(HWND)
        rig.service.capture(binding, deadline=ObservationDeadline(1000))
        assert rig.service.cached_bytes() > 0
        rig.backend.last.close()
        assert not rig.tracker.is_alive(binding)
        assert rig.service.cached_bytes() == 0
        # 앞선 창들의 네이티브 세션은 다음 캡처의 회수에서 이미 멈췄다 (실행 끝까지 미루지 않음)
        assert all(s.stopped for s in rig.backend.sessions[:-1])
    assert rig.service.all_finished()


def test_destroy_event_releases_session_pixels(rig: Rig) -> None:
    # 추적기 파괴 이벤트(WGC on_closed 전)로도 그 바인딩 세션의 픽셀을 놓는다
    rig.capture()
    native = rig.backend.last
    assert rig.service.cached_bytes() > 0
    rig.tracker.notify_destroyed(HWND)
    assert rig.service.cached_bytes() == 0
    rig.fails(WINDOW_GONE)
    # 그 바인딩을 다시 캡처하면 회수 대기 세션까지 실제로 멈춘다 (검수 T4-2 Mid)
    assert native.stopped and native.finished
    assert rig.service.close(rig.binding.binding_id)
    # 같은 hwnd의 새 바인딩은 새 세션으로 캡처된다
    rig.api.destroy(HWND)
    rig.api.add(HWND, PID, title="Game")
    fresh = rig.tracker.bind(HWND)
    shot = rig.service.capture(fresh, deadline=ObservationDeadline(1000))
    assert shot.info.window == fresh and rig.service.sessions_started == 2
    assert rig.service.close_all() and all(s.stopped for s in rig.backend.sessions)


def run_with_limit(fn: Callable[[], None], limit_s: float = 3.0) -> None:
    """교착하면 기한 안에 끝나지 않는다 — 데몬 스레드에서 돌리고 기한 뒤 실패로 본다."""
    errors: list[BaseException] = []

    def body() -> None:
        try:
            fn()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    thread.join(limit_s)
    assert not thread.is_alive(), "교착: 기한 안에 끝나지 않았다"
    if errors:
        raise errors[0]


def test_closed_during_session_start_does_not_deadlock(rig: Rig) -> None:
    # 세션 시작(서비스 잠금 안) 중 동기 on_closed → 사망 알림이 잠금을 기다리지 않는다
    # (검수 T4-2 High, 시작 중 종료)
    rig.backend.on_start = lambda s: s.close()

    def scenario() -> None:
        with pytest.raises(PlatformError) as info:
            rig.capture(100)
        assert info.value.code == WINDOW_GONE

    run_with_limit(scenario)
    assert rig.backend.last.stopped and rig.service.all_finished()


def test_closed_callback_racing_with_retire_does_not_deadlock(rig: Rig) -> None:
    # 종료 콜백이 사망 알림 안에 있는 동안, 회수가 (capture의 재생성·폐기와 같은 잠금 범위로)
    # 그 세션을 멈추고 콜백 스레드를 join한다 (검수 T4-2 High, 회수 중 종료)
    in_callback, resume = threading.Event(), threading.Event()

    def pause(_binding_id: str) -> None:
        in_callback.set()
        assert resume.wait(2)

    tracker = WindowTracker(rig.api)
    tracker.on_death(pause)  # 서비스 알림보다 먼저 불린다
    service = CaptureService(
        tracker, backend=rig.backend, info=rig.screen.info, dpi_of=lambda _h: 96
    )
    binding = tracker.bind(HWND)
    service.capture(binding, deadline=ObservationDeadline(1000))
    session = service._sessions[binding.binding_id]
    native = rig.backend.last
    callback = threading.Thread(target=native.close, daemon=True)
    callback.start()
    assert in_callback.wait(1)
    plain_stop = native.stop

    def stop_joining_callback() -> None:
        # windows-capture CaptureControl.stop처럼 콜백 스레드가 끝나기를 기다린다
        resume.set()
        callback.join()
        plain_stop()

    native.stop = stop_joining_callback  # type: ignore[method-assign]

    def scenario() -> None:
        with service._lock:
            service._retire(session)
        assert service.close_all()

    run_with_limit(scenario)
    assert native.stopped and service.all_finished()


def test_destroyed_binding_session_stopped_by_close_and_other_reaping(rig: Rig) -> None:
    # 파괴 알림으로 회수 목록에 옮겨진 세션: 명시적 close는 그것까지 멈추고 끝나야 True,
    # 다른 바인딩의 회수도 그것을 멈춘다 (검수 T4-2 Mid)
    rig.capture()
    native = rig.backend.last
    rig.tracker.notify_destroyed(HWND)
    assert rig.service.close(rig.binding.binding_id)
    assert native.stopped and native.finished
    # 다른 경로: 알림 뒤 다른 바인딩의 캡처(회수)가 먼저 와도 멈춘다
    rig.api.destroy(HWND)
    rig.api.add(HWND, PID, title="Game")
    second = rig.tracker.bind(HWND)
    rig.service.capture(second, deadline=ObservationDeadline(1000))
    native2 = rig.backend.last
    rig.tracker.notify_destroyed(HWND)
    rig.api.destroy(HWND)
    rig.api.add(HWND, PID, title="Game")
    other = rig.tracker.bind(HWND)  # 같은 hwnd 값의 새 창 = 다른 바인딩
    rig.service.capture(other, deadline=ObservationDeadline(1000))
    assert native2.stopped and native2.finished
    # 끝나지 않는 세션은 성공으로 보고하지 않는다
    stuck = rig.backend.last
    stuck.stop = lambda: setattr(stuck, "stopped", True)  # type: ignore[method-assign]
    assert not rig.service.close(other.binding_id)
    assert not rig.service.all_finished()
    stuck.finished = True
    assert rig.service.close(other.binding_id) and rig.service.all_finished()


def test_resize_recovery_progresses_across_short_node_deadlines(rig: Rig) -> None:
    # 0.25초보다 짧은 노드 기한 요청만 이어져도 세션 다시 열기가 진행된다 (검수 T4-1 Mid 4)
    from kookabug_platform.errors import ObservationTimeout

    rig.capture()
    rig.screen.client_size = (80, 50)
    start = time.monotonic()
    recovered = None
    for _ in range(12):
        try:
            recovered = rig.service.capture(
                rig.binding, deadline=ObservationDeadline(1000, node_ms=80)
            )
            break
        except ObservationTimeout:
            pass
    assert recovered is not None and recovered.size == (80, 50)
    assert rig.service.sessions_started == 2
    assert time.monotonic() - start < 0.25 + 0.2


def test_reopened_session_first_frame_wait_carries_over_short_deadlines(rig: Rig) -> None:
    # 다시 연 세션의 첫 프레임이 늦어도 다음 짧은 요청이 그 세션을 이어 기다린다 (새로 열지 않음)
    from kookabug_platform.errors import ObservationTimeout

    rig.capture()
    rig.screen.client_size = (80, 50)
    slow: list[FakeCaptureSession] = []
    rig.backend.on_start = lambda s: slow.append(s)
    timeouts = 0
    while not slow:
        with pytest.raises(ObservationTimeout):
            rig.service.capture(rig.binding, deadline=ObservationDeadline(1000, node_ms=80))
        timeouts += 1
        assert timeouts < 10
    with pytest.raises(ObservationTimeout):
        rig.service.capture(rig.binding, deadline=ObservationDeadline(1000, node_ms=60))
    later(30, lambda: slow[0].push(rig.screen.bgra(77)))
    shot = rig.service.capture(rig.binding, deadline=ObservationDeadline(1000, node_ms=500))
    assert shot.size == (80, 50) and (shot.pixels == 77).all()
    assert rig.service.sessions_started == 2


_MTA_SCRIPT = """
import ctypes
from kookabug_platform.capture import ensure_mta
from kookabug_platform.win32 import ole32

def apartment():
    kind, qualifier = ctypes.c_int(), ctypes.c_int()
    hr = ole32.CoGetApartmentType(ctypes.byref(kind), ctypes.byref(qualifier)) & 0xFFFFFFFF
    return hr, kind.value

ensure_mta()
ensure_mta()  # 두 번 불러도 한 번만 잡는다
assert apartment() == (0, ole32.APTTYPE_MTA), apartment()
import onnxruntime  # 실측으로 프로세스 MTA를 없애는 라이브러리
assert apartment() == (0, ole32.APTTYPE_MTA), apartment()
print("mta kept")
"""


def test_ensure_mta_keeps_process_mta_across_com_teardown() -> None:
    # WGC 세션 사이에 다른 라이브러리가 MTA를 없애면 다음 세션 시작이 접근 위반 (T4-3 검수).
    # 세션 없이 MTA 유지 자체를 새 프로세스에서 본다 (헤드리스에서도 돈다)
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", _MTA_SCRIPT],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "mta kept" in result.stdout


def test_close_all_stops_every_session(rig: Rig) -> None:
    other = rig.tracker.bind(HWND)
    rig.capture()
    rig.service.capture(other, deadline=ObservationDeadline(1000))
    rig.backend.last.die()  # 버려질 세션도 끝까지 멈춘다
    rig.service.capture(other, deadline=ObservationDeadline(1000))
    assert rig.service.sessions_started == 3
    assert rig.service.close_all()
    assert rig.service.all_finished()
    assert all(s.finished for s in rig.backend.sessions)
