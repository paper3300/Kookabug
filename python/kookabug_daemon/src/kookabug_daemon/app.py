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
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, TextIO

from kookabug_core.service import WorkspaceService
from kookabug_core.workspace import WorkspaceError
from kookabug_daemon.documents import DocumentTable, GraphChecker
from kookabug_daemon.methods import MethodSpec, RunsLike, registry
from kookabug_daemon.methods.tools import Authorizer
from kookabug_daemon.options import DEFAULT_IDLE_TIMEOUT_S, SESSION_WAIT_S, add_arguments
from kookabug_daemon.protocol import DAEMON_VERSION, PROTOCOL, json_text
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
from kookabug_daemon.transport import Limits, Transport
from kookabug_daemon.watch import DocChange, Watcher
from kookabug_sdk import _faults

__all__ = [
    "DEFAULT_IDLE_TIMEOUT_S",
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
LOG_KEEP: Final = 20
WATCH_INTERVAL_S: Final = 1.0
"""파일 변경 폴링 간격 (M2 계획 Q10)."""


class NoRuns:
    """실행 관리가 붙기 전(T5)의 빈 실행 목록."""

    def active_run(self) -> str | None:
        return None

    def cancel_all_and_wait(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class DaemonConfig:
    workspace: Path
    idle_timeout_s: float = DEFAULT_IDLE_TIMEOUT_S
    session_wait_s: float = SESSION_WAIT_S
    platform_fake: Path | None = None
    log_level: str = "info"
    limits: Limits = field(default_factory=Limits)
    watch_interval_s: float = WATCH_INTERVAL_S


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
        self._runs: RunsLike = runs or NoRuns()
        self._authorizer = Authorizer(self.service)
        self._documents = DocumentTable(self.root)
        self._checker = GraphChecker(self.root)
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
    def shutting_down(self) -> bool:
        return self._shutting_down

    @property
    def platform_fake(self) -> Path | None:
        return self.config.platform_fake

    @property
    def documents(self) -> DocumentTable:
        return self._documents

    @property
    def checker(self) -> GraphChecker:
        return self._checker

    def credentials(self) -> tuple[str, str, str] | None:
        if self.session is None:
            return None
        return self.token, self.start_id, str(self.root)

    def connections_changed(self) -> None:
        self._idle_since = None

    def connection_closed(self, number: int) -> None:
        self._documents.release_connection(number)

    # ---------------------------------------------------------------- 파일 변경 알림

    def _publish_changes(self, paths: list[str], changes: list[DocChange]) -> None:
        """감시 결과를 알린다 (이벤트 루프 안). 문서 변경은 감시가 정한 연결에만 보낸다."""
        if paths:
            self.transport.broadcast("workspace.changed", {"paths": paths})
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
            busy = self.transport.count() > 0 or self._runs.active_run() is not None
            if busy:
                self._idle_since = None
            elif self._idle_since is None:
                self._idle_since = now
            elif now - self._idle_since >= timeout:
                self.request_shutdown(force=False, reason=f"유휴 {timeout:g}초")
                return
            await asyncio.sleep(interval)

    async def serve(self, on_ready: Callable[[SessionInfo], None] | None = None) -> str:
        """포트를 열고 `session.json`을 공개한 뒤 끝날 때까지 돈다. 끝난 이유를 돌려준다."""
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        try:
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
                )
                tasks = [
                    asyncio.create_task(self._idle_watch()),
                    asyncio.create_task(watcher.run()),
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
    return DaemonConfig(
        workspace=root,
        idle_timeout_s=args.idle_timeout_s,
        session_wait_s=args.session_wait_s,
        platform_fake=fake,
        log_level=args.log_level,
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
        config = config_from_args(args)
    except UsageError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return run(config, as_json=args.json, dpi_error=dpi_error)
