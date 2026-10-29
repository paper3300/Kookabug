"""노드 함수 실행 경계 (`NodeInvoker`).

실행기는 exec 노드와 순수 노드 모두 이 경계를 거쳐 노드 함수를 부른다. M0a는 같은 프로세스에서
부르는 `InProcessInvoker`이고, M0b가 워커 프로세스 구현으로 바꿔 끼운다.

계약: `ctx`는 실행 ctx(`StepContext`, 아직 감싸지 않은 것)다. 구현은 SDK가 정한 대로 노드 종류에
맞게 감싸고(순수 → `PureContext`, exec → `EffectContext`) 결과를 선언과 대조해 `Result`를 돌려준다
(`NodeFunction.invoke`가 하는 일). 노드 예외·`ContextViolation`·`NodeContractError`·`Cancelled`는
그대로 던진다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from kookabug_core.ir import Node
from kookabug_core.registry import NodeDef
from kookabug_sdk import Result
from kookabug_sdk.context import Context

__all__ = ["InProcessInvoker", "NodeInvoker"]


class NodeInvoker(Protocol):
    def invoke(
        self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
    ) -> Result: ...


class InProcessInvoker:
    """같은 프로세스에서 `@node` 함수를 부른다."""

    def invoke(
        self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
    ) -> Result:
        return nodedef.function.invoke(ctx, inputs)
