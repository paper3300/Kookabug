"""Windows 실행 플랫폼 `WindowsPlatform` (구현 계획 M1 2.2~2.7, runner 연결 T9).

runner의 `platform.kind: windows`. 창 수명 추적기·WGC 캡처 세션·프레임 저장소·비전·OCR·창·프로세스
·공용 입력 서비스를 한 실행 동안 묶는다. 코어 플랫폼 프로토콜(`PixelPlatform`·`ObservingPlatform`·
`WindowPlatform`·`StepInputPlatform`)을 구현한다.

- **창 참조 ↔ 바인딩**: 창을 정할 때(`windows.find`·`process.find_window`가 준 창, 다른 실행이 만든
  참조를 처음 쓸 때) 바인딩을 만든다. 돌려주는 `WindowRef`에는 `pid`·`process_created`·`binding`이
  붙는다. 쓸 때마다 추적기가 확인한다(닫혔거나 같은 hwnd의 다른 창이면 `window_gone`)
- **캡처**: 스텝 창의 WGC 세션에서 클라이언트 영역(또는 그 영역). 픽셀은 저장소, 노드에는 참조
  이미지. 대상 창이 없으면 `platform_unavailable`
- **프로세스**: 띄운 게임은 실행 Job 소속이고, 창은 Job 안 모든 프로세스에서 찾는다(런처 대응).
  창 기다리기는 노드 기한까지(설정 기한 없음)
- **입력**: 공용 입력 서비스 → 입력 액터(`attach_input`). 재검증의 "지금 창" = 그 창의 지금
  클라이언트 크기·DPI·캡처 방식 `wgc`
- 추적기 스레드와 캡처 서비스는 처음 쓸 때 시작하고 `close()`가 멈춘다
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from kookabug_core.engine.context import InputObserver, ObservationLimits
from kookabug_core.engine.errors import EngineError
from kookabug_core.inputs import PlatformUnavailable
from kookabug_core.inputs.actor import InputActor
from kookabug_core.inputs.service import InputService, InputSink
from kookabug_core.record.artifacts import (
    CaptureMeta,
    FindEvidence,
    StagedFrame,
    find_with_report,
)
from kookabug_core.record.video import VideoFrame
from kookabug_core.win import Job, Process
from kookabug_platform import process as processes
from kookabug_platform import windows as wins
from kookabug_platform.capture import BACKEND, CaptureService
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.engines import RunEngines, deadline_of
from kookabug_platform.errors import PlatformError
from kookabug_platform.frames import FrameStore, encode_png
from kookabug_platform.tracker import WindowBinding, WindowTracker
from kookabug_sdk.context import Cancelled, InputApi
from kookabug_sdk.errors import ObservationTimeout
from kookabug_sdk.types import (
    Image,
    Match,
    OcrResult,
    ProcessRef,
    Rect,
    Target,
    WindowInfo,
    WindowRef,
)

__all__ = ["WindowsPlatform"]

_POLL_S = 0.05


@dataclass(frozen=True, slots=True)
class _State:
    backend: str
    client_size: tuple[int, int]
    dpi: int


class _NoSink:
    """입력 액터가 붙기 전 (`input` 효과 노드가 없는 실행)."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        raise PlatformUnavailable


class WindowsPlatform:
    """한 실행의 Windows 플랫폼. 실행이 끝나면 `close()`."""

    def __init__(
        self,
        *,
        run_id: str = "",
        job: Job | None = None,
        store: FrameStore | None = None,
        engines: RunEngines | None = None,
        tracker: WindowTracker | None = None,
        capture: CaptureService | None = None,
    ) -> None:
        self.run_id = run_id
        self.job = job
        self.store = store or FrameStore()
        self.engines = engines or RunEngines(self.store)
        self._tracker = tracker
        self._own_tracker = tracker is None
        self._capture = capture
        self._lock = threading.Lock()
        self._processes: dict[int, Process] = {}
        # 입력 액터는 runner가 임대권을 얻은 뒤 붙인다 (`attach_input`)
        self.service = InputService(cast(InputSink, _NoSink()), self)
        self._actor: InputActor | None = None

    # ------------------------------------------------------------ 수명

    @property
    def tracker(self) -> WindowTracker:
        """창 수명 추적기 (처음 쓸 때 이벤트 스레드를 띄운다)."""
        with self._lock:
            if self._tracker is None:
                self._tracker = WindowTracker(run_id=self.run_id)
            tracker = self._tracker
        if self._own_tracker and not tracker.running:
            tracker.start()
        return tracker

    @property
    def started_tracker(self) -> WindowTracker | None:
        """이미 만든 추적기 (쓰지 않았으면 None — 만들지 않는다)."""
        return self._tracker

    @property
    def capture_service(self) -> CaptureService:
        tracker = self.tracker
        with self._lock:
            if self._capture is None:
                self._capture = CaptureService(tracker)
            return self._capture

    def attach_input(self, sink: InputSink) -> None:
        """입력 액터를 붙인다 (그 뒤 `ctx.input` 요청이 액터 큐로 간다)."""
        self.service.sink = sink
        self._actor = sink if isinstance(sink, InputActor) else None

    def close(self) -> bool:
        """캡처 세션을 모두 멈추고 추적기 스레드를 멈춘다. 세션이 전부 끝났으면 True."""
        finished = True
        if self._capture is not None:
            finished = self._capture.close_all()
        if self._tracker is not None and self._own_tracker:
            self._tracker.stop()
        for proc in self._processes.values():
            with contextlib.suppress(Exception):
                proc.close()
        return finished

    # ------------------------------------------------------------ 창 참조

    def resolve(self, window: WindowRef) -> WindowBinding:
        """창 참조 → 이 실행의 바인딩 (확인까지). 닫혔으면 `window_gone`."""
        created = int(window.process_created) if window.process_created.isdigit() else 0
        return self.tracker.resolve(
            window.handle, pid=window.pid, process_created=created, binding=window.binding
        )

    def _ref(self, hwnd: int) -> WindowRef:
        """새로 찾은 창(hwnd)의 참조. 그 살아 있는 창의 바인딩이 있으면 그것, 없으면 새로 만든다 —
        같은 프로세스가 같은 hwnd로 다시 만든 창을 여러 번 찾아도 바인딩 하나다(옛 창의 바인딩·
        참조는 `window_gone` 그대로)."""
        info = wins.window_info(hwnd)
        return _ref_of(self.tracker.acquire(hwnd), info.title)

    # ------------------------------------------------------------ 입력 (공용 입력 서비스)

    @property
    def input(self) -> InputApi:
        raise PlatformUnavailable("Windows 입력은 스텝 ctx로만 보낸다")

    def input_for(
        self,
        step: str,
        window: WindowRef | None,
        observer: InputObserver,
        sleep: Callable[[int], None],
    ) -> InputApi:
        return self.service.for_step(step, window, observer, sleep=sleep)

    def bind(self, window: WindowRef) -> object:
        return self.resolve(window)

    def identify(self, window: WindowRef) -> WindowRef:
        return _ref_of(self.resolve(window), window.title)

    def state(self, window: WindowRef) -> _State:
        info = wins.window_info(self.resolve(window).hwnd)
        return _State(BACKEND, info.client_size, info.dpi)

    # ------------------------------------------------------------ 캡처

    def _binding_for_capture(self, window: WindowRef | None) -> WindowBinding:
        if window is None:
            raise EngineError(
                "platform_unavailable",
                "캡처할 대상 창이 정해지지 않았다 (앱 실행·창 붙기로 대상 창을 먼저 정한다)",
            )
        return self.resolve(window)

    def capture_staged(
        self, window: WindowRef | None, region: Rect | None, limits: ObservationLimits
    ) -> tuple[Image, StagedFrame]:
        binding = self._binding_for_capture(window)
        deadline = deadline_of(limits)
        assert deadline is not None
        frame = self.capture_service.capture(binding, region, deadline=deadline)
        info = frame.info
        assert window is not None
        origin = (0, 0) if info.region is None else (info.region[0], info.region[1])
        meta = CaptureMeta(
            client_size=info.client_size,
            dpi=info.dpi,
            origin=origin,
            backend=info.backend,
            # 캡처한 실제 바인딩으로 (호출자가 넘긴 참조는 바인딩·PID가 비어 있을 수 있다 — 그
            # 관측의 `Match`가 같은 HWND에 새로 뜬 창의 입력으로 통과하지 않게)
            window=_ref_of(info.window, window.title),
            observed_at=info.observed_at,
            frame=info.frame_seq,
        )
        width, height = frame.size
        image = Image(width=width, height=height, frame=info.frame_seq)
        return image, StagedFrame(frame.key, frame.pixels, meta)

    def video_frame(self, window: WindowRef, timeout_ms: int) -> VideoFrame:
        """녹화 프레임 (M3 2.5, 녹화 스레드): 그 창의 최신 프레임(캡처 서비스의 최신 프레임 재사용
        규칙 그대로). 프레임 저장소·`capture_id`를 쓰지 않는다. 설정 기한 안에 못 받으면 예외."""
        binding = self.resolve(window)
        frame = self.capture_service.capture(
            binding, None, deadline=ObservationDeadline(max(1, timeout_ms))
        )
        return VideoFrame(frame.pixels, frame.size, frame.info.pixels_at)

    def capture(self, window: WindowRef | None, region: Rect | None) -> Image:
        """저장소 없이 쓸 때(검사): PNG 바이트 이미지."""
        image, staged = self.capture_staged(window, region, ObservationLimits(2000))
        return Image(image.width, image.height, frame=image.frame, data=encode_png(staged.pixels))

    # ------------------------------------------------------------ 찾기·비교·OCR

    def find(
        self, image: Image, target: Target, *, region: Rect | None, limits: ObservationLimits
    ) -> Match | None:
        return self.engines.find(image, target, region=region, limits=limits)

    def find_report(
        self, image: Image, target: Target, *, region: Rect | None, limits: ObservationLimits
    ) -> tuple[Match | None, FindEvidence | None]:
        """찾기 + 매칭 후보 (M3 2.6)."""
        return find_with_report(self.engines, image, target, region=region, limits=limits)

    def diff(self, a: Image, b: Image, *, region: Rect | None) -> float:
        return self.engines.diff(a, b, region=region)

    def read_text(
        self, image: Image, *, region: Rect | None, sensitive: bool, limits: ObservationLimits
    ) -> OcrResult:
        return self.engines.read_text(image, region=region, sensitive=sensitive, limits=limits)

    def before_node(self, node_type: str, check: Callable[[], None]) -> None:
        """노드 함수를 부르기 전: 엔진 준비(OCR)를 기다린다 (`PreparingPlatform`)."""
        self.engines.before_node(node_type, check)

    # ------------------------------------------------------------ 창

    def find_window(
        self, title: str | None, process_name: str | None, owned: bool
    ) -> WindowRef | None:
        hwnd = wins.find_window(title=title, process_name=process_name, owned=owned)
        return None if hwnd is None else self._ref(hwnd)

    def window_info(self, window: WindowRef) -> WindowInfo:
        binding = self.resolve(window)
        info = wins.window_info(binding.hwnd)
        ref = _ref_of(binding, info.title)
        return WindowInfo(
            window=ref,
            title=info.title,
            process_name=info.process_name,
            class_name=info.class_name,
            client_size=info.client_size,
            client_origin=info.client_origin,
            dpi=info.dpi,
            minimized=info.minimized,
            visible=info.visible,
            fullscreen=info.fullscreen,
        )

    def set_client_size(self, window: WindowRef, width: int, height: int) -> bool:
        return wins.set_client_size(self.resolve(window).hwnd, width, height)

    def activate(self, window: WindowRef) -> bool:
        # 최선 노력, 입력 없이: 닫힌 창도 예외 없이 넘어간다 (다음 관측·입력이 window_gone으로
        # 알린다)
        try:
            hwnd = self.resolve(window).hwnd
        except PlatformError:
            return False
        return wins.activate(hwnd)

    def bring_forward(self, window: WindowRef, step: str | None) -> bool:
        """실행 첫 창을 앞으로 (D1, 실행기가 실행에서 한 번만 부른다). 입력 없는 방법이 안 되면
        포그라운드 잠금을 풀려고 Alt 누르기·떼기를 **입력 액터로** 넣는다 — 임대권을 가진 실행
        (그래프에 입력 노드가 있어 액터가 붙은 실행)만, 게이트가 열려 있을 때만, 입력 기록·복구와
        함께. 액터가 없으면(입력 없는 그래프 — 키보드 입력이 없으니 포그라운드도 필요 없다) Alt 없이
        끝난다."""
        try:
            hwnd = self.resolve(window).hwnd
        except PlatformError:
            return False
        actor = self._actor
        tap = None if actor is None else (lambda: _tap_alt(actor, step))
        return wins.activate(hwnd, tap_alt=tap)

    # ------------------------------------------------------------ 프로세스

    def launch(self, path: str, args: Sequence[str], cwd: str | None) -> ProcessRef:
        proc = processes.launch(path, list(args), cwd=cwd)
        with self._lock:
            self._processes[proc.pid] = proc
        return ProcessRef(proc.pid, Path(path).name)

    def _process(self, process: ProcessRef) -> Process:
        with self._lock:
            proc = self._processes.get(process.pid)
        if proc is not None:
            return proc
        try:
            proc = Process.open(process.pid, terminate=True)
        except ProcessLookupError as exc:
            raise EngineError(
                "process_gone", f"프로세스 {process.pid}를 열 수 없다: {exc}"
            ) from exc
        with self._lock:
            return self._processes.setdefault(process.pid, proc)

    def close_process(self, process: ProcessRef, force_after_ms: int) -> bool:
        return processes.close(self._process(process), force_after_ms)

    def _pids(self, process: ProcessRef) -> list[int]:
        return processes.candidate_pids(process.pid, self.job)

    def process_window(
        self, process: ProcessRef, title: str | None, limits: ObservationLimits | None
    ) -> WindowRef | None:
        hwnd = wins.find_window(title=title, pids=self._pids(process))
        if hwnd is not None or limits is None:
            return None if hwnd is None else self._ref(hwnd)
        # 창이 뜨기를 노드 기한까지 기다린다 (설정 기한은 걸지 않는다: 게임 시작은 캡처보다 길다)
        node_ms = limits.node_ms if limits.node_ms is not None else limits.run_ms or 0
        deadline = ObservationDeadline(
            max(1, node_ms) + 1000, node_ms=limits.node_ms, run_ms=limits.run_ms, check=limits.check
        )
        while True:
            deadline.ensure(_window_timeout)
            hwnd = wins.find_window(title=title, pids=self._pids(process))
            if hwnd is not None:
                return self._ref(hwnd)
            time.sleep(min(_POLL_S, deadline.remaining_s()))


def _ref_of(binding: WindowBinding, title: str) -> WindowRef:
    """이 실행의 바인딩 → 완전한 창 참조 (HWND·PID·생성 시각·바인딩 ID)."""
    return WindowRef(
        handle=binding.hwnd,
        title=title,
        pid=binding.pid,
        process_created=str(binding.process_created),
        binding=binding.binding_id,
    )


def _window_timeout() -> BaseException:
    return ObservationTimeout("창이 기한 안에 뜨지 않았다")


def _tap_alt(actor: InputActor, step: str | None) -> bool:
    """포그라운드 잠금을 풀 Alt 하나 (입력 액터: 게이트가 닫혔거나 넣지 못하면 False — 액터가 누른
    키는 실패 정리·복구가 뗀다)."""
    try:
        actor.tap_unguarded("alt", step=step)
    except Exception, Cancelled:
        # 게이트가 닫혔으면(취소·마무리) 넣지 않았다 — 취소는 다음 확인 지점이 알린다
        return False
    return True
