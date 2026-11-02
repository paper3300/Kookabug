"""디버거 확인 지점·브레이크포인트·Step 목표 (구현 계획 M3 2.2·2.3).

멈출지는 runner가 정하고, 실행기는 두 곳에서 묻기만 한다.

1. **스텝 경계**: 스텝을 시작하기 직전(`step.start` 전). 실행기의 `before_step(StepPoint)`.
   브레이크포인트·Step 목표·일시정지 요청을 본다
2. **폴링 확인 지점**: 코어 노드의 멈출 수 있는 기다림(`ctx.sleep` → 런타임 `wait_pausable`) 안.
   일시정지 요청만 본다. 워커 노드·입력 동작·관측 호출 안에서는 멈추지 않는다

**브레이크포인트 열쇠**는 (워크스페이스 기준 그래프 경로, 노드 ID)다. 서브그래프 파일에 건 것은
어느 호출에서든, 반복 본문 노드에 건 것은 회차마다 적중한다.

**Step 목표**는 재개할 때 멈춘 자리의 호출 깊이 `d`(그 스텝 `path` 길이)로 정한다. 반복은 깊이를
더하지 않는다.

- `continue`: 목표 없음 (다음 브레이크포인트·일시정지 요청까지)
- `step_over`: 깊이 ≤ `d`인 다음 경계
- `step_into`: 다음 경계 (깊이 무관). 그래프 시작점(`core.graph.entry`) 경계는 Step 목표가
  아니므로 서브그래프로 들어가면 첫 동작 노드에서 멈춘다
- `step_out`: 깊이 < `d`인 다음 경계 (맨 바깥에서는 `continue`와 같다)
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, runtime_checkable

__all__ = [
    "RESUME_MODES",
    "Breakpoint",
    "PauseCounter",
    "PausePoint",
    "ResumeMode",
    "StepPoint",
    "step_limit",
]

type ResumeMode = Literal["continue", "step_over", "step_into", "step_out"]
RESUME_MODES: Final[frozenset[str]] = frozenset({"continue", "step_over", "step_into", "step_out"})


@dataclass(frozen=True, slots=True, order=True)
class Breakpoint:
    """브레이크포인트 하나 (`breakpoints.schema.json#/$defs/Breakpoint`). `graph`는 워크스페이스
    기준 경로 그대로다: runner는 스냅샷 안의 같은 상대 경로로 프로그램을 읽으므로 스텝의 그래프
    경로에도 `snapshot/` 접두가 없다. 그래서 접두를 떼지 않는다(워크스페이스에 `snapshot/` 폴더가
    있으면 그 폴더의 그래프다)."""

    graph: str
    node: str

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Breakpoint:
        return cls(str(data["graph"]), str(data["node"]))

    @classmethod
    def many(cls, items: Iterable[Mapping[str, Any]]) -> tuple[Breakpoint, ...]:
        """목록 → 겹치지 않고 정렬된 튜플 (순서 무관, 같은 항목은 하나)."""
        return tuple(sorted({cls.from_json(item) for item in items}))

    def to_json(self) -> dict[str, str]:
        return {"graph": self.graph, "node": self.node}


def step_limit(mode: ResumeMode, depth: int) -> int | None:
    """재개 방식 → 다음에 멈출 경계의 최대 깊이 (`None`이면 Step 목표 없음)."""
    if mode == "step_into":
        return 1 << 30
    if mode == "step_over":
        return depth
    if mode == "step_out":
        return depth - 1 if depth > 1 else None
    return None


@dataclass(frozen=True, slots=True)
class StepPoint:
    """확인 지점의 스텝: 스텝 ID, 노드 ID, 노드가 든 그래프(프로그램 기준 경로 — 스냅샷 실행이면
    워크스페이스 기준과 같다), 호출 경로(그 노드까지).

    `entry`는 그래프 시작점(`core.graph.entry`) 스텝이다. 아무 동작도 없는 자리라 Step 목표로는
    멈추지 않는다(서브그래프로 들어가면 첫 동작 노드에서 멈춤). 브레이크포인트·일시정지 요청은
    본다."""

    step: str
    node: str
    graph: str
    path: tuple[str, ...]
    entry: bool = False

    @property
    def depth(self) -> int:
        """호출 깊이 (`path` 길이)."""
        return len(self.path)

    @property
    def key(self) -> Breakpoint:
        """이 자리의 브레이크포인트 열쇠."""
        return Breakpoint(self.graph, self.node)

    def to_event(self) -> dict[str, object]:
        """`debug.pause`에 싣는 위치 필드."""
        return {"step": self.step, "node": self.node, "graph": self.graph, "path": list(self.path)}


class PausePoint(Protocol):
    """폴링 확인 지점 (runner 멈춤 게이트)."""

    def wait_request(self, timeout_s: float) -> bool:
        """취소되거나 멈춤 요청이 올 때까지(최대 `timeout_s`초) 기다린다. 멈춤 요청이 있으면 True
        (요청을 소비하지 않는다)."""
        ...

    def at_poll(self, point: StepPoint) -> None:
        """멈춤 요청을 이 자리에서 확정하고(`debug.pause where: poll`) 재개·취소까지 기다린다."""
        ...


@runtime_checkable
class PauseCounter(Protocol):
    """멈춘 횟수를 아는 기한 시계 (runner 활성 시계). 스텝 구간에 멈춤이 있었는지 가린다."""

    @property
    def pauses(self) -> int: ...
