"""노드 모양: 그래프 노드마다 실제 입력 핀·출력 핀·출구 (M2 계획 2.7).

에디터는 핀 모양을 직접 계산하지 않는다. 정적 선언, `DynamicExits`(`config` 배열 순서),
`FromInterface`(`graph.call` → 그 서브그래프 `interface`)를 검증과 같은 함수(`validate.pins`)로 풀어
daemon이 보낸다.

**대체 모양**(`unknown`): 레지스트리에 없는 타입·다른 버전, 서브그래프를 읽지 못한 `graph.call`은
JSON 키로 그린다. 입력 = `in`의 키(타입 `any`), 출구 = `next`의 키, 출력 = 다른 노드의 `$link`가
읽는 이름. 알 수 있는 노드라도 일부를 알 수 없으면(동적 출구 config가 틀림 등) 그 부분만 JSON 키로
채운다.

루트 그래프가 형식 검사에 걸려 IR이 없으면(`value_shapes`) 값에서 노드를 최대한 읽어 같은 규칙으로
그린다. 편집 중인 그래프는 틀릴 수 있기 때문이다.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from kookabug_core.ir import GRAPH_CALL, GRAPH_EXIT, Graph, Link, Node
from kookabug_core.loader import Program
from kookabug_core.registry import MISSING, ExitDecl, InputDecl, Registry
from kookabug_core.schema import check_shape
from kookabug_core.validate.pins import NodePins, dynamic_exit_names, node_pins

__all__ = ["ExitShape", "OutputShape", "PinShape", "Shape", "node_shapes", "value_shapes"]

ANY = "any"


@dataclass(frozen=True, slots=True)
class PinShape:
    name: str
    type: str
    nullable: bool = False
    optional: bool = False
    required: bool = False
    default: Any = MISSING
    enum: tuple[Any, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    min_items: int | None = None
    description: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "nullable": self.nullable,
            "optional": self.optional,
            "required": self.required,
        }
        if self.default is not MISSING:
            out["default"] = self.default
        if self.enum is not None:
            out["enum"] = list(self.enum)
        for key in ("minimum", "maximum", "min_items", "description"):
            if (value := getattr(self, key)) is not None:
                out[key] = value
        return out


@dataclass(frozen=True, slots=True)
class OutputShape:
    name: str
    type: str
    nullable: bool = False

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type, "nullable": self.nullable}


@dataclass(frozen=True, slots=True)
class ExitShape:
    name: str
    kind: Literal["ok", "fail"]
    outputs: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "outputs": list(self.outputs)}


@dataclass(frozen=True, slots=True)
class Shape:
    inputs: tuple[PinShape, ...]
    outputs: tuple[OutputShape, ...]
    exits: tuple[ExitShape, ...]
    unknown: bool = False
    """레지스트리로 모양을 알 수 없어 JSON 키로 만든 대체 모양."""

    def to_json(self) -> dict[str, Any]:
        return {
            "unknown": self.unknown,
            "inputs": [p.to_json() for p in self.inputs],
            "outputs": [p.to_json() for p in self.outputs],
            "exits": [e.to_json() for e in self.exits],
        }


def node_shapes(
    program: Program, graph: Graph, registry: Registry | None = None
) -> dict[str, Shape]:
    """`graph`(보통 `program.graphs[program.root]`) 노드 ID → 모양."""
    if registry is None:
        from kookabug_core.registry import default_registry

        registry = default_registry()
    readers = _link_outputs(graph.links)
    return {
        node.id: _shape(program, graph, node, registry, readers.get(node.id, ()))
        for node in graph.nodes.values()
    }


def value_shapes(
    program: Program, path: str, value: Any, registry: Registry | None = None
) -> dict[str, Shape]:
    """편집 버퍼 값의 모양. 루트 IR이 있으면(형식 검사 통과) 그것으로, 없으면 값에서 읽어서."""
    graph = program.graphs.get(path)
    if graph is None:
        graph = graph_of_value(path, value)
    return node_shapes(program, graph, registry)


# ------------------------------------------------------------------ 계산


def _link_outputs(links: list[Link]) -> dict[str, tuple[str, ...]]:
    """노드 ID → 다른 노드의 `$link`가 읽는 출력 이름 (정렬)."""
    found: dict[str, set[str]] = {}
    for link in links:
        found.setdefault(link.producer, set()).add(link.output)
    return {k: tuple(sorted(v)) for k, v in found.items()}


def _fallback(node: Node, link_outputs: tuple[str, ...]) -> Shape:
    return Shape(
        _fallback_inputs(node), _fallback_outputs(link_outputs), _fallback_exits(node), unknown=True
    )


def _fallback_inputs(node: Node) -> tuple[PinShape, ...]:
    return tuple(PinShape(name, ANY, nullable=True, optional=True) for name in node.inputs)


def _fallback_outputs(link_outputs: tuple[str, ...]) -> tuple[OutputShape, ...]:
    return tuple(OutputShape(name, ANY, nullable=True) for name in link_outputs)


def _fallback_exits(node: Node) -> tuple[ExitShape, ...]:
    return tuple(ExitShape(name, "ok") for name in node.next)


def _shape(
    program: Program, graph: Graph, node: Node, registry: Registry, link_outputs: tuple[str, ...]
) -> Shape:
    nodedef = registry.get(node.type)
    if nodedef is None or nodedef.version != node.version:
        return _fallback(node, link_outputs)
    if node.type == GRAPH_CALL and program.callee(graph.path, node.id) is None:
        return _fallback(node, link_outputs)  # 서브그래프 파일이 없거나 깨짐
    pins: NodePins = node_pins(program, graph, node, nodedef)
    describe = _descriptions(program, graph, node, nodedef.decl)
    inputs = (
        _fallback_inputs(node)
        if pins.inputs is None
        else tuple(_pin(decl, describe.get(name)) for name, decl in pins.inputs.items())
    )
    outputs = (
        _fallback_outputs(link_outputs)
        if pins.outputs is None
        else tuple(OutputShape(o.name, o.type, o.nullable) for o in pins.outputs.values())
    )
    if pins.exits is None:
        exits = _fallback_exits(node)
    else:
        # 동적 출구는 config 배열 순서대로 앞에, 고정 출구(extra)는 뒤에
        first = dynamic_exit_names(node, nodedef) or []
        order = [*dict.fromkeys(first), *(n for n in pins.exits if n not in first)]
        exits = tuple(_exit(pins.exits[n]) for n in order)
    return Shape(inputs, outputs, exits)


def _pin(decl: InputDecl, description: str | None) -> PinShape:
    return PinShape(
        decl.name,
        decl.type,
        nullable=decl.nullable,
        optional=decl.optional,
        required=decl.required,
        default=decl.default,
        enum=decl.enum,
        minimum=decl.minimum,
        maximum=decl.maximum,
        min_items=decl.min_items,
        description=description,
    )


def _exit(decl: ExitDecl) -> ExitShape:
    return ExitShape(decl.name, decl.kind, decl.outputs)


def _descriptions(
    program: Program, graph: Graph, node: Node, decl: Mapping[str, Any]
) -> dict[str, str]:
    """입력 핀 이름 → 설명 (노드 스키마 선언, interface에서 온 핀은 그 interface 선언)."""
    section: Any = decl.get("inputs")
    if node.type == GRAPH_CALL:
        callee = program.callee(graph.path, node.id)
        section = _section(callee.interface if callee else None, "inputs")
    elif node.type == GRAPH_EXIT:
        section = _section(graph.interface, "outputs")
    if not isinstance(section, Mapping):
        return {}
    return {
        name: spec["description"]
        for name, spec in section.items()
        if isinstance(spec, Mapping) and isinstance(spec.get("description"), str)
    }


def _section(interface: Mapping[str, Any] | None, part: str) -> Any:
    return interface.get(part) if isinstance(interface, Mapping) else None


# ------------------------------------------------------------------ 값에서 읽기


def graph_of_value(path: str, value: Any) -> Graph:
    """형식 검사에 걸린 그래프 값에서 모양 계산에 쓸 만큼만 읽는다 (특수 값은 해석하지 않는다).

    노드가 객체가 아니면 건너뛰고, 틀린 필드는 빈 값으로 둔다. interface가 형식에 맞지 않으면
    없는 것으로 본다(그 interface에서 오는 핀은 JSON 키로 그린다).
    """
    data: Mapping[str, Any] = value if isinstance(value, Mapping) else {}
    interface = data.get("interface")
    if not isinstance(interface, Mapping) or check_shape(
        interface, "graph", ref="#/$defs/Interface"
    ):
        interface = None
    kind = data.get("kind")
    graph = Graph(
        path=path,
        kind=kind if kind in ("test", "subgraph") else "test",
        nodes={},
        plugins={},
        interface=interface,
        data=data,
    )
    raw_nodes = data.get("nodes")
    for node_id, raw in raw_nodes.items() if isinstance(raw_nodes, Mapping) else ():
        if not isinstance(node_id, str) or not isinstance(raw, Mapping):
            continue
        node_type = raw.get("type")
        version = raw.get("version")
        inputs = _mapping(raw.get("in"))
        nexts = _mapping(raw.get("next"))
        graph.nodes[node_id] = Node(
            id=node_id,
            type=node_type if isinstance(node_type, str) else "",
            version=version if isinstance(version, int) and not isinstance(version, bool) else 0,
            title=None,
            inputs=dict(inputs),
            config=dict(_mapping(raw.get("config"))),
            next={k: v for k, v in nexts.items() if isinstance(v, str)},
            raw=raw,
        )
        for pin, pin_value in inputs.items():
            for producer, output in _links(pin_value):
                graph.links.append(Link(node_id, (pin,), producer, output))
    return graph


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _links(value: Any) -> Iterator[tuple[str, str]]:
    """값 안의 `$link` (노드, 출력). `$literal` 안은 보지 않는다."""
    if isinstance(value, list):
        for item in value:
            yield from _links(item)
    elif isinstance(value, Mapping):
        if len(value) == 1 and "$link" in value:
            ref = value["$link"]
            if isinstance(ref, str) and "." in ref:
                producer, output = ref.split(".", 1)
                yield producer, output
        elif "$literal" not in value:
            for item in value.values():
                yield from _links(item)
