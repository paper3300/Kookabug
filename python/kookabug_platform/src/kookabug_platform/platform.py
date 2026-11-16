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
from dataclasses import dataclass, replace
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
from kookabug_core.win import Job, Process, ProcessId, is_alive
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
FAMILY_REFRESH_S = 0.5
"""대상 창 캡처 때 게임 가족 기록을 다시 확인하는 최소 간격 (UX9 3)."""


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
        self._families: dict[int, processes.GameFamily] = {}
        """따라가기 대상 게임 PID → 그 게임의 가족 기록 (UX9 3)."""
        self._refreshed: dict[int, float] = {}
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
        if self._families:
            self._touch_family(binding.pid)
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
            # 관측의 `Match`가 같은 HWND에 새로 뜬 창의 입력으로 통과하지 않게). 호출자 참조가
            # 바로 그 바인딩으로 풀렸으면 바인딩 이름은 호출자의 것(다른 실행이 만든 참조도
            # 같은 창이면 실행기 프레임 확인을 지난다 — UX9 2)
            window=_captured_ref(info.window, binding, window),
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

    def window_title(self, window: WindowRef) -> str:
        """그 창의 지금 제목만 (`window_info`보다 가볍다 — 붙여 실행 기록 가림이 자주 읽는다,
        UX7)."""
        from kookabug_platform.win32.api import DEFAULT_API

        return DEFAULT_API.window_title(self.resolve(window).hwnd)

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

    def focus_before_input(self, window: WindowRef, step: str | None) -> bool:
        """입력 노드 직전 창 앞으로 (UX4, 노드 "실행 전" 옵션). 입력 임대권을 쥔 실행(액터가 붙은
        실행)에서만 가져온다 — 액터가 없으면 아무것도 하지 않고 False. 방법은 `bring_forward`와
        같다(입력 없는 방법 → 안 되면 액터를 거친 Alt, 게이트·입력 기록·복구 그대로). 이미 앞이면
        아무 입력 없이 끝난다."""
        actor = self._actor
        if actor is None:
            return False
        try:
            hwnd = self.resolve(window).hwnd
        except PlatformError:
            return False
        return wins.activate(hwnd, tap_alt=lambda: _tap_alt(actor, step))

    # ------------------------------------------------------------ 프로세스

    def launch(self, path: str, args: Sequence[str], cwd: str | None) -> ProcessRef:
        proc = processes.launch(path, list(args), cwd=cwd)
        with self._lock:
            self._processes[proc.pid] = proc
        return ProcessRef(proc.pid, Path(path).name)

    def _process(self, process: ProcessRef) -> Process:
        """닫을 프로세스 핸들. `created`가 있으면(창에서 만든 참조 — UX12 검수 1 High 5) 같은
        생성 시각의 프로세스일 때만 — 그 PID를 다시 쓴 다른 프로세스면 `process_gone`. 확인은 연
        핸들로 하므로 확인과 종료 사이에 PID가 바뀌지 않는다."""
        expected: int | None = None
        if process.created:
            if not process.created.isdigit():
                raise EngineError("process_gone", f"프로세스 {process.pid}의 생성 시각을 모른다")
            expected = int(process.created)
        with self._lock:
            proc = self._processes.get(process.pid)
        if proc is not None:
            if expected is not None and proc.created != expected:
                raise EngineError(
                    "process_gone", f"PID {process.pid}는 다른 프로세스다 (생성 시각이 다름)"
                )
            return proc
        target: ProcessId | int = (
            process.pid if expected is None else ProcessId(process.pid, expected)
        )
        try:
            proc = Process.open(target, terminate=True)
        except ProcessLookupError as exc:
            raise EngineError(
                "process_gone", f"프로세스 {process.pid}를 열 수 없다: {exc}"
            ) from exc
        with self._lock:
            return self._processes.setdefault(process.pid, proc)

    def close_process(self, process: ProcessRef, force_after_ms: int) -> bool:
        return processes.close(self._process(process), force_after_ms)

    def _launched(self, process: ProcessRef) -> bool:
        with self._lock:
            return process.pid in self._processes

    def _pids(self, process: ProcessRef) -> list[int]:
        """그 프로세스의 창을 찾을 PID들: 이 실행이 띄운 프로세스면 실행 Job 안 전부(런처가 띄운
        아래 프로세스), 아니면(붙여 실행의 게임) 그 프로세스 하나."""
        if not self._launched(process):
            return [process.pid]
        return processes.candidate_pids(process.pid, self.job)

    def _main_window(self, process: ProcessRef, title: str | None) -> int | None:
        """주 창(보이고·최소화·cloaked 아님 중 클라이언트 넓이가 가장 큰 창, UX9 A). 쓸 수 있는 창이
        없으면 지금처럼 첫 창."""
        pids = self._pids(process)
        found = wins.main_window(title=title, pids=pids)
        return found if found is not None else wins.find_window(title=title, pids=pids)

    def process_window(
        self, process: ProcessRef, title: str | None, limits: ObservationLimits | None
    ) -> WindowRef | None:
        if self._launched(process):
            self.refresh_family(process)  # 가족 기록을 미리 (UX9 3)
        hwnd = self._main_window(process, title)
        if hwnd is not None or limits is None:
            return None if hwnd is None else self._ref(hwnd)
        # 창이 뜨기를 노드 기한까지 기다린다 (설정 기한은 걸지 않는다: 게임 시작은 캡처보다 길다)
        node_ms = limits.node_ms if limits.node_ms is not None else limits.run_ms or 0
        deadline = ObservationDeadline(
            max(1, node_ms) + 1000, node_ms=limits.node_ms, run_ms=limits.run_ms, check=limits.check
        )
        while True:
            deadline.ensure(_window_timeout)
            if self._launched(process):
                self.refresh_family(process)
            hwnd = self._main_window(process, title)
            if hwnd is not None:
                return self._ref(hwnd)
            time.sleep(min(_POLL_S, deadline.remaining_s()))

    # ------------------------------------------------------------ 창 따라가기 (UX9 A)

    def _family(self, process: ProcessRef, created: str) -> list[ProcessId]:
        """따라가기 소유 범위 (UX9 3): 그 게임의 **기록해 둔 가족**(처음 정체 + 확인된 자손) 중 지금
        살아 있는 것. 부를 때마다 가족 기록을 한 번 확인·갱신한다(`process.family` 규칙 — 살아 있는
        가족 밑 새 자손만, 사후 추정 없음). 실행 Job 전체가 아니다. 처음 정체는 띄운 프로세스면 그
        핸들의 생성 시각, 아니면(붙여 실행) 처음 붙은 창의 생성 시각(`created`, 같은 PID). 정체를
        모르면 빈 목록 (식별 불능 = 따라가지 않음)."""
        with self._lock:
            proc = self._processes.get(process.pid)
            record = self._families.get(process.pid)
        alive: bool
        if proc is not None:
            raw = getattr(proc, "created", None)
            made = raw if isinstance(raw, int) and raw > 0 else None
            try:
                alive = bool(proc.alive())
            except Exception:
                alive = False
        else:
            made = record.root.created if record is not None else None
            if made is None and created.isdigit():
                made = int(created)
            alive = made is not None and is_alive(ProcessId(process.pid, made))
        if made is None:
            return []
        if record is None or record.root.created != made:
            record = processes.GameFamily(ProcessId(process.pid, made))
            with self._lock:
                self._families[process.pid] = record
        try:
            return processes.family(record, alive)
        except Exception:
            return [record.root] if alive else []

    def refresh_family(self, process: ProcessRef) -> None:
        """띄운 게임의 가족 기록을 미리 갱신한다 (창을 기다리는 동안 — 런처가 본 게임을 띄우고
        끝나기 전에 자손을 기록해 두게, UX9 3). 실패는 무시한다."""
        with contextlib.suppress(Exception):
            self._family(process, "")

    def _touch_family(self, pid: int) -> None:
        """그 PID가 가족 기록(처음 정체·자손)에 든 게임이면 그 기록을 갱신한다 (대상 창 캡처 때,
        `FAMILY_REFRESH_S`에 한 번 — 본 창이 뜨기 전에 런처의 새 자손을 기록해 두게, UX9 3)."""
        now = time.monotonic()
        with self._lock:
            due = [
                root
                for root, record in self._families.items()
                if (pid == root or pid in record.members)
                and now - self._refreshed.get(root, 0.0) >= FAMILY_REFRESH_S
            ]
            for root in due:
                self._refreshed[root] = now
        for root in due:
            self.refresh_family(ProcessRef(root))

    def process_running(self, process: ProcessRef, created: str) -> bool:
        """그 게임 프로세스(PID+생성 시각)나 그 자손이 아직 살아 있나 (UX9 2). 실행 Job 안의 다른
        프로세스는 보지 않는다. 정체를 모르면 False."""
        return bool(self._family(process, created))

    def follow_window(self, process: ProcessRef, created: str) -> WindowRef | None:
        """그 게임 프로세스와 그 자손의 지금 주 창 (UX9 2). 열거 때 그 HWND의 PID·생성 시각과
        바인딩(`_ref`)의 PID·생성 시각이 같고 허용 집합 안일 때만 돌려준다 — 열거와 바인딩 사이에
        다른 프로세스가 HWND를 다시 쓰면 버린다(부른 쪽이 기한 안에서 다시 찾는다). 식별 불능도
        버린다."""
        allowed = {(p.pid, p.created) for p in self._family(process, created)}
        if not allowed:
            return None
        from kookabug_platform.win32.api import DEFAULT_API

        hwnd = wins.main_window(title=None, pids=sorted({pid for pid, _ in allowed}))
        if hwnd is None:
            return None
        try:
            pid = DEFAULT_API.window_pid(hwnd)
            made = DEFAULT_API.process_created(pid) if pid else None
        except Exception:
            return None
        if made is None or (pid, made) not in allowed:
            return None
        try:
            ref = self._ref(hwnd)
        except PlatformError:
            return None
        bound = int(ref.process_created) if ref.process_created.isdigit() else None
        if ref.handle != hwnd or ref.pid != pid or bound != made or not ref.binding:
            return None
        return ref

    def window_alive(self, window: WindowRef) -> bool:
        """그 창 참조가 이 실행에서 아직 쓸 수 있나 (바인딩 확인 — 닫혔거나 다른 창이면 False)."""
        try:
            self.resolve(window)
        except PlatformError:
            return False
        return True


def _ref_of(binding: WindowBinding, title: str) -> WindowRef:
    """이 실행의 바인딩 → 완전한 창 참조 (HWND·PID·생성 시각·바인딩 ID)."""
    return WindowRef(
        handle=binding.hwnd,
        title=title,
        pid=binding.pid,
        process_created=str(binding.process_created),
        binding=binding.binding_id,
    )


def _captured_ref(captured: WindowBinding, asked: WindowBinding, window: WindowRef) -> WindowRef:
    """캡처한 프레임의 창 참조. 캡처가 요청 참조를 푼 바인딩 그대로였으면 요청 참조의 바인딩 이름을
    쓰고, 아니면 실제 바인딩 (실행기가 다르다고 보고 버린다)."""
    ref = _ref_of(captured, window.title)
    if captured.binding_id == asked.binding_id and window.binding:
        return replace(ref, binding=window.binding)
    return ref


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
