"""검증 모듈이 같이 쓰는 맥락: 프로그램, 레지스트리, 노드별 핀 (계산한 것은 기억)."""

from __future__ import annotations

from dataclasses import dataclass, field

from kookabug_core.codes import diag
from kookabug_core.diagnostics import Diagnostic
from kookabug_core.ir import Graph, Node
from kookabug_core.loader import Program
from kookabug_core.registry import NodeDef, Registry
from kookabug_core.validate.pins import NodePins, node_pins

__all__ = ["ValidationContext"]


@dataclass
class ValidationContext:
    program: Program
    registry: Registry
    diagnostics: list[Diagnostic] = field(default_factory=list[Diagnostic])
    _pins: dict[tuple[str, str], NodePins | None] = field(
        default_factory=dict[tuple[str, str], NodePins | None]
    )

    def graphs(self) -> list[Graph]:
        return [self.program.graphs[k] for k in sorted(self.program.graphs)]

    def nodedef(self, node: Node) -> NodeDef | None:
        nodedef = self.registry.get(node.type)
        # 버전이 다르면 선언(핀·출구)이 다를 수 있으므로 그 노드는 더 검사하지 않는다
        if nodedef is None or nodedef.version != node.version:
            return None
        return nodedef

    def pins(self, graph: Graph, node: Node) -> NodePins | None:
        key = (graph.path, node.id)
        if key not in self._pins:
            nodedef = self.nodedef(node)
            self._pins[key] = (
                None if nodedef is None else node_pins(self.program, graph, node, nodedef)
            )
        return self._pins[key]

    def report(
        self,
        code: str,
        message: str,
        graph: Graph,
        node: str | None = None,
        pointer: str | None = None,
    ) -> None:
        self.diagnostics.append(diag(code, message, file=graph.path, node=node, pointer=pointer))
