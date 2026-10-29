"""노드 함수 실행 경계 (`NodeInvoker`).

실행기는 exec 노드와 순수 노드 모두 이 경계를 거쳐 노드 함수를 부른다. `InProcessInvoker`는 같은
프로세스에서 부르고, M0b runner는 `RoutingInvoker`로 core 노드는 같은 프로세스, 그 밖의 플러그인
노드는 워커 프로세스(`kookabug_core.workerhost.WorkerInvoker`)로 보낸다.

계약: `ctx`는 실행 ctx(`StepContext`, 아직 감싸지 않은 것)다. 구현은 SDK가 정한 대로 노드 종류에
맞게 감싸고(순수 → `PureContext`, exec → `EffectContext`) 결과를 선언과 대조해 `Result`를 돌려준다
(`NodeFunction.invoke`가 하는 일). 노드 예외·`ContextViolation`·`NodeContractError`·`Cancelled`는
그대로 던진다.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any, Protocol

from kookabug_core.engine.errors import EngineError
from kookabug_core.ir import Node
from kookabug_core.registry import NodeDef
from kookabug_sdk import Result
from kookabug_sdk.context import Context
from kookabug_sdk.decorators import CORE_PLUGIN

__all__ = ["InProcessInvoker", "NodeInvoker", "RoutingInvoker"]


class NodeInvoker(Protocol):
    def invoke(
        self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
    ) -> Result: ...


class InProcessInvoker:
    """같은 프로세스에서 `@node` 함수를 부른다."""

    def invoke(
        self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
    ) -> Result:
        if nodedef.function is None:
            raise EngineError(
                "remote_node_in_process",
                f"'{node.id}': {nodedef.type}은(는) 워커에서 실행하는 원격 노드다",
            )
        return nodedef.function.invoke(ctx, inputs)


class RoutingInvoker:
    """`nodedef.plugin`으로 실행 위치를 고른다: `local_plugins`(기본 core)는 같은 프로세스,
    그 밖은 `remote`.

    `remote`가 없으면(워커 없는 실행) 그 밖의 플러그인 노드는 `error`다.
    """

    def __init__(
        self,
        remote: NodeInvoker | None,
        *,
        local: NodeInvoker | None = None,
        local_plugins: Collection[str] = (CORE_PLUGIN,),
    ) -> None:
        self.remote = remote
        self.local: NodeInvoker = local or InProcessInvoker()
        self.local_plugins = frozenset(local_plugins)

    def invoke(
        self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
    ) -> Result:
        if nodedef.plugin in self.local_plugins:
            return self.local.invoke(nodedef, node, ctx, inputs)
        if self.remote is None:
            raise EngineError(
                "worker_missing",
                f"'{node.id}': 플러그인 '{nodedef.plugin}' 노드를 실행할 워커가 없다",
            )
        return self.remote.invoke(nodedef, node, ctx, inputs)
