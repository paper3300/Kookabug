"""값 검사: `$link`가 같은 그래프의 있는 노드·출력을 가리키는가.

`$setting`·`$secret`·`$target` 해석 문제(`setting_missing`·`setting_null`·`secret_missing`·
`target_missing`·`target_invalid`)는 로더가 읽으면서 남긴다 (`kookabug_core.loader`).
"""

from __future__ import annotations

from kookabug_core.diagnostics import json_pointer
from kookabug_core.validate.context import ValidationContext

__all__ = ["check"]


def check(ctx: ValidationContext) -> None:
    for graph in ctx.graphs():
        for link in graph.links:
            pointer = json_pointer("nodes", link.consumer, "in", *link.path)
            producer = graph.nodes.get(link.producer)
            if producer is None:
                ctx.report(
                    "link_bad_node",
                    f"$link '{link.producer}.{link.output}': 노드 '{link.producer}'이(가) 없다",
                    graph,
                    link.consumer,
                    pointer,
                )
                continue
            pins = ctx.pins(graph, producer)
            if pins is None or pins.outputs is None:
                continue  # 노드 타입·서브그래프 문제는 따로 보고된다
            if link.output not in pins.outputs:
                known = ", ".join(sorted(pins.outputs)) or "없음"
                ctx.report(
                    "link_bad_output",
                    f"$link '{link.producer}.{link.output}': '{producer.type}'에 출력 "
                    f"'{link.output}'이(가) 없다 (출력: {known})",
                    graph,
                    link.consumer,
                    pointer,
                )
