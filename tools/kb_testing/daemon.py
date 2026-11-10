"""daemon 검사 헬퍼 (M2 T3).

    root = make_workspace(tmp_path / "ws")
    proc = DaemonProcess.start(spawned, root, tmp_path / "d1", "--idle-timeout-s", "5")
    info = proc.first_line()              # --json 첫 줄 (started·already_running·error)

    with ThreadDaemon(root, runs=fake) as d:   # 같은 프로세스의 다른 스레드에서 Daemon.serve
        with d.client() as client: ...

하위 프로세스는 런처 없이 띄운다(`python_cmd`): `Popen.pid`가 daemon의 PID다.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Self

from kb_testing.proc import Spawned, direct_env, isolated_env, python_cmd, wait_until
from kookabug_core.permissions import TOOLSETS
from kookabug_core.service import WorkspaceService
from kookabug_core.win import CHILD_FLAGS
from kookabug_daemon.app import Daemon, DaemonConfig
from kookabug_daemon.client import UI_CLIENT, DaemonClient
from kookabug_daemon.methods import MethodSpec, RunsLike
from kookabug_daemon.recorder_hook import HookTesting
from kookabug_daemon.session import DaemonLock, SessionInfo
from kookabug_daemon.transport import Limits

__all__ = [
    "DAEMON_CMD",
    "DaemonProcess",
    "FakeRuns",
    "ThreadDaemon",
    "copy_sample_workspace",
    "daemon_env",
    "make_workspace",
]

DAEMON_CMD: Final = python_cmd("-m", "kookabug_cli", "daemon")


def make_workspace(root: Path, data: Mapping[str, Any] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "kookabug.json").write_text(
        json.dumps(dict(data or {"format": "kookabug.workspace/0"})), encoding="utf-8"
    )
    return root.resolve()


def copy_sample_workspace(dest: Path) -> Path:
    """예제 워크스페이스(`fixtures/sample-game/workspace`) 사본 (`runs/`·`.kookabug/` 제외)."""
    from kb_testing.packaging import REPO_ROOT

    source = REPO_ROOT / "fixtures" / "sample-game" / "workspace"
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns("runs", ".kookabug"))
    return dest.resolve()


def daemon_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    """격리 환경(바깥 `KOOKABUG_*` 제거) + 런처 없이 이 venv를 쓰는 환경."""
    return direct_env(isolated_env(tmp_path, None, **extra))


@dataclass
class DaemonProcess:
    """`kookabug daemon --json` 하위 프로세스. stdout·stderr는 `out` 폴더의 파일로."""

    proc: Any
    out: Path

    @classmethod
    def start(
        cls,
        spawned: Spawned,
        root: Path,
        out: Path,
        *args: str,
        env: Mapping[str, str],
        json_output: bool = True,
    ) -> DaemonProcess:
        out.mkdir(parents=True, exist_ok=True)
        cmd = [*DAEMON_CMD, "--workspace", str(root), *(["--json"] if json_output else []), *args]
        with (out / "stdout.log").open("ab") as stdout, (out / "stderr.log").open("ab") as stderr:
            proc = spawned.popen(
                cmd, env=dict(env), stdout=stdout, stderr=stderr, creationflags=CHILD_FLAGS
            )
        return cls(proc, out)

    @property
    def pid(self) -> int:
        return int(self.proc.pid)

    def stdout(self) -> str:
        path = self.out / "stdout.log"
        return path.read_text("utf-8", errors="replace") if path.exists() else ""

    def output(self) -> str:
        err = self.out / "stderr.log"
        text = err.read_text("utf-8", errors="replace") if err.exists() else ""
        return f"--- stdout\n{self.stdout()[-4000:]}\n--- stderr\n{text[-4000:]}"

    def first_line(self, timeout: float = 30.0) -> dict[str, Any]:
        def line() -> str | None:
            text = self.stdout()
            return text.split("\n", 1)[0] if "\n" in text else None

        found = wait_until(line, timeout=timeout, message=self.output)
        assert found is not None
        return json.loads(found)

    def wait(self, timeout: float = 30.0) -> int:
        return int(self.proc.wait(timeout))

    def alive(self) -> bool:
        return self.proc.poll() is None


class FakeRuns:
    """가짜 실행 핸들: 진행 중인 실행 ID와 취소 기록."""

    def __init__(self, active: str | None = None) -> None:
        self.active = active
        self.cancelled = threading.Event()

    def active_run(self) -> str | None:
        return self.active

    def reserve_shutdown(self, *, force: bool) -> str | None:
        return None if force else self.active

    def cancel_all_and_wait(self) -> None:
        self.cancelled.set()
        self.active = None


class ThreadDaemon:
    """잠금을 쥐고 다른 스레드의 이벤트 루프에서 `Daemon.serve()`를 돌린다."""

    def __init__(
        self,
        root: Path,
        *,
        runs: RunsLike | None = None,
        methods: Mapping[str, MethodSpec] | None = None,
        service: Any = None,
        limits: Limits | None = None,
        idle_timeout_s: float = 600.0,
        environ: Mapping[str, str] | None = None,
        watch_interval_s: float = 1.0,
        platform_fake: Path | None = None,
        plugin_modules: tuple[str, ...] = (),
        recorder_script: Path | None = None,
        recorder_script_speed: float | None = float("inf"),
        recorder_testing: HookTesting | None = None,
        agent_toolsets: Iterable[str] | None = None,
        approval_timeout_s: float | None = None,
        plugin_environ: Mapping[str, str] | None = None,
        job_heartbeat_s: float | None = None,
    ) -> None:
        """`agent_toolsets`: agent 연결이 hello 때 갖는 툴셋. None이면 **전부**(M5 이전 검사가
        툴셋 없이 판정만 보던 그대로). M5 툴셋 검사는 제품 기본값 `("core",)`을 넘긴다.
        `approval_timeout_s`: 사람 확인 대기 (None이면 제품 기본값 120초).
        `plugin_environ`: 플러그인 작업의 환경 변수 (M6 — 검사의 SDK wheel·uv 캐시)."""
        self.root = root
        extra: dict[str, Any] = {}
        if approval_timeout_s is not None:
            extra["approval_timeout_s"] = approval_timeout_s
        if plugin_environ is not None:
            extra["plugin_environ"] = dict(plugin_environ)
        if job_heartbeat_s is not None:
            extra["job_heartbeat_s"] = job_heartbeat_s
        self._owners: list[tuple[DaemonClient, threading.Event, threading.Thread]] = []
        config = DaemonConfig(
            **extra,
            agent_toolsets=frozenset(TOOLSETS if agent_toolsets is None else agent_toolsets),
            workspace=root,
            idle_timeout_s=idle_timeout_s,
            limits=limits or Limits(),
            watch_interval_s=watch_interval_s,
            platform_fake=platform_fake,
            plugin_modules=plugin_modules,
            recorder_script=recorder_script,
            recorder_script_speed=recorder_script_speed,
            recorder_testing=recorder_testing,
        )
        if service is None:
            service = WorkspaceService(root, environ=dict(environ or {}))
        self.lock = DaemonLock.acquire(root)
        self.daemon = Daemon(config, service=service, runs=runs, methods=methods)
        self.ready = threading.Event()
        self.reason: str | None = None
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="thread-daemon", daemon=True)

    def _run(self) -> None:
        try:
            self.reason = asyncio.run(self.daemon.serve(lambda _: self.ready.set()))
        except BaseException as exc:
            self.error = exc
            self.ready.set()

    def __enter__(self) -> Self:
        self._thread.start()
        if not self.ready.wait(30) or self.error is not None:
            self.lock.close()
            raise RuntimeError(f"daemon이 시작하지 못했다: {self.error!r}")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        for client, stop, beat in self._owners:
            stop.set()
            beat.join(5)
            client.close()
        self.daemon.stop("test")
        self._thread.join(30)
        self.lock.close()

    def begin_job(self, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """`job.begin`을 부르고 그 소유 연결(M8 R8)을 이 daemon이 끝날 때까지 열어 두며 heartbeat를
        보낸다 (`agent-job` 대역). 결과에 `owner`(그 연결)를 더한다 — 검사가 끊어 유실을 흉내
        낸다."""
        client = self.client()
        begun = dict(client.call("job.begin", {"playbook": "triage", **dict(params or {})}))
        stop = threading.Event()
        every = max(0.05, self.daemon.config.job_heartbeat_s / 3)

        def beat() -> None:
            while not stop.wait(every):
                try:
                    client.call("job.heartbeat", {"job": begun["job"]}, timeout=5)
                except Exception:
                    return

        thread = threading.Thread(target=beat, name="job-owner-beat", daemon=True)
        if begun.get("state") == "running":
            thread.start()
        self._owners.append((client, stop, thread))
        begun["owner"] = client
        return begun

    @property
    def session(self) -> SessionInfo:
        assert self.daemon.session is not None
        return self.daemon.session

    @property
    def port(self) -> int:
        return self.session.port

    def client(self, client: Mapping[str, Any] = UI_CLIENT, **kwargs: Any) -> DaemonClient:
        return DaemonClient.connect(self.port, self.session.token, client=client, **kwargs)

    def finished(self, timeout: float = 30.0) -> str | None:
        """daemon이 스스로 끝날 때까지 기다린다 (유휴·shutdown)."""
        self._thread.join(timeout)
        assert not self._thread.is_alive(), "daemon이 끝나지 않았다"
        return self.reason

    def is_running(self) -> bool:
        return self._thread.is_alive()

    def call_in_loop(self, fn: Any, *args: Any) -> Any:
        """이벤트 루프 스레드에서 `fn(*args)`를 불러 결과를 돌려준다."""
        loop = self.daemon._loop  # pyright: ignore[reportPrivateUsage]
        assert loop is not None

        async def call() -> Any:
            return fn(*args)

        return asyncio.run_coroutine_threadsafe(call(), loop).result(30)
