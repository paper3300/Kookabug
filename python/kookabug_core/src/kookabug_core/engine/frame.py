"""호출 프레임: 테스트 하나, 또는 서브그래프 호출 하나.

프레임마다 출력 표(노드 → 그 노드가 나간 출구의 출력), 변수, 대기 중인 fail 목록, 반복 스택, 현재
대상 창을 둔다. 출력 표에 없는 값을 읽으면 `error`다 (`$link`는 이번 경로에서 이미 만들어진 출력만
읽는다). 반복은 프레임 안에서만 돈다 (서브그래프 호출은 새 프레임이라 반복 스택도 새로 시작한다).
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from kookabug_core.engine.errors import EngineError
from kookabug_core.engine.provenance import Origin
from kookabug_core.engine.verdict import Cause
from kookabug_core.ir import Graph, LinkRef
from kookabug_core.record.policy import RecordPolicy
from kookabug_sdk.result import ExitKind
from kookabug_sdk.types import WindowRef

__all__ = ["Frame", "FrameExit", "LoopState"]

_LOOP_SERIAL = itertools.count(1)


@dataclass(eq=False)
class LoopState:
    """실행 중인 반복 하나 (`core.flow.repeat`·`while`)."""

    node: str
    scope: frozenset[str]
    """범위: `body`에서 닿는 노드 (종료 노드·반복 노드 자신 제외, 정적 계산)."""
    limit: int
    """`repeat`의 `times`, `while`의 `max_iterations`. 반복에 들어갈 때 정한다."""
    started: int = 0
    """시작한 회차 수. 지금 회차의 `index`는 `started - 1`."""
    returning: bool = False
    """본문이 끝나 이 반복 노드로 돌아가는 중 (암묵적 귀환)."""
    serial: int = field(default_factory=lambda: next(_LOOP_SERIAL))
    """반복 실행 하나의 일련번호 (같은 반복 노드에 다시 들어오면 새 번호 — 썸네일 정리 열쇠)."""


@dataclass(frozen=True, slots=True)
class FrameExit:
    """서브그래프가 `core.graph.exit`로 끝났다. 호출 노드는 이 출구로 나간다."""

    exit: str
    kind: ExitKind
    outputs: Mapping[str, Any]
    origins: Mapping[str, Origin | None] = field(default_factory=dict[str, Origin | None])
    """출력별 관측 출처 (`core.graph.exit` 입력의 출처 — 호출 노드 출력으로 넘어간다)."""


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
    record_policy: RecordPolicy = field(default_factory=RecordPolicy)
    """이 프레임의 실효 기록 정책 (워크스페이스 → 테스트 → 호출 노드 → 서브그래프 → …).
    `record()` 메서드(출력 표)와 별개다."""
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    vars: dict[str, Any] = field(default_factory=dict[str, Any])
    pending: list[Cause] = field(default_factory=list[Cause])
    """연결된 fail 출구로 나간 스텝 (종료 노드·공개 exit에 닿으면 해소)."""
    loops: list[LoopState] = field(default_factory=list[LoopState])
    """반복 스택 (맨 끝이 가장 안쪽)."""
    input_origins: Mapping[str, Origin | None] = field(default_factory=dict[str, Origin | None])
    """`inputs`의 핀별 관측 출처 (부른 호출 노드 입력의 출처, M3 2.4)."""
    origins: dict[str, dict[str, Origin | None]] = field(
        default_factory=dict[str, dict[str, Origin | None]]
    )
    """출력 표의 핀별 관측 출처."""
    var_origins: dict[str, Origin | None] = field(default_factory=dict[str, Origin | None])
    """변수의 관측 출처 (값과 같이 저장한다)."""
    outer_loops: tuple[tuple[int, int], ...] = ()
    """이 프레임을 부른 호출 스텝을 감싼 반복 회차들 `(일련번호, 회차)` (바깥부터)."""
    chain: tuple[str, ...] = ()
    """루트 테스트부터 이 프레임까지의 그래프 경로 (치트 허용의 서브그래프 `qa` 교집합, M8)."""
    in_cheat: bool = False
    """치트 구현 서브그래프 안이다 (그 아래 치트 노드는 거부 — 중첩 금지)."""

    def node_path(self, node: str) -> tuple[str, ...]:
        return (*self.path, node)

    def loop_chain(self, node: str) -> tuple[tuple[int, int], ...]:
        """`node` 스텝을 감싼 반복 회차들 (호출 경계를 넘어 바깥부터). 반복 노드 자신의 스텝은 그
        반복 바깥이다 (`loops.iteration`과 같다)."""
        own = tuple((s.serial, s.started - 1) for s in self.loops if s.node != node)
        return (*self.outer_loops, *own)

    def record(
        self,
        node: str,
        outputs: Mapping[str, Any],
        origins: Mapping[str, Origin | None] | None = None,
    ) -> None:
        self.outputs[node] = dict(outputs)
        self.origins[node] = dict(origins or {})

    def invalidate(self, nodes: Iterable[str]) -> None:
        """출력을 지운다 (반복이 다음 회차로 갈 때 그 범위의 출력)."""
        for node in nodes:
            self.outputs.pop(node, None)
            self.origins.pop(node, None)

    def origin_of(self, ref: LinkRef) -> Origin | None:
        """출력 표 값의 관측 출처 (`read`가 성공한 참조)."""
        return self.origins.get(ref.node, {}).get(ref.output)

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
