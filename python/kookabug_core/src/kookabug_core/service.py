"""워크스페이스 서비스: CLI·daemon이 같이 쓰는 진입점.

권한·입력 임대권·감독 코드는 `kookabug_core`에 하나만 두고 CLI와 daemon이 같은 코드를 쓴다
(구현 계획 3장 계약). 같은 요청은 어느 쪽에서 와도 `authorize`가 같은 판정을 낸다.
실행 시작(`start_run`)은 판정(`kb_run_start`, 인자 = 그래프 경로) → ask면 승인 확인 →
`Supervisor.start` 순서다. 거부·승인 없음이면 실행 폴더도 프로세스도 만들지 않는다.

판정과 시작 사이에 자기 단계(중복 방지 키·실행 중 확인·사전 검증)를 두는 호출자(daemon, M2 계획
2.8)는 `require`로 판정한 뒤 그 판정을 `start_decided`에 넘긴다. 다시 판정하지 않는다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Final

from kookabug_core.permissions import (
    USER_SETTINGS_FILE,
    Decision,
    Policy,
    Principal,
    decide,
    load_policy,
    user_config_dir,
)
from kookabug_core.runner.spec import PlatformSpec
from kookabug_core.supervisor import DEFAULT_DEADLINE_MS, RunHandle, StartOptions, Supervisor
from kookabug_core.workspace import WORKSPACE_FILE, RunConditions, WorkspaceError

__all__ = [
    "AGENT_ENV",
    "DEV_MODULES_AGENT",
    "RUN_START_TOOL",
    "ApprovalRequired",
    "DevModulesRefused",
    "ForbiddenUnavailable",
    "PermissionDenied",
    "WorkspaceService",
    "cli_principal",
    "guard_options",
    "refuse_dev_modules",
    "start_options",
]

AGENT_ENV: Final = "KOOKABUG_AGENT"
RUN_START_TOOL: Final = "kb_run_start"


class PermissionDenied(Exception):
    """권한 판정이 deny다."""

    def __init__(self, tool: str, decision: Decision) -> None:
        super().__init__(decision.describe(tool))
        self.tool = tool
        self.decision = decision


DEV_MODULES_AGENT: Final = "dev_modules_agent"
"""개발 모듈 거부 이유 (M6 계획 3.7): 에이전트 주체는 `--plugin-module` 실행을 쓸 수 없다."""


class DevModulesRefused(Exception):
    """에이전트 주체가 개발 모듈(`--plugin-module`)로 실행하려 했다. 아무것도 시작하지 않았다.

    개발 모듈은 설치·신뢰 확인 없이 임의 모듈을 import하므로 사람 전용이다 (M6 계획 D11)."""

    code: Final = "permission_denied"
    reason: Final = DEV_MODULES_AGENT

    def __init__(self, modules: tuple[str, ...]) -> None:
        super().__init__(
            f"permission_denied ({DEV_MODULES_AGENT}): 에이전트는 개발 모듈 "
            f"{', '.join(modules)}로 실행할 수 없다. 플러그인을 설치한 뒤 실행한다"
        )
        self.modules = modules


def refuse_dev_modules(principal: Principal, modules: tuple[str, ...]) -> None:
    """에이전트 주체 + 개발 모듈이면 `DevModulesRefused` (실행을 시작하기 전에 부른다)."""
    if modules and principal.kind == "agent":
        raise DevModulesRefused(tuple(modules))


class ForbiddenUnavailable(Exception):
    """Agent·무인 실행인데 금지 동작 목록(`automation.forbidden`)을 읽지 못했다 (M8 3.7·R6 fail
    closed). 아무것도 시작하지 않았다."""

    code: Final = "forbidden_unverifiable"
    reason: Final = "config_unreadable"

    def __init__(self) -> None:
        super().__init__(
            f"{self.code} ({self.reason}): 금지 동작 목록을 읽지 못해 Agent·무인 실행을 시작하지 "
            "않았다"
        )


def guard_options(root: Path, principal: Principal, options: StartOptions | None) -> StartOptions:
    """주체로 정하는 실행 조건 (공용 진입점 `start_decided`만 부른다).

    - 사람 없는 Agent(CLI `KOOKABUG_AGENT` 포함)의 실행은 무인(치트 무인 분류, M8 3.5)
    - Agent 주체이거나 무인인 실행은 입력마다 금지 동작 판정(M8 3.7·R6): 시작 때 `kookabug.json`
      목록을 고정한다. 목록이 비면 None(판정 없음). 읽지 못하면 `ForbiddenUnavailable`
    - 사람 실행은 금지 목록을 싣지 않는다(호출자가 넣었어도 지운다 — 출처는 여기 하나)"""
    from kookabug_core import forbidden

    opts = options or StartOptions()
    unattended = opts.unattended or (principal.kind == "agent" and not principal.attended)
    spec: tuple[dict[str, str], ...] | None = None
    if principal.kind == "agent" or unattended:
        try:
            items = forbidden.load_items(root)
        except forbidden.ForbiddenConfigError as exc:
            raise ForbiddenUnavailable() from exc
        spec = tuple(forbidden.to_spec(items)) or None
    return replace(opts, unattended=unattended, forbidden=spec)


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

    def user_settings_path(self) -> Path | None:
        """사용자 설정 파일 (권한 사용자 계층). 폴더를 정할 수 없으면 None."""
        folder = user_config_dir(self._environ)
        return None if folder is None else folder / USER_SETTINGS_FILE

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
        if options is not None:
            refuse_dev_modules(principal, options.plugin_modules)
        decision = self.require(principal, RUN_START_TOOL, graph, approved=approved)
        return self.start_decided(decision, graph, options, principal=principal, approved=approved)

    def start_decided(
        self,
        decision: Decision,
        graph: str,
        options: StartOptions | None = None,
        *,
        principal: Principal,
        approved: bool = False,
    ) -> RunHandle:
        """이미 집행한 판정(`require`의 결과)으로 실행을 시작한다. 다시 판정하지 않는다. 거부이거나
        승인 없는 ask인 판정을 넘기면 아무것도 만들지 않고 `ValueError`(호출자의 버그).

        **실행 시작의 공용 진입점**이다 (CLI `start_run`·daemon `run.start`·제어 실행·자동 채택 검증
        실행이 모두 지난다). 주체로 무인 여부와 금지 동작 목록을 여기서 정한다(`guard_options`) —
        호출자가 넘긴 `forbidden`은 쓰지 않는다. 금지 목록을 읽지 못하면 아무것도 만들지 않고
        `ForbiddenUnavailable`(fail closed)."""
        if decision.final == "deny" or (decision.final == "ask" and not approved):
            raise ValueError(f"허용되지 않은 판정으로는 시작할 수 없다: {decision.final}")
        guarded = guard_options(self.root, principal, options)
        handle = self.supervisor.start(self.root, graph, guarded)
        handle.decision = decision
        return handle


_CONDITION_FIELDS: Final = (
    "worker_cancel_grace_ms",
    "worker_start_timeout_ms",
    "shutdown_grace_ms",
    "frame_budget_mib",
    "frame_output_refs",
)


def start_options(
    conditions: RunConditions,
    *,
    deadline_ms: int | None = None,
    capture_timeout_ms: int | None = None,
    profile: str | None = None,
    settings: Mapping[str, object] | None = None,
    plugin_modules: tuple[str, ...] = (),
    platform: PlatformSpec | None = None,
) -> StartOptions:
    """실행 조건: 호출 인자 → `kookabug.json`의 `run` 블록 → 감독자 기본값 (CLI `run`·daemon
    `run.start`가 같이 쓴다). 관측 기한 기본값은 `RunSpec`의 기본값(2000)이다."""
    timing = {
        name: value
        for name in _CONDITION_FIELDS
        if (value := getattr(conditions, name)) is not None
    }
    deadline = deadline_ms if deadline_ms is not None else conditions.deadline_ms
    capture = (
        capture_timeout_ms if capture_timeout_ms is not None else conditions.capture_timeout_ms
    )
    if capture is not None:
        timing["capture_timeout_ms"] = capture
    return StartOptions(
        deadline_ms=DEFAULT_DEADLINE_MS if deadline is None else deadline,
        profile=profile,
        settings=dict(settings or {}),
        plugin_modules=tuple(plugin_modules),
        platform=platform or PlatformSpec("windows"),
        **timing,
    )
