"""daemon 메서드 묶음. 메서드 하나 = 처리기 + 대표 인자(권한 판정에 넘기는 값).

전송(`transport`)이 봉투·params 형식 검사 → 대표 인자 → 판정(`tools.Authorizer`) → 처리기 →
결과 형식 검사 순서로 부른다. 처리기는 이벤트 루프에서 돈다. 막히는 코어 호출은
`asyncio.to_thread`로 넘긴다.

메서드 본문은 작업별 모듈이 더한다 (M2 계획: 세션 T3, 워크스페이스·그래프 T4, 실행 T5, target T6).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from kookabug_core.permissions import Principal

if TYPE_CHECKING:
    from kookabug_core.service import WorkspaceService
    from kookabug_daemon.approvals import ApprovalBroker
    from kookabug_daemon.documents import DocumentTable, GraphChecker
    from kookabug_daemon.frames import FrameCache
    from kookabug_daemon.image_cache import EditorCache
    from kookabug_daemon.permission_files import PermissionFiles
    from kookabug_daemon.runs import RunManager
    from kookabug_daemon.targets import TargetStore

__all__ = ["Call", "DaemonContext", "MethodSpec", "RunsLike", "no_arg", "registry"]


class RunsLike(Protocol):
    """daemon이 감독하는 실행 (T5가 채운다). 수명 판단(유휴 종료·shutdown)에 쓴다."""

    def active_run(self) -> str | None:
        """진행 중이거나 시작 중(시작 예약)인 실행의 ID. 없으면 None."""
        ...

    def reserve_shutdown(self, *, force: bool) -> str | None:
        """종료를 정한다. 시작 예약과 같은 잠금 안에서 판단한다: force가 아니고 진행·시작 중인
        실행이 있으면 정하지 않고 그 ID를 돌려준다. 정했으면 None이고, 그 뒤 시작 요청은
        새 runner를 만들지 못한다(`shutting_down`)."""
        ...

    def cancel_all_and_wait(self) -> None:
        """진행 중인 실행을 모두 취소하고 마무리를 기다린다 (막히는 호출)."""
        ...


class DaemonContext(Protocol):
    """처리기가 보는 daemon."""

    @property
    def runs(self) -> RunsLike:
        """수명 판단(유휴 종료·shutdown)에 쓰는 실행 목록."""
        ...

    @property
    def run_manager(self) -> RunManager:
        """실행 메서드(`run.*`)가 쓰는 실행 관리."""
        ...

    @property
    def root(self) -> Path:
        """워크스페이스 루트 (해석한 절대 경로)."""
        ...

    @property
    def platform_fake(self) -> Path | None:
        """숨은 `--platform-fake` 사양 (상태 바 정보에 쓴다)."""
        ...

    @property
    def documents(self) -> DocumentTable: ...

    @property
    def checker(self) -> GraphChecker: ...

    @property
    def frames(self) -> FrameCache:
        """편집기 정지 화면 (target 편집기)."""
        ...

    @property
    def image_cache(self) -> EditorCache:
        """`.kookabug/cache/editor/` (RPC에 이미지를 싣지 않는다)."""
        ...

    @property
    def targets(self) -> TargetStore:
        """target 열기·미리보기·저장 (저장 잠금·에디터 소유 기록)."""
        ...

    def request_shutdown(self, *, force: bool, reason: str) -> None: ...

    def connection_toolsets(self, connection: int) -> frozenset[str]:
        """그 연결의 켜진 툴셋 (M5 계획 D3)."""
        ...

    def enable_toolsets(self, connection: int, toolsets: Iterable[str]) -> frozenset[str]:
        """그 연결의 툴셋을 켜고 켠 뒤 전체를 돌려준다."""
        ...

    def agent_connections(self) -> list[dict[str, Any]]:
        """붙은 agent 연결 목록 (`agent.connections`, M5 B5)."""
        ...

    def breakpoints_changed(self, connection: int, breakpoints: list[dict[str, str]]) -> None:
        """브레이크포인트 목록이 바뀌었다: 바꾼 연결(`connection`) 말고 UI 연결들에 알린다
        (`debug.breakpoints.changed`, 이벤트 루프 안)."""
        ...

    @property
    def service(self) -> WorkspaceService:
        """판정·정책 (`permissions.get`)."""
        ...

    @property
    def approvals(self) -> ApprovalBroker:
        """판정과 사람 확인 (M5 3.6). 스스로 판정하는 처리기가 부른다."""
        ...

    @property
    def permission_files(self) -> PermissionFiles:
        """권한 파일 읽기·쓰기 (M5 3.6)."""
        ...


@dataclass(frozen=True, slots=True)
class Call:
    """요청 하나. `params`는 형식 검사를 지난 값이다."""

    daemon: DaemonContext
    principal: Principal
    connection: int
    method: str
    params: Mapping[str, Any] = field(default_factory=dict[str, Any])
    client_kind: str = "agent"
    """연결의 `client.kind` (`ui`·`agent`). 사람이 UI에서 시작한 실행인지 가린다 (M3 2.1)."""


type Handler = Callable[[Call], Awaitable[dict[str, Any]]]
type ArgOf = Callable[[Call], str]


def no_arg(call: Call) -> str:
    """대표 인자가 없는 메서드 (M2 계획 2.5 표의 "—")."""
    return ""


@dataclass(frozen=True, slots=True)
class MethodSpec:
    handler: Handler
    arg: ArgOf = no_arg
    self_authorized: bool = False
    """처리기가 계약이 정한 자리에서 같은 판정(`Authorizer.require`)을 직접 한다. 전송은 미리
    판정하지 않는다 (`run.start`: 시작 잠금 안의 ② 단계, M2 계획 2.8)."""


def registry() -> dict[str, MethodSpec]:
    """이 daemon이 처리하는 메서드. 계약에 있지만 여기 없는 메서드는 `method_not_found`다."""
    from kookabug_daemon.methods import (
        agent,
        agents,
        approval,
        control,
        debug,
        graph,
        nodes,
        permissions,
        recorder,
        run,
        run_agent,
        screens,
        secrets,
        session,
        target,
        windows,
        workspace,
    )

    return {
        **agent.METHODS,
        **agents.METHODS,
        **approval.METHODS,
        **control.METHODS,
        **permissions.METHODS,
        **debug.METHODS,
        **recorder.METHODS,
        **secrets.METHODS,
        **session.METHODS,
        **workspace.METHODS,
        **nodes.METHODS,
        **graph.METHODS,
        **run.METHODS,
        **run_agent.METHODS,
        **screens.METHODS,
        **windows.METHODS,
        **target.METHODS,
    }
