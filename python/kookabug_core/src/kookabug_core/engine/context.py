"""실행 ctx: 노드가 받는 `Context`의 core 구현과, 한 실행이 같이 쓰는 상태(`Runtime`).

노드 함수는 이 ctx를 SDK `guard()`로 감싼 것을 받는다 (순수 노드는 `PureContext`, exec 노드는
선언한 효과만 쓰는 `EffectContext`). 그래서 순수 노드 제한은 `fake_context`와 같은 래퍼 하나로
걸린다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from kookabug_core.engine.cancel import CancelToken, DeadlineExceeded
from kookabug_core.engine.frame import Frame
from kookabug_core.engine.invoker import NodeInvoker
from kookabug_core.ir import Node
from kookabug_core.loader import Program
from kookabug_core.registry import Registry
from kookabug_sdk.context import ArtifactsApi, Clock, Deadline, InputApi, LogApi, VarsApi
from kookabug_sdk.types import Image, Match, Point, Rect, Secret, WindowRef

__all__ = ["ArtifactStore", "Platform", "Runtime", "StepContext"]


class Platform(Protocol):
    """게임과 만나는 쪽: 캡처와 입력. M0a는 `FakePlatform`, M1이 Windows 구현을 붙인다."""

    @property
    def input(self) -> InputApi: ...
    def capture(self, window: WindowRef | None, region: Rect | None) -> Image: ...


class ArtifactStore(Protocol):
    def save(self, step: str, image: Image, name: str) -> str:
        """저장하고 실행 폴더 기준 경로를 돌려준다."""
        ...


@dataclass(eq=False)
class Runtime:
    """한 실행의 공용 상태: 프로그램, 레지스트리, 노드 실행 경계, 플랫폼, 시계, 취소, 전체 기한,
    이벤트."""

    run: str
    program: Program
    registry: Registry
    invoker: NodeInvoker
    platform: Platform
    artifacts: ArtifactStore
    clock: Clock
    cancel: CancelToken
    deadline: Deadline
    deadline_ms: int
    emit_to: Callable[[dict[str, Any]], None]
    step_artifacts: dict[str, list[str]] = field(default_factory=dict[str, list[str]])

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
    def __init__(self, runtime: Runtime, step: str) -> None:
        self._runtime = runtime
        self._step = step

    def save(self, image: Image, name: str) -> str:
        path = self._runtime.artifacts.save(self._step, image, name)
        self._runtime.step_artifacts.setdefault(self._step, []).append(path)
        return path


class CheckedInput:
    """입력 앞뒤로 취소·전체 기한을 확인한다 (취소된 뒤에는 게임에 입력하지 않는다)."""

    def __init__(self, runtime: Runtime) -> None:
        self._runtime = runtime

    def click(self, at: Point | Rect | Match, *, button: str = "left") -> None:
        self._runtime.check()
        self._runtime.platform.input.click(at, button=button)
        self._runtime.check()

    def key(self, key: str) -> None:
        self._runtime.check()
        self._runtime.platform.input.key(key)
        self._runtime.check()

    def type_text(self, text: str | Secret) -> None:
        self._runtime.check()
        self._runtime.platform.input.type_text(text)
        self._runtime.check()


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
        return CheckedInput(self._runtime)

    def capture(self, region: Rect | None = None) -> Image:
        self._runtime.check()
        image = self._runtime.platform.capture(self._frame.current_window, region)
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
        return lookup.value

    def path(self, rel: str) -> Path:
        path = self._runtime.program.workspace.resolve(rel)
        if path is None:
            raise ValueError(f"'{rel}'은(는) 워크스페이스 기준 경로가 아니다")
        return path
