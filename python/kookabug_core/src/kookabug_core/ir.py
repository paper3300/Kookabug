"""그래프의 내부 표현 (로더가 만들고 검증·실행기가 읽는다).

`Node.inputs`는 `in`의 특수 값을 해석한 값 트리다.
- `$link` → `LinkRef` (값은 실행 때 읽는다)
- `$secret` → `kookabug_sdk.Secret`, `$target` → `kookabug_sdk.types.Target`
- `$setting` → 설정값, `$literal` → 안의 값 그대로
- 해석하지 못한 값(없는 설정·비밀값·target) → `Unresolved` (진단은 로더가 남긴다)
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "GRAPH_CALL",
    "GRAPH_ENTRY",
    "GRAPH_EXIT",
    "TEST_TERMINALS",
    "ExecEdge",
    "Graph",
    "Link",
    "LinkRef",
    "Node",
    "Unresolved",
]

# 로더·검증이 이름으로 알아야 하는 코어 노드 (실행기가 직접 처리하는 노드)
GRAPH_ENTRY = "core.graph.entry"
GRAPH_EXIT = "core.graph.exit"
GRAPH_CALL = "core.graph.call"
TEST_TERMINALS = frozenset({"core.test.pass", "core.test.fail", "core.test.skip"})

type Path = tuple[str | int, ...]


@dataclass(frozen=True, slots=True)
class LinkRef:
    node: str
    output: str

    def __str__(self) -> str:
        return f"{self.node}.{self.output}"


@dataclass(frozen=True, slots=True)
class Unresolved:
    """해석하지 못한 특수 값. `tag`는 `$setting` 등, `key`는 그 값."""

    tag: str
    key: str


@dataclass(frozen=True, slots=True)
class Link:
    """data 연결: `consumer`의 입력 `path`(핀 이름부터) ← `producer.output`."""

    consumer: str
    path: Path
    producer: str
    output: str

    @property
    def pin(self) -> str:
        return str(self.path[0])


@dataclass(frozen=True, slots=True)
class ExecEdge:
    """exec 연결: `node`의 `exit` 출구 → `target`."""

    node: str
    exit: str
    target: str


@dataclass
class Node:
    id: str
    type: str
    version: int
    title: str | None
    inputs: dict[str, Any]
    config: dict[str, Any]
    next: dict[str, str]
    raw: Mapping[str, Any]

    @property
    def retry(self) -> Mapping[str, Any] | None:
        retry = self.config.get("retry")
        return retry if isinstance(retry, Mapping) else None

    @property
    def plugin(self) -> str:
        return self.type.split(".", 1)[0]


@dataclass
class Graph:
    """그래프 파일 하나. `path`는 워크스페이스 루트 기준('/' 구분)."""

    path: str
    kind: Literal["test", "subgraph"]
    nodes: dict[str, Node]
    plugins: dict[str, str]
    interface: Mapping[str, Any] | None = None
    links: list[Link] = field(default_factory=list[Link])
    data: Mapping[str, Any] = field(default_factory=dict[str, Any])

    def exec_edges(self) -> Iterator[ExecEdge]:
        for node in self.nodes.values():
            for exit, target in node.next.items():
                yield ExecEdge(node.id, exit, target)

    def links_of(self, consumer: str) -> list[Link]:
        return [link for link in self.links if link.consumer == consumer]

    def nodes_of_type(self, node_type: str) -> list[Node]:
        return [n for n in self.nodes.values() if n.type == node_type]
