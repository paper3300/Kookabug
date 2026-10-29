"""호출 프레임: 테스트 하나, 또는 서브그래프 호출 하나.

프레임마다 출력 표(노드 → 그 노드가 나간 출구의 출력), 변수, 대기 중인 fail 목록, 현재 대상 창을
둔다. 출력 표에 없는 값을 읽으면 `error`다 (`$link`는 이번 경로에서 이미 만들어진 출력만 읽는다).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from kookabug_core.engine.errors import EngineError
from kookabug_core.engine.verdict import Cause
from kookabug_core.ir import Graph, LinkRef
from kookabug_sdk.result import ExitKind
from kookabug_sdk.types import WindowRef

__all__ = ["Frame", "FrameExit"]


@dataclass(frozen=True, slots=True)
class FrameExit:
    """서브그래프가 `core.graph.exit`로 끝났다. 호출 노드는 이 출구로 나간다."""

    exit: str
    kind: ExitKind
    outputs: Mapping[str, Any]


@dataclass(eq=False)
class Frame:
    graph: Graph
    path: tuple[str, ...]
    """이 프레임을 부른 호출 노드들 (테스트 프레임은 빈 튜플)."""
    parent: str | None
    """부른 스텝 ID."""
    depth: int
    inputs: Mapping[str, Any]
    """`core.graph.entry`가 줄 값 (interface 입력, 기본값 채움)."""
    current_window: WindowRef | None = None
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    vars: dict[str, Any] = field(default_factory=dict[str, Any])
    pending: list[Cause] = field(default_factory=list[Cause])
    """연결된 fail 출구로 나간 스텝 (종료 노드·공개 exit에 닿으면 해소)."""

    def node_path(self, node: str) -> tuple[str, ...]:
        return (*self.path, node)

    def record(self, node: str, outputs: Mapping[str, Any]) -> None:
        self.outputs[node] = dict(outputs)

    def invalidate(self, nodes: Iterable[str]) -> None:
        """출력을 지운다 (반복이 다음 회차로 갈 때 그 범위의 출력)."""
        for node in nodes:
            self.outputs.pop(node, None)

    def read(self, ref: LinkRef) -> Any:
        outputs = self.outputs.get(ref.node)
        if outputs is None:
            raise EngineError(
                "link_missing",
                f"'{ref}': '{ref.node}'은(는) 이번 경로에서 실행되지 않았다 "
                "(건너뛴 분기이거나 지난 반복의 값)",
            )
        if ref.output not in outputs:
            raise EngineError(
                "link_missing",
                f"'{ref}': '{ref.node}'이(가) 나간 출구는 '{ref.output}'을(를) 주지 않는다",
            )
        return outputs[ref.output]
