"""스텝 입력 계산과 순수 노드 즉석 계산 (스키마 v0 7장 "`$link` 평가").

- 입력은 스텝이 시작될 때 한 번 계산한다
- exec 노드의 출력은 호출 프레임 출력 표에서 읽는다 (노드를 실행시키지 않는다, 없으면 `error`)
- 순수 노드의 출력은 그 자리에서 계산한다. 한 번의 소비(입력 계산 한 번) 안에서는 같은 순수
  노드를 한 번만 계산하고(메모), 다음 소비 때는 다시 계산한다
- 순수 노드 계산 중에 같은 순수 노드로 다시 들어오면 `error`(`pure_reentry`). 실행 전 검증
  (`pure_cycle`)을 건너뛴 그래프의 방어다
- 값은 복사해서 넘긴다. 노드가 받은 list·dict를 고쳐도 그래프 상수·출력 표·변수는 그대로다
- 계산한 값은 핀 선언과 다시 대조한다. `any` 출력을 거쳐 온 값(비밀값이 `string` 핀으로 가는 것
  포함)은 실행 전 검증이 못 막기 때문이다
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from kookabug_core.engine.context import Runtime, StepContext
from kookabug_core.engine.errors import EngineError, error_code
from kookabug_core.engine.frame import Frame
from kookabug_core.ir import LinkRef, Node, Unresolved
from kookabug_core.registry import NodeDef
from kookabug_core.validate.pins import node_pins
from kookabug_core.validate.types import value_problems

__all__ = ["check_inputs", "nodedef_of", "resolve_inputs"]


def nodedef_of(runtime: Runtime, node: Node) -> NodeDef:
    nodedef = runtime.registry.get(node.type)
    if nodedef is None:
        raise EngineError(
            "unknown_node_type", f"'{node.id}': 설치된 플러그인에 '{node.type}'이(가) 없다"
        )
    if nodedef.version != node.version:
        raise EngineError(
            "node_version_mismatch",
            f"'{node.id}': {node.type} version {node.version} ≠ 설치된 {nodedef.version}",
        )
    return nodedef


def resolve_inputs(runtime: Runtime, frame: Frame, node: Node, step: str) -> dict[str, Any]:
    """`node`의 입력을 계산한다 (소비 한 번)."""
    return _Evaluation(runtime, frame, step).inputs(node)


def _no_link(ref: LinkRef) -> None:
    return None


def check_inputs(runtime: Runtime, frame: Frame, node: Node, values: Mapping[str, Any]) -> None:
    """계산한 입력 값을 핀 선언(타입·선택지·범위)과 대조한다."""
    nodedef = nodedef_of(runtime, node)
    pins = node_pins(runtime.program, frame.graph, node, nodedef).inputs
    if pins is None:
        return
    for pin, value in values.items():
        decl = pins.get(pin)
        if decl is None:
            raise EngineError("unknown_input", f"'{node.id}'에 입력 '{pin}'이(가) 없다")
        problems = value_problems(value, decl, _no_link, (pin,))
        if problems:
            _, code, message = problems[0]
            raise EngineError(code, f"'{node.id}' 입력 '{pin}': {message}")


class _Evaluation:
    def __init__(self, runtime: Runtime, frame: Frame, step: str) -> None:
        self.runtime = runtime
        self.frame = frame
        self.step = step
        self.memo: dict[str, Mapping[str, Any]] = {}
        self.stack: list[str] = []

    def inputs(self, node: Node) -> dict[str, Any]:
        values = {pin: self.value(v) for pin, v in node.inputs.items()}
        check_inputs(self.runtime, self.frame, node, values)
        return values

    def value(self, value: Any) -> Any:
        if isinstance(value, LinkRef):
            return self.link(value)
        if isinstance(value, Unresolved):
            raise EngineError(
                "input_unresolved", f"{value.tag} '{value.key}'을(를) 해석하지 못했다"
            )
        if isinstance(value, list):
            items: list[Any] = value
            return [self.value(v) for v in items]
        if isinstance(value, dict):
            mapping: dict[str, Any] = value
            return {k: self.value(v) for k, v in mapping.items()}
        return copy.deepcopy(value)

    def link(self, ref: LinkRef) -> Any:
        producer = self.frame.graph.nodes.get(ref.node)
        if producer is None:
            raise EngineError("link_bad_node", f"'{ref}': 노드 '{ref.node}'이(가) 없다")
        nodedef = nodedef_of(self.runtime, producer)
        if not nodedef.pure:
            return copy.deepcopy(self.frame.read(ref))
        outputs = self.pure(producer, nodedef)
        if ref.output not in outputs:
            raise EngineError(
                "link_bad_output", f"'{ref}': 순수 노드가 '{ref.output}'을(를) 주지 않았다"
            )
        return copy.deepcopy(outputs[ref.output])

    def pure(self, node: Node, nodedef: NodeDef) -> Mapping[str, Any]:
        if node.id in self.memo:
            return self.memo[node.id]
        if node.id in self.stack:
            cycle = [*self.stack[self.stack.index(node.id) :], node.id]
            raise EngineError(
                "pure_reentry",
                "순수 노드 계산이 같은 노드로 다시 들어왔다: "
                + " → ".join(f"'{n}'" for n in cycle),
            )
        self.stack.append(node.id)
        try:
            values = self.inputs(node)
            config = nodedef.effective_config(node.config)
            ctx = StepContext(self.runtime, self.frame, node, self.step, config)
            try:
                result = self.runtime.invoker.invoke(nodedef, node, ctx, values)
            except EngineError:
                raise
            except Exception as exc:
                raise EngineError(
                    error_code(exc), f"순수 노드 '{node.id}'({node.type}): {_describe(exc)}"
                ) from exc
        finally:
            self.stack.pop()
        self.memo[node.id] = result.outputs
        return result.outputs


def _describe(exc: BaseException) -> str:
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__
