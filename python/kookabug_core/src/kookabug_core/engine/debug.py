"""디버거 확인 지점 (구현 계획 M3 2.2).

멈출지는 runner가 정하고, 실행기는 두 곳에서 묻기만 한다.

1. **스텝 경계**: 스텝을 시작하기 직전(`step.start` 전). 실행기의 `before_step(StepPoint)`
2. **폴링 확인 지점**: 코어 노드의 멈출 수 있는 기다림(`ctx.sleep` → 런타임 `wait_pausable`) 안.
   일시정지 요청만 본다. 워커 노드·입력 동작·관측 호출 안에서는 멈추지 않는다
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ["PauseCounter", "PausePoint", "StepPoint"]


@dataclass(frozen=True, slots=True)
class StepPoint:
    """확인 지점의 스텝: 스텝 ID, 노드 ID, 노드가 든 그래프(프로그램 기준 경로 — 스냅샷 실행이면
    워크스페이스 기준과 같다), 호출 경로(그 노드까지)."""

    step: str
    node: str
    graph: str
    path: tuple[str, ...]

    @property
    def depth(self) -> int:
        """호출 깊이 (`path` 길이)."""
        return len(self.path)

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
