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
- 점·사각형 배열 상수(`[x, y]`, `[x, y, w, h]`)는 대조한 뒤 핀 타입대로 `Point`·`Rect`로 바꿔
  준다. 노드는 상수 모양을 따로 바꾸지 않는다
- 관측 출처 (M3 2.4, `resolve_traced`): 핀마다 기댄 가장 오래된 관측의 세대를 같이 낸다. 순수
  노드 출력은 그 계산의 입력·읽은 변수 중 가장 오래된 것이다(순수 `var.get`은 오래된 값을 거부하지
  않고 출처만 남긴다 — 받는 스텝의 입력 검사가 정한다)
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from kookabug_core.engine.context import Runtime, StepContext
from kookabug_core.engine.errors import EngineError, error_code
from kookabug_core.engine.frame import Frame
from kookabug_core.engine.provenance import Origin, StepTrace, oldest
from kookabug_core.ir import LinkRef, Node, Unresolved
from kookabug_core.registry import NodeDef
from kookabug_core.validate.pins import node_pins
from kookabug_core.validate.types import coerce, pin_type, value_problems

__all__ = ["check_inputs", "nodedef_of", "resolve_inputs", "resolve_traced"]


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


def resolve_inputs(
    runtime: Runtime,
    frame: Frame,
    node: Node,
    step: str,
    only: frozenset[str] | None = None,
) -> dict[str, Any]:
    """`node`의 입력을 계산한다 (소비 한 번). `only`를 주면 그 핀만 계산·대조한다."""
    return _Evaluation(runtime, frame, step).inputs(node, only)[0]


def resolve_traced(
    runtime: Runtime,
    frame: Frame,
    node: Node,
    step: str,
    only: frozenset[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Origin | None]]:
    """`resolve_inputs` + 핀별 관측 출처 (M3 2.4). exec 노드 출력은 출력 표의 출처, 순수 노드
    출력은 그 계산의 바닥(입력·읽은 변수 중 가장 오래된 것), 상수·설정·비밀값은 출처 없음."""
    return _Evaluation(runtime, frame, step).inputs(node, only)


def _no_link(ref: LinkRef) -> None:
    return None


def check_inputs(
    runtime: Runtime, frame: Frame, node: Node, values: Mapping[str, Any]
) -> dict[str, Any]:
    """계산한 입력 값을 핀 선언(타입·선택지·범위)과 대조하고, 점·사각형 배열 상수를 핀 타입대로
    `Point`·`Rect`로 바꾼 값을 돌려준다 (`validate.types.coerce`)."""
    nodedef = nodedef_of(runtime, node)
    pins = node_pins(runtime.program, frame.graph, node, nodedef).inputs
    if pins is None:
        return dict(values)
    checked: dict[str, Any] = {}
    for pin, value in values.items():
        decl = pins.get(pin)
        if decl is None:
            raise EngineError("unknown_input", f"'{node.id}'에 입력 '{pin}'이(가) 없다")
        problems = value_problems(value, decl, _no_link, (pin,))
        if problems:
            _, code, message = problems[0]
            raise EngineError(code, f"'{node.id}' 입력 '{pin}': {message}")
        checked[pin] = coerce(value, pin_type(decl.type))
    return checked


class _Evaluation:
    def __init__(self, runtime: Runtime, frame: Frame, step: str) -> None:
        self.runtime = runtime
        self.frame = frame
        self.step = step
        self.memo: dict[str, tuple[Mapping[str, Any], Origin | None]] = {}
        self.stack: list[str] = []

    def inputs(
        self, node: Node, only: frozenset[str] | None = None
    ) -> tuple[dict[str, Any], dict[str, Origin | None]]:
        values: dict[str, Any] = {}
        origins: dict[str, Origin | None] = {}
        for pin, v in node.inputs.items():
            if only is None or pin in only:
                values[pin], origins[pin] = self.value(v)
        return check_inputs(self.runtime, self.frame, node, values), origins

    def value(self, value: Any) -> tuple[Any, Origin | None]:
        """값과 그 관측 출처 (목록·객체는 안의 링크 중 가장 오래된 것)."""
        if isinstance(value, LinkRef):
            return self.link(value)
        if isinstance(value, Unresolved):
            raise EngineError(
                "input_unresolved", f"{value.tag} '{value.key}'을(를) 해석하지 못했다"
            )
        if isinstance(value, list):
            items: list[Any] = value
            pairs = [self.value(v) for v in items]
            return [v for v, _ in pairs], _oldest_of(o for _, o in pairs)
        if isinstance(value, dict):
            mapping: dict[str, Any] = value
            entries = {k: self.value(v) for k, v in mapping.items()}
            return {k: v for k, (v, _) in entries.items()}, _oldest_of(
                o for _, o in entries.values()
            )
        return copy.deepcopy(value), None

    def link(self, ref: LinkRef) -> tuple[Any, Origin | None]:
        producer = self.frame.graph.nodes.get(ref.node)
        if producer is None:
            raise EngineError("link_bad_node", f"'{ref}': 노드 '{ref.node}'이(가) 없다")
        nodedef = nodedef_of(self.runtime, producer)
        if not nodedef.pure:
            return copy.deepcopy(self.frame.read(ref)), self.frame.origin_of(ref)
        outputs, origin = self.pure(producer, nodedef)
        if ref.output not in outputs:
            raise EngineError(
                "link_bad_output", f"'{ref}': 순수 노드가 '{ref.output}'을(를) 주지 않았다"
            )
        return copy.deepcopy(outputs[ref.output]), origin

    def pure(self, node: Node, nodedef: NodeDef) -> tuple[Mapping[str, Any], Origin | None]:
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
            values, origins = self.inputs(node)
            config = nodedef.effective_config(node.config)
            # 순수 노드의 변수 읽기(`var.get`)는 거부하지 않고 출처만 남긴다 (받는 스텝이 정한다)
            trace = StepTrace(node.type, inputs=origins, values=values)
            ctx = StepContext(
                self.runtime, self.frame, node, self.step, config, trace=trace, pure=True
            )
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
        self.memo[node.id] = (result.outputs, trace.floor)
        return self.memo[node.id]


def _oldest_of(origins: Iterable[Origin | None]) -> Origin | None:
    found: Origin | None = None
    for origin in origins:
        found = oldest(found, origin)
    return found


def _describe(exc: BaseException) -> str:
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__
