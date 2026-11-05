"""기록 정책 검사 (M4 T12, STATE ⑦): 효과 없는 하위 층 `record.video: "on"`.

영상 정책은 위가 아래를 이긴다 (스키마 v0 6장, `record.policy`). 워크스페이스에 `record.video`가
없으면 `failed_only`라, 테스트·서브그래프·노드에서 `on`을 써도 켜지지 않는다. 실행과 같은 차례
(워크스페이스 → 테스트 그래프 → (호출 노드 → 서브그래프)… → 노드)로 실효값을 쌓으며, `on`인데 바로
위 층까지의 실효값이 더 센 곳마다 경고 `video_on_ineffective`를 낸다. 메시지에 이긴 층을 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

from kookabug_core.diagnostics import json_pointer
from kookabug_core.ir import Graph
from kookabug_core.validate.context import ValidationContext
from kookabug_core.workspace import WORKSPACE_FILE

if TYPE_CHECKING:
    from kookabug_core.record.policy import RecordPolicy

__all__ = ["check", "source_label"]

_MAX_DEPTH: Final = 16
_MODE_LABEL: Final = {"on": "켬", "failed_only": "실패만", "off": "끔"}


def source_label(source: str | None) -> str:
    """정책을 정한 층의 이름: 없으면 워크스페이스 기본값, 아니면 파일(`#` 앞)."""
    if source is None:
        return "워크스페이스 기본값"
    return source.split("#", 1)[0]


def check(ctx: ValidationContext) -> None:
    # record 패키지는 engine(→ validate)을 읽으므로 여기서 늦게 읽는다 (순환 import)
    from kookabug_core.record.policy import graph_source, workspace_policy

    program = ctx.program
    root = program.graphs.get(program.root)
    if root is None:
        return
    record = program.workspace.config.get("record")
    policy = workspace_policy(
        record if isinstance(record, Mapping) else None, graph_source(WORKSPACE_FILE)
    )
    _Walk(ctx).graph(root, policy, 0)


class _Walk:
    def __init__(self, ctx: ValidationContext) -> None:
        self.ctx = ctx
        self.seen: set[tuple[str, str, str | None]] = set()
        self.reported: set[tuple[str, str]] = set()

    def graph(self, graph: Graph, above: RecordPolicy, depth: int) -> None:
        from kookabug_core.record.policy import graph_source, node_source

        self.warn(graph, None, graph.record, above, json_pointer("record", "video"))
        policy = above.layer(graph.record, graph_source(graph.path))
        key = (graph.path, policy.video, policy.sources.get("video"))
        if key in self.seen or depth > _MAX_DEPTH:
            return
        self.seen.add(key)
        for node_id in sorted(graph.nodes):
            node = graph.nodes[node_id]
            pointer = json_pointer("nodes", node_id, "record", "video")
            self.warn(graph, node_id, node.record, policy, pointer)
            callee = self.ctx.program.callee(graph.path, node_id)
            if callee is not None:
                inner = policy.layer(node.record, node_source(graph.path, node_id))
                self.graph(callee, inner, depth + 1)

    def warn(
        self,
        graph: Graph,
        node: str | None,
        record: Mapping[str, Any] | None,
        above: RecordPolicy,
        pointer: str,
    ) -> None:
        if not isinstance(record, Mapping) or record.get("video") != "on" or above.video == "on":
            return
        if (graph.path, pointer) in self.reported:
            return
        self.reported.add((graph.path, pointer))
        winner = source_label(above.sources.get("video"))
        mode = _MODE_LABEL.get(above.video, above.video)
        self.ctx.report(
            "video_on_ineffective",
            f"record.video 'on'은 효과가 없다: 위 층({winner})의 영상 정책이 "
            f"'{above.video}'({mode})다 (위가 아래를 이긴다)",
            graph,
            node,
            pointer,
        )
