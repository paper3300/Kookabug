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
from kookabug_core.ir import Node
from kookabug_core.loader import Program
from kookabug_core.record.artifacts import ArtifactStore, Recorder, StagedFrame
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
    ProcessRef,
    Rect,
    Secret,
    Target,
    WindowInfo,
    WindowRef,
)

__all__ = [
    "DEFAULT_CAPTURE_TIMEOUT_MS",
    "ArtifactStore",
    "ObservationLimits",
    "ObservingPlatform",
    "PixelPlatform",
    "Platform",
    "Runtime",
    "StepContext",
    "StepInputPlatform",
    "WindowPlatform",
]

DEFAULT_CAPTURE_TIMEOUT_MS: Final = 2000
"""`run.capture_timeout_ms` 기본값 (조율자 결정 Q2)."""
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
class ObservingPlatform(Protocol):
    """찾기·비교·OCR을 주는 플랫폼 (M1 2.5·2.6). 참조 이미지면 픽셀은 프레임 저장소에 있다."""

    def find(
        self, image: Image, target: Target, *, region: Rect | None, limits: ObservationLimits
    ) -> Match | None: ...
    def diff(self, a: Image, b: Image, *, region: Rect | None) -> float: ...
    def read_text(
        self, image: Image, *, region: Rect | None, sensitive: bool, limits: ObservationLimits
    ) -> OcrResult: ...


@runtime_checkable
class WindowPlatform(Protocol):
    """창·프로세스를 주는 플랫폼 (M1 2.2). 돌려주는 창 참조에는 이 실행의 바인딩이 붙어 있다."""

    def find_window(
        self, title: str | None, process_name: str | None, owned: bool
    ) -> WindowRef | None: ...
    def window_info(self, window: WindowRef) -> WindowInfo: ...
    def set_client_size(self, window: WindowRef, width: int, height: int) -> bool: ...
    def activate(self, window: WindowRef) -> None: ...
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

    def wait_pausable(self, ms: int, point: StepPoint) -> None:
        """멈출 수 있는 기다림 (코어 노드의 `ctx.sleep`: 대기 폴링·`flow.delay`). 취소·멈춤
        요청으로 바로 깬다. 멈춤 요청이면 이 자리에서 멈춤을 확정하고(`debug.pause where: poll`),
        재개 뒤 남은 활성 시간만큼 마저 기다린다. 확인 지점이 없는 실행이면 `wait_hold`와 같다."""
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
                gate.at_poll(point)
            self.check()


class FrameVars:
    """호출 프레임 변수."""

    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def get(self, name: str, default: Any = ...) -> Any:
        if name in self._values:
            return self._values[name]
        if default is ...:
            raise KeyError(f"변수 '{name}'이(가) 없다")
        return default

    def has(self, name: str) -> bool:
        return name in self._values

    def set(self, name: str, value: Any) -> None:
        self._values[name] = value


class StepLog:
    """`ctx.log` → `log` 이벤트. 메시지는 `str()`로 남기므로 비밀값은 가려진다."""

    def __init__(self, runtime: Runtime, step: str, node: str) -> None:
        self._runtime = runtime
        self._step = step
        self._node = node

    def _emit(self, level: str, message: object) -> None:
        self._runtime.emit(
            {
                "event": "log",
                "level": level,
                "message": str(message),
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
        found = self._platform.find(image, target, region=region, limits=limits)
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
        # 기록: 스텝의 마지막 OCR 글자 (sensitive면 남기지 않고 생략 이유만 — 스키마 6장)
        text = "" if sensitive or isinstance(result.text, Secret) else result.text
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
    ) -> None:
        self._runtime = runtime
        self._frame = frame
        self._node = node
        self._step = step
        self._config = config
        self._window = frame.current_window if isinstance(window, EllipsisType) else window
        self.stale: StaleObservation | None = None
        """이 스텝의 입력이 재검증으로 거부됐다 (노드가 삼켜도 처리되지 않은 fail)."""

    @property
    def runtime(self) -> Runtime:
        return self._runtime

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
        return FrameVars(self._frame.vars)

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
        """호출 프레임의 현재 창을 바꾼다 (다음 스텝부터). 이 스텝의 창·입력 요청은 그대로다."""
        self._frame.current_window = window

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
        runtime.check()
        return image

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
        """코어 노드의 기다림 = 폴링 확인 지점 (M3 2.2)."""
        self._runtime.wait_pausable(ms, self.point)

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
