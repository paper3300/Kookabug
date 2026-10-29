"""runner 검사 하네스: 테스트 프로세스 안의 **실제 `Supervisor`**(`kookabug_core.supervisor`)가
감독자 역할을 한다 (구현 계획 M0b T9 하네스를 T10에서 `Supervisor`로 바꿔 끼웠다).

    h = RunnerHarness.make(tmp_path, graph)          # 워크스페이스·그래프
    h.start(spawned)                                  # Supervisor.start: 실행 폴더·Job·runner·hello
    h.cancel()                                        # run.cancel (+ 하드 종료 타이머)
    done = h.finish()                                 # runner 종료 → 복구 경로(recover)

감독자 규칙(하드 종료 타이머·채널 상실·복구 경로)은 `Supervisor`의 것 그대로다. 하네스는 runner를
런처 없이 띄우고(`python_cmd`, `Popen.pid`가 runner) 정리 픽스처에 등록하는 것만 더한다.

감독자 사망 검사는 별도의 "감독자 역할" 프로세스(`dummy_supervisor=True`)를 띄워 그 식별을 사양에
넣고, `kill_supervisor()`가 그것을 끝내며 감독자의 Job 핸들도 닫는다(`RunHandle.abandon`, 감독자가
죽으면 그 핸들이 닫히는 것과 같다). 이때 하네스는 하드 종료도 복구도 하지 않는다. 실제 감독자
프로세스를 죽이는 검사는 `tests/supervisor/test_supervisor_death.py`(`procs/supervisor_host.py`).
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from helpers.graphs import GraphBuilder, make_workspace
from helpers.worker import PLUGIN_MODULES, worker_env
from kb_testing.proc import Spawned, direct_env, python_cmd, read_fake_input_log, wait_until
from kookabug_core.inputs.lease import LEASE_NAME_ENV, STATE_DIR_ENV, read_lease_file
from kookabug_core.record import RunView, read_run, read_run_json
from kookabug_core.record.runfolder import RunFolder
from kookabug_core.recovery import RecoverResult
from kookabug_core.runner.control import ControlState
from kookabug_core.runner.spec import PlatformSpec
from kookabug_core.supervisor import RunHandle, StartOptions, Supervisor
from kookabug_core.win import CHILD_FLAGS, Job, Process, ProcessId, identify
from kookabug_core.workspace import Workspace
from kookabug_sdk.rpc import RpcPeer

__all__ = ["RUNNER_CMD", "TEST", "Done", "RunnerHarness", "events_of", "step_of"]

TEST: Final = "tests/t.graph.json"
RUNNER_CMD: Final = python_cmd("-m", "kookabug_core.runner")
"""런처 없이 runner를 띄우는 명령 (환경은 `direct_env()`)."""


@dataclass
class Done:
    """runner가 끝나고 복구 경로까지 돈 결과."""

    exit_code: int | None
    recovered: RecoverResult | None
    view: RunView
    run_json: dict[str, Any] | None

    @property
    def run_end(self) -> dict[str, Any] | None:
        return self.view.run_end

    def of(self, kind: str) -> list[dict[str, Any]]:
        return events_of(self.view.events, kind)


def events_of(events: Sequence[Mapping[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [dict(e) for e in events if e.get("event") == kind]


def step_of(events: Sequence[Mapping[str, Any]], node: str) -> tuple[dict[str, Any], Any]:
    """노드의 (`step.start`, `step.end` 또는 None)."""
    (start,) = [e for e in events if e.get("event") == "step.start" and e.get("node") == node]
    ends = [e for e in events if e.get("event") == "step.end" and e.get("step") == start["step"]]
    return dict(start), (dict(ends[0]) if ends else None)


@dataclass
class RunnerHarness:
    tmp_path: Path
    ws: Workspace
    graph: str = TEST
    faults: Sequence[Mapping[str, Any]] = ()
    plugin_modules: Sequence[str] = PLUGIN_MODULES
    frames: Sequence[str] = ()
    hooks: Mapping[str, Mapping[str, str]] = field(default_factory=dict[str, Mapping[str, str]])
    fake_input: bool = True
    deadline_ms: int = 60_000
    shutdown_grace_ms: int = 3_000
    self_kill_margin_ms: int = 10_000
    worker_cancel_grace_ms: int = 1_000
    worker_start_timeout_ms: int = 30_000
    hard_stop: bool = True
    """감독자 하드 종료 타이머를 쓴다 (False: 감독자가 runner를 끝내지 않는다)."""
    dummy_supervisor: bool = False
    env_extra: Mapping[str, str] = field(default_factory=dict[str, str])
    settings: Mapping[str, Any] = field(default_factory=dict[str, Any])
    profile: str | None = None
    lease_name: str | None = None
    state_dir: Path | None = None

    # 실행 중 상태
    handle: RunHandle | None = None
    supervisor_proc: subprocess.Popen[bytes] | None = None
    lease_env: dict[str, str] = field(default_factory=dict[str, str])
    messages: list[tuple[str, dict[str, Any]]] = field(
        default_factory=list[tuple[str, dict[str, Any]]]
    )
    """제어 채널에서 주고받은 메시지 (감독자 기준 `send`·`recv`)."""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def make(
        cls,
        tmp_path: Path,
        graph: GraphBuilder | None = None,
        *,
        ws_settings: Mapping[str, Any] | None = None,
        **kw: Any,
    ) -> RunnerHarness:
        ws = make_workspace(tmp_path / "ws", settings=ws_settings)
        if graph is not None:
            graph.write(ws, kw.get("graph", TEST))
        return cls(tmp_path=tmp_path, ws=ws, **kw)

    # ------------------------------------------------------------ 감독자 상태

    @property
    def _h(self) -> RunHandle:
        assert self.handle is not None, "start() 전이다"
        return self.handle

    @property
    def folder(self) -> RunFolder | None:
        return None if self.handle is None else self.handle.folder

    @property
    def job(self) -> Job | None:
        return None if self.handle is None else self.handle.job

    @property
    def runner(self) -> Process | None:
        return None if self.handle is None else self.handle.runner

    @property
    def runner_ident(self) -> ProcessId | None:
        return None if self.handle is None else self.handle.runner_ident

    @property
    def peer(self) -> RpcPeer | None:
        return None if self.handle is None else self.handle.peer

    @property
    def stopping(self) -> list[str]:
        return [] if self.handle is None else self.handle.stopping

    @property
    def hard_stopped(self) -> bool:
        return self.handle is not None and self.handle.hard_stopped

    @property
    def channel_lost(self) -> bool:
        return self.handle is not None and self.handle.channel_lost

    # ------------------------------------------------------------ 경로·환경

    @property
    def run_dir(self) -> Path:
        assert self.folder is not None
        return self.folder.path

    @property
    def input_log(self) -> Path:
        return self.tmp_path / "input.jsonl"

    def frame(self, name: str) -> str:
        """`frames/<이름>.png` 가짜 프레임 파일을 만들고 절대 경로를 돌려준다."""
        path = self.tmp_path / "frames" / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG fake")
        return str(path)

    def env(self) -> dict[str, str]:
        extra = dict(self.env_extra)
        env = worker_env(self.tmp_path, list(self.faults) or None, **extra)
        if self.lease_name is not None:
            env[LEASE_NAME_ENV] = self.lease_name
        if self.state_dir is not None:
            env[STATE_DIR_ENV] = str(self.state_dir)
        return direct_env(env)

    def platform(self) -> PlatformSpec:
        if not self.fake_input and not self.frames:
            return PlatformSpec("none")
        return PlatformSpec(
            "fake",
            frames=tuple(self.frames),
            input_log=str(self.input_log) if self.fake_input else None,
            hooks=self.hooks,
        )

    def options(self) -> StartOptions:
        return StartOptions(
            deadline_ms=self.deadline_ms,
            profile=self.profile,
            settings=dict(self.settings),
            plugin_modules=tuple(self.plugin_modules),
            platform=self.platform(),
            runs_dir=self.tmp_path / "runs",
            worker_cancel_grace_ms=self.worker_cancel_grace_ms,
            worker_start_timeout_ms=self.worker_start_timeout_ms,
            shutdown_grace_ms=self.shutdown_grace_ms,
            self_kill_margin_ms=self.self_kill_margin_ms,
        )

    # ------------------------------------------------------------ 시작

    def start(self, spawned: Spawned) -> RunnerHarness:
        env = self.env()
        self.lease_env = env
        supervisor: ProcessId | None = None
        if self.dummy_supervisor:
            self.supervisor_proc = spawned.popen(
                python_cmd("-c", "import time; time.sleep(600)"),
                env=env,
                creationflags=CHILD_FLAGS,
            )
            supervisor = identify(self.supervisor_proc.pid)
            assert supervisor is not None
        self.handle = Supervisor(
            runner_cmd=RUNNER_CMD,
            env=env,
            supervisor=supervisor,
            hard_stop=self.hard_stop,
            trace=self._trace,
        ).start(self.ws.root, self.graph, self.options())
        if self.handle.launcher is not None:
            spawned.track(self.handle.launcher)
        if self.handle.start_error is not None:
            error = self.handle.start_error
            raise AssertionError(f"runner가 시작하지 못했다: {error}\n{self.stderr()}")
        # 하네스는 런처 없이 띄우므로 띄운 프로세스가 runner다
        assert self.handle.launcher is not None and self.runner is not None
        assert self.runner.pid == self.handle.launcher.pid
        return self

    def _trace(self, direction: str, body: bytes) -> None:
        with self._lock:
            self.messages.append((direction, json.loads(body)))

    # ------------------------------------------------------------ 제어

    def cancel(self) -> ControlState | None:
        return self._h.cancel()

    def pause(self) -> ControlState:
        return self._h.pause()

    def resume(self) -> ControlState:
        return self._h.resume()

    def hard_stop_now(self) -> None:
        """`TerminateProcess(runner, 4)` (살아 있을 때만)."""
        self._h.hard_stop()

    def close_channel(self) -> None:
        """감독자가 살아 있는 채로 제어 채널만 닫는다 (이것으로 하드 종료하지 않는다)."""
        self._h.close_control()

    def kill_supervisor(self) -> None:
        """감독자 역할 프로세스를 끝내고, 감독자가 쥐던 Job 핸들도 닫는다. 그 뒤 하네스는 감독자가
        아니다(하드 종료·복구 없음)."""
        assert self.supervisor_proc is not None, "dummy_supervisor=True로 띄운다"
        self.hard_stop = False
        self._h.abandon()
        self.supervisor_proc.kill()
        self.supervisor_proc.wait(10)

    def kill_runner(self) -> None:
        assert self.runner is not None
        self.runner.terminate(1)

    # ------------------------------------------------------------ 끝

    def wait(self, timeout: float = 30.0) -> int:
        try:
            code = self._h.wait_exit(timeout)
        except TimeoutError:
            detail = self.stderr()
            raise AssertionError(f"runner가 {timeout}초 안에 끝나지 않았다\n{detail}") from None
        assert code is not None
        return code

    def recover(self) -> RecoverResult:
        return self._h.recover()

    def finish(self, timeout: float = 30.0, *, recover_record: bool = True) -> Done:
        """runner 종료를 기다리고 (감독자면) 복구 경로를 부른다."""
        code = self.wait(timeout)
        recovered = self.recover() if recover_record else None
        self._h.close()
        return Done(code, recovered, read_run(self.run_dir), self.run_json())

    def job_pids(self) -> list[int]:
        assert self.job is not None
        return self.job.process_ids()

    # ------------------------------------------------------------ 보기

    def view(self) -> RunView:
        return read_run(self.run_dir)

    def events(self) -> list[dict[str, Any]]:
        return self.view().events

    def has_event(self, kind: str, **match: Any) -> bool:
        return any(
            e.get("event") == kind and all(e.get(k) == v for k, v in match.items())
            for e in self.events()
        )

    def wait_event(self, kind: str, timeout: float = 30.0, **match: Any) -> None:
        wait_until(
            lambda: self.has_event(kind, **match),
            timeout=timeout,
            message=lambda: f"{kind} {match} 없음\n{self.stderr()}",
        )

    def wait_log(self, message: str, timeout: float = 30.0) -> None:
        self.wait_event("log", timeout, message=message)

    def run_json(self) -> dict[str, Any] | None:
        return read_run_json(self.run_dir / "run.json")

    def fake_inputs(self) -> list[dict[str, Any]]:
        return read_fake_input_log(self.input_log)

    def lease_file(self) -> dict[str, Any] | None:
        return read_lease_file(self.lease_env[STATE_DIR_ENV])

    def stderr(self) -> str:
        if self.folder is None:
            return ""
        parts = []
        for name in ("runner.stderr.log", "worker.stderr.log"):
            path = self.folder.logs / name
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    parts.append(f"--- {name}\n{text[-4000:]}")
        return "\n".join(parts)
