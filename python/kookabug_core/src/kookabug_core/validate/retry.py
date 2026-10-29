"""재시도 검사: 그래프의 `config.retry`는 노드 타입이 선언한 범위 안에서만 켠다 (스키마 v0 6장)."""

from __future__ import annotations

from collections.abc import Mapping

from kookabug_core.diagnostics import json_pointer
from kookabug_core.validate.context import ValidationContext

__all__ = ["check"]


def check(ctx: ValidationContext) -> None:
    for graph in ctx.graphs():
        for node in graph.nodes.values():
            if "retry" not in node.config:
                continue
            nodedef = ctx.nodedef(node)
            if nodedef is None:
                continue
            retry = node.config["retry"]
            pointer = json_pointer("nodes", node.id, "config", "retry")
            if nodedef.retry_mode == "never":
                ctx.report(
                    "retry_not_allowed",
                    f"'{node.type}'은(는) 재시도를 선언하지 않았다 (retry never)",
                    graph,
                    node.id,
                    pointer,
                )
                continue
            if not isinstance(retry, Mapping):
                continue  # 형식 검사가 막는다
            attempts = retry.get("max_attempts")
            if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
                ctx.report(
                    "retry_max_attempts",
                    f"max_attempts는 첫 실행을 포함한 1 이상의 정수다 ({attempts!r})",
                    graph,
                    node.id,
                    json_pointer("nodes", node.id, "config", "retry", "max_attempts"),
                )
            on = retry.get("on", [])
            for i, name in enumerate(on if isinstance(on, list) else []):
                if name not in nodedef.retry_on:
                    allowed = ", ".join(nodedef.retry_on)
                    ctx.report(
                        "retry_exit_not_allowed",
                        f"출구 '{name}'은(는) 재시도할 수 없다 (재시도 출구: {allowed})",
                        graph,
                        node.id,
                        json_pointer("nodes", node.id, "config", "retry", "on", i),
                    )
