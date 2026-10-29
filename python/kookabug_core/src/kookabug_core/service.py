"""워크스페이스 서비스: CLI·daemon이 같이 쓰는 진입점.

권한·입력 임대권·감독 코드는 `kookabug_core`에 하나만 두고 CLI와 daemon이 같은 코드를 쓴다
(구현 계획 3장 계약). 같은 요청은 어느 쪽에서 와도 `authorize`가 같은 판정을 낸다.
실행 시작(`start_run`)은 판정(`kb_run_start`, 인자 = 그래프 경로) → ask면 승인 확인 →
`Supervisor.start` 순서다. 거부·승인 없음이면 실행 폴더도 프로세스도 만들지 않는다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from kookabug_core.permissions import (
    Decision,
    Policy,
    Principal,
    decide,
    load_policy,
    user_config_dir,
)
from kookabug_core.supervisor import RunHandle, StartOptions, Supervisor
from kookabug_core.workspace import WORKSPACE_FILE, WorkspaceError

__all__ = [
    "AGENT_ENV",
    "RUN_START_TOOL",
    "ApprovalRequired",
    "PermissionDenied",
    "WorkspaceService",
    "cli_principal",
]

AGENT_ENV: Final = "KOOKABUG_AGENT"
RUN_START_TOOL: Final = "kb_run_start"


class PermissionDenied(Exception):
    """권한 판정이 deny다."""

    def __init__(self, tool: str, decision: Decision) -> None:
        super().__init__(decision.describe(tool))
        self.tool = tool
        self.decision = decision


class ApprovalRequired(Exception):
    """판정이 ask이고 사람의 승인을 받지 않았다. 아무것도 실행하지 않았다."""

    def __init__(self, tool: str, decision: Decision) -> None:
        super().__init__(decision.describe(tool))
        self.tool = tool
        self.decision = decision


def cli_principal(environ: Mapping[str, str] | None = None) -> Principal:
    """CLI를 부른 주체. `KOOKABUG_AGENT=<연결 ID>`가 있으면 사람 없는 에이전트, 없으면 사람.

    에이전트가 스스로 밝히는 표시일 뿐 보안 경계가 아니다.
    """
    env = os.environ if environ is None else environ
    if AGENT_ENV in env:
        return Principal("agent", env[AGENT_ENV] or "agent", attended=False)
    return Principal("user", "cli", attended=True)


class WorkspaceService:
    """워크스페이스 하나에 대한 서버 API.

    정책 파일은 판정할 때마다 다시 읽는다 (설정을 바꾸면 다음 요청부터 적용).
    """

    def __init__(
        self,
        root: str | Path,
        *,
        environ: Mapping[str, str] | None = None,
        supervisor: Supervisor | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        if not (self.root / WORKSPACE_FILE).is_file():
            raise WorkspaceError(
                f"{self.root / WORKSPACE_FILE}이(가) 없다. 워크스페이스 루트가 아니다"
            )
        self._environ = environ
        self.supervisor = supervisor or Supervisor()

    def policy(self) -> Policy:
        return load_policy(self.root, user_config_dir(self._environ))

    def authorize(self, principal: Principal, tool: str, arg: str = "") -> Decision:
        return decide(self.policy(), principal, tool, arg)

    def require(
        self, principal: Principal, tool: str, arg: str = "", *, approved: bool = False
    ) -> Decision:
        """판정해서 실행할 수 없으면 예외. ask는 `approved=True`일 때만 통과한다."""
        decision = self.authorize(principal, tool, arg)
        if decision.final == "deny":
            raise PermissionDenied(tool, decision)
        if decision.final == "ask" and not approved:
            raise ApprovalRequired(tool, decision)
        return decision

    def start_run(
        self,
        principal: Principal,
        graph: str,
        options: StartOptions | None = None,
        *,
        approved: bool = False,
    ) -> RunHandle:
        """실행을 시작한다. 판정이 deny면 `PermissionDenied`, ask이고 승인이 없으면
        `ApprovalRequired` — 둘 다 아무것도 만들지 않는다. 시작 뒤의 실패(runner가 hello를 못
        함 등)는 핸들의 결과(`wait()`)로 알린다.

        판정은 한 번만 한다. 집행한 그 판정을 핸들(`handle.decision`)이나 예외(`exc.decision`)로
        돌려주므로, 호출자는 따로 `authorize()`를 부르지 않고 이것을 보고한다."""
        decision = self.require(principal, RUN_START_TOOL, graph, approved=approved)
        handle = self.supervisor.start(self.root, graph, options)
        handle.decision = decision
        return handle
