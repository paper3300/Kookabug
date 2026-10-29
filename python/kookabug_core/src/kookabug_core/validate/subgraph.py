"""서브그래프 검사: 호출 대상, 호출 순환·깊이, 종료 노드 위치, 공개 출구와 출력 (G15·G16)."""

from __future__ import annotations

from collections import defaultdict

from kookabug_core.diagnostics import json_pointer
from kookabug_core.ir import GRAPH_CALL, GRAPH_EXIT, TEST_TERMINALS, Graph
from kookabug_core.loader import MAX_CALL_DEPTH
from kookabug_core.validate.context import ValidationContext

__all__ = ["MAX_CALL_DEPTH", "check"]


def check(ctx: ValidationContext) -> None:
    for graph in ctx.graphs():
        _terminals(ctx, graph)
        if graph.kind == "subgraph":
            _exits(ctx, graph)
        _call_targets(ctx, graph)
    _call_chains(ctx)


def _terminals(ctx: ValidationContext, graph: Graph) -> None:
    for node in graph.nodes.values():
        pointer = json_pointer("nodes", node.id, "type")
        if graph.kind == "subgraph" and node.type in TEST_TERMINALS:
            ctx.report(
                "terminal_in_subgraph",
                f"'{node.type}'은(는) 테스트에서만 쓴다. 서브그래프는 {GRAPH_EXIT}로 끝낸다",
                graph,
                node.id,
                pointer,
            )
        if graph.kind == "test" and node.type == GRAPH_EXIT:
            ctx.report(
                "graph_exit_in_test",
                f"테스트에는 {GRAPH_EXIT}를 둘 수 없다. core.test.pass·fail·skip으로 끝낸다",
                graph,
                node.id,
                pointer,
            )


def _exits(ctx: ValidationContext, graph: Graph) -> None:
    interface = graph.interface or {}
    exits = interface.get("exits", {})
    outputs = interface.get("outputs", {})
    required = sorted(name for name, decl in outputs.items() if not decl.get("nullable", False))
    used: set[str] = set()
    for node in graph.nodes.values():
        if node.type != GRAPH_EXIT or ctx.nodedef(node) is None:
            continue
        name = node.config.get("exit")
        if isinstance(name, str):
            used.add(name)
            if name not in exits:
                known = ", ".join(sorted(exits))
                ctx.report(
                    "exit_name_unknown",
                    f"config.exit '{name}'이(가) interface.exits에 없다 (출구: {known})",
                    graph,
                    node.id,
                    json_pointer("nodes", node.id, "config", "exit"),
                )
        for output in required:
            if output not in node.inputs:
                ctx.report(
                    "exit_missing_required_output",
                    f"출력 '{output}'은(는) nullable이 아니므로 모든 {GRAPH_EXIT}가 줘야 한다",
                    graph,
                    node.id,
                    json_pointer("nodes", node.id, "in"),
                )
    for name in sorted(set(exits) - used):
        ctx.report(
            "interface_exit_unused",
            f"interface 출구 '{name}'로 나가는 {GRAPH_EXIT}가 없다",
            graph,
            pointer=json_pointer("interface", "exits", name),
        )


def _call_targets(ctx: ValidationContext, graph: Graph) -> None:
    for node in graph.nodes_of_type(GRAPH_CALL):
        ref = ctx.program.calls.get((graph.path, node.id))
        target = node.config.get("graph")
        if ref is None or not isinstance(target, str):
            continue  # config.graph가 없거나 문자열이 아님 → config_invalid
        pointer = json_pointer("nodes", node.id, "config", "graph")
        if ref.status == "missing":
            ctx.report(
                "call_target_missing",
                f"서브그래프 파일 '{target}'이(가) 없다",
                graph,
                node.id,
                pointer,
            )
        elif ref.status == "bad_path":
            ctx.report(
                "call_target_missing",
                f"'{target}'은(는) 워크스페이스 경로가 아니다 (루트 기준, '/' 구분, '..' 없이)",
                graph,
                node.id,
                pointer,
            )
        elif ref.status == "ok":
            callee = ctx.program.callee(graph.path, node.id)
            if callee is not None and callee.kind != "subgraph":
                ctx.report(
                    "call_target_not_subgraph",
                    f"'{target}'은(는) 테스트 그래프다. 서브그래프(kind: subgraph)만 부를 수 있다",
                    graph,
                    node.id,
                    pointer,
                )


def _call_chains(ctx: ValidationContext) -> None:
    """루트에서 시작하는 호출 그래프에서 순환(되돌아가는 호출)과 너무 깊은 호출을 찾는다."""
    program = ctx.program
    edges: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for caller, node in sorted(program.calls):
        callee = program.callee(caller, node)
        if callee is not None and callee.kind == "subgraph":
            edges[caller].append((node, callee.path))

    root = program.root
    if root not in program.graphs:
        return
    # 1) 깊이 우선 탐색으로 되돌아가는 간선(순환) 찾기
    state: dict[str, int] = {}  # 1 = 탐색 중, 2 = 끝
    back: set[tuple[str, str]] = set()
    order: list[str] = []
    stack: list[tuple[str, int]] = [(root, 0)]
    state[root] = 1
    while stack:
        here, i = stack[-1]
        if i < len(edges[here]):
            stack[-1] = (here, i + 1)
            node, callee = edges[here][i]
            if state.get(callee) == 1:
                back.add((here, node))
                cycle = [g for g, _ in stack[[g for g, _ in stack].index(callee) :]] + [callee]
                ctx.report(
                    "call_cycle",
                    "서브그래프 호출이 순환한다: " + " → ".join(cycle),
                    program.graphs[here],
                    node,
                    json_pointer("nodes", node, "config", "graph"),
                )
            elif callee not in state:
                state[callee] = 1
                stack.append((callee, 0))
        else:
            state[here] = 2
            order.append(here)
            stack.pop()

    # 2) 순환을 뺀 호출 그래프에서 루트로부터 가장 긴 깊이
    depth: dict[str, int] = {root: 0}
    for here in reversed(order):  # 위상 순서
        for node, callee in edges[here]:
            if (here, node) in back or here not in depth:
                continue
            if depth[here] == MAX_CALL_DEPTH:
                ctx.report(
                    "call_depth",
                    f"서브그래프 호출이 {MAX_CALL_DEPTH}단계보다 깊다 ('{callee}' 호출)",
                    program.graphs[here],
                    node,
                    json_pointer("nodes", node, "config", "graph"),
                )
            depth[callee] = max(depth.get(callee, 0), depth[here] + 1)
