"""노드가 외부와 만나는 `ctx`.

노드는 `Context` 프로토콜로만 창·캡처·입력·기록·시간·변수를 다룬다. 실행기(core)와
`kookabug_sdk.testing.fake_context`가 구현을 준다. 제한(선언 안 한 효과, 순수 노드)은
`GuardedContext` 래퍼로 걸고, 실행기와 가짜 ctx가 같은 래퍼를 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, NoReturn, Protocol, cast

from kookabug_sdk.types import Image, Match, Point, Rect, Secret, WindowRef

__all__ = [
    "EFFECTS",
    "ArtifactsApi",
    "BlockedApi",
    "Cancelled",
    "Clock",
    "Context",
    "ContextViolation",
    "Deadline",
    "Effect",
    "EffectContext",
    "EffectNotDeclared",
    "GuardedContext",
    "InputApi",
    "LogApi",
    "VarsApi",
]

type Effect = Literal["capture", "input", "process"]
EFFECTS: Final[frozenset[str]] = frozenset({"capture", "input", "process"})


class Cancelled(BaseException):
    """실행 취소. `except Exception`에 잡히지 않도록 BaseException이다."""


class ContextViolation(RuntimeError):
    """노드가 쓸 수 없는 ctx 기능을 불렀다. 실행기는 `error`로 본다."""


class EffectNotDeclared(ContextViolation):
    """`@node(effects=...)`에 선언하지 않은 효과를 ctx로 썼다."""


class Clock(Protocol):
    def now_ms(self) -> int: ...
    def sleep(self, ms: int) -> None: ...


@dataclass(frozen=True, slots=True)
class Deadline:
    clock: Clock
    end_ms: int

    @property
    def passed(self) -> bool:
        return self.clock.now_ms() >= self.end_ms

    @property
    def remaining_ms(self) -> int:
        return max(0, self.end_ms - self.clock.now_ms())


class VarsApi(Protocol):
    """호출 프레임 변수. 없는 이름을 기본값 없이 읽으면 KeyError."""

    def get(self, name: str, default: Any = ...) -> Any: ...
    def has(self, name: str) -> bool: ...
    def set(self, name: str, value: Any) -> None: ...


class LogApi(Protocol):
    def debug(self, message: object) -> None: ...
    def info(self, message: object) -> None: ...
    def warn(self, message: object) -> None: ...
    def error(self, message: object) -> None: ...


class ArtifactsApi(Protocol):
    def save(self, image: Image, name: str) -> str | None:
        """저장하고 실행 폴더 기준 경로를 준다. 기록 정책(구간 끄기·비밀값 입력)으로 남기지 않으면
        None (실행 기록에는 생략 이유가 남는다)."""
        ...


class InputApi(Protocol):
    def click(self, at: Point | Rect | Match, *, button: str = "left") -> None: ...
    def key(self, key: str) -> None: ...
    def type_text(self, text: str | Secret) -> None: ...


class Context(Protocol):
    @property
    def config(self) -> Mapping[str, Any]:
        """그래프 노드의 `config` 값."""
        ...

    @property
    def window(self) -> WindowRef | None:
        """현재 대상 창."""
        ...

    @property
    def vars(self) -> VarsApi: ...
    @property
    def log(self) -> LogApi: ...
    @property
    def artifacts(self) -> ArtifactsApi: ...
    @property
    def input(self) -> InputApi: ...
    def capture(self, region: Rect | None = None) -> Image: ...
    def deadline(self, ms: int) -> Deadline: ...
    def sleep(self, ms: int) -> None: ...
    def check_cancel(self) -> None: ...
    def setting(self, key: str) -> Any: ...
    def path(self, rel: str) -> Path: ...


class GuardedContext:
    """다른 ctx를 감싸 일부 기능을 막는 래퍼의 바탕. 막힌 호출은 `violations`에도 남긴다
    (노드 코드가 예외를 삼켜도 실행기가 `error`로 볼 수 있게)."""

    def __init__(self, inner: Context) -> None:
        self._inner = inner
        self.violations: list[ContextViolation] = []

    @property
    def inner(self) -> Context:
        return self._inner

    def _violate(self, exc: ContextViolation) -> NoReturn:
        self.violations.append(exc)
        raise exc

    @property
    def config(self) -> Mapping[str, Any]:
        return self._inner.config

    @property
    def window(self) -> WindowRef | None:
        return self._inner.window

    @property
    def vars(self) -> VarsApi:
        return self._inner.vars

    @property
    def log(self) -> LogApi:
        return self._inner.log

    @property
    def artifacts(self) -> ArtifactsApi:
        return self._inner.artifacts

    @property
    def input(self) -> InputApi:
        return self._inner.input

    def capture(self, region: Rect | None = None) -> Image:
        return self._inner.capture(region)

    def deadline(self, ms: int) -> Deadline:
        return self._inner.deadline(ms)

    def sleep(self, ms: int) -> None:
        self._inner.sleep(ms)

    def check_cancel(self) -> None:
        self._inner.check_cancel()

    def setting(self, key: str) -> Any:
        return self._inner.setting(key)

    def path(self, rel: str) -> Path:
        return self._inner.path(rel)


class BlockedApi:
    """어떤 속성에 접근해도 막는 객체 (`ctx.input`, `ctx.log` 등의 대역)."""

    def __init__(self, guard: GuardedContext, make: Callable[[str], ContextViolation]) -> None:
        self._guard = guard
        self._make = make

    def __getattr__(self, name: str) -> NoReturn:
        if name.startswith("__"):
            raise AttributeError(name)
        self._guard._violate(self._make(name))


class EffectContext(GuardedContext):
    """선언한 효과만 쓰게 한다. `capture` → `ctx.capture`, `input` → `ctx.input`."""

    def __init__(self, inner: Context, effects: Collection[str]) -> None:
        super().__init__(inner)
        self.effects = frozenset(effects)

    def _missing(self, effect: str, what: str) -> EffectNotDeclared:
        return EffectNotDeclared(
            f"ctx.{what}을(를) 쓰려면 @node(effects=...)에 '{effect}'을(를) 선언해야 한다"
        )

    @property
    def input(self) -> InputApi:
        if "input" not in self.effects:
            return cast(
                InputApi, BlockedApi(self, lambda name: self._missing("input", f"input.{name}"))
            )
        return self._inner.input

    def capture(self, region: Rect | None = None) -> Image:
        if "capture" not in self.effects:
            self._violate(self._missing("capture", "capture"))
        return self._inner.capture(region)
