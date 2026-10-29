"""구조 검사: entry 개수, 노드 타입·버전·플러그인 선언, 입력·출구 이름, next 대상, config, 폴더."""

from __future__ import annotations

import re

from kookabug_core.diagnostics import json_pointer
from kookabug_core.ir import GRAPH_ENTRY, GRAPH_EXIT, Graph, Node
from kookabug_core.registry import DynamicExitsDecl, NodeDef
from kookabug_core.validate.context import ValidationContext
from kookabug_core.validate.pins import dynamic_exit_names
from kookabug_core.validate.types import value_problems

__all__ = ["check"]

# config에서 노드 스키마가 아니라 그래프 공통 규칙이 정하는 키 (retry 검사가 본다)
COMMON_CONFIG = frozenset({"retry"})
_FOLDER_KIND = {"tests": "test", "subgraphs": "subgraph"}
_EXIT_NAME = re.compile(r"^[a-z_][a-z0-9_]*\Z")


def check(ctx: ValidationContext) -> None:
    for graph in ctx.graphs():
        _entry(ctx, graph)
        _folder(ctx, graph)
        for node in graph.nodes.values():
            _node(ctx, graph, node)


def _entry(ctx: ValidationContext, graph: Graph) -> None:
    entries = sorted(n.id for n in graph.nodes.values() if n.type == GRAPH_ENTRY)
    if len(entries) != 1:
        found = ", ".join(entries) if entries else "없음"
        ctx.report(
            "entry_count",
            f"{GRAPH_ENTRY}는 정확히 하나여야 한다 (지금: {found})",
            graph,
            pointer="/nodes",
        )


def _folder(ctx: ValidationContext, graph: Graph) -> None:
    expected = _FOLDER_KIND.get(graph.path.split("/", 1)[0])
    if expected is not None and expected != graph.kind:
        ctx.report(
            "kind_folder_mismatch",
            f"{graph.path.split('/', 1)[0]}/ 폴더에 kind '{graph.kind}' 그래프가 있다 "
            f"('{expected}'이어야 한다)",
            graph,
            pointer="/kind",
        )


def _node(ctx: ValidationContext, graph: Graph, node: Node) -> None:
    at = node.id
    if node.plugin not in graph.plugins:
        ctx.report(
            "plugin_not_declared",
            f"노드 타입 '{node.type}'의 플러그인 '{node.plugin}'이(가) 그래프 plugins에 없다",
            graph,
            at,
            json_pointer("nodes", at, "type"),
        )
    for exit, target in node.next.items():
        if target not in graph.nodes:
            ctx.report(
                "dangling_next",
                f"출구 '{exit}'이(가) 없는 노드 '{target}'을(를) 가리킨다",
                graph,
                at,
                json_pointer("nodes", at, "next", exit),
            )
            continue
        target_def = ctx.registry.get(graph.nodes[target].type)
        if target_def is not None and target_def.pure:
            # 순수 노드는 exec 핀이 없다. 소비하는 노드가 $link로 읽을 때 계산된다 (스키마 v0 7장)
            ctx.report(
                "exec_into_pure",
                f"출구 '{exit}'이(가) 순수 노드 '{target}'({target_def.type})로 간다. "
                "순수 노드는 exec 연결을 받지 않고 $link로 읽는다",
                graph,
                at,
                json_pointer("nodes", at, "next", exit),
            )

    nodedef = ctx.registry.get(node.type)
    if nodedef is None:
        ctx.report(
            "unknown_node_type",
            f"설치된 플러그인에 노드 타입 '{node.type}'이(가) 없다",
            graph,
            at,
            json_pointer("nodes", at, "type"),
        )
        return
    if nodedef.version != node.version:
        ctx.report(
            "node_version_mismatch",
            f"'{node.type}' 버전이 {node.version}인데 설치된 노드는 {nodedef.version}이다",
            graph,
            at,
            json_pointer("nodes", at, "version"),
        )
        return

    pins = ctx.pins(graph, node)
    assert pins is not None
    if pins.inputs is not None:
        for pin in node.inputs:
            if pin not in pins.inputs:
                known = ", ".join(sorted(pins.inputs)) or "없음"
                ctx.report(
                    "unknown_input",
                    f"'{node.type}'에 입력 '{pin}'이(가) 없다 (입력: {known})",
                    graph,
                    at,
                    json_pointer("nodes", at, "in", pin),
                )
        if node.type != GRAPH_EXIT:  # exit 노드의 필수 출력은 subgraph 검사(G16)가 본다
            for name, decl in pins.inputs.items():
                if decl.required and name not in node.inputs:
                    ctx.report(
                        "missing_required_input",
                        f"입력 '{name}'에 값이 없다 (기본값 없는 입력)",
                        graph,
                        at,
                        json_pointer("nodes", at, "in"),
                    )
    if pins.exits is not None:
        for exit in node.next:
            if exit not in pins.exits:
                known = ", ".join(sorted(pins.exits)) or "없음"
                ctx.report(
                    "unknown_exit",
                    f"'{node.type}'에 출구 '{exit}'이(가) 없다 (출구: {known})",
                    graph,
                    at,
                    json_pointer("nodes", at, "next", exit),
                )
    _config(ctx, graph, node, nodedef)


def _config(ctx: ValidationContext, graph: Graph, node: Node, nodedef: NodeDef) -> None:
    at = node.id
    declared = {c.name: c for c in nodedef.config}
    for key, value in node.config.items():
        pointer = json_pointer("nodes", at, "config", key)
        if key in COMMON_CONFIG:
            continue
        decl = declared.get(key)
        if decl is None:
            known = ", ".join(sorted(declared)) or "없음"
            ctx.report(
                "config_invalid",
                f"'{node.type}'에 config '{key}'이(가) 없다 (config: {known})",
                graph,
                at,
                pointer,
            )
            continue
        for path, _, message in value_problems(value, decl, lambda _: None):
            ctx.report(
                "config_invalid",
                f"config '{key}': {message}",
                graph,
                at,
                json_pointer("nodes", at, "config", key, *path),
            )
    for name, decl in declared.items():
        if decl.required and name not in node.config:
            ctx.report(
                "config_invalid",
                f"config '{name}'이(가) 없다 (기본값 없는 설정)",
                graph,
                at,
                json_pointer("nodes", at, "config"),
            )
    _dynamic_exits(ctx, graph, node, nodedef)


def _dynamic_exits(ctx: ValidationContext, graph: Graph, node: Node, nodedef: NodeDef) -> None:
    """동적 출구 이름은 겹치지 않고, 고정 출구(`extra`)와도 겹치지 않는다."""
    exits = nodedef.exits
    names = dynamic_exit_names(node, nodedef)
    if not isinstance(exits, DynamicExitsDecl) or names is None:
        return
    fixed = {e.name for e in exits.extra}
    given = exits.from_config in node.config  # 아니면 노드 스키마의 기본값
    for i, name in enumerate(names):
        if name in names[:i]:
            why = "두 번 있다"
        elif name in fixed:
            why = "고정 출구와 이름이 같다"
        elif not _EXIT_NAME.match(name):
            why = "출구 이름 형식이 아니다 (소문자·숫자·밑줄)"
        else:
            continue
        where = ("config", exits.from_config, i) if given else ("config",)
        source = "" if given else f" (config '{exits.from_config}' 기본값)"
        ctx.report(
            "config_invalid",
            f"동적 출구 '{name}'이(가) {why}{source}",
            graph,
            node.id,
            json_pointer("nodes", node.id, *where),
        )
