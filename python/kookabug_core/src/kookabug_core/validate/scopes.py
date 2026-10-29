"""exec 흐름 검사: 명시적 순환, 반복 범위 단일 진입, 경로 끝, `while` 한도 (스키마 v0 2장·7장).

- `exec_cycle`: exec 연결은 DAG여야 한다. 반복은 본문 끝의 암묵적 귀환으로만 한다
- `loop_scope_entry`: 범위 안 노드로 들어오는 연결은 범위 안이나 반복 노드의 `body` 출구에서만.
  이 규칙 하나로 범위끼리 "완전히 포함 또는 분리"가 된다 (부분 겹침은 어딘가에서 밖→안 연결을
  만든다)
- 경로 끝(entry에서 닿는 노드의 연결 안 된 `ok` 출구): 테스트는 `unconnected_ok_exit` 경고(검증
  노드 제외), 서브그래프는 `subgraph_path_open` 오류 (G15). 반복 범위 안이면 반복 노드로 돌아가므로
  제외
- `while_requires_limit`: `core.flow.while`에 `max_iterations`가 없다
"""

from __future__ import annotations

from kookabug_core.diagnostics import json_pointer
from kookabug_core.ir import GRAPH_EXIT, Graph
from kookabug_core.validate.context import ValidationContext
from kookabug_core.validate.flow import (
    LOOP_BODY,
    entry_of,
    exec_next,
    is_loop,
    is_pure,
    loop_scopes,
    reach,
)

__all__ = ["WHILE", "WHILE_LIMIT", "check"]

WHILE = "core.flow.while"
WHILE_LIMIT = "max_iterations"


def check(ctx: ValidationContext) -> None:
    for graph in ctx.graphs():
        scopes = loop_scopes(ctx, graph)
        _exec_cycles(ctx, graph)
        _scope_entries(ctx, graph, scopes)
        _path_ends(ctx, graph, scopes)
        _while_limits(ctx, graph)


def _exec_cycles(ctx: ValidationContext, graph: Graph) -> None:
    """깊이 우선 탐색으로 되돌아가는 연결마다 하나씩 보고한다."""
    done: set[str] = set()
    for root in sorted(graph.nodes):
        if root in done or is_pure(ctx, graph.nodes[root]):
            continue
        active = {root}
        stack = [(root, iter(exec_next(ctx, graph, graph.nodes[root])))]
        while stack:
            here, edges = stack[-1]
            step = next(edges, None)
            if step is None:
                stack.pop()
                active.discard(here)
                done.add(here)
                continue
            exit, target = step
            if target in active:
                path = [n for n, _ in stack]
                cycle = [*path[path.index(target) :], target]
                hint = (
                    " 본문 끝을 연결하지 않으면 반복 노드로 돌아간다 (암묵적 귀환)"
                    if is_loop(ctx, graph.nodes[target])
                    else " 반복은 core.flow.repeat·while의 body로만 한다"
                )
                ctx.report(
                    "exec_cycle",
                    "exec 연결이 순환한다: " + " → ".join(f"'{n}'" for n in cycle) + "." + hint,
                    graph,
                    here,
                    json_pointer("nodes", here, "next", exit),
                )
            elif target not in done:
                active.add(target)
                stack.append((target, iter(exec_next(ctx, graph, graph.nodes[target]))))


def _scope_entries(ctx: ValidationContext, graph: Graph, scopes: dict[str, frozenset[str]]) -> None:
    for node in sorted(graph.nodes.values(), key=lambda n: n.id):
        if is_pure(ctx, node):
            continue
        for exit, target in exec_next(ctx, graph, node):
            entered = [
                loop
                for loop, scope in scopes.items()
                if target in scope
                and node.id not in scope
                and not (node.id == loop and exit == LOOP_BODY)
            ]
            if not entered:
                continue
            loops = ", ".join(f"'{loop}'" for loop in entered)
            ctx.report(
                "loop_scope_entry",
                f"출구 '{exit}'이(가) 반복 {loops}의 범위 안 노드 '{target}'(으)로 밖에서 "
                "들어간다. 범위에는 반복 노드의 body 출구로만 들어간다 (범위를 넘는 합류 금지)",
                graph,
                node.id,
                json_pointer("nodes", node.id, "next", exit),
            )


def _path_ends(ctx: ValidationContext, graph: Graph, scopes: dict[str, frozenset[str]]) -> None:
    """entry에서 닿는 노드만 본다 (닿지 않는 노드는 경로가 아니다)."""
    entry = entry_of(graph)
    if entry is None:
        return
    reachable = reach(ctx, graph, [entry])
    in_scope = frozenset[str]().union(*scopes.values())
    for node in sorted(graph.nodes.values(), key=lambda n: n.id):
        if node.id not in reachable:
            continue
        nodedef = ctx.nodedef(node)
        pins = ctx.pins(graph, node)
        if nodedef is None or nodedef.pure or pins is None or pins.exits is None:
            continue
        if node.id in in_scope:
            continue  # 본문 끝은 가장 안쪽 반복 노드로 돌아간다
        for exit, decl in sorted(pins.exits.items()):
            if decl.kind != "ok" or exit in node.next:
                continue
            if exit == LOOP_BODY and is_loop(ctx, node):
                continue  # 빈 본문은 바로 반복 노드로 돌아온다
            pointer = json_pointer("nodes", node.id, "next")
            if graph.kind == "subgraph":
                ctx.report(
                    "subgraph_path_open",
                    f"ok 출구 '{exit}'이(가) 연결되지 않아 서브그래프 경로가 끝난다. "
                    f"서브그래프의 경로는 공개 exit({GRAPH_EXIT})로 끝내야 한다",
                    graph,
                    node.id,
                    pointer,
                )
            elif not nodedef.assertion:
                ctx.report(
                    "unconnected_ok_exit",
                    f"ok 출구 '{exit}'이(가) 연결되지 않아 테스트가 여기서 끝난다 "
                    "(검증 없이 끝나는 경로). 검증 노드나 core.test.*로 끝낸다",
                    graph,
                    node.id,
                    pointer,
                )


def _while_limits(ctx: ValidationContext, graph: Graph) -> None:
    for node in graph.nodes_of_type(WHILE):
        if ctx.nodedef(node) is not None and WHILE_LIMIT not in node.inputs:
            ctx.report(
                "while_requires_limit",
                f"{WHILE}에는 횟수 한도 '{WHILE_LIMIT}'(1 이상)가 필요하다 (무한 반복 방지)",
                graph,
                node.id,
                json_pointer("nodes", node.id, "in"),
            )
