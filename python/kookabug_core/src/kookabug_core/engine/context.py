"""실행 ctx: 노드가 받는 `Context`의 core 구현과, 한 실행이 같이 쓰는 상태(`Runtime`).

노드 함수는 이 ctx를 SDK `guard()`로 감싼 것을 받는다 (순수 노드는 `PureContext`, exec 노드는
선언한 효과만 쓰는 `EffectContext`). 그래서 순수 노드 제한은 `fake_context`와 같은 래퍼 하나로
걸린다.

**대상 창** (M1 2.8): 스텝 ctx의 창은 만들 때 정한다 — 그 스텝의 공통 입력 `in.window`, 없으면 그
스텝 시작 때의 호출 프레임 현재 창. 캡처·입력 요청은 이 창으로 간다. `set_window`는 호출 프레임의
현재 창만 바꾼다(다음 스텝부터).

**관측** (M1 2.6): `capture`·`vision.find`·`ocr.read`·`process.find_window`는 노드 기한
(`deadline`)이 이미 지났으면 시작하지 않고 `ObservationTimeout`. 플랫폼에는 `ObservationLimits`
(설정 기한 `run.capture_timeout_ms`, 노드 기한·전체 기한의 남은 시간, 취소 확인)를 넘기고,
플랫폼이 원인별 예외(노드 기한 → `ObservationTimeout`, 설정 기한 → `capture_timeout`, 전체 기한
→ `DeadlineExceeded`)를 낸다. 플랫폼에 그 기능이 없으면 `platform_unavailable`.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import EllipsisType
from typing import Any, Final, Protocol, cast, runtime_checkable

from kookabug_core.canonical import loads_strict
from kookabug_core.engine.cancel import CancelToken, DeadlineExceeded
from kookabug_core.engine.debug import PauseCounter, PausePoint, StepPoint
from kookabug_core.engine.errors import EngineError
from kookabug_core.engine.frame import Frame
from kookabug_core.engine.invoker import NodeInvoker
from kookabug_core.engine.provenance import CaptureEpochs, Epochs, Origin, StepTrace
from kookabug_core.ir import Node
from kookabug_core.loader import Program
from kookabug_core.record.artifacts import ArtifactStore, FindEvidence, Recorder, StagedFrame
from kookabug_core.registry import Registry
from kookabug_core.workspace import SettingLookup
from kookabug_sdk.context import (
    ArtifactsApi,
    Clock,
    Deadline,
    InputApi,
    LogApi,
    OcrApi,
    ProcessApi,
    VarsApi,
    VisionApi,
    Where,
    WindowsApi,
)
from kookabug_sdk.errors import ObservationTimeout, StaleObservation
from kookabug_sdk.types import (
    FrameRef,
    Image,
    Match,
    OcrResult,
    Point,
    ProcessRef,
    Rect,
    Secret,
    SecretMessage,
    Target,
    WindowInfo,
    WindowRef,
)

__all__ = [
    "DEFAULT_CAPTURE_TIMEOUT_MS",
    "FOREGROUND_NOT_ACQUIRED",
    "OCR_NODE_TYPES",
    "ArtifactStore",
    "FindReportingPlatform",
    "ForegroundPlatform",
    "ObservationLimits",
    "ObservingPlatform",
    "PixelPlatform",
    "Platform",
    "PreparingPlatform",
    "Runtime",
    "StepContext",
    "StepInputPlatform",
    "WindowPlatform",
]

DEFAULT_CAPTURE_TIMEOUT_MS: Final = 2000
"""`run.capture_timeout_ms` 기본값 (조율자 결정 Q2)."""
FOREGROUND_NOT_ACQUIRED: Final = "foreground_not_acquired"
"""실행 첫 대상 창을 앞으로 가져오지 못했을 때 `warn` 로그 메시지의 머리 (실행은 계속한다)."""
OBSERVATIONS_KEPT: Final = 256
"""캡처 시점 관측을 기억하는 최근 캡처 수 (OCR 결과에 실을 때 찾는다)."""
_WAIT_SLICE_MS: Final = 50
"""멈출 수 있는 기다림의 한 조각 (요청·취소는 조건 변수로 바로 깨우고, 이것은 안전판이다)."""


@dataclass(frozen=True, slots=True)
class ObservationLimits:
    """관측 호출 하나의 기한 재료 (M1 2.6). 플랫폼이 원인별 기한으로 바꾼다.

    `config_ms`는 설정 기한, `node_ms`는 노드가 넘긴 기한의 남은 시간(없으면 None), `run_ms`는 전체
    기한의 남은 시간(없으면 None), `check`는 취소·전체 기한 확인(취소됐으면 예외).
    """

    config_ms: int
    node_ms: int | None = None
    run_ms: int | None = None
    check: Callable[[], None] | None = None


class Platform(Protocol):
    """게임과 만나는 쪽: 캡처와 입력. M0a는 `FakePlatform`, M1이 Windows 구현을 붙인다."""

    @property
    def input(self) -> InputApi: ...
    def capture(self, window: WindowRef | None, region: Rect | None) -> Image: ...


class InputObserver(Protocol):
    """입력 요청을 만든 스텝의 관측 (`inputs.service.Observer`와 같은 모양)."""

    def rematch(self, match: Match) -> Match | None: ...
    def note(self, message: str) -> None: ...
    def observation_stale(self, match: Match) -> str | None: ...
    def coordinate_stale(self, at: Point | Rect) -> str | None: ...


@runtime_checkable
class StepInputPlatform(Protocol):
    """스텝마다 입력 경로를 주는 플랫폼 (runner: 공용 입력 서비스 → 입력 액터 큐).

    플랫폼이 이것을 구현하면 `ctx.input`은 `input`이 아니라 `input_for(스텝, 그 스텝의 창, 관측)`
    으로 간다. 창은 그 스텝 ctx를 만들 때 정한 것이라 요청 뒤에 바뀌지 않는다. `observer`는
    재검증의 다시 찾기·기록에 쓴다. `sleep`은 누르고 있기의 기다림(런타임 `wait_hold` — 취소로만
    깨고 멈춤 요청은 보지 않는다).
    """

    def input_for(
        self,
        step: str,
        window: WindowRef | None,
        observer: InputObserver,
        sleep: Callable[[int], None],
    ) -> InputApi: ...


@runtime_checkable
class PixelPlatform(Protocol):
    """캡처 픽셀을 프레임 저장소에 두는 플랫폼 (M1 2.7).

    실행에 프레임 저장소(`Recorder.frames`)가 있으면 `ctx.capture`는 `capture`가 아니라 이것을
    부르고, 노드에는 픽셀 없는 참조 이미지를 준다. 픽셀은 `capture_id`로 저장소에 등록된다.
    """

    def capture_staged(
        self, window: WindowRef | None, region: Rect | None, limits: ObservationLimits
    ) -> tuple[Image, StagedFrame]: ...


@runtime_checkable
class FindReportingPlatform(Protocol):
    """찾기 결과와 함께 상위 후보·임계값을 주는 플랫폼 (매칭 후보 증거, M3 2.6). 후보를 모르면
    두 번째 값이 None."""

    def find_report(
        self, image: Image, target: Target, *, region: Rect | None, limits: ObservationLimits
    ) -> tuple[Match | None, FindEvidence | None]: ...


@runtime_checkable
class ObservingPlatform(Protocol):
    """찾기·비교·OCR을 주는 플랫폼 (M1 2.5·2.6). 참조 이미지면 픽셀은 프레임 저장소에 있다."""

    def find(
        self, image: Image, target: Target, *, region: Rect | None, limits: ObservationLimits
    ) -> Match | None: ...
    def diff(self, a: Image, b: Image, *, region: Rect | None) -> float: ...
    def read_text(
        self, image: Image, *, region: Rect | None, sensitive: bool, limits: ObservationLimits
    ) -> OcrResult: ...


OCR_NODE_TYPES: Final = frozenset(
    {"core.assert.text", "core.ocr.read", "core.ocr.wait_text", "core.ocr.click_text"}
)
"""글자를 읽는 코어 노드. runner는 이 노드를 쓰는 실행의 시작 때 OCR 엔진을 미리 준비하고, 실행기는
이 노드 함수를 부르기 전에 준비가 끝나기를 기다린다 (`PreparingPlatform`)."""


@runtime_checkable
class PreparingPlatform(Protocol):
    """노드 함수를 부르기 전에 그 노드가 쓸 엔진 준비(OCR 모델·세션)를 기다리는 플랫폼 (M2 사람
    확인 S 결함 ②). 실행기가 시도마다 노드 함수 직전(노드가 자기 기한을 만들기 전)에 부르므로
    준비 시간은 노드 기한도 설정 기한도 먹지 않는다. 기다리는 동안 `check`(취소·전체 기한)를
    본다."""

    def before_node(self, node_type: str, check: Callable[[], None]) -> None: ...


@runtime_checkable
class WindowPlatform(Protocol):
    """창·프로세스를 주는 플랫폼 (M1 2.2). 돌려주는 창 참조에는 이 실행의 바인딩이 붙어 있다."""

    def find_window(
        self, title: str | None, process_name: str | None, owned: bool
    ) -> WindowRef | None: ...
    def window_info(self, window: WindowRef) -> WindowInfo: ...
    def set_client_size(self, window: WindowRef, width: int, height: int) -> bool: ...
    def activate(self, window: WindowRef) -> bool | None:
        """최선 노력으로 앞으로. 포그라운드가 됐으면 True, 못 가져왔으면 False, 모르면 None."""
        ...

    def launch(self, path: str, args: Sequence[str], cwd: str | None) -> ProcessRef: ...
    def close_process(self, process: ProcessRef, force_after_ms: int) -> bool: ...
    def process_window(
        self, process: ProcessRef, title: str | None, limits: ObservationLimits | None
    ) -> WindowRef | None:
        """`limits`가 None이면 지금 있는 창만 본다. 있으면 노드 기한까지 기다린다."""
        ...


class _WindowState(Protocol):
    @property
    def backend(self) -> str: ...
    @property
    def client_size(self) -> tuple[int, int]: ...
    @property
    def dpi(self) -> int: ...


@runtime_checkable
class ForegroundPlatform(Protocol):
    """실행 첫 창을 앞으로 가져오는 플랫폼 (D1). 노드의 `activate`(입력 없는 최선 노력)와 달리
    포그라운드 잠금을 풀 입력(runner 입력 액터를 거친 Alt)까지 쓸 수 있다. 실행기가 실행에서 처음
    `set_window`할 때 한 번만 부른다. 없으면 `activate`를 쓴다."""

    def bring_forward(self, window: WindowRef, step: str | None) -> bool | None: ...


@runtime_checkable
class _StatePlatform(Protocol):
    """지금 창의 캡처 방식·클라이언트 크기·DPI를 주는 플랫폼 (공용 입력 서비스의 `state`와 같다)."""

    def state(self, window: WindowRef) -> _WindowState: ...


@dataclass(frozen=True, slots=True)
class Mark:
    """경과를 재기 시작한 자리: 실제 시계·기한 시계 값과 그때까지 멈춘 횟수."""

    wall: int
    active: int
    pauses: int


@dataclass(eq=False)
class Runtime:
    """한 실행의 공용 상태: 프로그램, 레지스트리, 노드 실행 경계, 플랫폼, 시계, 취소, 전체 기한,
    이벤트, 기록 정책(`recorder`), 관측의 설정 기한(`capture_timeout_ms`).

    **시계 둘** (M3 2.2): `clock`은 기한 시계(노드 기한·전체 기한·기다림 — runner에서는 멈춘 시간을
    뺀 활성 시계), `wall`은 경과 시계(`duration_ms`, 없으면 `clock`). `pause_point`가 있으면 코어
    노드의 `ctx.sleep`이 폴링 확인 지점이 된다(`wait_pausable`)."""

    run: str
    program: Program
    registry: Registry
    invoker: NodeInvoker
    platform: Platform
    recorder: Recorder
    clock: Clock
    cancel: CancelToken
    deadline: Deadline
    deadline_ms: int
    emit_to: Callable[[dict[str, Any]], None]
    on_setting: Callable[[SettingLookup], None] | None = None
    """노드가 `ctx.setting()`으로 실제로 읽은 설정 (runner가 실행 조건 `run.json`에 남긴다)."""
    capture_timeout_ms: int = DEFAULT_CAPTURE_TIMEOUT_MS
    observations: OrderedDict[int, tuple[FrameRef, WindowRef | None]] = field(
        default_factory=OrderedDict[int, tuple[FrameRef, WindowRef | None]]
    )
    """캡처 번호 → 그 캡처 시점의 관측(캡처 방식·클라이언트 크기·DPI, 창). 최근
    `OBSERVATIONS_KEPT`개 — OCR 결과에 실어 줄 `Match`의 재검증에 쓴다."""
    wall: Clock | None = None
    pause_point: PausePoint | None = None
    epochs: Epochs = field(default_factory=Epochs)
    """관측 세대 (재개마다 1 오름, M3 2.4). runner는 멈춤 게이트와 같은 것을 준다."""
    capture_epochs: CaptureEpochs = field(default_factory=CaptureEpochs)
    """캡처 번호 → 세대 (입력 서비스의 재검증이 찾는다)."""
    on_observed: Callable[[FrameRef], None] | None = None
    """실행에서 처음 관측한 창(캡처 방식·클라이언트 크기·DPI)을 받는다 (`run.json.observed`, M3
    2.6). 한 번만 불린다."""
    observed: FrameRef | None = None
    """처음 관측."""
    foreground_tried: bool = False
    """이 실행에서 현재 창이 처음 정해질 때 그 창을 앞으로 가져오기를 했다 (D1, 한 번만)."""

    @property
    def epoch(self) -> int:
        """지금 관측 세대."""
        return self.epochs.current

    def note_capture(self, capture_id: int | None, source: str) -> Origin:
        """캡처 하나: 그 번호의 세대를 표에 적고 그 관측의 출처를 돌려준다."""
        epoch = self.epochs.current
        if capture_id is not None:
            self.capture_epochs.note(capture_id, epoch)
        return Origin(epoch, source)

    @property
    def wall_clock(self) -> Clock:
        """경과 시계 (따로 주지 않았으면 기한 시계)."""
        return self.clock if self.wall is None else self.wall

    def _pauses(self) -> int:
        clock = self.clock
        return clock.pauses if isinstance(clock, PauseCounter) else 0

    def mark(self) -> Mark:
        return Mark(self.wall_clock.now_ms(), self.clock.now_ms(), self._pauses())

    def elapsed(self, mark: Mark) -> tuple[int, int | None]:
        """`mark`부터의 (실제 경과, 멈춘 시간을 뺀 경과). 그 사이 멈춤이 없었으면 뒤는 None."""
        wall = max(0, self.wall_clock.now_ms() - mark.wall)
        if self._pauses() == mark.pauses:
            return wall, None
        return wall, max(0, min(wall, self.clock.now_ms() - mark.active))

    def note_observation(self, capture_id: int, frame: FrameRef, window: WindowRef | None) -> None:
        self.observations[capture_id] = (frame, window)
        while len(self.observations) > OBSERVATIONS_KEPT:
            self.observations.popitem(last=False)
        if self.observed is None:
            self.observed = frame
            if self.on_observed is not None:
                self.on_observed(frame)

    def limits(self, deadline: Deadline | None) -> ObservationLimits:
        """관측 호출 하나의 기한. 노드 기한이 이미 지났으면 `ObservationTimeout`(시작하지 않음)."""
        if deadline is not None and deadline.passed:
            raise ObservationTimeout("노드 기한이 지나 관측을 시작하지 않았다")
        self.check()
        return ObservationLimits(
            config_ms=self.capture_timeout_ms,
            node_ms=None if deadline is None else deadline.remaining_ms,
            run_ms=self.deadline.remaining_ms,
            check=self.check,
        )

    def emit(self, event: Mapping[str, Any]) -> None:
        self.emit_to({**event, "run": self.run})

    def check(self) -> None:
        """취소·전체 기한 확인. 스텝 시작, 노드 호출 직전·직후, `ctx`의 캡처·입력 앞뒤,
        `ctx.check_cancel()`, `ctx.sleep()`이 부른다."""
        self.cancel.check()
        if self.deadline.passed:
            raise DeadlineExceeded(f"테스트 전체 기한 {self.deadline_ms}ms를 넘었다")

    def wait_hold(self, ms: int) -> None:
        """멈춤 요청을 보지 않는 기다림 (입력 서비스의 누르고 있기·드래그 지속). 취소로만 깬다 —
        키를 누른 채 멈추지 않는다. 그 사이 온 멈춤 요청은 다음 확인 지점에서 확정된다. 전체
        기한을 넘는 만큼은 기다리지 않고 기한에서 멈춘다."""
        self.check()
        if ms < 0:
            raise ValueError(f"sleep 시간은 0 이상이다: {ms}")
        remaining = self.deadline.remaining_ms
        if ms >= remaining:
            self.clock.sleep(remaining)
            self.cancel.check()  # 기다리는 동안 취소됐으면 그 사유로
            raise DeadlineExceeded(f"테스트 전체 기한 {self.deadline_ms}ms를 넘었다")
        self.clock.sleep(ms)
        self.check()

    def wait_pausable(
        self, ms: int, point: StepPoint, on_resume: Callable[[], None] | None = None
    ) -> None:
        """멈출 수 있는 기다림 (코어 노드의 `ctx.sleep`: 대기 폴링·`flow.delay`). 취소·멈춤
        요청으로 바로 깬다. 멈춤 요청이면 이 자리에서 멈춤을 확정하고(`debug.pause where: poll`),
        재개 뒤 남은 활성 시간만큼 마저 기다린다. 확인 지점이 없는 실행이면 `wait_hold`와 같다.

        재개(세대가 오름) 직후 `on_resume()`을 부른다 — 다음 관측·입력·출구 선택 전에 그 스텝의
        입력을 다시 검사하고 노드 안 관측을 무효로 표시한다(M3 2.4 "폴링 재개"). 던지면 기다림도
        거기서 끝난다."""
        gate = self.pause_point
        if gate is None:
            self.wait_hold(ms)
            return
        self.check()
        if ms < 0:
            raise ValueError(f"sleep 시간은 0 이상이다: {ms}")
        end = self.clock.now_ms() + ms
        while True:
            left = end - self.clock.now_ms()
            if left <= 0:
                return
            # 기한 시계로 남은 만큼(전체 기한까지). 멈춘 동안 기한 시계는 머물므로 재개 뒤
            # 남은 활성 시간만 기다린다. 조각은 짧게 끊어 늦은 깨움을 놓치지 않는다
            span = min(left, self.deadline.remaining_ms, _WAIT_SLICE_MS)
            if gate.wait_request(span / 1000):
                self.check()
                before = self.epochs.current
                gate.at_poll(point)
                if on_resume is not None and self.epochs.current != before:
                    on_resume()
            self.check()


class FrameVars:
    """호출 프레임 변수. 값과 관측 출처를 같이 저장한다 (M3 2.4 "변수").

    읽은 값의 출처는 그 스텝 바닥에 합친다. `refuse_stale`이면(예외 목록이 아닌 exec 노드 — 코어든
    워커 RPC든) 지금 세대보다 오래된 관측값을 돌려주지 않고 `StaleObservation`(처리되지 않은 fail).
    순수 노드(`var.get`)는 돌려주고 출처만 남긴다 — 그 값을 받는 스텝의 입력 검사가 정한다.
    쓰는 값에는 지금 스텝 바닥을 출처로 붙인다(변수에서 읽은 관측을 가공해 다시 써도 옛 값이다).
    """

    def __init__(self, ctx: StepContext, *, refuse_stale: bool) -> None:
        self._ctx = ctx
        self._frame = ctx.frame
        self._refuse = refuse_stale

    def get(self, name: str, default: Any = ...) -> Any:
        values = self._frame.vars
        if name not in values:
            if default is ...:
                raise KeyError(f"변수 '{name}'이(가) 없다")
            return default
        origin = self._frame.var_origins.get(name)
        current = self._ctx.runtime.epoch
        if self._refuse and origin is not None and origin.stale(current):
            exc = StaleObservation(
                f"변수 '{name}'은(는) 디버거 재개 전 관측('{origin.source}', 세대 {origin.epoch} "
                f"< 지금 {current})이다 — 멈춘 동안 화면이 바뀌었을 수 있어 쓰지 않는다"
            )
            self._ctx.stale = exc
            raise exc
        self._ctx.trace.note(origin)
        return values[name]

    def has(self, name: str) -> bool:
        return name in self._frame.vars

    def set(self, name: str, value: Any) -> None:
        self._frame.vars[name] = value
        self._frame.var_origins[name] = self._ctx.trace.floor


class StepLog:
    """`ctx.log` → `log` 이벤트. 메시지는 `str()`로 남긴다. 비밀값은 `record.redact_secrets`가 켜진
    실행만 가리고, 아니면 원문이다 (D3)."""

    def __init__(self, runtime: Runtime, step: str, node: str) -> None:
        self._runtime = runtime
        self._step = step
        self._node = node

    def _emit(self, level: str, message: object) -> None:
        redact = self._runtime.recorder.redact_secrets
        if isinstance(message, Secret) and not redact:
            text = message.reveal()
        elif isinstance(message, SecretMessage):
            text = message.masked if redact else message.raw
        else:
            text = str(message)
        self._runtime.emit(
            {
                "event": "log",
                "level": level,
                "message": text,
                "node": self._node,
                "step": self._step,
            }
        )

    def debug(self, message: object) -> None:
        self._emit("debug", message)

    def info(self, message: object) -> None:
        self._emit("info", message)

    def warn(self, message: object) -> None:
        self._emit("warn", message)

    def error(self, message: object) -> None:
        self._emit("error", message)


class StepArtifacts:
    """`ctx.artifacts`. 기록 정책으로 생략하면 None을 주고 artifacts 목록에 넣지 않는다."""

    def __init__(self, runtime: Runtime, step: str) -> None:
        self._runtime = runtime
        self._step = step

    def save(self, image: Image, name: str) -> str | None:
        return self._runtime.recorder.screenshot(self._step, image, name)


class CheckedInput:
    """입력 앞뒤로 취소·전체 기한을 확인한다 (취소된 뒤에는 게임에 입력하지 않는다)."""

    def __init__(self, runtime: Runtime, ctx: StepContext) -> None:
        self._runtime = runtime
        platform = runtime.platform
        self._input: InputApi = (
            platform.input_for(ctx.step, ctx.window, ctx, runtime.wait_hold)
            if isinstance(platform, StepInputPlatform)
            else platform.input
        )

    def click(self, at: Where, *, button: str = "left", count: int = 1) -> None:
        self._runtime.check()
        self._input.click(at, button=button, count=count)
        self._runtime.check()

    def drag(self, start: Where, end: Where, *, duration_ms: int = 0, button: str = "left") -> None:
        self._runtime.check()
        self._input.drag(start, end, duration_ms=duration_ms, button=button)
        self._runtime.check()

    def scroll(self, at: Where, amount: int) -> None:
        self._runtime.check()
        self._input.scroll(at, amount)
        self._runtime.check()

    def key(self, key: str, *, hold_ms: int = 0) -> None:
        self._runtime.check()
        self._input.key(key, hold_ms=hold_ms)
        self._runtime.check()

    def type_text(self, text: str | Secret) -> None:
        self._runtime.check()
        self._input.type_text(text)
        self._runtime.check()


class _Unavailable:
    """플랫폼에 없는 ctx 기능 (`ctx.vision`·`ocr`·`windows`·`process`). 부르면
    `platform_unavailable`."""

    def __init__(self, api: str) -> None:
        self._api = api

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        raise EngineError(
            "platform_unavailable", f"이 실행에서는 ctx.{self._api}.{name}을(를) 쓸 수 없다"
        )


class _StepVision:
    """`ctx.vision` → 플랫폼 찾기·비교. 찾기 앞뒤로 취소·기한을 본다."""

    def __init__(self, ctx: StepContext, platform: ObservingPlatform) -> None:
        self._ctx = ctx
        self._platform = platform

    def find(
        self,
        image: Image,
        target: Target,
        *,
        region: Rect | None = None,
        deadline: Deadline | None = None,
    ) -> Match | None:
        runtime = self._ctx.runtime
        limits = runtime.limits(deadline)
        platform = self._platform
        if isinstance(platform, FindReportingPlatform):
            # 매칭 후보: 그 스텝의 마지막 찾기를 남긴다 (fail 출구 증거, M3 2.6)
            found, report = platform.find_report(image, target, region=region, limits=limits)
            if report is not None:
                runtime.recorder.found(self._ctx.step, report)
        else:
            found = platform.find(image, target, region=region, limits=limits)
        runtime.check()
        return found

    def diff(self, a: Image, b: Image, *, region: Rect | None = None) -> float:
        runtime = self._ctx.runtime
        runtime.check()
        value = self._platform.diff(a, b, region=region)
        runtime.check()
        return value


class _StepOcr:
    def __init__(self, ctx: StepContext, platform: ObservingPlatform) -> None:
        self._ctx = ctx
        self._platform = platform

    def read(
        self,
        image: Image,
        *,
        region: Rect | None = None,
        sensitive: bool = False,
        deadline: Deadline | None = None,
    ) -> OcrResult:
        runtime = self._ctx.runtime
        limits = runtime.limits(deadline)
        result = self._platform.read_text(image, region=region, sensitive=sensitive, limits=limits)
        seen = runtime.observations.get(image.capture_id) if image.capture_id is not None else None
        if seen is not None:
            # 읽은 이미지의 캡처 시점 관측 (읽는 동안 창이 바뀌어도 그때 것 — 줄 Match 재검증용)
            result = replace(result, frame_info=seen[0], window=seen[1])
        # 기록: 스텝의 마지막 OCR 글자 (비밀값 가림이 켜진 실행에서 sensitive면 남기지 않고 생략
        # 이유만 — 스키마 6장. 꺼져 있으면 원문, D3)
        if isinstance(result.text, Secret):
            text = "" if runtime.recorder.redact_secrets else result.text.reveal()
        else:
            text = "" if sensitive and runtime.recorder.redact_secrets else result.text
        runtime.recorder.ocr_read(self._ctx.step, image, text, sensitive=sensitive)
        runtime.check()
        return result


class _StepWindows:
    def __init__(self, ctx: StepContext, platform: WindowPlatform) -> None:
        self._ctx = ctx
        self._platform = platform

    def find(
        self, title: str | None = None, process_name: str | None = None, *, owned: bool = False
    ) -> WindowRef | None:
        self._ctx.runtime.check()
        return self._platform.find_window(title, process_name, owned)

    def info(self, window: WindowRef) -> WindowInfo:
        self._ctx.runtime.check()
        return self._platform.window_info(window)

    def set_client_size(self, window: WindowRef, width: int, height: int) -> bool:
        self._ctx.runtime.check()
        return self._platform.set_client_size(window, width, height)

    def activate(self, window: WindowRef) -> None:
        self._ctx.runtime.check()
        if self._ctx.brought_forward == window:
            return  # 이 스텝의 set_window가 실행 첫 창으로 방금 앞으로 가져왔다
        self._platform.activate(window)


class _StepProcess:
    def __init__(self, ctx: StepContext, platform: WindowPlatform) -> None:
        self._ctx = ctx
        self._platform = platform

    def launch(self, path: str, args: Sequence[str] = (), cwd: str | None = None) -> ProcessRef:
        self._ctx.runtime.check()
        process = self._platform.launch(path, list(args), cwd)
        self._ctx.runtime.check()
        return process

    def close(self, process: ProcessRef, force_after_ms: int) -> bool:
        self._ctx.runtime.check()
        return self._platform.close_process(process, force_after_ms)

    def find_window(
        self, process: ProcessRef, title: str | None = None, *, deadline: Deadline | None = None
    ) -> WindowRef | None:
        runtime = self._ctx.runtime
        limits = runtime.limits(deadline) if deadline is not None else None
        if limits is None:
            runtime.check()
        found = self._platform.process_window(process, title, limits)
        runtime.check()
        return found


class _RecordedInput:
    """입력이 재검증으로 거부되면(`StaleObservation`) 스텝 ctx에 남긴다 — 노드가 그 예외를
    삼키고 정상으로 끝나도 실행기가 처리되지 않은 fail로 본다."""

    def __init__(self, ctx: StepContext, inner: InputApi) -> None:
        self._ctx = ctx
        self._inner = inner

    def _guarded(self, call: Callable[[], None]) -> None:
        try:
            call()
        except StaleObservation as exc:
            self._ctx.stale = exc
            raise

    def click(self, at: Where, *, button: str = "left", count: int = 1) -> None:
        self._guarded(lambda: self._inner.click(at, button=button, count=count))

    def drag(self, start: Where, end: Where, *, duration_ms: int = 0, button: str = "left") -> None:
        self._guarded(lambda: self._inner.drag(start, end, duration_ms=duration_ms, button=button))

    def scroll(self, at: Where, amount: int) -> None:
        self._guarded(lambda: self._inner.scroll(at, amount))

    def key(self, key: str, *, hold_ms: int = 0) -> None:
        self._guarded(lambda: self._inner.key(key, hold_ms=hold_ms))

    def type_text(self, text: str | Secret) -> None:
        self._guarded(lambda: self._inner.type_text(text))


class StepContext:
    """노드 하나(스텝 하나)의 ctx. 순수 노드는 그 노드를 소비하는 스텝의 ID를 쓴다.

    `config`는 선언 기본값을 채운 것이다 (`NodeDef.effective_config`). `window`를 주면(None 포함)
    그 스텝의 대상 창으로 확정된 것이고, 주지 않으면 지금 호출 프레임의 현재 창이다 — 만들 때
    정해진다. 실행기는 스텝 시작 때 한 번 정해 재시도마다 같은 값을 준다.
    """

    def __init__(
        self,
        runtime: Runtime,
        frame: Frame,
        node: Node,
        step: str,
        config: Mapping[str, Any],
        window: WindowRef | EllipsisType | None = ...,
        *,
        trace: StepTrace | None = None,
        pure: bool = False,
    ) -> None:
        self._runtime = runtime
        self._frame = frame
        self._node = node
        self._step = step
        self._config = config
        self._window = frame.current_window if isinstance(window, EllipsisType) else window
        self.trace: StepTrace = trace if trace is not None else StepTrace(node.type)
        """이 스텝(순수 노드면 그 계산 한 번)의 관측 출처 (M3 2.4)."""
        self._pure = pure
        self.stale: StaleObservation | None = None
        """이 스텝의 입력이 재검증으로 거부됐다 (노드가 삼켜도 처리되지 않은 fail)."""
        self.brought_forward: WindowRef | None = None
        """이 스텝의 `set_window`가 실행 첫 창으로 앞으로 가져온 창 (뒤따르는 `activate`는
        건너뛴다)."""

    @property
    def runtime(self) -> Runtime:
        return self._runtime

    @property
    def frame(self) -> Frame:
        return self._frame

    @property
    def config(self) -> Mapping[str, Any]:
        return self._config

    @property
    def step(self) -> str:
        """이 ctx의 스텝 ID (워커에 노드를 보낼 때 같이 보낸다)."""
        return self._step

    @property
    def run_remaining_ms(self) -> int:
        """테스트 전체 기한까지 남은 시간 (워커가 자기 쪽 `sleep`·`check_cancel`에 쓴다)."""
        return self._runtime.deadline.remaining_ms

    @property
    def window(self) -> WindowRef | None:
        return self._window

    @property
    def vars(self) -> VarsApi:
        return FrameVars(self, refuse_stale=not self._pure and not self.trace.exempt)

    @property
    def log(self) -> LogApi:
        return StepLog(self._runtime, self._step, self._node.id)

    @property
    def artifacts(self) -> ArtifactsApi:
        return StepArtifacts(self._runtime, self._step)

    @property
    def input(self) -> InputApi:
        return _RecordedInput(self, CheckedInput(self._runtime, self))

    @property
    def vision(self) -> VisionApi:
        platform = self._runtime.platform
        if isinstance(platform, ObservingPlatform):
            return _StepVision(self, platform)
        return cast(VisionApi, _Unavailable("vision"))

    @property
    def ocr(self) -> OcrApi:
        platform = self._runtime.platform
        if isinstance(platform, ObservingPlatform):
            return _StepOcr(self, platform)
        return cast(OcrApi, _Unavailable("ocr"))

    @property
    def windows(self) -> WindowsApi:
        platform = self._runtime.platform
        if isinstance(platform, WindowPlatform):
            return _StepWindows(self, platform)
        return cast(WindowsApi, _Unavailable("windows"))

    @property
    def process(self) -> ProcessApi:
        platform = self._runtime.platform
        if isinstance(platform, WindowPlatform):
            return _StepProcess(self, platform)
        return cast(ProcessApi, _Unavailable("process"))

    def set_window(self, window: WindowRef) -> None:
        """호출 프레임의 현재 창을 바꾼다 (다음 스텝부터). 이 스텝의 창·입력 요청은 그대로다.

        실행에서 처음 정하는 창이면 그 창을 한 번 앞으로 가져온다 (D1: 실행 시작 때 게임 창을
        앞으로). 못 가져와도 실행은 막지 않고 `warn` 로그를 남긴다 — 그 뒤 키보드 입력이
        포그라운드 확인에서 `window_not_foreground`로 알린다. 실행 **도중** 포커스를 잃은 창은 다시
        가져오지 않는다(U1).
        """
        self._frame.current_window = window
        runtime = self._runtime
        platform = runtime.platform
        if runtime.foreground_tried or not isinstance(platform, WindowPlatform):
            return
        runtime.foreground_tried = True
        self.brought_forward = window
        try:
            if isinstance(platform, ForegroundPlatform):
                acquired = platform.bring_forward(window, self._step)
            else:
                acquired = platform.activate(window)
        except Exception:
            acquired = False  # 창 문제는 다음 관측·입력이 알린다
        if acquired is False:
            runtime.emit(
                {
                    "event": "log",
                    "level": "warn",
                    "message": (
                        f"{FOREGROUND_NOT_ACQUIRED}: 실행 첫 대상 창 "
                        f"{window.title!r} (HWND {window.handle:#x})을(를) 앞으로 가져오지 "
                        "못했다 (다른 프로그램이 포그라운드를 쥐고 있을 수 있다). "
                        "키보드 입력 노드는 창이 앞에 올 때까지 window_not_foreground로 끝난다"
                    ),
                    "node": self._node.id,
                    "step": self._step,
                }
            )

    def capture(self, region: Rect | None = None, *, deadline: Deadline | None = None) -> Image:
        runtime = self._runtime
        limits = runtime.limits(deadline)
        platform = runtime.platform
        recorder = runtime.recorder
        if recorder.frames is not None and isinstance(platform, PixelPlatform):
            raw, staged = platform.capture_staged(self._window, region, limits)
            image = recorder.captured(self._step, raw, staged)
            meta = staged.meta
            if meta is not None and image.capture_id is not None:
                seen = FrameRef(
                    meta.backend, meta.client_size, meta.dpi, image.capture_id, meta.observed_at
                )
                runtime.note_observation(image.capture_id, seen, meta.window or self._window)
        else:
            image = recorder.captured(self._step, platform.capture(self._window, region))
            self._note_state(image)
        # 관측 세대: 캡처 번호 → 지금 세대, 이 스텝의 바닥에 합친다 (M3 2.4)
        self.trace.note(runtime.note_capture(image.capture_id, self._source))
        runtime.check()
        return image

    @property
    def _source(self) -> str:
        """관측 출처의 이름: 노드 경로 (서브그래프 안이면 호출 노드부터)."""
        return "/".join(self._frame.node_path(self._node.id))

    def _note_state(self, image: Image) -> None:
        """관측 조건을 주지 않는 캡처: 플랫폼이 창 상태를 알면 캡처 직후 그것을 관측으로 둔다."""
        platform = self._runtime.platform
        if (
            self._window is None
            or image.capture_id is None
            or not isinstance(platform, _StatePlatform)
        ):
            return
        try:
            now = platform.state(self._window)
        except Exception:
            return  # 관측 정보가 없을 뿐이다 (창 문제는 다음 관측·입력이 알린다)
        size = (int(now.client_size[0]), int(now.client_size[1]))
        seen = FrameRef(str(now.backend), size, int(now.dpi), image.capture_id, time.time())
        self._runtime.note_observation(image.capture_id, seen, self._window)

    # ------------------------------------------------------------ 입력 재검증 (공용 입력 서비스)

    def rematch(self, match: Match) -> Match | None:
        """`match.target`을 이 스텝 창의 새 캡처에서 다시 찾는다 (설정 기한만, 노드 기한 없음)."""
        if match.target is None:
            return None
        target = self._load_target(match.target)
        return self.vision.find(self.capture(), target)

    def note(self, message: str) -> None:
        self.log.info(message)

    def observation_stale(self, match: Match) -> str | None:
        """그 `Match`가 디버거 재개 전 관측이면 그 설명 (M3 2.4 "입력 서비스 재검증"). 멈추지 않은
        실행(세대 0)은 늘 None — M1 그대로다.

        세대는 runner 표(`capture_id` → 세대)로만 정한다. 표에 없는 번호(출처 없음)도 오래된
        것으로 본다. 이 스텝이 재개 전 관측에서 온 입력을 받았으면(`input` 효과 노드의 `Match`
        예외) 그 스텝의 모든 `Match`를 다시 찾는다 — 워커가 옛 `Match`의 캡처 번호를 새 것으로
        바꿔 보내도 세탁되지 않는다."""
        current = self._runtime.epoch
        if current == 0:
            return None
        info = match.frame_info
        capture_id = info.capture_id if info is not None else None
        epoch = self._runtime.capture_epochs.epoch_of(capture_id)
        if epoch is None:
            return f"이 실행의 관측 출처를 알 수 없다 (캡처 번호 {capture_id})"
        if epoch < current:
            return f"디버거 재개 전 관측이다 (캡처 {capture_id}, 세대 {epoch} < 지금 {current})"
        return self.step_stale()

    def step_stale(self) -> str | None:
        """이 스텝이 디버거 재개 전 관측을 입력으로 받았으면(`input` 노드의 `Match` 예외) 그 설명.
        입력 서비스가 이 스텝의 `Match`를 모두 다시 찾는다."""
        current = self._runtime.epoch
        floor = self.trace.input_floor
        if current == 0 or floor is None or not floor.stale(current):
            return None
        return (
            f"디버거 재개 전 관측('{floor.source}', 세대 {floor.epoch} < 지금 {current})을 "
            "입력으로 받은 스텝이다"
        )

    def coordinate_stale(self, at: Point | Rect) -> str | None:
        """그 좌표 입력을 거절할 이유 (M3 2.4). 재개 전 관측을 입력으로 받은 스텝에서, 출처가 없는
        입력 핀 값(상수·설정 — 관측과 무관)과 같지 않은 좌표는 `Match`에서 뽑았을 수 있고 다시 찾을
        출처가 없다. 출처 없는 핀 값 그대로의 좌표(예: `input.drag`의 상수 끝점)는 받는다."""
        stale = self.step_stale()
        if stale is None:
            return None
        trace = self.trace
        for pin, value in trace.values.items():
            if trace.inputs.get(pin) is None and _holds(value, at):
                return None
        return stale

    def _load_target(self, rel: str) -> Target:
        path = self._runtime.program.workspace.resolve(rel)
        if path is None:
            path = Path(rel)
        try:
            spec = loads_strict(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise EngineError(
                "target_image_invalid", f"다시 찾을 target '{rel}'을(를) 읽을 수 없다: {exc}"
            ) from exc
        return Target(name=rel, path=path, spec=spec)

    def deadline(self, ms: int) -> Deadline:
        return Deadline(self._runtime.clock, self._runtime.clock.now_ms() + ms)

    @property
    def point(self) -> StepPoint:
        """이 스텝의 확인 지점 위치 (폴링 멈춤의 `debug.pause`)."""
        frame = self._frame
        node = self._node.id
        return StepPoint(self._step, node, frame.graph.path, frame.node_path(node))

    def sleep(self, ms: int) -> None:
        """코어 노드의 기다림 = 폴링 확인 지점 (M3 2.2). 그 자리에서 멈췄다 재개하면 입력을 다시
        검사하고 노드 안 관측을 무효로 표시한다 (M3 2.4 "폴링 재개")."""
        self._runtime.wait_pausable(ms, self.point, self._poll_resumed)

    def _poll_resumed(self) -> None:
        """폴링 재개 직후 (다음 관측·입력·출구 선택 전): 시작 때 통과한 입력도 이제 오래된 관측일
        수 있다. 그러면 `StaleObservation` — 노드가 삼켜도 실행기가 처리되지 않은 fail로 본다."""
        self.trace.poll_resumed()
        problem = self.trace.stale_inputs(self._runtime.epoch)
        if problem is not None:
            exc = StaleObservation(problem)
            self.stale = exc
            raise exc

    def observations_reset(self) -> bool:
        """폴링 재개로 노드 안 관측(이전 프레임·후보·안정 시간)이 무효가 됐나. 코어 폴링 노드가
        보고 들고 있던 관측을 버린 뒤 `reset_observations()`로 알린다."""
        return self.trace.reset_pending

    def reset_observations(self) -> None:
        """노드가 관측을 버렸다: 스텝 바닥을 입력 출처로 되돌린다. 알리지 않으면 바닥이 옛 세대로
        남아 출력이 오래된 값이 된다(안전한 쪽)."""
        self.trace.reset()

    def check_cancel(self) -> None:
        self._runtime.check()

    def setting(self, key: str) -> Any:
        program = self._runtime.program
        lookup = program.workspace.lookup_setting(key, program.options)
        problem = program.workspace.setting_problem(lookup, program.options)
        if problem is not None:
            raise KeyError(problem[1])
        if self._runtime.on_setting is not None:
            self._runtime.on_setting(lookup)
        return lookup.value

    def path(self, rel: str) -> Path:
        path = self._runtime.program.workspace.resolve(rel)
        if path is None:
            raise ValueError(f"'{rel}'은(는) 워크스페이스 기준 경로가 아니다")
        return path


def _holds(value: Any, at: Point | Rect) -> bool:
    """핀 값이 그 좌표이거나 (목록·객체 안에) 그 좌표를 담고 있나."""
    if type(value) is type(at) and value == at:
        return True
    if isinstance(value, (list, tuple)):
        items = cast(Sequence[Any], value)
        return any(_holds(item, at) for item in items)
    if isinstance(value, Mapping):
        entries = cast(Mapping[str, Any], value)
        return any(_holds(item, at) for item in entries.values())
    return False
