"""`$link` 지배 검사 (스키마 v0 7장 "`$link` 평가"·"반복 범위").

exec 노드 C가 exec 노드 P의 출력 `o`를 읽으면 (순수 노드를 거쳐 읽어도 C 기준으로 본다):
- `link_out_of_scope`: P가 반복 L의 범위 안(또는 P = L)인데 C는 그 범위 밖이다. 종료 노드는 범위
  계산에서 빠지므로 따로 본다: L의 본문 안(범위 안 노드·L의 body 출구)에서만 오는 종료 노드는 그
  회차 값을 읽을 수 있어 지배 검사만 받고, 범위 밖에서도 오면 이 오류다
- `link_not_dominated`: P의 출구 중 `o`를 주는 출구를 막은 exec 그래프에서 entry → C 경로가 남는다.
  지배 규칙과 "그 출구가 출력을 주는가"를 한 번에 본다. 반복의 암묵적 귀환은 간선에 넣지 않으므로
  본문 뒤쪽 노드의 출력(지난 회차 값)을 앞쪽에서 읽는 것도 여기서 막힌다
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from kookabug_core.diagnostics import json_pointer
from kookabug_core.ir import Graph, Link
from kookabug_core.validate.context import ValidationContext
from kookabug_core.validate.flow import (
    LOOP_BODY,
    entry_of,
    exec_next,
    is_pure,
    is_terminal,
    loop_scopes,
    reach,
)

__all__ = ["check", "exec_sources"]


@dataclass(frozen=True, slots=True)
class Source:
    """C가 읽는 exec 출력 하나. `via`는 거쳐 온 순수 노드 (C 쪽부터)."""

    producer: str
    output: str
    via: tuple[str, ...]


def exec_sources(ctx: ValidationContext, graph: Graph, link: Link) -> list[Source]:
    """연결 하나가 순수 노드를 거쳐 결국 읽는 exec 출력들 (같은 출력은 한 번).

    순수 노드 순환(`pure_cycle`)이 있어도 방문 집합으로 끝난다.
    """
    found: dict[tuple[str, str], Source] = {}
    seen: set[str] = set()
    stack: list[tuple[Link, tuple[str, ...]]] = [(link, ())]
    while stack:
        here, via = stack.pop()
        producer = graph.nodes.get(here.producer)
        if producer is None:
            continue  # link_bad_node
        if not is_pure(ctx, producer):
            found.setdefault((here.producer, here.output), Source(here.producer, here.output, via))
            continue
        if producer.id in seen:
            continue
        seen.add(producer.id)
        for inner in reversed(graph.links_of(producer.id)):
            stack.append((inner, (*via, producer.id)))
    return [found[k] for k in sorted(found)]


def check(ctx: ValidationContext) -> None:
    for graph in ctx.graphs():
        _graph(ctx, graph)


def _graph(ctx: ValidationContext, graph: Graph) -> None:
    entry = entry_of(graph)
    scopes = loop_scopes(ctx, graph)
    reachable: dict[tuple[str, frozenset[str]], set[str]] = {}
    incoming: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for node in graph.nodes.values():
        if not is_pure(ctx, node):
            for exit, target in exec_next(ctx, graph, node):
                incoming[target].append((node.id, exit))
    for consumer in sorted(graph.nodes):
        if is_pure(ctx, graph.nodes[consumer]):
            continue
        terminal_from = incoming[consumer] if is_terminal(ctx, graph.nodes[consumer]) else None
        for link in graph.links_of(consumer):
            for source in exec_sources(ctx, graph, link):
                pointer = json_pointer("nodes", consumer, "in", *link.path)
                problem = _out_of_scope(scopes, consumer, source, terminal_from)
                if problem is not None:
                    ctx.report("link_out_of_scope", problem, graph, consumer, pointer)
                    continue
                if entry is None:
                    continue
                giving = _giving_exits(ctx, graph, source)
                if giving is None:
                    continue
                key = (source.producer, giving)
                if key not in reachable:
                    reachable[key] = reach(ctx, graph, [entry], blocked={source.producer: giving})
                if consumer in reachable[key]:
                    ctx.report(
                        "link_not_dominated",
                        _not_dominated(consumer, source, giving),
                        graph,
                        consumer,
                        pointer,
                    )


def _giving_exits(ctx: ValidationContext, graph: Graph, source: Source) -> frozenset[str] | None:
    """생산 노드의 출구 중 그 출력을 주는 것. 알 수 없으면 None (원인 진단은 따로 나간다)."""
    pins = ctx.pins(graph, graph.nodes[source.producer])
    if pins is None or pins.exits is None or pins.outputs is None:
        return None
    if source.output not in pins.outputs:
        return None  # link_bad_output
    return frozenset(name for name, decl in pins.exits.items() if source.output in decl.outputs)


def _ref(source: Source) -> str:
    chain = "".join(f"'{p}' ← " for p in source.via)
    return f"{chain}'{source.producer}.{source.output}'"


def _out_of_scope(
    scopes: dict[str, frozenset[str]],
    consumer: str,
    source: Source,
    terminal_from: list[tuple[str, str]] | None,
) -> str | None:
    """`terminal_from`: 소비 노드가 종료 노드면 그리로 오는 연결 (노드, 출구), 아니면 None."""
    for loop, scope in scopes.items():
        inside = source.producer in scope or source.producer == loop
        if not inside or consumer in scope:
            continue
        if terminal_from is not None and all(
            node in scope or (node, exit) == (loop, LOOP_BODY) for node, exit in terminal_from
        ):
            continue  # 본문 안에서만 오는 종료 노드는 그 회차 값을 읽는다 (지배 검사만)
        where = "반복 노드의 출력" if source.producer == loop else "반복 범위 안 노드의 출력"
        shared = " (범위 밖에서도 오는 종료 노드)" if terminal_from is not None else ""
        return (
            f"{_ref(source)}은(는) '{loop}' {where}이라 범위 밖에서 읽을 수 없다{shared}. "
            "값을 밖으로 꺼내려면 core.var.set을 쓴다"
        )
    return None


def _not_dominated(consumer: str, source: Source, giving: frozenset[str]) -> str:
    if consumer == source.producer:
        return f"'{consumer}'이(가) 자기 출력을 읽는다: {_ref(source)} (아직 만들어지지 않은 값)"
    if not giving:
        return (
            f"{_ref(source)}: '{source.producer}'의 어느 출구도 출력 '{source.output}'을 "
            "주지 않는다"
        )
    exits = ", ".join(sorted(giving))
    return (
        f"{_ref(source)}: '{consumer}'에 닿는 실행 경로 중 '{source.producer}'의 출구 "
        f"({exits})를 지나지 않는 경로가 있다 (건너뛴 분기·다른 출구·지난 반복의 값)"
    )
