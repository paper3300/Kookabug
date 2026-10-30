"""실행 ctx: 노드가 받는 `Context`의 core 구현과, 한 실행이 같이 쓰는 상태(`Runtime`).

노드 함수는 이 ctx를 SDK `guard()`로 감싼 것을 받는다 (순수 노드는 `PureContext`, exec 노드는
선언한 효과만 쓰는 `EffectContext`). 그래서 순수 노드 제한은 `fake_context`와 같은 래퍼 하나로
걸린다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

from kookabug_core.engine.cancel import CancelToken, DeadlineExceeded
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
from kookabug_sdk.errors import ObservationTimeout
from kookabug_sdk.types import Image, Rect, Secret, WindowRef

__all__ = [
    "ArtifactStore",
    "PixelPlatform",
    "Platform",
    "Runtime",
    "StepContext",
    "StepInputPlatform",
]


class Platform(Protocol):
    """게임과 만나는 쪽: 캡처와 입력. M0a는 `FakePlatform`, M1이 Windows 구현을 붙인다."""

    @property
    def input(self) -> InputApi: ...
    def capture(self, window: WindowRef | None, region: Rect | None) -> Image: ...


@runtime_checkable
class StepInputPlatform(Protocol):
    """스텝마다 입력 경로를 주는 플랫폼 (M0b runner: 입력 액터 큐에 스텝 ID와 함께 넣는다).

    플랫폼이 이것을 구현하면 `ctx.input`은 `input`이 아니라 `input_for(스텝)`으로 간다.
    """

    def input_for(self, step: str) -> InputApi: ...


@runtime_checkable
class PixelPlatform(Protocol):
    """캡처 픽셀을 프레임 저장소에 두는 플랫폼 (M1 2.7).

    실행에 프레임 저장소(`Recorder.frames`)가 있으면 `ctx.capture`는 `capture`가 아니라 이것을
    부르고, 노드에는 픽셀 없는 참조 이미지를 준다. 픽셀은 `capture_id`로 저장소에 등록된다.
    """

    def capture_staged(
        self, window: WindowRef | None, region: Rect | None
    ) -> tuple[Image, StagedFrame]: ...


@dataclass(eq=False)
class Runtime:
    """한 실행의 공용 상태: 프로그램, 레지스트리, 노드 실행 경계, 플랫폼, 시계, 취소, 전체 기한,
    이벤트, 기록 정책(`recorder`)."""

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

    def emit(self, event: Mapping[str, Any]) -> None:
        self.emit_to({**event, "run": self.run})

    def check(self) -> None:
        """취소·전체 기한 확인. 스텝 시작, 노드 호출 직전·직후, `ctx`의 캡처·입력 앞뒤,
        `ctx.check_cancel()`, `ctx.sleep()`이 부른다."""
        self.cancel.check()
        if self.deadline.passed:
            raise DeadlineExceeded(f"테스트 전체 기한 {self.deadline_ms}ms를 넘었다")

    def sleep(self, ms: int) -> None:
        """기다린다. 전체 기한을 넘는 만큼은 기다리지 않고 기한에서 멈춘다."""
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

    def __init__(self, runtime: Runtime, step: str) -> None:
        self._runtime = runtime
        platform = runtime.platform
        self._input: InputApi = (
            platform.input_for(step) if isinstance(platform, StepInputPlatform) else platform.input
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


class Unconnected:
    """아직 실행기에 연결하지 않은 ctx 기능 (`ctx.vision`·`ocr`·`windows`·`process`·`set_window`).

    SDK 계약(M1 T8)이 먼저 들어오고 runner 연결(T9)이 붙인다. 부르면 `platform_unavailable`.
    """

    def __init__(self, api: str) -> None:
        self._api = api

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        raise EngineError(
            "platform_unavailable", f"이 실행에서는 ctx.{self._api}.{name}을(를) 쓸 수 없다"
        )


class StepContext:
    """노드 하나(스텝 하나)의 ctx. 순수 노드는 그 노드를 소비하는 스텝의 ID를 쓴다.

    `config`는 선언 기본값을 채운 것이다 (`NodeDef.effective_config`).
    """

    def __init__(
        self, runtime: Runtime, frame: Frame, node: Node, step: str, config: Mapping[str, Any]
    ) -> None:
        self._runtime = runtime
        self._frame = frame
        self._node = node
        self._step = step
        self._config = config

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
        return self._frame.current_window

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
        return CheckedInput(self._runtime, self._step)

    @property
    def vision(self) -> VisionApi:
        return cast(VisionApi, Unconnected("vision"))

    @property
    def ocr(self) -> OcrApi:
        return cast(OcrApi, Unconnected("ocr"))

    @property
    def windows(self) -> WindowsApi:
        return cast(WindowsApi, Unconnected("windows"))

    @property
    def process(self) -> ProcessApi:
        return cast(ProcessApi, Unconnected("process"))

    def set_window(self, window: WindowRef) -> None:
        raise EngineError("platform_unavailable", "이 실행에서는 ctx.set_window를 쓸 수 없다")

    def capture(self, region: Rect | None = None, *, deadline: Deadline | None = None) -> Image:
        # 노드 기한을 캡처 대기에 넣는 것은 플랫폼 연결(T9). 여기서는 지난 기한이면 시작하지 않는다
        if deadline is not None and deadline.passed:
            raise ObservationTimeout("노드 기한이 지나 캡처를 시작하지 않았다")
        self._runtime.check()
        platform = self._runtime.platform
        recorder = self._runtime.recorder
        window = self._frame.current_window
        if recorder.frames is not None and isinstance(platform, PixelPlatform):
            raw, staged = platform.capture_staged(window, region)
            image = recorder.captured(self._step, raw, staged)
        else:
            image = recorder.captured(self._step, platform.capture(window, region))
        self._runtime.check()
        return image

    def deadline(self, ms: int) -> Deadline:
        return Deadline(self._runtime.clock, self._runtime.clock.now_ms() + ms)

    def sleep(self, ms: int) -> None:
        self._runtime.sleep(ms)

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
