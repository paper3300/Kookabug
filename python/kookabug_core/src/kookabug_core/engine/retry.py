"""관측 재시도 (스키마 v0 6장 "재시도").

- 노드 함수가 재시도 출구(`config.retry.on`, 생략하면 노드 스키마의 `retry.on`)로 나왔고 시도가
  `max_attempts`보다 적으면, 출구를 확정하지 않고 노드 함수를 다시 부른다
- 중간 시도는 `attempt.end` 이벤트로만 남는다. 출력 표·대기 중인 fail·판정에는 마지막 시도 하나만
  들어간다 (`step.end`의 `attempt`). 다른 스텝이 이미 확정한 결과는 건드리지 않는다
- 입력은 스텝 시작 때 한 번 계산한 값을 그대로 쓴다. 시도마다 ctx를 새로 만들므로 노드 기한
  (`ctx.deadline`)은 새로 시작하고, 테스트 전체 기한은 늘리지 않는다
- error·취소·기한 초과는 예외라 재시도하지 않고 바로 전파한다
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kookabug_core.engine.errors import EngineError
from kookabug_core.ir import Node
from kookabug_core.registry import NodeDef
from kookabug_sdk import Result

__all__ = ["RetryPolicy", "retry_policy"]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 1
    on: frozenset[str] = frozenset()

    def again(self, result: Result, attempt: int) -> bool:
        """`attempt`번째 시도 결과가 `result`일 때 한 번 더 하는가."""
        return result.kind == "fail" and result.exit in self.on and attempt < self.max_attempts


def retry_policy(nodedef: NodeDef, node: Node) -> RetryPolicy:
    """그래프의 `config.retry`. 없으면 재시도 없음 (`max_attempts` 1).

    선언 범위를 벗어난 설정은 실행 전 검증과 같은 코드의 `error` (검증을 건너뛴 그래프의 방어).
    """
    retry: Any = node.config.get("retry")
    if retry is None:
        return RetryPolicy()
    if nodedef.retry_mode == "never":
        raise EngineError(
            "retry_not_allowed", f"'{node.id}': '{node.type}'은(는) 재시도를 선언하지 않았다"
        )
    if not isinstance(retry, Mapping):
        raise EngineError("retry_max_attempts", f"'{node.id}': config.retry가 객체가 아니다")
    settings: Mapping[str, Any] = retry
    attempts = settings.get("max_attempts")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise EngineError(
            "retry_max_attempts",
            f"'{node.id}': max_attempts는 첫 실행을 포함한 1 이상의 정수다 ({attempts!r})",
        )
    on = settings.get("on", list(nodedef.retry_on))
    names: list[Any] = on if isinstance(on, list) else []
    if wrong := [name for name in names if name not in nodedef.retry_on]:
        raise EngineError(
            "retry_exit_not_allowed", f"'{node.id}': 출구 {wrong}은(는) 재시도할 수 없다"
        )
    return RetryPolicy(attempts, frozenset(names))
