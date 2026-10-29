"""순수 노드의 ctx 제한.

순수 노드는 부작용이 없어야 한다. 막는 것: `capture`, `input`(모든 메서드), `artifacts`(모든
메서드), `log`(모든 메서드), `sleep`, `vars.set`. 변수 읽기(복사본)·설정값·창·기한·취소 확인은
된다.
실행기(core)와 `fake_context(pure=True)`가 이 래퍼 하나를 같이 쓴다.
"""

from __future__ import annotations

import copy
from typing import Any, NoReturn, cast

from kookabug_sdk.context import (
    ArtifactsApi,
    BlockedApi,
    ContextViolation,
    GuardedContext,
    InputApi,
    LogApi,
    VarsApi,
)
from kookabug_sdk.types import Image, Rect

__all__ = ["PureContext", "PureContextViolation"]


class PureContextViolation(ContextViolation):
    """순수 노드가 부작용 있는 ctx 기능을 불렀다."""


def _violation(what: str) -> PureContextViolation:
    return PureContextViolation(f"순수 노드는 ctx.{what}을(를) 쓸 수 없다")


class _ReadOnlyVars:
    """변수 읽기만 된다. 값은 깊은 복사본이라, 순수 노드가 list·dict를 고치거나 그대로 출력해도
    호출 프레임 변수는 바뀌지 않는다 (소비 횟수가 값을 바꾸지 않게)."""

    def __init__(self, guard: PureContext, inner: VarsApi) -> None:
        self._guard = guard
        self._inner = inner

    def get(self, name: str, default: Any = ...) -> Any:
        if default is ...:
            return copy.deepcopy(self._inner.get(name))
        return copy.deepcopy(self._inner.get(name, default))

    def has(self, name: str) -> bool:
        return self._inner.has(name)

    def set(self, name: str, value: Any) -> NoReturn:
        self._guard._violate(_violation("vars.set"))


class PureContext(GuardedContext):
    @property
    def vars(self) -> VarsApi:
        return _ReadOnlyVars(self, self._inner.vars)

    @property
    def log(self) -> LogApi:
        return cast(LogApi, BlockedApi(self, lambda name: _violation(f"log.{name}")))

    @property
    def artifacts(self) -> ArtifactsApi:
        return cast(ArtifactsApi, BlockedApi(self, lambda name: _violation(f"artifacts.{name}")))

    @property
    def input(self) -> InputApi:
        return cast(InputApi, BlockedApi(self, lambda name: _violation(f"input.{name}")))

    def capture(self, region: Rect | None = None) -> Image:
        self._violate(_violation("capture"))

    def sleep(self, ms: int) -> None:
        self._violate(_violation("sleep"))
