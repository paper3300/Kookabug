"""그래프 노드 하나의 실제 핀·출구.

노드 스키마 선언에 그래프 맥락을 더해 만든다.
- `FromInterface`: `core.graph.entry` 출력 = 자기 그래프 `interface.inputs`,
  `core.graph.exit` 입력 = 자기 그래프 `interface.outputs`,
  `core.graph.call` 입력·출력·출구 = 부르는 서브그래프 `interface`
- `DynamicExits`: `config.<from_config>` 배열 + `extra`

서브그래프 출력은 모든 출구가 준다 (G16: 모든 exit 노드가 nullable 아닌 출력을 주고, nullable은
`null`로 채운다). `core.graph.exit` 입력은 여기서는 모두 생략 가능으로 두고 G16 검사는 `subgraph`가
한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kookabug_core.ir import GRAPH_CALL, GRAPH_ENTRY, GRAPH_EXIT, Graph, Node
from kookabug_core.loader import Program
from kookabug_core.registry import (
    MISSING,
    DynamicExitsDecl,
    ExitDecl,
    InputDecl,
    NodeDef,
    OutputDecl,
)

__all__ = ["NodePins", "dynamic_exit_names", "node_pins"]


@dataclass(frozen=True, slots=True)
class NodePins:
    """`None`인 항목은 알 수 없음 (부르는 서브그래프를 못 읽음, 동적 출구 config가 틀림 등).
    알 수 없는 항목은 검사를 건너뛴다 (원인 진단이 따로 나간다)."""

    inputs: Mapping[str, InputDecl] | None
    outputs: Mapping[str, OutputDecl] | None
    exits: Mapping[str, ExitDecl] | None


def _interface(graph: Graph | None, part: str) -> Mapping[str, Any] | None:
    if graph is None:
        return None
    interface = graph.interface or {}
    section = interface.get(part, {})
    return section if isinstance(section, Mapping) else {}


def _interface_inputs(section: Mapping[str, Any], *, all_optional: bool) -> dict[str, InputDecl]:
    pins: dict[str, InputDecl] = {}
    for name, decl in section.items():
        default = decl.get("default", MISSING)
        if all_optional:
            pins[name] = InputDecl(
                name, decl["type"], nullable=bool(decl.get("nullable", False)), optional=True
            )
        else:
            pins[name] = InputDecl(name, decl["type"], default=default)
    return pins


def _interface_outputs(section: Mapping[str, Any]) -> dict[str, OutputDecl]:
    return {
        name: OutputDecl(name, decl["type"], bool(decl.get("nullable", False)))
        for name, decl in section.items()
    }


def node_pins(program: Program, graph: Graph, node: Node, nodedef: NodeDef) -> NodePins:
    callee = program.callee(graph.path, node.id) if node.type == GRAPH_CALL else None

    inputs: Mapping[str, InputDecl] | None
    if isinstance(nodedef.inputs, tuple):
        inputs = {p.name: p for p in nodedef.inputs}
    elif node.type == GRAPH_EXIT:
        section = _interface(graph, "outputs")
        inputs = None if section is None else _interface_inputs(section, all_optional=True)
    elif node.type == GRAPH_CALL:
        section = _interface(callee, "inputs")
        inputs = None if section is None else _interface_inputs(section, all_optional=False)
    else:
        inputs = None

    outputs: Mapping[str, OutputDecl] | None
    if isinstance(nodedef.outputs, tuple):
        outputs = {p.name: p for p in nodedef.outputs}
    elif node.type == GRAPH_ENTRY:
        section = _interface(graph, "inputs")
        outputs = None if section is None else _interface_outputs(section)
    elif node.type == GRAPH_CALL:
        section = _interface(callee, "outputs")
        outputs = None if section is None else _interface_outputs(section)
    else:
        outputs = None

    return NodePins(inputs, outputs, _exits(node, nodedef, outputs, callee))


def dynamic_exit_names(node: Node, nodedef: NodeDef) -> list[str] | None:
    """`DynamicExits` 노드의 동적 출구 이름: `config.<from_config>`, 생략했으면 그 config의 기본값.

    값이 문자열 배열이 아니거나(→ `config_invalid`) 기본값도 없으면(→ 필수 config 누락) None.
    """
    exits = nodedef.exits
    if not isinstance(exits, DynamicExitsDecl):
        return None
    if exits.from_config in node.config:
        names = node.config[exits.from_config]
    else:
        decl = next((c for c in nodedef.config if c.name == exits.from_config), None)
        names = MISSING if decl is None else decl.default
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        return None
    return list(names)


def _exits(
    node: Node,
    nodedef: NodeDef,
    outputs: Mapping[str, OutputDecl] | None,
    callee: Graph | None,
) -> Mapping[str, ExitDecl] | None:
    exits = nodedef.exits
    if exits is None:
        return {}
    if isinstance(exits, tuple):
        if isinstance(nodedef.outputs, str) and outputs is not None:
            # 출력이 interface에서 오는 노드(graph.entry)의 출구는 그 출력을 전부 준다
            names = tuple(sorted(outputs))
            return {e.name: ExitDecl(e.name, e.kind, names) for e in exits}
        return {e.name: e for e in exits}
    if isinstance(exits, DynamicExitsDecl):
        dynamic = dynamic_exit_names(node, nodedef)
        if dynamic is None:
            return None
        found = {e.name: e for e in exits.extra}
        for name in dynamic:
            found.setdefault(name, ExitDecl(name, exits.kind, exits.outputs))
        return found
    section = _interface(callee, "exits")
    if section is None:
        return None
    names = tuple(sorted(outputs or {}))
    return {name: ExitDecl(name, decl["kind"], names) for name, decl in section.items()}
