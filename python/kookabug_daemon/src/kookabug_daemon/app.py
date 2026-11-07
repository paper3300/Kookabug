"""daemon 진입점과 수명 (M2 계획 2.3).

    kookabug daemon --workspace <루트> [--idle-timeout-s 600] [--json] [--log-level info]

1. DPI 인식을 Per-Monitor V2로 정한다 (진입점 첫 줄. target 캡처·미리보기가 좌표를 쓴다)
2. 워크스페이스를 확인한다 (아니면 종료 코드 6)
3. `.kookabug/daemon.lock`을 얻는다
   - 잠금 충돌이면 경쟁에서 진 것이다. 15초 안에 유효한 세션이 나오면 "이미 실행 중"(종료 코드 0,
     `--json`이면 그 세션 정보), 안 나오면 6
   - 접근 거부·I/O 오류는 경쟁이 아니다. 곧바로 6
4. 로그 파일(`.kookabug/logs/daemon-<시각>-<pid>.log`)을 열고 포트를 연 뒤 `session.json`을 공개한다
5. 연결도 진행 중인 실행도 없는 상태가 유휴 시간 이어지거나 `daemon.shutdown`을 받으면 끝낸다.
   끝날 때 자기 `start_id`인 `session.json`만 지운다. 잠금은 프로세스가 끝나며 풀린다

`--json` 출력(한 줄)에는 토큰을 싣지 않는다. 토큰은 `session.json`에서만 읽는다.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import secrets
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, TextIO

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.loader import Program
from kookabug_core.permissions import TOOLSETS
from kookabug_core.plugins import LOCK_FILE, Layout, PluginError
from kookabug_core.plugins import runtime as plugin_runtime
from kookabug_core.plugins.envs import state_signature as env_state_signature
from kookabug_core.plugins.lockfile import revision_of
from kookabug_core.plugins.runtime import installed_schemas
from kookabug_core.registry import Registry, RegistryError, default_registry
from kookabug_core.runner.spec import PlatformSpec
from kookabug_core.service import (
    DevModulesRefused,
    WorkspaceService,
    cli_principal,
    refuse_dev_modules,
)
from kookabug_core.validate.plugins import plugin_diagnostics, used_plugins
from kookabug_core.workspace import WorkspaceError
from kookabug_daemon.agent_cache import AgentCache
from kookabug_daemon.approvals import APPROVAL_TIMEOUT_S, ApprovalBroker
from kookabug_daemon.documents import DocumentTable, GraphChecker
from kookabug_daemon.frame_guard import FILE as GUARD_FILE
from kookabug_daemon.frame_guard import FrameGuard
from kookabug_daemon.frames import FrameCache
from kookabug_daemon.image_cache import EditorCache
from kookabug_daemon.lease_watch import LeaseWatcher, lease_dir
from kookabug_daemon.methods import MethodSpec, RunsLike, registry
from kookabug_daemon.methods.screens import in_screens
from kookabug_daemon.methods.secrets import RecorderSecretSource
from kookabug_daemon.methods.tools import Authorizer
from kookabug_daemon.options import DEFAULT_IDLE_TIMEOUT_S, SESSION_WAIT_S, add_arguments
from kookabug_daemon.permission_files import PermissionFiles
from kookabug_daemon.plugin_jobs import PluginJobs
from kookabug_daemon.protocol import DAEMON_VERSION, PROTOCOL, json_text
from kookabug_daemon.recorder import RecorderService
from kookabug_daemon.recorder_hook import HookTesting, testing_options
from kookabug_daemon.recorder_store import RecorderStore
from kookabug_daemon.runs import RunManager
from kookabug_daemon.screen_source import ScreenSource, make_source
from kookabug_daemon.session import (
    LOGS_DIR,
    PRIVATE_DIR,
    DaemonLock,
    LockBusy,
    SessionInfo,
    own_session,
    remove_session,
    wait_for_valid_session,
    write_session,
)
from kookabug_daemon.targets import TargetStore
from kookabug_daemon.transport import Limits, Transport
from kookabug_daemon.watch import DocChange, Watcher
from kookabug_sdk import _faults

__all__ = [
    "DEFAULT_IDLE_TIMEOUT_S",
    "EXIT_DENIED",
    "EXIT_OK",
    "EXIT_USAGE",
    "Daemon",
    "DaemonConfig",
    "NoRuns",
    "UsageError",
    "add_arguments",
    "config_from_args",
    "main",
    "run",
]

log = logging.getLogger("kookabug_daemon")

EXIT_OK: Final = 0
EXIT_USAGE: Final = 6
"""사용법·환경 오류 (CLI와 같은 값)."""
EXIT_DENIED: Final = 5
"""권한 거부 (CLI와 같은 값): 에이전트 주체의 개발 모듈 daemon (M6 3.7)."""
LOG_KEEP: Final = 20
WATCH_INTERVAL_S: Final = 1.0
"""파일 변경 폴링 간격 (M2 계획 Q10)."""
DEFAULT_AGENT_TOOLSETS: Final = frozenset({"core"})


class NoRuns:
    """빈 실행 목록 (수명 검사용)."""

    def active_run(self) -> str | None:
        return None

    def reserve_shutdown(self, *, force: bool) -> str | None:
        return None

    def cancel_all_and_wait(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class DaemonConfig:
    workspace: Path
    idle_timeout_s: float = DEFAULT_IDLE_TIMEOUT_S
    session_wait_s: float = SESSION_WAIT_S
    platform_fake: Path | None = None
    plugin_modules: tuple[str, ...] = ()
    """개발·테스트용 플러그인 모듈 (실행의 워커, 사전 검증·팔레트 레지스트리)."""
    log_level: str = "info"
    limits: Limits = field(default_factory=Limits)
    watch_interval_s: float = WATCH_INTERVAL_S
    recorder_testing: HookTesting | None = None
    """검사 전용 녹화 옵션 (`KOOKABUG_TESTING=1`일 때만, M4 계획 2.2)."""
    recorder_script: Path | None = None
    """가짜 플랫폼 녹화가 흘릴 각본 JSONL (`--recorder-script`, 가짜 플랫폼일 때만)."""
    recorder_script_speed: float | None = 1.0
    """각본을 흘리는 빠르기 (`inf` = 기다리지 않음, None = 검사가 직접 흘림)."""
    agent_toolsets: frozenset[str] = DEFAULT_AGENT_TOOLSETS
    """agent 연결이 hello 때 갖는 툴셋 (M5 계획 D3: core). 검사 헬퍼만 바꾼다."""
    approval_timeout_s: float = APPROVAL_TIMEOUT_S
    """사람 확인을 기다리는 시간 (M5 U3: 120초). 검사 헬퍼만 바꾼다."""
    plugin_environ: Mapping[str, str] | None = None
    """플러그인 작업(uv·앱 SDK wheel 찾기)의 환경 변수. None이면 이 프로세스의 것 (검사 헬퍼만
    바꾼다)."""


class PluginRegistry:
    """코어 노드 + 개발 모듈 `modules`의 노드 선언(runner가 워커 hello로 등록하는 것과 같은 선언) +
    설치 플러그인(`root`의 `kookabug.lock`)의 노드 스키마. 설치 플러그인은 커밋된 wheel 안 스키마
    파일을 읽는다 — daemon은 플러그인 코드를 import하지 않는다 (M6 D9). 개발 모듈과 ID가 겹치면
    개발 모듈이 이긴다 (runner와 같은 규칙). 부를 때마다 새 레지스트리를 만든다."""

    def __init__(self, modules: tuple[str, ...], root: Path | None) -> None:
        self.modules = modules
        self.root = root
        self.local: frozenset[str] = frozenset()
        """코어·개발 모듈 플러그인 ID (설치 플러그인 진단에서 뺀다 — runner와 같은 규칙)."""

    def __call__(self) -> Registry:
        found = default_registry()
        if self.modules:
            from kookabug_sdk.worker import collect_plugins

            for plugin in collect_plugins(self.modules):
                found.add_remote(plugin["schema"])
        self.local = frozenset(found.plugins)
        if self.root is not None:
            for plugin_id, schema in sorted(installed_schemas(self.root).items()):
                if plugin_id in found.plugins:
                    continue
                with contextlib.suppress(RegistryError):
                    found.add_remote(schema)
        return found


def plugin_registry(modules: tuple[str, ...], root: Path | None = None) -> Callable[[], Registry]:
    """`PluginRegistry` (개발 모듈도 설치 플러그인도 없으면 코어만)."""
    if not modules and root is None:
        return default_registry
    return PluginRegistry(modules, root)


def _read_or_none(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _env_state(root: Path, data: bytes | None) -> str:
    """잠금 환경들의 지금 상태 표지 (깨짐·없음 알아채기). 잠금이 없거나 읽을 수 없으면 빈 것."""
    try:
        environments = json.loads(data or b"null")["environments"]
        return env_state_signature(Layout(root).envs, environments)
    except ValueError, TypeError, KeyError, AttributeError, OSError:
        return ""


def run_platform(config: DaemonConfig) -> PlatformSpec:
    """daemon이 띄우는 실행의 플랫폼: 실제 Windows, 숨은 `--platform-fake`면 가짜."""
    if config.platform_fake is None:
        return PlatformSpec("windows")
    data = json.loads(config.platform_fake.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{config.platform_fake}은(는) JSON 객체여야 한다")
    spec: dict[str, Any] = data
    return PlatformSpec.fake_from(spec, config.platform_fake.parent)


class Daemon:
    """daemon 하나 (잠금은 호출자가 쥔다). `serve()`는 끝날 때까지 돈다."""

    def __init__(
        self,
        config: DaemonConfig,
        *,
        service: WorkspaceService | None = None,
        runs: RunsLike | None = None,
        methods: Mapping[str, MethodSpec] | None = None,
    ) -> None:
        self.config = config
        self.root = config.workspace.resolve()
        self.service = service or WorkspaceService(self.root)
        self._authorizer = Authorizer(self.service)
        self._documents = DocumentTable(self.root)
        plugin_environ = os.environ if config.plugin_environ is None else config.plugin_environ
        self.plugin_jobs = PluginJobs(self.root, plugin_environ, self)
        """플러그인 작업 (M6 B4 `plugins.*`)."""
        lock_bytes = _read_or_none(self.root / LOCK_FILE)
        self._plugin_revision: str | None = revision_of(lock_bytes)
        self._plugin_env_state = _env_state(self.root, lock_bytes)
        self._plugin_revision_lock = threading.Lock()
        registry_factory = PluginRegistry(config.plugin_modules, self.root)
        self._checker = GraphChecker(
            self.root, registry_factory, self._plugin_checker(registry_factory)
        )
        self._frames = FrameCache()
        self._image_cache = EditorCache(self.root)
        self._targets = TargetStore(self.root, self._frames)
        self.screen_source: ScreenSource = make_source(config.platform_fake)
        """창 목록·캡처 원천 (실제 Windows 또는 장면 가짜 게임, M7 3.12)."""
        self.guard = FrameGuard(self.root, self._frames, self._targets, self.screen_source)
        """에이전트 정지 화면 보호 판정 (M7 3.5a)."""
        # 보호 기록 손상으로 처음 막았을 때 사람 연결에 알린다 (값 없음, M7 3라운드)
        self.guard.on_corrupt = lambda: self.post(
            lambda: self.notify_ui("agent.protect_corrupt", {"path": GUARD_FILE})
        )
        self._run_manager = RunManager(
            self.root,
            self.service,
            self._authorizer,
            lambda: self._checker.registry,
            platform=run_platform(config),
            plugin_modules=config.plugin_modules,
        )
        self._runs: RunsLike = runs or self._run_manager
        # 상태 폴더는 runner에 넘기는 환경으로 정한다 (판정만 하는 서비스 대역에는 감독자가 없다)
        supervisor = getattr(self.service, "supervisor", None)
        self._lease = LeaseWatcher(lease_dir(getattr(supervisor, "env", None)), self._publish_lease)
        self.transport = Transport(self, registry() if methods is None else methods, config.limits)
        self.start_id = secrets.token_hex(16)
        self.token = secrets.token_hex(32)
        self.session: SessionInfo | None = None
        self.exit_reason: str | None = None
        self._shutting_down = False
        self._force = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._idle_since: float | None = time.monotonic()
        self.recorder_secrets: RecorderSecretSource | None = None
        """녹화 세션 메모리의 원문 (`secrets.create`). 녹화 세션(M4 T8)이 둔다."""
        self.recorder = RecorderService(self)
        """녹화 세션 (M4 T8, `recorder.*`)."""
        self.permission_files = PermissionFiles(self.root, self.service)
        """권한 파일 읽기·쓰기 (M5 B3 `permissions.*`·"항상 허용")."""
        self.approvals = ApprovalBroker(self, self._authorizer, config.approval_timeout_s)
        """사람 확인 (M5 B3 `approval.*`)."""
        self._agent_numbers: set[int] = set()
        """붙은 agent 연결 번호 (M5 B5 `agent.connections.changed`를 알릴지 정한다)."""

    # ---------------------------------------------------------------- Host (transport)

    @property
    def context(self) -> Daemon:
        return self

    @property
    def authorizer(self) -> Authorizer:
        return self._authorizer

    @property
    def runs(self) -> RunsLike:
        return self._runs

    @property
    def run_manager(self) -> RunManager:
        return self._run_manager

    @property
    def shutting_down(self) -> bool:
        return self._shutting_down

    @property
    def agent_toolsets(self) -> frozenset[str]:
        return self.config.agent_toolsets

    def connection_toolsets(self, connection: int) -> frozenset[str]:
        conn = self.transport.find(connection)
        return frozenset() if conn is None else conn.toolsets

    def enable_toolsets(self, connection: int, toolsets: Iterable[str]) -> frozenset[str]:
        """그 연결의 툴셋을 켠다 (이벤트 루프 안). 켠 뒤의 전체를 돌려준다."""
        conn = self.transport.find(connection)
        if conn is None:
            return frozenset()
        before = conn.toolsets
        conn.toolsets = conn.toolsets | frozenset(toolsets)
        if conn.toolsets != before and conn.number in self._agent_numbers:
            self.notify_ui("agent.connections.changed", {})
        return conn.toolsets

    def agent_connections(self) -> list[dict[str, Any]]:
        """붙은 agent 연결 목록 (`agent.connections`, M5 B5). 번호 순서."""
        out: list[dict[str, Any]] = []
        for conn in sorted(self.transport.connections, key=lambda c: c.number):
            principal = conn.principal
            if principal is None or conn.mismatch or principal.kind != "agent":
                continue
            out.append(
                {
                    "connection": conn.number,
                    "id": principal.id,
                    "name": conn.client_name,
                    "attended": principal.attended,
                    "toolsets": [t for t in TOOLSETS if t in conn.toolsets],
                    "since": conn.since,
                }
            )
        return out

    @property
    def platform_fake(self) -> Path | None:
        return self.config.platform_fake

    @property
    def documents(self) -> DocumentTable:
        return self._documents

    @property
    def checker(self) -> GraphChecker:
        return self._checker

    @property
    def frames(self) -> FrameCache:
        return self._frames

    @property
    def image_cache(self) -> EditorCache:
        return self._image_cache

    @property
    def targets(self) -> TargetStore:
        return self._targets

    def credentials(self) -> tuple[str, str, str] | None:
        if self.session is None:
            return None
        return self.token, self.start_id, str(self.root)

    def connections_changed(self) -> None:
        self._idle_since = None

    def connection_closed(self, number: int) -> None:
        self._documents.release_connection(number)
        self._run_manager.connection_closed(number)
        self.recorder.connection_closed(number)
        self.plugin_jobs.connection_closed(number)
        if number in self._agent_numbers:
            self._agent_numbers.discard(number)
            self.notify_ui("agent.connections.changed", {})

    # ---------------------------------------------------------------- 실행 알림 (runs.RunSink)

    def post(self, fn: Callable[[], None]) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            with contextlib.suppress(RuntimeError):  # 루프가 막 닫혔다: 보낼 곳이 없다
                loop.call_soon_threadsafe(fn)

    def notify(self, connection: int, method: str, params: Mapping[str, Any], run_id: str) -> None:
        conn = self.transport.find(connection)
        if conn is not None:
            self.transport.notify(conn, method, params, run_id=run_id)

    def resume(self, connection: int, run_id: str) -> None:
        conn = self.transport.find(connection)
        if conn is not None:
            conn.resume_run(run_id)

    def on_lag(self, connection: int, listener: Callable[[str], None]) -> bool:
        conn = self.transport.find(connection)
        if conn is None:
            return False
        conn.lag_listeners.append(listener)
        return True

    def ui_attached(self) -> bool:
        # 이벤트 루프 밖(감시 스레드)에서 읽는다: 연결 집합을 복사해 본다
        return any(
            c.authenticated and not c.mismatch and c.client_kind == "ui"
            for c in list(self.transport.connections)
        )

    def connection_name(self, connection: int) -> str:
        """그 연결의 `client.name` (확인 카드 표시용, 끝난 연결이면 빈 글자)."""
        conn = self.transport.find(connection)
        return "" if conn is None else conn.client_name

    def notify_ui(self, method: str, params: Mapping[str, Any]) -> None:
        """ui 연결에만 알린다 (이벤트 루프 안, `approval.*` — 에이전트는 확인 요청을 보지
        못한다)."""
        for conn in self.transport.ui_connections():
            self.transport.notify(conn, method, params)

    def breakpoints_changed(self, connection: int, breakpoints: list[dict[str, str]]) -> None:
        params = {"breakpoints": breakpoints}
        for conn in self.transport.ui_connections():
            if conn.number != connection:
                self.transport.notify(conn, "debug.breakpoints.changed", params)

    def _publish_lease(self, owner: dict[str, Any] | None) -> None:
        self.transport.broadcast("lease.changed", {"owner": owner})

    def connection_authenticated(self, number: int) -> None:
        # 알림은 바뀔 때만 오므로 붙은 직후 지금 소유자를 한 번 알린다 (hello 응답 뒤 순서)
        conn = self.transport.find(number)
        if conn is not None:
            self.transport.notify(conn, "lease.changed", {"owner": self._lease.owner})
            if conn.principal is not None and conn.principal.kind == "agent":
                self._agent_numbers.add(number)
                self.notify_ui("agent.connections.changed", {})

    # ---------------------------------------------------------------- 플러그인 (M6 B4)

    def _plugin_checker(
        self, factory: PluginRegistry
    ) -> Callable[[Program, Registry], list[Diagnostic]]:
        """편집기 사전 검증의 설치 플러그인 진단 (`plugin_not_installed`·`plugin_env_missing`·
        `plugin_env_stale`·`plugin_version_differs`). 읽기만 한다 — 실행은 runner가 다시 본다."""
        jobs = self.plugin_jobs

        def stale(lock: Mapping[str, Any]) -> str | None:
            try:
                return jobs.app().stale_reason(lock)
            except PluginError as exc:
                return exc.message

        def check(program: Program, registry: Registry) -> list[Diagnostic]:
            used = used_plugins(program) - factory.local
            if not used:
                return []
            problems, versions = plugin_runtime.inspect(self.root, used, stale=stale)
            found = [(p.code, p.plugin, p.message) for p in problems]
            return plugin_diagnostics(program, found, versions)

        return check

    def plugins_lock_check(self) -> None:
        """`kookabug.lock`이 마지막으로 알린 것과 다르면 레지스트리를 다시 만들게 하고 모든 연결에
        `plugins.changed {revision}` (잠금을 밖에서 바꿔도 — 감시가 부른다). 잠금은 그대로인데 환경
        상태(완성 표식·깨짐 기록)가 바뀌어도 같은 알림이다 (M6 B6: 검증에서 탈락한 환경의
        위젯을 내린다). 어느 스레드에서나."""
        lock_bytes = _read_or_none(self.root / LOCK_FILE)
        revision = revision_of(lock_bytes)
        env_state = _env_state(self.root, lock_bytes)
        with self._plugin_revision_lock:
            if revision == self._plugin_revision and env_state == self._plugin_env_state:
                return
            self._plugin_revision = revision
            self._plugin_env_state = env_state
        self._checker.invalidate()
        self.post(lambda: self.transport.broadcast("plugins.changed", {"revision": revision}))

    # ---------------------------------------------------------------- 파일 변경 알림

    def _publish_changes(self, paths: list[str], changes: list[DocChange]) -> None:
        """감시 결과를 알린다 (이벤트 루프 안). 문서 변경은 감시가 정한 연결에만 보낸다."""
        if LOCK_FILE in paths:
            self.plugins_lock_check()
        if paths:
            # agent 연결에는 screens/ 경로를 알리지 않는다 (화면 지도는 screens.*로만, M5 3.5 H4)
            hidden = [p for p in paths if not in_screens(p)]
            for conn in list(self.transport.connections):
                agent = conn.principal is not None and conn.principal.kind == "agent"
                shown = hidden if agent else paths
                if shown:
                    self.transport.notify(conn, "workspace.changed", {"paths": shown})
        for change in changes:
            conn = self.transport.find(change.connection)
            if conn is not None:
                params = {"doc_id": change.entry.doc_id, "revision": change.revision}
                self.transport.notify(conn, "graph.changed", params)

    # ---------------------------------------------------------------- 수명

    def request_shutdown(self, *, force: bool, reason: str) -> None:
        """끝내기 시작한다 (이벤트 루프 안에서). 이미 끝나는 중이면 force만 더한다."""
        self._force = self._force or force
        if self._shutting_down:
            return
        log.info("끝낸다: %s%s", reason, " (실행 취소)" if force else "")
        self._shutting_down = True
        self.exit_reason = reason
        if self._stop is not None:
            self._stop.set()

    def stop(self, reason: str = "stop") -> None:
        """다른 스레드에서 끝내기 (검사·신호)."""
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(lambda: self.request_shutdown(force=False, reason=reason))

    async def _idle_watch(self) -> None:
        timeout = self.config.idle_timeout_s
        interval = max(0.05, min(1.0, timeout / 4))
        while not self._shutting_down:
            now = time.monotonic()
            busy = (
                self.transport.count() > 0
                or self._runs.active_run() is not None
                or self.plugin_jobs.active()
            )
            if busy:
                self._idle_since = None
            elif self._idle_since is None:
                self._idle_since = now
            elif now - self._idle_since >= timeout:
                # 종료 판단은 시작 예약과 같은 잠금 안에서: 그 사이 예약된 시작이 있으면 유휴가
                # 아니고, 정한 뒤에 오는 시작은 runner를 만들지 못한다
                if self._runs.reserve_shutdown(force=False) is None:
                    self.request_shutdown(force=False, reason=f"유휴 {timeout:g}초")
                    return
                self._idle_since = None
            await asyncio.sleep(interval)

    async def serve(self, on_ready: Callable[[SessionInfo], None] | None = None) -> str:
        """포트를 열고 `session.json`을 공개한 뒤 끝날 때까지 돈다. 끝난 이유를 돌려준다."""
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        self._run_manager.sink = self
        try:
            # 편집기 캐시는 시작 때 비운다 (옛 daemon의 frame_id는 모두 만료다). 녹화 세션 저장소도
            # (지난 daemon이 남긴 세션 — 원문이 찍힌 화면 PNG가 있을 수 있다)
            await asyncio.to_thread(self._image_cache.reset)
            await asyncio.to_thread(AgentCache(self.root).reset)
            await asyncio.to_thread(RecorderStore.clear_all, self.root)
            # 에이전트 보호 기록 (M7 R1): 재시작 뒤에도 비밀값을 넣은 창은 계속 보호한다
            await asyncio.to_thread(self.guard.load)
            async with self.transport.serve() as server:
                port = self.transport.bound(server)
                await asyncio.to_thread(_faults.fault_point, "daemon.before_session_publish")
                info = own_session(
                    root=self.root,
                    port=port,
                    start_id=self.start_id,
                    token=self.token,
                    protocol=PROTOCOL,
                    daemon_version=DAEMON_VERSION,
                )
                # 파일을 보고 바로 붙는 클라이언트가 인증될 수 있게 먼저 정한다
                self.session = info
                await asyncio.to_thread(write_session, self.root, info)
                log.info("포트 %d에서 받는다 (start_id %s)", port, self.start_id)
                if on_ready is not None:
                    on_ready(info)
                watcher = Watcher(
                    self.root,
                    self._documents,
                    self._publish_changes,
                    self.config.watch_interval_s,
                    on_tick=self.plugins_lock_check,
                )
                tasks = [
                    asyncio.create_task(self._idle_watch()),
                    asyncio.create_task(watcher.run()),
                    asyncio.create_task(self._lease.run()),
                ]
                if not self._shutting_down:
                    await self._stop.wait()
                if self._force:
                    await asyncio.to_thread(self._runs.cancel_all_and_wait)
                await self.transport.close_all(self.exit_reason or "shutdown")
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            # 진행 중인 플러그인 작업은 취소하고 마무리(staging 정리)를 기다린다 — 커밋 전이면
            # 잠금·기존 환경 그대로 (M6 3.5)
            await asyncio.to_thread(self.plugin_jobs.close)
            await asyncio.to_thread(self.recorder.close)
            await asyncio.to_thread(self._run_manager.close)
            self._checker.close()
            if self.session is not None:
                await asyncio.to_thread(remove_session, self.root, self.start_id)
        return self.exit_reason or "shutdown"


# ---------------------------------------------------------------- 명령


class UsageError(Exception):
    """daemon을 시작할 수 없다 (워크스페이스·인자). 종료 코드 6."""


def _find_workspace(given: str | None) -> Path:
    from kookabug_core.workspace import Workspace

    try:
        ws = Workspace.open(Path(given)) if given else Workspace.find(Path.cwd())
    except WorkspaceError as exc:
        raise UsageError(str(exc)) from exc
    return ws.root


def config_from_args(args: argparse.Namespace) -> DaemonConfig:
    root = _find_workspace(args.workspace)
    fake: Path | None = None
    if args.platform_fake is not None:
        fake = Path(args.platform_fake).resolve()
        try:
            data = json.loads(fake.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UsageError(f"--platform-fake {fake}을(를) 읽을 수 없다: {exc}") from exc
        if not isinstance(data, dict):
            raise UsageError(f"--platform-fake {fake}은(는) JSON 객체여야 한다")
    try:
        testing = testing_options(
            os.environ,
            accept_extra_info=args.recorder_accept_extra_info,
            ime_query_window=args.recorder_ime_query_window,
        )
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    script: Path | None = None
    if args.recorder_script is not None:
        if fake is None:
            raise UsageError("--recorder-script는 --platform-fake와 함께만 쓴다")
        script = Path(args.recorder_script).resolve()
    return DaemonConfig(
        workspace=root,
        idle_timeout_s=args.idle_timeout_s,
        session_wait_s=args.session_wait_s,
        platform_fake=fake,
        plugin_modules=tuple(args.plugin_modules),
        log_level=args.log_level,
        recorder_testing=testing,
        recorder_script=script,
        recorder_script_speed=args.recorder_script_speed,
    )


def _setup_logging(root: Path, level: str) -> Path:
    """stderr와 로그 파일. 오래된 daemon 로그는 최근 `LOG_KEEP`개만 남긴다."""
    folder = root / PRIVATE_DIR / LOGS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    old = sorted(folder.glob("daemon-*.log"), key=lambda p: p.stat().st_mtime)
    for path in old[: max(0, len(old) - (LOG_KEEP - 1))]:
        with contextlib.suppress(OSError):
            path.unlink()
    path = folder / f"daemon-{datetime.now(UTC):%Y%m%dT%H%M%S}-{os.getpid()}.log"
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root_logger = logging.getLogger()
    for handler in (logging.StreamHandler(sys.stderr), logging.FileHandler(path, encoding="utf-8")):
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())
    logging.getLogger("websockets").setLevel(logging.WARNING)
    return path


def _emit(out: TextIO, as_json: bool, data: dict[str, Any], text: str) -> None:
    print(json_text(data) if as_json else text, file=out, flush=True)


def run(
    config: DaemonConfig,
    *,
    as_json: bool = False,
    dpi_error: str | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """잠금 → 공개 → 끝날 때까지. 종료 코드를 돌려준다 (0 정상·이미 실행 중, 6 환경 오류)."""
    stdout: TextIO = sys.stdout if out is None else out
    stderr: TextIO = sys.stderr if err is None else err

    def fail(message: str) -> int:
        if as_json:
            _emit(stdout, True, {"status": "error", "error": message}, "")
        print(f"오류: {message}", file=stderr, flush=True)
        return EXIT_USAGE

    _faults.set_role("supervisor")
    try:
        service = WorkspaceService(config.workspace)
    except WorkspaceError as exc:
        return fail(str(exc))
    root = service.root
    try:
        lock = DaemonLock.acquire(root)
    except LockBusy:
        from kookabug_daemon.client import probe_session

        found = wait_for_valid_session(root, probe_session, timeout=config.session_wait_s)
        if found is None:
            return fail(
                f"다른 daemon이 잠금을 쥐고 있지만 {config.session_wait_s:g}초 안에 유효한 세션이 "
                f"나오지 않았다 ({root / PRIVATE_DIR})"
            )
        _emit(
            stdout,
            as_json,
            {"status": "already_running", "session": found.public()},
            f"이미 실행 중이다: PID {found.pid}, 포트 {found.port}",
        )
        return EXIT_OK
    except OSError as exc:
        return fail(f"잠금 파일을 열 수 없다: {exc}")

    with lock:
        log_path = _setup_logging(root, config.log_level)
        log.info("daemon %s 시작: 워크스페이스 %s, PID %d", DAEMON_VERSION, root, os.getpid())
        if dpi_error is None:
            log.info("DPI 인식: per_monitor_v2")
        else:
            log.warning("DPI 인식을 정하지 못했다: %s", dpi_error)
        _faults.fault_point("daemon.after_lock")
        daemon = Daemon(config, service=service)

        def ready(info: SessionInfo) -> None:
            _emit(
                stdout,
                as_json,
                {
                    "status": "started",
                    "session": info.public(),
                    "log": str(log_path),
                    "dpi_awareness": "per_monitor_v2" if dpi_error is None else None,
                    "dpi_error": dpi_error,
                },
                f"daemon 시작: 포트 {info.port}, 워크스페이스 {root} (로그 {log_path})",
            )

        try:
            reason = asyncio.run(daemon.serve(ready))
        except KeyboardInterrupt:
            reason = "Ctrl+C"
        except OSError as exc:  # 포트를 열지 못함·session.json을 쓰지 못함
            log.exception("daemon을 시작하지 못했다")
            return fail(f"daemon을 시작하지 못했다: {exc}")
        log.info("daemon 끝: %s", reason)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m kookabug_daemon` (CLI `kookabug daemon`과 같은 인자)."""
    from kookabug_core.win import dpi

    dpi_error = dpi.enable_at_startup()  # 창 API보다 먼저 (M1 2.2)
    parser = argparse.ArgumentParser(prog="kookabug-daemon", description="Kookabug daemon")
    add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        # 개발 모듈 daemon은 사람만 띄운다 (M6 3.7, CLI `kookabug daemon`과 같다)
        refuse_dev_modules(cli_principal(), tuple(args.plugin_modules))
    except DevModulesRefused as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return EXIT_DENIED
    try:
        config = config_from_args(args)
    except UsageError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return run(config, as_json=args.json, dpi_error=dpi_error)
