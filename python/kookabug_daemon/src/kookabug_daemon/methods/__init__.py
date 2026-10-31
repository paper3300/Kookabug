"""daemon 메서드 묶음. 메서드 하나 = 처리기 + 대표 인자(권한 판정에 넘기는 값).

전송(`transport`)이 봉투·params 형식 검사 → 대표 인자 → 판정(`tools.Authorizer`) → 처리기 →
결과 형식 검사 순서로 부른다. 처리기는 이벤트 루프에서 돈다. 막히는 코어 호출은
`asyncio.to_thread`로 넘긴다.

메서드 본문은 작업별 모듈이 더한다 (M2 계획: 세션 T3, 워크스페이스·그래프 T4, 실행 T5, target T6).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from kookabug_core.permissions import Principal

__all__ = ["Call", "DaemonContext", "MethodSpec", "RunsLike", "no_arg", "registry"]


class RunsLike(Protocol):
    """daemon이 감독하는 실행 (T5가 채운다). 수명 판단(유휴 종료·shutdown)에 쓴다."""

    def active_run(self) -> str | None:
        """진행 중이거나 시작 중인 실행의 ID. 없으면 None."""
        ...

    def cancel_all_and_wait(self) -> None:
        """진행 중인 실행을 모두 취소하고 마무리를 기다린다 (막히는 호출)."""
        ...


class DaemonContext(Protocol):
    """처리기가 보는 daemon."""

    @property
    def runs(self) -> RunsLike: ...

    def request_shutdown(self, *, force: bool, reason: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Call:
    """요청 하나. `params`는 형식 검사를 지난 값이다."""

    daemon: DaemonContext
    principal: Principal
    connection: int
    method: str
    params: Mapping[str, Any] = field(default_factory=dict[str, Any])


type Handler = Callable[[Call], Awaitable[dict[str, Any]]]
type ArgOf = Callable[[Call], str]


def no_arg(call: Call) -> str:
    """대표 인자가 없는 메서드 (M2 계획 2.5 표의 "—")."""
    return ""


@dataclass(frozen=True, slots=True)
class MethodSpec:
    handler: Handler
    arg: ArgOf = no_arg


def registry() -> dict[str, MethodSpec]:
    """이 daemon이 처리하는 메서드. 계약에 있지만 여기 없는 메서드는 `method_not_found`다."""
    from kookabug_daemon.methods import session

    return {**session.METHODS}
