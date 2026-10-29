"""runner 검사 하네스: 테스트 프로세스가 **감독자 역할**을 한다 (구현 계획 M0b T9, T10이
`Supervisor`로 바꿔 끼운다).

    h = RunnerHarness.make(tmp_path, graph)          # 워크스페이스·그래프·실행 폴더
    h.start(spawned)                                  # Job·제어 리스너·runner 띄우기·runner.hello
    h.cancel()                                        # run.cancel (+ 하드 종료 타이머)
    done = h.finish()                                 # runner 종료 → 복구 경로(recover)

감독자 규칙 (2.7): 실행 Job을 만들고 핸들을 쥔다. runner의 stdin에 `RunSpec`을 준다. `cancel()`
또는 runner의 `runner.stopping` 알림을 처음 받은 때부터 `shutdown_grace_ms`가 지나도 runner가 살아
있으면 `TerminateProcess(runner, 4)`(하드 종료 타이머). 제어 채널을 잃으면 곧바로 하드 종료.
runner가 끝나면 복구 경로(`recover`)를 부른다.

감독자 사망 검사는 별도의 "감독자 역할" 프로세스(`dummy_supervisor=True`)를 띄워 그 식별을 사양에
넣고, `kill_supervisor()`가 그것을 끝내며 하네스의 Job 핸들도 닫는다(감독자가 죽으면 그 핸들이
닫히는 것과 같다). 이때 하네스는 하드 종료도 복구도 하지 않는다.
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
from kookabug_core.record import RunView, create_run_folder, read_run, read_run_json
from kookabug_core.record.runfolder import RunFolder
from kookabug_core.recovery import RecoverResult, recover, supervisor_backend
from kookabug_core.runner.spec import (
    ControlSpec,
    PlatformSpec,
    RunSpec,
    ident_from_json,
)
from kookabug_core.win import CHILD_FLAGS, Job, Process, ProcessId, current, identify, run_job_name
from kookabug_core.workspace import Workspace
from kookabug_sdk.pipe import PipeConnection, PipeListener, new_key, new_pipe_name
from kookabug_sdk.rpc import Incoming, PeerLost, RpcPeer

__all__ = ["TEST", "Done", "RunnerHarness", "events_of", "step_of"]

TEST: Final = "tests/t.graph.json"
HARD_STOP_EXIT: Final = 4
HELLO_TIMEOUT_S: Final = 30.0
CONTROL_CALL_TIMEOUT_S: Final = 5.0


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
    """감독자 하드 종료 타이머를 쓴다 (False: 하네스가 runner를 끝내지 않는다)."""
    dummy_supervisor: bool = False
    env_extra: Mapping[str, str] = field(default_factory=dict[str, str])
    settings: Mapping[str, Any] = field(default_factory=dict[str, Any])
    profile: str | None = None
    lease_name: str | None = None
    state_dir: Path | None = None

    # 실행 중 상태
    folder: RunFolder | None = None
    job: Job | None = None
    proc: subprocess.Popen[bytes] | None = None
    runner: Process | None = None
    runner_ident: ProcessId | None = None
    supervisor_proc: subprocess.Popen[bytes] | None = None
    peer: RpcPeer | None = None
    stopping: list[str] = field(default_factory=list[str])
    hard_stopped: bool = False
    channel_lost: bool = False
    lease_env: dict[str, str] = field(default_factory=dict[str, str])
    messages: list[tuple[str, dict[str, Any]]] = field(
        default_factory=list[tuple[str, dict[str, Any]]]
    )
    """제어 채널에서 주고받은 메시지 (하네스 기준 `send`·`recv`)."""
    _timer: threading.Timer | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _closing_channel: bool = False

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

    # ------------------------------------------------------------ 시작

    def start(self, spawned: Spawned, *, wait_hello: bool = True) -> RunnerHarness:
        self.folder = create_run_folder(self.tmp_path / "runs", self.graph)
        self.job = Job.create(run_job_name(self.folder.run_id))
        env = self.env()
        self.lease_env = env
        supervisor = current()
        if self.dummy_supervisor:
            self.supervisor_proc = spawned.popen(
                python_cmd("-c", "import time; time.sleep(600)"),
                env=env,
                creationflags=CHILD_FLAGS,
            )
            ident = identify(self.supervisor_proc.pid)
            assert ident is not None
            supervisor = ident
        key = new_key()
        listener = PipeListener(new_pipe_name("control"))
        spec = RunSpec(
            run_id=self.folder.run_id,
            run_dir=self.folder.path,
            workspace_root=self.ws.root,
            graph=self.graph,
            control=ControlSpec(listener.name, key),
            job_name=run_job_name(self.folder.run_id),
            supervisor=supervisor,
            deadline_ms=self.deadline_ms,
            profile=self.profile,
            settings=dict(self.settings),
            plugin_modules=tuple(self.plugin_modules),
            platform=self.platform(),
            worker_cancel_grace_ms=self.worker_cancel_grace_ms,
            worker_start_timeout_ms=self.worker_start_timeout_ms,
            shutdown_grace_ms=self.shutdown_grace_ms,
            self_kill_margin_ms=self.self_kill_margin_ms,
        )
        accepted: list[PipeConnection | BaseException] = []
        accept = threading.Thread(
            target=lambda: accepted.append(_accept(listener, key)), daemon=True
        )
        accept.start()
        logs = self.folder.logs
        with (
            (logs / "runner.stdout.log").open("ab") as out,
            (logs / "runner.stderr.log").open("ab") as err,
        ):
            self.proc = spawned.popen(
                python_cmd("-m", "kookabug_core.runner"),
                stdin=subprocess.PIPE,
                stdout=out,
                stderr=err,
                env=env,
                creationflags=CHILD_FLAGS,
            )
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(spec.to_json()).encode("utf-8"))
        self.proc.stdin.close()
        self.runner = Process.open(self.proc.pid, terminate=True)
        accept.join(HELLO_TIMEOUT_S)
        result = accepted[0] if accepted else None
        if not isinstance(result, PipeConnection):
            raise AssertionError(f"runner가 제어 채널에 붙지 않았다: {result!r}\n{self.stderr()}")
        self.peer = RpcPeer(result, name="harness-control", trace=self._trace).start()
        if wait_hello:
            self.wait_hello()
        return self

    def _trace(self, direction: str, body: bytes) -> None:
        with self._lock:
            self.messages.append((direction, json.loads(body)))

    def wait_hello(self) -> ProcessId:
        assert self.peer is not None
        item = self.peer.incoming.get(timeout=HELLO_TIMEOUT_S)
        assert isinstance(item, Incoming) and item.method == "runner.hello", item
        self.runner_ident = ident_from_json(item.params["runner"])
        assert self.runner is not None and self.runner_ident == self.runner.ident
        self.peer.respond(item, {})
        threading.Thread(target=self._dispatch, name="harness-dispatch", daemon=True).start()
        return self.runner_ident

    def _dispatch(self) -> None:
        peer = self.peer
        assert peer is not None
        while True:
            item = peer.incoming.get()
            if isinstance(item, PeerLost):
                self.channel_lost = True
                if not self._closing_channel and self.hard_stop:
                    self.hard_stop_now()  # 제어 채널을 잃은 감독자: 곧바로 하드 종료
                return
            if item.method == "runner.stopping":
                self.stopping.append(item.params["reason"])
                self._arm()

    # ------------------------------------------------------------ 제어

    def _call(self, method: str) -> str:
        assert self.peer is not None
        reply = self.peer.call(method, timeout=CONTROL_CALL_TIMEOUT_S)
        return reply["state"]

    def cancel(self) -> str:
        self._arm()
        return self._call("run.cancel")

    def pause(self) -> str:
        return self._call("run.pause")

    def resume(self) -> str:
        return self._call("run.resume")

    def _arm(self) -> None:
        if not self.hard_stop:
            return
        with self._lock:
            if self._timer is not None:
                return
            self._timer = threading.Timer(self.shutdown_grace_ms / 1000, self.hard_stop_now)
            self._timer.daemon = True
            self._timer.start()

    def hard_stop_now(self) -> None:
        """`TerminateProcess(runner, 4)` (살아 있을 때만)."""
        runner = self.runner
        if runner is not None and runner.alive():
            self.hard_stopped = True
            runner.terminate(HARD_STOP_EXIT)

    def close_channel(self) -> None:
        """감독자가 살아 있는 채로 제어 채널만 닫는다 (하네스는 이것으로 하드 종료하지 않는다)."""
        assert self.peer is not None
        self._closing_channel = True
        self.peer.close()

    def kill_supervisor(self) -> None:
        """감독자 역할 프로세스를 끝내고, 감독자가 쥐던 Job 핸들도 닫는다. 그 뒤 하네스는 감독자가
        아니다(하드 종료·복구 없음)."""
        assert self.supervisor_proc is not None, "dummy_supervisor=True로 띄운다"
        self.hard_stop = False
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
        self.supervisor_proc.kill()
        self.supervisor_proc.wait(10)
        if self.job is not None:
            self.job.close()
            self.job = None

    def kill_runner(self) -> None:
        assert self.runner is not None
        self.runner.terminate(1)

    # ------------------------------------------------------------ 끝

    def wait(self, timeout: float = 30.0) -> int:
        assert self.runner is not None
        code = self.runner.wait(timeout)
        if code is None:
            raise AssertionError(f"runner가 {timeout}초 안에 끝나지 않았다\n{self.stderr()}")
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
        return code

    def recover(self) -> RecoverResult:
        assert self.runner is not None and self.folder is not None
        env = self.lease_env
        return recover(
            self.run_dir,
            self.runner,
            self.job,
            backend=supervisor_backend(self.platform().to_json(), self.folder.run_id),
            seed={"run_id": self.folder.run_id, "graph": self.graph},
            lease_name=env.get(LEASE_NAME_ENV),
            lease_dir=env.get(STATE_DIR_ENV),
        )

    def finish(self, timeout: float = 30.0, *, recover_record: bool = True) -> Done:
        """runner 종료를 기다리고 (감독자면) 복구 경로를 부른다."""
        code = self.wait(timeout)
        recovered = self.recover() if recover_record else None
        self.job = None
        if self.peer is not None:
            self.peer.close()
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


def _accept(listener: PipeListener, key: bytes) -> PipeConnection | BaseException:
    try:
        return listener.accept(key, timeout=HELLO_TIMEOUT_S)
    except BaseException as exc:
        return exc
