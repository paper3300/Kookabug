"""워커 검사 하네스: runner가 할 일(스냅샷 → 워커 hello·등록 → 검증 → 실행)을 테스트 프로세스에서
한다 (runner 프로세스는 T9). 실행기는 하네스를 부른 스레드(= runner 주 스레드 역할)에서 돈다.

    h = WorkerHarness(ws, "tests/t.graph.json", tmp_path)
    ran = h.run_all()                      # 스냅샷·워커 시작·검증·실행·shutdown
    assert ran.verdict == "pass"

이 모듈은 testkit을 import하지 않는다 (runner가 플러그인 코드를 import하지 않음을 하위 프로세스로
확인하는 검사가 이 하네스를 쓴다). 워커는 `PYTHONPATH`의 testkit을 `--plugin-module`처럼 읽는다.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from kb_testing.proc import faults_env, isolated_env
from kookabug_core.diagnostics import Diagnostic
from kookabug_core.engine import (
    CancelToken,
    ExecOptions,
    Executor,
    FakePlatform,
    InProcessInvoker,
    MemoryArtifacts,
    NodeInvoker,
    RoutingInvoker,
    RunResult,
)
from kookabug_core.loader import Program
from kookabug_core.record.snapshot import take_snapshot
from kookabug_core.registry import Registry, default_registry
from kookabug_core.validate import validate
from kookabug_core.workerhost import WorkerInvoker, WorkerProcess
from kookabug_core.workspace import MemorySecrets, Workspace

TESTS_DIR: Final = Path(__file__).resolve().parents[1]
TOOLS_DIR: Final = TESTS_DIR.parents[2] / "tools"
PLUGIN_MODULES: Final = ("testkit.nodes",)
RUN_ID: Final = "r1"


def worker_env(
    tmp_path: Path, faults: Sequence[Mapping[str, Any]] | None = None, **extra: str
) -> dict[str, str]:
    """워커(와 하위 runner 역할 프로세스) 환경: 격리 + testkit을 찾는 `PYTHONPATH` + 고장 규칙."""
    env = isolated_env(tmp_path, None, **extra)
    env["PYTHONPATH"] = os.pathsep.join([str(TESTS_DIR), str(TOOLS_DIR)])
    return faults_env(faults, env) if faults else env


class Events:
    """이벤트 모음 (실행기 싱크 + 워커 이벤트). 여러 스레드가 쓴다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[dict[str, Any]] = []

    def emit(self, event: Mapping[str, Any]) -> None:
        with self._lock:
            self._items.append({"run": RUN_ID, **event})

    @property
    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items)

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.all if e["event"] == kind]

    def has_log(self, message: str) -> bool:
        return any(e.get("message") == message for e in self.of("log"))


class WorkerHarness:
    def __init__(
        self,
        ws: Workspace,
        rel: str,
        tmp_path: Path,
        *,
        env: Mapping[str, str] | None = None,
        frames: Iterable[str] = (),
        on_capture: Callable[[int], None] | None = None,
        secrets: Mapping[str, str] | None = None,
        modules: Sequence[str] = PLUGIN_MODULES,
        start_timeout_ms: int = 30_000,
        cancel_grace_ms: int = 2_000,
        deadline_ms: int = 60_000,
        trace: Callable[[str, bytes], None] | None = None,
    ) -> None:
        self.ws = ws
        self.rel = rel
        self.run_dir = tmp_path / "run"
        self.env = dict(env) if env is not None else worker_env(tmp_path)
        self.platform = FakePlatform(frames, on_capture=on_capture)
        self.secrets = MemorySecrets(dict(secrets or {}))
        self.modules = tuple(modules)
        self.start_timeout_ms = start_timeout_ms
        self.cancel_grace_ms = cancel_grace_ms
        self.deadline_ms = deadline_ms
        self.trace = trace
        self.registry: Registry = default_registry()
        self.cancel = CancelToken()
        self.events = Events()
        self.artifacts = MemoryArtifacts()
        self.program: Program | None = None
        self.worker: WorkerProcess | None = None
        self.local: NodeInvoker = InProcessInvoker()
        self.remote: NodeInvoker | None = None

    @property
    def files_root(self) -> Path:
        return self.run_dir / "snapshot"

    def prepare(self) -> Program:
        snap = take_snapshot(self.ws, self.rel, self.files_root, secrets=self.secrets)
        self.program = snap.program
        return snap.program

    def check(self) -> None:
        self.cancel.check()

    def start_worker(self) -> WorkerProcess:
        self.worker = WorkerProcess.start(
            modules=self.modules,
            files_root=self.files_root,
            log_dir=self.run_dir / "logs",
            run_id=RUN_ID,
            workspace_id=str(self.ws.root),
            registry=self.registry,
            emit=self.events.emit,
            check=self.check,
            start_timeout_ms=self.start_timeout_ms,
            cancel_grace_ms=self.cancel_grace_ms,
            env=self.env,
            trace=self.trace,
        )
        self.remote = WorkerInvoker(self.worker)
        return self.worker

    def validate(self) -> list[Diagnostic]:
        assert self.program is not None
        return validate(self.program, self.registry)

    def run(self) -> RunResult:
        assert self.program is not None
        executor = Executor(
            self.registry,
            platform=self.platform,
            cancel=self.cancel,
            artifacts=self.artifacts,
            sink=self.events,
            invoker=RoutingInvoker(self.remote, local=self.local),
        )
        return executor.run(
            self.program,
            ExecOptions(deadline_ms=self.deadline_ms, run_id=RUN_ID, graph_prefix="snapshot/"),
        )

    def shutdown(self) -> None:
        if self.worker is not None:
            self.worker.shutdown()

    def run_all(self) -> RunResult:
        self.prepare()
        self.start_worker()
        try:
            return self.run()
        finally:
            self.shutdown()

    def log_text(self, stream: str = "stdout") -> str:
        path = self.run_dir / "logs" / f"worker.{stream}.log"
        return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


class Background:
    """`fn()`을 다른 스레드에서 돌린다 (테스트 스레드가 취소·kill을 하는 동안 실행)."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        self.result: Any = None
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, args=(fn,), daemon=True)
        self._thread.start()

    def _run(self, fn: Callable[[], Any]) -> None:
        try:
            self.result = fn()
        except BaseException as exc:
            self.error = exc

    def join(self, timeout: float = 30.0) -> Any:
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise AssertionError(f"{timeout}초 안에 끝나지 않았다")
        if self.error is not None:
            raise self.error
        return self.result
