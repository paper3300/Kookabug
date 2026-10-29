"""반복 실행: `core.flow.repeat`·`core.flow.while` (스키마 v0 7장 "반복").

- 반복 노드에 도착할 때마다(처음 들어올 때, 본문이 끝나 돌아올 때) 스텝 하나다. 그 스텝이
  `body`(이번 회차 `index`)·`done`·`limit` 중 하나로 나간다
- 처음 들어올 때 반복 스택에 쌓고 한도(`times`·`max_iterations`)를 정한다. `done`·`limit`로 나가면
  꺼낸다. 돌아올 때는 한도 입력을 다시 계산·대조하지 않는다 (`REENTRY_INPUTS`: `while`의
  `condition`만 새로 계산). 본문이 한도의 원본 변수를 바꿔도 이 반복에는 영향이 없다
- 경로 끝(연결 안 된 ok 출구, 빈 본문 포함)은 반복 스택 맨 위(가장 안쪽) 반복 노드로 돌아간다
  (암묵적 귀환). 돌아갈 때 그 범위의 출력을 지운다. 그래서 다음 회차나 `done` 뒤에서 지난 회차
  값을 읽으면 `error`이고, 안쪽 범위는 바깥 범위에 들어 있어 바깥 회차가 바뀌면 같이 지워진다
- `while` 조건은 반복 노드 스텝의 입력이라 검사할 때마다 새로 계산한다(순수 노드도 새로). 판단
  순서: 거짓 → `done`, 참인데 이미 `max_iterations`번 실행 → `limit`(fail), 아니면 본문
- 본문 끝에 대기 중인 fail이 남았으면 돌아가지 않고 전파한다 (실행기가 이 모듈보다 먼저 본다,
  G14). 처리되지 않은 fail·error·종료 노드·공개 exit는 프레임을 빠져나가므로 반복도 같이 끝난다
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kookabug_core.engine.errors import EngineError
from kookabug_core.engine.frame import Frame, LoopState
from kookabug_core.ir import Graph, Node
from kookabug_core.loader import Program
from kookabug_core.registry import Registry
from kookabug_core.validate.context import ValidationContext
from kookabug_core.validate.flow import loop_scopes
from kookabug_sdk import Result

__all__ = ["REENTRY_INPUTS", "LoopScopes", "enter", "iteration", "path_end", "resuming"]

_LIMIT_INPUT = {"repeat": "times", "while": "max_iterations"}

REENTRY_INPUTS: Mapping[str, frozenset[str]] = {
    "repeat": frozenset(),
    "while": frozenset({"condition"}),
}
"""본문 끝에서 돌아올 때 새로 계산하는 입력 (한도는 들어올 때 정한 값을 쓴다)."""


class LoopScopes:
    """그래프별 반복 범위 (실행 전 검증과 같은 계산, 한 번만 한다)."""

    def __init__(self, program: Program, registry: Registry) -> None:
        self._ctx = ValidationContext(program, registry)
        self._scopes: dict[str, dict[str, frozenset[str]]] = {}

    def of(self, graph: Graph) -> Mapping[str, frozenset[str]]:
        if graph.path not in self._scopes:
            self._scopes[graph.path] = loop_scopes(self._ctx, graph)
        return self._scopes[graph.path]


def enter(
    frame: Frame, node: Node, engine: str, inputs: Mapping[str, Any], scope: frozenset[str]
) -> Result:
    """반복 노드 스텝 하나: 이번에 나갈 출구를 정한다.

    돌아오는 중이면 `inputs`에는 `REENTRY_INPUTS`만 있다.
    """
    loops = frame.loops
    state = loops[-1] if resuming(frame, node.id) else None
    if state is None:
        state = LoopState(node.id, scope, _limit(node, engine, inputs))
        loops.append(state)
    state.returning = False

    if engine == "while":
        condition = inputs.get("condition")
        if condition is None:
            raise EngineError("missing_required_input", f"'{node.id}': 입력 'condition'이 없다")
        if not condition:
            loops.pop()
            return Result.ok("done")
        if state.started >= state.limit:
            loops.pop()
            return Result.fail(
                "limit",
                f"'{node.id}': 조건이 아직 참인데 max_iterations {state.limit}회를 다 실행했다",
            )
    elif state.started >= state.limit:
        loops.pop()
        return Result.ok("done")
    state.started += 1
    return Result.ok("body", index=state.started - 1)


def resuming(frame: Frame, node: str) -> bool:
    """`node`가 본문 끝에서 돌아오는 중인 반복 노드인가 (처음 들어오는 것이 아니다)."""
    loops = frame.loops
    return bool(loops) and loops[-1].node == node and loops[-1].returning


def path_end(frame: Frame) -> str | None:
    """경로 끝: 가장 안쪽 반복 노드로 돌아간다 (그 범위의 출력을 지운다). 반복 밖이면 None."""
    if not frame.loops:
        return None
    state = frame.loops[-1]
    frame.invalidate(state.scope)
    state.returning = True
    return state.node


def iteration(frame: Frame, node: str) -> int | None:
    """`node` 스텝의 회차 (0부터): 그 스텝을 감싼 가장 안쪽 반복의 지금 회차.

    반복 노드 자신의 스텝은 그 반복 바깥의 회차를 쓴다.
    """
    for state in reversed(frame.loops):
        if state.node != node:
            return state.started - 1
    return None


def _limit(node: Node, engine: str, inputs: Mapping[str, Any]) -> int:
    name = _LIMIT_INPUT[engine]
    value = inputs.get(name)
    if value is None:
        code = "while_requires_limit" if engine == "while" else "missing_required_input"
        raise EngineError(code, f"'{node.id}': 입력 '{name}'이(가) 없다")
    return value
