"""그래프 노드 하나의 실제 핀·출구.

노드 스키마 선언에 그래프 맥락을 더해 만든다.
- `FromInterface`: `core.graph.entry` 출력 = 자기 그래프 `interface.inputs`,
  `core.graph.exit` 입력 = 자기 그래프 `interface.outputs`,
  `core.graph.call` 입력·출력·출구 = 부르는 서브그래프 `interface`
- `DynamicExits`: `config.<from_config>` 배열 + `extra`

서브그래프 출력은 모든 출구가 준다 (G16: 모든 exit 노드가 nullable 아닌 출력을 주고, nullable은
`null`로 채운다). `core.graph.exit` 입력은 여기서는 모두 생략 가능으로 두고 G16 검사는 `subgraph`가
한다.

공통 입력 `window`(MVP 노드 목록 "공통 입력"): 노드 스키마에 없어도 모든 exec 노드(실행기가 직접
처리하는 `engine` 노드 포함)는 `in.window`(`window`, 생략 가능, `null` = 현재 대상 창)를 가진다.
그 스텝의 ctx와 그 스텝의 입력 요청만 그 창을 대상으로 하고, `core.graph.call`이면 서브그래프가 그
창을 현재 대상 창으로 이어받는다. 그 노드의 입력에 이미 `window`가 있으면(스키마가 직접 선언한
`core.window.set_current`, `window`라는 서브그래프 입력) 그 입력을 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

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

__all__ = ["COMMON_WINDOW", "NodePins", "dynamic_exit_names", "has_common_window", "node_pins"]

COMMON_WINDOW: Final = InputDecl("window", "window", nullable=True, optional=True)
"""공통 입력 `window`의 선언."""


def has_common_window(nodedef: NodeDef, inputs: Mapping[str, InputDecl]) -> bool:
    """이 노드가 공통 입력 `window`를 받는가: exec 노드이고 그 노드의 입력(`inputs`, 선언·
    interface에서 만든 것)에 `window`가 없다."""
    return not nodedef.pure and COMMON_WINDOW.name not in inputs


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
    if inputs is not None and has_common_window(nodedef, inputs):
        inputs = {**inputs, COMMON_WINDOW.name: COMMON_WINDOW}

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
    names = nodedef.effective_config(node.config).get(exits.from_config, MISSING)
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
