"""변수 검사: `core.var.get`이 읽는 이름을 같은 그래프에서 상수로 정하는 `core.var.set`이 없으면
경고 (G10). 변수는 호출 프레임마다 따로이므로 다른 그래프의 `var.set`은 세지 않는다."""

from __future__ import annotations

from kookabug_core.diagnostics import json_pointer
from kookabug_core.validate.context import ValidationContext

__all__ = ["VAR_GET", "VAR_SET", "check"]

VAR_GET = "core.var.get"
VAR_SET = "core.var.set"


def check(ctx: ValidationContext) -> None:
    for graph in ctx.graphs():
        names = {
            name
            for node in graph.nodes_of_type(VAR_SET)
            if isinstance(name := node.inputs.get("name"), str)
        }
        for node in graph.nodes_of_type(VAR_GET):
            name = node.inputs.get("name")
            if isinstance(name, str) and name not in names:
                ctx.report(
                    "var_never_set",
                    f"변수 '{name}'을(를) 정하는 {VAR_SET}(이름 상수)가 이 그래프에 없다",
                    graph,
                    node.id,
                    json_pointer("nodes", node.id, "in", "name"),
                )
