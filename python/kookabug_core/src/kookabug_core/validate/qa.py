"""그래프 `qa`·치트 노드 검사 (M8 계획 3.5): 설정 오류는 `qa_invalid`.

- 루트 `qa.claims`: 주장·rev가 지식 파일(지금 또는 옛 rev)에 있고, `assertions`가 루트 그래프의
  검증 노드(`assertion: true`)다
- `qa.cheats.allow`(루트·서브그래프): 치트 ID가 `knowledge/cheats.json`에 있고, 인자 제한이 정의된
  인자만 가리키며 범위 제한은 `min`·`max` 중 하나 이상
- 치트 노드: `config.cheat`가 있는 치트이고 콘솔 구현 서브그래프를 읽었다(구현 누락은 설정 오류)

허용 판정(채택·digest·무인·범위·횟수)은 실행 때 치트 노드가 한다 (`kookabug_core.qa.CheatGate`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kookabug_core.diagnostics import json_pointer
from kookabug_core.ir import QA_CHEAT, Graph
from kookabug_core.qa import QA_INVALID, find_claim
from kookabug_core.validate.context import ValidationContext

__all__ = ["check"]


def check(ctx: ValidationContext) -> None:
    program = ctx.program
    root = program.graphs.get(program.root)
    if root is None:
        return
    qa = program.qa
    if qa is not None:
        _claims(ctx, root, qa)
    for graph in ctx.graphs():
        graph_qa = graph.data.get("qa")
        if isinstance(graph_qa, Mapping):
            _allow(ctx, graph, graph_qa)
        for node in graph.nodes_of_type(QA_CHEAT):
            _cheat_node(ctx, graph, node.id, node.config)


def _claims(ctx: ValidationContext, root: Graph, qa: Mapping[str, Any]) -> None:
    for i, claim in enumerate(qa.get("claims", ())):
        pointer = json_pointer("qa", "claims", i)
        claim_id, rev = str(claim.get("id")), int(claim.get("rev", 0))
        if not find_claim(ctx.program, claim_id, rev):
            ctx.report(
                QA_INVALID,
                f"qa 주장 '{claim_id}' rev {rev}이(가) 지식 파일에 없다",
                root,
                None,
                pointer,
            )
        for j, node_id in enumerate(claim.get("assertions", ())):
            node = root.nodes.get(str(node_id))
            nodedef = ctx.nodedef(node) if node is not None else None
            if nodedef is None or not nodedef.assertion:
                ctx.report(
                    QA_INVALID,
                    f"qa 주장 '{claim_id}'의 '{node_id}'이(가) 이 그래프의 검증 노드가 아니다",
                    root,
                    str(node_id) if node is not None else None,
                    json_pointer("qa", "claims", i, "assertions", j),
                )


def _allow(ctx: ValidationContext, graph: Graph, qa: Mapping[str, Any]) -> None:
    cheats: Any = qa.get("cheats")
    allow: list[Any] = list(cheats.get("allow", ())) if isinstance(cheats, Mapping) else []
    for i, entry in enumerate(allow):
        pointer = json_pointer("qa", "cheats", "allow", i)
        cheat_id = str(entry.get("id"))
        cheat = ctx.program.cheat(cheat_id)
        if cheat is None:
            ctx.report(
                QA_INVALID,
                f"qa가 허용한 치트 '{cheat_id}'이(가) 치트 정의에 없다",
                graph,
                None,
                pointer,
            )
            continue
        spec = cheat.get("args") or {}
        for name, limit in (entry.get("args") or {}).items():
            if name not in spec:
                ctx.report(
                    QA_INVALID,
                    f"치트 '{cheat_id}'에 인자 '{name}'이(가) 없다",
                    graph,
                    None,
                    json_pointer("qa", "cheats", "allow", i, "args", name),
                )
            elif "enum" not in limit and "min" not in limit and "max" not in limit:
                ctx.report(
                    QA_INVALID,
                    f"치트 '{cheat_id}' 인자 '{name}' 범위에 min·max가 없다",
                    graph,
                    None,
                    json_pointer("qa", "cheats", "allow", i, "args", name),
                )


def _cheat_node(ctx: ValidationContext, graph: Graph, node_id: str, config: Any) -> None:
    pointer = json_pointer("nodes", node_id, "config", "cheat")
    cheat_id = config.get("cheat") if isinstance(config, Mapping) else None
    cheat = ctx.program.cheat(cheat_id) if isinstance(cheat_id, str) else None
    if cheat is None:
        ctx.report(
            QA_INVALID,
            f"치트 노드가 가리키는 치트 '{cheat_id}'이(가) 없다",
            graph,
            node_id,
            pointer,
        )
        return
    if ctx.program.callee(graph.path, node_id) is None:
        ctx.report(
            QA_INVALID,
            f"치트 '{cheat_id}'의 구현(콘솔 서브그래프)을 읽지 못했다",
            graph,
            node_id,
            pointer,
        )
