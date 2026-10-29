"""노드 결과."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = ["ExitKind", "NodeContractError", "Result"]

type ExitKind = Literal["ok", "fail"]


class NodeContractError(RuntimeError):
    """노드가 선언과 다르게 동작했다 (선언 안 한 출구·출력 등). 실행기는 `error`로 본다."""


@dataclass(frozen=True, slots=True)
class Result:
    """exec 노드는 `Result.ok`/`Result.fail`을 반환한다. 순수 노드 결과는 `exit`·`kind`가 None."""

    exit: str | None
    kind: ExitKind | None
    outputs: Mapping[str, Any] = field(default_factory=dict)
    message: str | None = None

    @classmethod
    def ok(cls, exit: str, /, **outputs: Any) -> Result:
        return cls(exit, "ok", dict(outputs))

    @classmethod
    def fail(cls, exit: str, /, message: str | None = None, **outputs: Any) -> Result:
        return cls(exit, "fail", dict(outputs), message)
