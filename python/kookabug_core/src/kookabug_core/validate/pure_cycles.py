"""순수 노드 data 순환 (G20): 순수 노드끼리의 `$link`(순수 → 순수)만으로 순환이 생기면 `pure_cycle`.

exec 노드의 출력은 이미 만든 값을 읽으므로 이 그래프에 넣지 않는다. 순수 노드가 exec 출력을 읽고
그 exec 노드가 다시 순수 노드를 읽는 것은 지배 검사(`link_not_dominated`)가 막는다.
"""

from __future__ import annotations

from collections import deque

from kookabug_core.diagnostics import json_pointer
from kookabug_core.ir import Graph
from kookabug_core.validate.context import ValidationContext
from kookabug_core.validate.flow import is_pure

__all__ = ["check"]


def check(ctx: ValidationContext) -> None:
    for graph in ctx.graphs():
        _graph(ctx, graph)


def _graph(ctx: ValidationContext, graph: Graph) -> None:
    pure = {n.id for n in graph.nodes.values() if is_pure(ctx, n)}
    # 소비 노드 → 읽는 순수 노드
    reads: dict[str, list[str]] = {
        q: sorted({link.producer for link in graph.links_of(q) if link.producer in pure})
        for q in sorted(pure)
    }
    reachable = {q: _reach(reads, q) for q in reads}
    reported: set[str] = set()
    for q in sorted(reads):
        if q in reported or q not in reachable[q]:
            continue
        members = {r for r in reachable[q] if q in reachable[r]}
        reported |= members
        cycle = _cycle(reads, q, members)
        link = next(link for link in graph.links_of(q) if link.producer == cycle[1])
        ctx.report(
            "pure_cycle",
            "순수 노드끼리 $link가 순환한다: "
            + " → ".join(f"'{n}'" for n in cycle)
            + " (→: $link로 읽음). 계산할 수 없다",
            graph,
            q,
            json_pointer("nodes", q, "in", *link.path),
        )


def _reach(reads: dict[str, list[str]], start: str) -> set[str]:
    """`start`에서 한 걸음 이상 가서 닿는 노드."""
    seen: set[str] = set()
    queue = deque(reads[start])
    while queue:
        here = queue.popleft()
        if here not in seen:
            seen.add(here)
            queue.extend(reads[here])
    return seen


def _cycle(reads: dict[str, list[str]], start: str, members: set[str]) -> list[str]:
    """`start`에서 출발해 돌아오는 가장 짧은 순환 (양 끝이 `start`)."""
    previous: dict[str, str] = {}
    queue = deque([start])
    while queue:
        here = queue.popleft()
        for there in reads[here]:
            if there not in members:
                continue
            if there == start:
                path = [here]
                while path[-1] != start:
                    path.append(previous[path[-1]])
                return [start, *reversed(path[:-1]), start] if here != start else [start, start]
            if there not in previous:
                previous[there] = here
                queue.append(there)
    raise AssertionError("순환 구성원인데 돌아오는 경로가 없다")
