"""관측 호출의 유효 기한: 노드 기한·설정 기한·전체 기한 구분 (구현 계획 M1 2.6, 계획 검수 11).

첫 프레임이 오지 않는 가짜 세션으로 기다림이 어느 기한에서 어떤 예외로 끝나는지 본다.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

from kb_testing.fake_capture import FakeCaptureBackend, FakeCaptureSession, FakeScreen
from kb_testing.fake_win32 import FakeWindowApi
from kookabug_core.engine.cancel import Cancelled, CancelToken, DeadlineExceeded
from kookabug_platform.capture import CaptureService
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.errors import CAPTURE_TIMEOUT, ObservationTimeout, PlatformError
from kookabug_platform.tracker import WindowBinding, WindowTracker

HWND, PID = 0x3000, 51
SLACK_S = 0.08


@pytest.fixture
def setup() -> Iterator[tuple[CaptureService, FakeCaptureBackend, WindowBinding]]:
    api = FakeWindowApi()
    api.add(HWND, PID)
    tracker = WindowTracker(api)
    screen = FakeScreen(HWND, PID)
    backend = FakeCaptureBackend()  # 프레임을 주지 않는다
    service = CaptureService(tracker, backend=backend, info=screen.info, dpi_of=lambda _h: 96)
    yield service, backend, tracker.bind(HWND)
    service.close_all()


def test_node_deadline_100ms_without_frame_is_observation_timeout(
    setup: tuple[CaptureService, FakeCaptureBackend, WindowBinding],
) -> None:
    service, _backend, binding = setup
    start = time.monotonic()
    with pytest.raises(ObservationTimeout):
        service.capture(binding, deadline=ObservationDeadline(2000, node_ms=100, run_ms=60_000))
    elapsed = time.monotonic() - start
    # 100 ms 안에 돌아오고, 설정 기한(capture_timeout)이 아니다
    assert 0.09 <= elapsed <= 0.1 + SLACK_S
    assert issubclass(ObservationTimeout, Exception)
    assert not issubclass(ObservationTimeout, PlatformError)


def test_config_deadline_is_capture_timeout(
    setup: tuple[CaptureService, FakeCaptureBackend, WindowBinding],
) -> None:
    service, _backend, binding = setup
    start = time.monotonic()
    with pytest.raises(PlatformError) as info:
        service.capture(binding, deadline=ObservationDeadline(150, node_ms=5000, run_ms=60_000))
    assert info.value.code == CAPTURE_TIMEOUT
    assert "첫 프레임" in info.value.message
    assert time.monotonic() - start <= 0.15 + SLACK_S


def test_run_deadline_is_deadline_exceeded(
    setup: tuple[CaptureService, FakeCaptureBackend, WindowBinding],
) -> None:
    service, _backend, binding = setup
    with pytest.raises(DeadlineExceeded):
        service.capture(binding, deadline=ObservationDeadline(2000, node_ms=1000, run_ms=100))


def test_zero_remaining_does_not_start(
    setup: tuple[CaptureService, FakeCaptureBackend, WindowBinding],
) -> None:
    service, backend, binding = setup
    with pytest.raises(ObservationTimeout):
        service.capture(binding, deadline=ObservationDeadline(2000, node_ms=0))
    with pytest.raises(DeadlineExceeded):
        service.capture(binding, deadline=ObservationDeadline(2000, node_ms=0, run_ms=0))
    assert backend.sessions == [] and service.sessions_started == 0
    # 이미 취소됐으면 시작하지 않는다
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        service.capture(binding, deadline=ObservationDeadline(2000, check=token.check))
    assert backend.sessions == []


def test_cancel_during_wait_ends_within_slice(
    setup: tuple[CaptureService, FakeCaptureBackend, WindowBinding],
) -> None:
    import threading

    service, _backend, binding = setup
    token = CancelToken()
    threading.Timer(0.1, token.cancel).start()
    start = time.monotonic()
    with pytest.raises(Cancelled) as info:
        service.capture(binding, deadline=ObservationDeadline(5000, check=token.check))
    assert not isinstance(info.value, DeadlineExceeded)
    assert time.monotonic() - start <= 0.1 + 0.05 + SLACK_S


@pytest.mark.parametrize("kind", ["node", "run", "config", "cancel"])
def test_ready_frame_after_deadline_or_cancel_is_not_returned(kind: str) -> None:
    # 세션 시작(끊을 수 없는 호출)이 늦어 그 사이 기한이 끝나거나 취소됐다 — 그 뒤에 준비된
    # 프레임을 성공으로 내보내지 않는다 (검수 T4-1 High 1)
    api = FakeWindowApi()
    api.add(HWND, PID)
    tracker = WindowTracker(api)
    screen = FakeScreen(HWND, PID)
    backend = FakeCaptureBackend()
    token = CancelToken()

    def slow_start(session: FakeCaptureSession) -> None:
        time.sleep(0.08)
        if kind == "cancel":
            token.cancel()
        session.push(screen.bgra(20))

    backend.on_start = slow_start
    service = CaptureService(
        tracker, backend=backend, info=screen.info, dpi_of=lambda _h: 96, fresh_wait_ms=0
    )
    deadline = ObservationDeadline(
        10 if kind == "config" else 1000,
        node_ms=10 if kind == "node" else None,
        run_ms=10 if kind == "run" else None,
        check=token.check,
    )
    expected: type[BaseException] = {
        "node": ObservationTimeout,
        "run": DeadlineExceeded,
        "config": PlatformError,
        "cancel": Cancelled,
    }[kind]
    try:
        with pytest.raises(expected) as info:
            service.capture(tracker.bind(HWND), deadline=deadline)
        if kind == "config":
            assert isinstance(info.value, PlatformError) and info.value.code == CAPTURE_TIMEOUT
        if kind == "cancel":
            assert not isinstance(info.value, DeadlineExceeded)
    finally:
        service.close_all()


def test_wait_checks_cancel_and_deadline_even_when_ready() -> None:
    import threading

    cond = threading.Condition()
    token = CancelToken()
    token.cancel()
    with cond, pytest.raises(Cancelled):
        ObservationDeadline(1000, check=token.check).wait(cond, lambda: True, RuntimeError)
    now = [0.0]
    expired = ObservationDeadline(100, node_ms=50, clock=lambda: now[0])
    now[0] = 0.06
    with cond, pytest.raises(ObservationTimeout):
        expired.wait(cond, lambda: True, RuntimeError)
    fresh = ObservationDeadline(100, clock=lambda: now[0])
    with cond:
        assert fresh.wait(cond, lambda: True, RuntimeError)


def test_static_frame_returned_when_node_deadline_shorter_than_fresh_wait(
    setup: tuple[CaptureService, FakeCaptureBackend, WindowBinding],
) -> None:
    # 새 프레임 대기(50 ms)보다 노드 기한이 짧아도, 멈춘 화면의 최신 프레임은 기한 안에 준다
    service, backend, binding = setup
    screen = FakeScreen(HWND, PID)
    backend.on_start = lambda s: s.push(screen.bgra(5))
    service.capture(binding, deadline=ObservationDeadline(2000))
    # 60 ms < 새 프레임 대기 50 ms + 확정 여유 25 ms
    shot = service.capture(binding, deadline=ObservationDeadline(2000, node_ms=60))
    assert shot.info.reused


def test_earliest_limit_and_ties() -> None:
    assert ObservationDeadline(100, node_ms=100, run_ms=100).limit == "run"
    assert ObservationDeadline(100, node_ms=100).limit == "node"
    assert ObservationDeadline(100, node_ms=200, run_ms=300).limit == "config"
    assert ObservationDeadline(500, node_ms=200, run_ms=100).limit == "run"
    with pytest.raises(ValueError):
        ObservationDeadline(0)
