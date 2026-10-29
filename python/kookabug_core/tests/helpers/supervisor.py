"""감독자 검사 헬퍼 (M0b T10).

이 프로세스 안의 실제 `Supervisor` (`start_run`):

    handle = start_run(tmp_path, spawned, graph, faults=[...], hooks={...})
    outcome = handle.wait(30)

감독자를 별도 프로세스(`procs/supervisor_host.py`)로 (`SupervisorHost`):

    host = SupervisorHost.make(tmp_path, graph, faults=[...])
    host.start(spawned)                     # 감독자 프로세스 → started.json
    host.kill_runner() / host.kill()        # runner·감독자 프로세스를 TerminateProcess로
    done = host.done()                      # 감독자의 wait() 결과 (done.json)

감독자 역할 고장 규칙(`role: supervisor`)은 감독자 호스트 프로세스에서만 동작한다(pytest 프로세스는
역할이 없다). runner는 같은 환경을 물려받지만 자기 역할(`runner`)의 규칙만 쓴다.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from helpers.graphs import GraphBuilder, make_workspace
from helpers.runner import RUNNER_CMD, TEST
from helpers.worker import PLUGIN_MODULES, worker_env
from kb_testing.proc import (
    PROCS_DIR,
    Spawned,
    direct_env,
    python_cmd,
    read_fake_input_log,
    wait_until,
)
from kookabug_core.inputs.lease import STATE_DIR_ENV, read_lease_file
from kookabug_core.record import RunView, read_run, read_run_json
from kookabug_core.runner.spec import PlatformSpec
from kookabug_core.supervisor import RunHandle, StartOptions, Supervisor
from kookabug_core.win import CHILD_FLAGS, Process, ProcessId, identify
from kookabug_core.workspace import Workspace

__all__ = [
    "GRACE_MS",
    "SupervisorHost",
    "events",
    "has_log",
    "job_idents",
    "runner_stderr",
    "start_run",
    "wait_log",
]

HOST: Final = PROCS_DIR / "supervisor_host.py"
GRACE_MS: Final = 2_000


def start_run(
    tmp_path: Path,
    spawned: Spawned,
    graph: GraphBuilder | None,
    *,
    faults: Sequence[Mapping[str, Any]] = (),
    hooks: Mapping[str, Mapping[str, str]] | None = None,
    runner_cmd: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    env_direct: bool = True,
    hello_timeout: float = 30.0,
    **opts: Any,
) -> RunHandle:
    """이 프로세스의 `Supervisor`로 실행을 시작한다. 워크스페이스는 `tmp_path/ws`, 가짜 입력 기록은
    `tmp_path/input.jsonl`. `env`를 주면 그 환경(임대권 이름 공유 등)을, 아니면 격리 환경을 쓴다."""
    ws_root = tmp_path / "ws"
    ws = make_workspace(ws_root) if not (ws_root / "kookabug.json").exists() else None
    if graph is not None:
        graph.write(ws or ws_root, TEST)
    base = dict(env) if env is not None else worker_env(tmp_path, list(faults) or None)
    opts.setdefault("shutdown_grace_ms", GRACE_MS)
    opts.setdefault("plugin_modules", PLUGIN_MODULES)
    opts.setdefault("worker_cancel_grace_ms", 1_000)
    opts.setdefault("runs_dir", tmp_path / "runs")
    options = StartOptions(
        platform=PlatformSpec(
            "fake",
            input_log=str(tmp_path / "input.jsonl"),
            hooks={h: dict(n) for h, n in (hooks or {}).items()},
        ),
        **opts,
    )
    supervisor = Supervisor(
        runner_cmd=RUNNER_CMD if runner_cmd is None else runner_cmd,
        env=direct_env(base) if env_direct else base,
        hello_timeout=hello_timeout,
    )
    handle = supervisor.start(ws_root, TEST, options)
    if handle.launcher is not None:
        spawned.track(handle.launcher)
    if handle.runner_ident is not None:
        spawned.track(handle.runner_ident)
    return handle


def events(handle: RunHandle) -> list[dict[str, Any]]:
    return read_run(handle.run_dir).events


def has_log(handle: RunHandle, message: str) -> bool:
    return any(e.get("event") == "log" and e.get("message") == message for e in events(handle))


def wait_log(handle: RunHandle, message: str) -> None:
    wait_until(
        lambda: has_log(handle, message),
        message=lambda: f"log {message} 없음\n{runner_stderr(handle)}",
    )


def runner_stderr(handle: RunHandle) -> str:
    parts = []
    for name in ("runner.stderr.log", "worker.stderr.log"):
        path = handle.folder.logs / name
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                parts.append(f"--- {name}\n{text[-4000:]}")
    return "\n".join(parts)


def job_idents(handle: RunHandle) -> list[ProcessId]:
    assert handle.job is not None
    return [i for i in (identify(pid) for pid in handle.job.process_ids()) if i is not None]


@dataclass
class SupervisorHost:
    tmp_path: Path
    ws: Workspace
    graph: str = TEST
    faults: Sequence[Mapping[str, Any]] = ()
    plugin_modules: Sequence[str] = PLUGIN_MODULES
    hooks: Mapping[str, Mapping[str, str]] = field(default_factory=dict[str, Mapping[str, str]])
    shutdown_grace_ms: int = 2_000
    self_kill_margin_ms: int = 10_000
    env_extra: Mapping[str, str] = field(default_factory=dict[str, str])
    proc: subprocess.Popen[bytes] | None = None
    env: dict[str, str] = field(default_factory=dict[str, str])

    @classmethod
    def make(cls, tmp_path: Path, graph: GraphBuilder | None = None, **kw: Any) -> SupervisorHost:
        ws = make_workspace(tmp_path / "ws")
        if graph is not None:
            graph.write(ws, kw.get("graph", TEST))
        return cls(tmp_path=tmp_path, ws=ws, **kw)

    @property
    def out(self) -> Path:
        return self.tmp_path / "host"

    @property
    def input_log(self) -> Path:
        return self.tmp_path / "input.jsonl"

    def start(self, spawned: Spawned) -> SupervisorHost:
        self.out.mkdir(parents=True, exist_ok=True)
        self.env = direct_env(
            worker_env(self.tmp_path, list(self.faults) or None, **dict(self.env_extra))
        )
        spec = {
            "workspace_root": str(self.ws.root),
            "graph": self.graph,
            "runner_cmd": RUNNER_CMD,
            "out": str(self.out),
            "options": {
                "deadline_ms": 60_000,
                "plugin_modules": list(self.plugin_modules),
                "platform": {
                    "kind": "fake",
                    "input_log": str(self.input_log),
                    "hooks": {h: dict(n) for h, n in self.hooks.items()},
                },
                "runs_dir": str(self.tmp_path / "runs"),
                "shutdown_grace_ms": self.shutdown_grace_ms,
                "self_kill_margin_ms": self.self_kill_margin_ms,
                "worker_cancel_grace_ms": 1_000,
            },
        }
        spec_file = self.out / "spec.json"
        spec_file.write_text(json.dumps(spec), encoding="utf-8")
        with (
            (self.out / "host.stdout.log").open("ab") as stdout,
            (self.out / "host.stderr.log").open("ab") as stderr,
        ):
            self.proc = spawned.popen(
                python_cmd(HOST, spec_file),
                env=self.env,
                stdout=stdout,
                stderr=stderr,
                creationflags=CHILD_FLAGS,
            )
        started = self.started()
        assert started["start_error"] is None, (started, self.stderr())
        spawned.track(self.runner_ident)
        return self

    def _status(self, name: str, timeout: float = 30.0) -> dict[str, Any]:
        path = self.out / name
        wait_until(path.exists, timeout=timeout, message=lambda: f"{name} 없음\n{self.stderr()}")
        return json.loads(path.read_text(encoding="utf-8"))

    def started(self) -> dict[str, Any]:
        return self._status("started.json")

    def done(self, timeout: float = 30.0) -> dict[str, Any]:
        return self._status("done.json", timeout)

    @property
    def run_dir(self) -> Path:
        return Path(self.started()["run_dir"])

    @property
    def runner_ident(self) -> ProcessId:
        return ProcessId.from_json(self.started()["runner"])

    def kill_runner(self) -> None:
        with Process.open(self.runner_ident, terminate=True) as proc:
            proc.terminate(1)
            proc.wait(10)

    def kill(self) -> None:
        """감독자 프로세스를 끝낸다 (그 Job 핸들도 OS가 닫는다)."""
        assert self.proc is not None
        self.proc.kill()
        self.proc.wait(10)

    def cancel(self) -> None:
        (self.out / "cancel").touch()

    def view(self) -> RunView:
        return read_run(self.run_dir)

    def run_json(self) -> dict[str, Any] | None:
        return read_run_json(self.run_dir / "run.json")

    def fake_inputs(self) -> list[dict[str, Any]]:
        return read_fake_input_log(self.input_log)

    def lease_file(self) -> dict[str, Any] | None:
        return read_lease_file(self.env[STATE_DIR_ENV])

    def has_log(self, message: str) -> bool:
        return any(
            e.get("event") == "log" and e.get("message") == message for e in self.view().events
        )

    def stderr(self) -> str:
        parts = []
        for path in (self.out / "host.stderr.log", *self._run_logs()):
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    parts.append(f"--- {path.name}\n{text[-4000:]}")
        return "\n".join(parts)

    def _run_logs(self) -> list[Path]:
        started = self.out / "started.json"
        if not started.exists():
            return []
        logs = Path(json.loads(started.read_text(encoding="utf-8"))["run_dir"]) / "logs"
        return [logs / "runner.stderr.log", logs / "worker.stderr.log"]
