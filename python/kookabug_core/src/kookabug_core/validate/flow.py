"""흐름 검사(`dominance`·`pure_cycles`·`scopes`)가 같이 쓰는 exec 그래프 도구.

- exec 그래프: 순수 노드가 아닌 노드와 `next` 연결. 없는 노드·순수 노드로 가는 연결은 빼고 본다
  (`dangling_next`·`exec_into_pure`로 따로 보고된다)
- 종료 노드: 출구가 없는 exec 노드 (`core.test.*`, `core.graph.exit`)
- 반복 범위: `core.flow.repeat`·`while`의 `body` 출구에서 도달할 수 있는 노드 (스키마 v0 7장).
  종료 노드와 반복 노드 자신은 넣지 않는다 (종료 노드는 범위 안팎에서 같이 쓸 수 있다)
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping

from kookabug_core.ir import GRAPH_ENTRY, Graph, Node
from kookabug_core.validate.context import ValidationContext

__all__ = [
    "LOOP_BODY",
    "LOOP_ENGINES",
    "entry_of",
    "exec_next",
    "is_loop",
    "is_pure",
    "is_terminal",
    "loop_scopes",
    "reach",
]

LOOP_ENGINES = frozenset({"repeat", "while"})
LOOP_BODY = "body"


def is_pure(ctx: ValidationContext, node: Node) -> bool:
    nodedef = ctx.registry.get(node.type)
    return nodedef is not None and nodedef.pure


def is_terminal(ctx: ValidationContext, node: Node) -> bool:
    nodedef = ctx.registry.get(node.type)
    return nodedef is not None and not nodedef.pure and nodedef.exits == ()


def is_loop(ctx: ValidationContext, node: Node) -> bool:
    nodedef = ctx.registry.get(node.type)
    return nodedef is not None and nodedef.engine in LOOP_ENGINES


def entry_of(graph: Graph) -> str | None:
    """`core.graph.entry`가 정확히 하나면 그 ID (아니면 `entry_count`가 이미 보고됨)."""
    entries = [n.id for n in graph.nodes.values() if n.type == GRAPH_ENTRY]
    return entries[0] if len(entries) == 1 else None


def exec_next(ctx: ValidationContext, graph: Graph, node: Node) -> list[tuple[str, str]]:
    """노드의 exec 연결 (출구, 대상)을 출구 이름 순으로."""
    found = []
    for exit, target in sorted(node.next.items()):
        target_node = graph.nodes.get(target)
        if target_node is not None and not is_pure(ctx, target_node):
            found.append((exit, target))
    return found


def reach(
    ctx: ValidationContext,
    graph: Graph,
    starts: Iterable[str],
    *,
    blocked: Mapping[str, frozenset[str]] | None = None,
    stop: frozenset[str] = frozenset(),
) -> set[str]:
    """`starts`에서 exec 연결로 닿는 노드 (`starts` 포함).

    `blocked[노드]`의 출구로는 나가지 않는다. `stop`의 노드에는 들어가지 않는다.
    """
    blocked = blocked or {}
    seen: set[str] = set()
    queue = deque(
        s for s in starts if s in graph.nodes and s not in stop and not is_pure(ctx, graph.nodes[s])
    )
    while queue:
        here = queue.popleft()
        if here in seen:
            continue
        seen.add(here)
        closed = blocked.get(here, frozenset())
        for exit, target in exec_next(ctx, graph, graph.nodes[here]):
            if exit not in closed and target not in seen and target not in stop:
                queue.append(target)
    return seen


def loop_scopes(ctx: ValidationContext, graph: Graph) -> dict[str, frozenset[str]]:
    """반복 노드 ID → 범위 (종료 노드·반복 노드 자신 제외)."""
    terminals = frozenset(n.id for n in graph.nodes.values() if is_terminal(ctx, n))
    scopes: dict[str, frozenset[str]] = {}
    for loop in sorted(graph.nodes.values(), key=lambda n: n.id):
        if not is_loop(ctx, loop):
            continue
        body = loop.next.get(LOOP_BODY)
        # 본문이 반복 노드로 돌아오는 연결(exec_cycle)을 따라가면 done 뒤까지 범위에 들어간다
        stop = terminals | {loop.id}
        scopes[loop.id] = frozenset(reach(ctx, graph, [body] if body else [], stop=stop))
    return scopes
