"""워크스페이스 서비스: CLI·daemon이 같이 쓰는 진입점.

권한·입력 임대권·감독 코드는 `kookabug_core`에 하나만 두고 CLI와 daemon이 같은 코드를 쓴다
(구현 계획 3장 계약). 같은 요청은 어느 쪽에서 와도 `authorize`가 같은 판정을 낸다.
실행 시작(`start_run`)은 감독자와 함께 붙인다.
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
from kookabug_core.workspace import WORKSPACE_FILE, WorkspaceError

__all__ = [
    "AGENT_ENV",
    "ApprovalRequired",
    "PermissionDenied",
    "WorkspaceService",
    "cli_principal",
]

AGENT_ENV: Final = "KOOKABUG_AGENT"


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

    def __init__(self, root: str | Path, *, environ: Mapping[str, str] | None = None) -> None:
        self.root = Path(root).resolve()
        if not (self.root / WORKSPACE_FILE).is_file():
            raise WorkspaceError(
                f"{self.root / WORKSPACE_FILE}이(가) 없다. 워크스페이스 루트가 아니다"
            )
        self._environ = environ

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
