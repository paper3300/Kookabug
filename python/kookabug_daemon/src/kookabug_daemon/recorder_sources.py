"""녹화 세션의 입력·프레임 원천 (M4 계획 2.1·2.5·2.9 "가짜 원천").

- **가짜**(`FakeRecording`, daemon이 가짜 플랫폼이고 각본이 주어졌을 때): 각본 JSONL을 가짜 훅 원천
  (`FakeHookSource` — 실제 훅 프로세스와 같은 번호 규칙)으로 흘리고, 같은 시각에 가짜 세계
  (`FakeWorld` — 가짜 사람이 장면 상태에 입력을 적용, 부품 합성 프레임)를 앞으로 돌린다. 메시지는
  실제와 같은 `HookStream`(연속성·`injected` 거르기)을 거친다. `speed`배 빠르게 흘리고(`inf`면
  기다리지 않음), None이면 검사가 `advance(t)`로 직접 흘린다. 각본이 `hook_exit`로 끝나면
  `hook_lost`
- **실제**(`RealRecording`): 대상 창 바인딩 → 링을 켠 WGC 캡처 + 기하 폴링 → 훅 프로세스
  (`HookClient`). 시작 단계마다 실패하면 앞 단계를 되돌릴 수 있게 단계를 나눠 둔다
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.recorder_hook import HookClient, HookStop, HookStream, HookTesting, HookUpdate
from kookabug_platform.recorder.fake import FAKE_HWND, FakeHookSource
from kookabug_platform.recorder.fake_frames import FakeWorld
from kookabug_platform.recorder.frames import FrameSource

__all__ = ["FakeRecording", "RealRecording", "Recording", "WindowFacts"]

log = logging.getLogger(__name__)

FIRST_FRAME_TIMEOUT_S: Final = 5.0
OVERFLOW_DRAIN_NS: Final = 150_000_000
"""넘침을 찾은 뒤 유실 앞 이벤트의 관측·표본을 이만큼 더 받는다 (가짜)."""

type UpdateSink = Callable[[HookUpdate, int], None]
type StopSink = Callable[[HookStop], None]


@dataclass(frozen=True, slots=True)
class WindowFacts:
    """`RecorderWindow` (시작 때의 값)."""

    handle: int
    title: str
    process: str
    client_size: tuple[int, int]
    dpi: int

    def to_json(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "title": self.title,
            "process": self.process,
            "client_size": list(self.client_size),
            "dpi": max(1, self.dpi),
        }


class Recording(Protocol):
    """녹화 원천 한 벌. 시작은 단계별(실패하면 세션이 앞 단계부터 거꾸로 `close`)."""

    target_hwnd: int
    window: WindowFacts

    @property
    def frames(self) -> FrameSource: ...
    def start_frames(self) -> None: ...
    def start_hook(self) -> None: ...
    def stop_hook(self) -> HookStop | None: ...
    def close(self) -> None: ...
    def now_ns(self) -> int: ...
    @property
    def ignored_injected(self) -> int: ...


# ---------------------------------------------------------------- 가짜


class FakeRecording:
    """가짜 각본 녹화. 훅 메시지는 가짜 시계(각본 시각)로 `HookStream`을 거친다."""

    def __init__(
        self,
        script: Path,
        scenario: Path,
        *,
        on_update: UpdateSink,
        on_stop: StopSink,
        speed: float | None,
        testing: HookTesting | None = None,
        args: tuple[str, ...] = (),
    ) -> None:
        source = FakeHookSource.from_jsonl(script)
        lines = [source.header, *source.lines]
        self.world = FakeWorld(lines, scenario, args=args)
        self.source = source
        self.stream = HookStream(mono_base_ns=0, testing=testing)
        self._items = source.timeline()
        self._index = 0
        self._now = 0
        self._on_update = on_update
        self._on_stop = on_stop
        self._speed = speed
        self._lock = threading.RLock()
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self._reported = False
        self._overflow_at: int | None = None
        geometry = self.world.source.actual_geometry
        self.target_hwnd = FAKE_HWND["target"]
        self.window = WindowFacts(
            self.target_hwnd,
            self.world.title,
            self.world.scenario.process_name,
            geometry.client_size,
            geometry.dpi,
        )

    @property
    def frames(self) -> FrameSource:
        return self.world

    @property
    def ignored_injected(self) -> int:
        return self.stream.ignored_injected

    def now_ns(self) -> int:
        return self._now

    def start_frames(self) -> None:
        self.world.start()

    def start_hook(self) -> None:
        self.advance(0)  # hook.hello
        if self.stream.hello is None:
            raise RequestFailed("hook_failed", "가짜 훅 원천이 hello를 보내지 않았다")
        if self._speed is not None:
            self._thread = threading.Thread(target=self._run, name="fake-hook", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        speed = self._speed or math.inf
        started = time.monotonic()
        while not self._halt.is_set():
            elapsed = time.monotonic() - started
            due = math.inf if math.isinf(speed) else int(elapsed * speed * 1e9)
            done = self.advance(due)
            if done:
                return
            self._halt.wait(0.01)

    def advance(self, t_ns: float) -> bool:
        """`t_ns`까지의 메시지를 보낸다. 각본 끝까지 보냈으면 True."""
        with self._lock:
            while self._index < len(self._items):
                t, message = self._items[self._index]
                if t > t_ns:
                    return False
                self._index += 1
                self._deliver(t, message)
            if self.source.exit_ns is not None and not self._reported:
                self._report(HookStop("hook_lost", "훅 프로세스가 끝났다 (가짜 각본 hook_exit)"))
            if self._overflow_at is not None and not self._reported:
                assert self.stream.stop is not None
                self._report(self.stream.stop)
            return True

    def _deliver(self, t: int, message: Mapping[str, Any]) -> None:
        self.world.advance_to(t)
        self._now = t
        if self._reported:
            return
        if self._overflow_at is not None and t > self._overflow_at + OVERFLOW_DRAIN_NS:
            assert self.stream.stop is not None
            self._report(self.stream.stop)
            return
        update = self.stream.feed(str(message["method"]), message["params"], t)
        stop = self.stream.stop
        if update is not None and (update.events or update.obs or update.ime):
            self._on_update(update, t)
        if stop is not None and self._overflow_at is None:
            if stop.reason == "input_overflow":
                self._overflow_at = t  # 유실 앞 이벤트의 관측·표본을 조금 더 받는다
            else:
                self._report(stop)

    def _report(self, stop: HookStop) -> None:
        self._reported = True
        self._on_stop(stop)

    def stop_hook(self) -> HookStop | None:
        """정상 멈춤: 지금까지 보낼 때가 된 메시지를 모두 보내고 멈춘다."""
        self._halt.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(10)
        if self._speed is not None and math.isinf(self._speed):
            self.advance(math.inf)
        with self._lock:
            self._reported = True  # 그 뒤 알림 없음
            stop = self.stream.stop
        return stop if stop is not None and stop.reason == "input_overflow" else None

    def close(self) -> None:
        self._halt.set()
        self.world.close()


# ---------------------------------------------------------------- 실제


def _window_facts(hwnd: int) -> WindowFacts:
    from kookabug_platform.errors import PlatformError
    from kookabug_platform.windows import window_info

    try:
        info = window_info(hwnd)
    except (PlatformError, OSError) as exc:
        raise RequestFailed("window_gone", f"창 {hwnd:#x}이(가) 없다: {exc}") from exc
    return WindowFacts(
        hwnd, info.title, info.process_name, (info.client_size[0], info.client_size[1]), info.dpi
    )


def launch_game(settings: Mapping[str, Any], *, timeout_s: float = 30.0) -> int:
    """워크스페이스 `game.*` 설정으로 게임을 띄우고 그 창을 기다린다 (녹화 Job이 아니라 daemon이
    띄우고 세션 끝에 닫지 않는다)."""
    from kookabug_platform.errors import PlatformError
    from kookabug_platform.process import launch
    from kookabug_platform.windows import find_window

    path = settings.get("game.executable")
    if not path:
        raise RequestFailed("launch_failed", "설정 game.executable이 없다")
    args = [str(a) for a in settings.get("game.args") or []]
    title = settings.get("game.title")
    try:
        launch(str(path), args, cwd=settings.get("game.cwd") or None)
    except PlatformError as exc:
        raise RequestFailed("launch_failed", str(exc)) from exc
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        hwnd = find_window(title=str(title) if title else None)
        if hwnd is not None:
            return hwnd
        time.sleep(0.2)
    raise RequestFailed("launch_failed", f"{timeout_s:g}초 안에 게임 창이 뜨지 않았다")


class RealRecording:
    """실제 창 녹화: WGC 링 + 기하 폴링 + 훅 프로세스."""

    def __init__(
        self,
        hwnd: int,
        *,
        on_update: UpdateSink,
        on_stop: StopSink,
        testing: HookTesting | None,
        logs_dir: Path | None,
    ) -> None:
        from kookabug_platform.capture import CaptureService
        from kookabug_platform.recorder.frames import CaptureFrameSource, RingPolicy
        from kookabug_platform.recorder.geometry import (
            Geometry,
            GeometryPoller,
            GeometryTimeline,
            mono_clock,
        )
        from kookabug_platform.tracker import WindowTracker
        from kookabug_platform.windows import activate, window_info

        self.target_hwnd = hwnd
        self.window = _window_facts(hwnd)
        self.base_ns = time.monotonic_ns()
        clock = mono_clock(self.base_ns)
        self._tracker = WindowTracker()
        self._tracker.start()
        self._closed = False
        try:
            binding = self._tracker.bind(hwnd)
        except Exception as exc:
            self._tracker.stop()
            raise RequestFailed("window_gone", f"창에 붙지 못했다: {exc}") from exc
        timeline = GeometryTimeline()
        poller = GeometryPoller(
            timeline, lambda: Geometry.of_info(window_info(hwnd)), clock_ns=clock
        )
        self._capture = CaptureService(self._tracker, ring=RingPolicy(), ring_clock_ns=clock)
        capture = self._capture
        self._frames = CaptureFrameSource(
            lambda: capture.open_ring(binding),
            lambda: capture.close(binding.binding_id),
            timeline,
            poller,
        )
        try:
            activate(hwnd)  # 실패하면 안내만 (P1과 같은 방법)
        except Exception:
            log.info("녹화 대상 창을 앞으로 가져오지 못했다")
        self._hook = HookClient(
            mono_base_ns=self.base_ns,
            on_update=lambda update: on_update(update, self.now_ns()),
            on_stop=on_stop,
            testing=testing,
            target_hwnd=hwnd,
            logs_dir=logs_dir,
        )
        self._hook_started = False

    @property
    def frames(self) -> FrameSource:
        return self._frames

    @property
    def ignored_injected(self) -> int:
        return self._hook.stream.ignored_injected

    def now_ns(self) -> int:
        return time.monotonic_ns() - self.base_ns

    def start_frames(self) -> None:
        try:
            self._frames.start()
        except Exception as exc:
            raise RequestFailed("capture_unsupported", f"캡처를 시작하지 못했다: {exc}") from exc
        deadline = time.monotonic() + FIRST_FRAME_TIMEOUT_S
        while time.monotonic() < deadline:
            latest = self._frames.ring.latest()
            if latest is not None and self._frames.geometry.frame_generation(
                latest.arrival_ns, latest.buffer_size
            ):
                return
            time.sleep(0.02)
        raise RequestFailed("capture_failed", "첫 검증된 프레임이 오지 않았다")

    def start_hook(self) -> None:
        try:
            self._hook.start()
        except Exception as exc:
            raise RequestFailed("hook_failed", f"훅 프로세스를 띄우지 못했다: {exc}") from exc
        self._hook_started = True

    def stop_hook(self) -> HookStop | None:
        if not self._hook_started:
            return None
        self._hook_started = False
        try:
            return self._hook.stop()
        except Exception as exc:  # 넘기기 기한 초과 등 — 녹화 끝부분이 빠졌을 수 있다
            log.warning("훅 멈춤이 깨끗하지 않았다: %s", exc)
            return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.stop_hook()
        try:
            self._frames.close()
        finally:
            self._capture.close_all()
            self._tracker.stop()
