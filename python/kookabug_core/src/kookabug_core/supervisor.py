"""감독자 (구현 계획 M0b 2.7): runner를 띄우고 제어하고, runner가 끝나면 복구 경로를 부른다.

    handle = Supervisor().start(workspace_root, "tests/a.graph.json", StartOptions(...))
    handle.cancel()                    # 취소 (+ 하드 종료 타이머)
    outcome = handle.wait()            # runner 종료 → 복구 경로(recover) → 결과

**시작**: 실행 폴더·`run_id` → 이름 있는 실행 Job(`KILL_ON_JOB_CLOSE`, 핸들은 감독자가 쥔다) →
제어 리스너 → runner 띄우기(stdin에 `RunSpec`, stdout·stderr는 `logs/` 파일) → `runner.hello`를
기한(`hello_timeout`) 안에 받는다. hello의 runner 식별이 Job 안의 프로세스인지 확인하고 **그
식별로** 프로세스를 연다 — venv 런처를 거쳐 띄웠으면 띄운 프로세스와 runner가 다르다. hello를 기한
안에 못 받으면(붙지 않음·인증 실패·먼저 끝남·형식 오류) 띄운 프로세스와 Job을 끝내고(하드 종료),
`wait()`가 복구 경로로 마무리한다 (`start_error`).

**하드 종료** = `TerminateProcess(runner, 4)` (살아 있을 때만). 다음 때 한다

- 하드 종료 타이머: `cancel()` 또는 runner의 `runner.stopping` 알림을 처음 받은 때부터
  `shutdown_grace_ms`가 지나도 runner가 살아 있으면. 외부 취소 없이 기한 초과·정상 마무리에서 멈춘
  runner도 같은 규칙이다. runner의 자기 종료 감시자(`self_kill_margin_ms` 뒤)는 그 뒤의 안전망이다
- 제어 채널을 잃었을 때(EOF·송신 실패·쓰기 기한 초과) — runner를 더 제어할 수 없으므로 곧바로.
  단 `runner.stopping`을 받은 뒤의 EOF는 runner가 마무리 끝에 채널을 닫은 것일 수 있으므로 하드
  종료 타이머에 맡긴다

**복구 작성자는 감독자 하나다**: `wait()`는 runner가 어떻게 끝났든(정상·하드 종료·kill·크래시)
`recover()`를 부른다 — runner 종료를 식별로 확인한 뒤 잘린 줄 자르기 → 임대권 안의 키 복구 →
`run.end`(없을 때만) → `run.json` → Job 정리. 같은 실행을 다시 `recover()`해도 결과가 같다.
`wait()`·`force_stop()`·`recover()`가 여러 스레드에서 겹쳐도 마무리 구간에는 한 스레드만 들어가고,
나머지는 같은 결과를 받는다. 신호 처리기는 즉시 돌아오는 `hard_stop()`만 부른다.

**시작 기한**은 띄우기 전부터 hello까지 하나다. stdin 사양 쓰기는 따로 스레드에서 하므로 자식이
읽지 않아 막혀도 기한이 지나면 자식을 끝낸다(그러면 쓰기도 풀린다).

고장 주입 역할(`_faults.set_role("supervisor")`)은 감독자 프로세스의 진입점(CLI 등)이 정한다.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from kookabug_core.inputs.lease import LEASE_NAME_ENV, STATE_DIR_ENV
from kookabug_core.record import read_run, read_run_json
from kookabug_core.record.journal import format_t
from kookabug_core.record.runfolder import RunFolder, create_run_folder
from kookabug_core.recovery import RecoverResult, recover, supervisor_backend
from kookabug_core.runner.control import ControlState
from kookabug_core.runner.spec import (
    DEFAULT_SELF_KILL_MARGIN_MS,
    DEFAULT_SHUTDOWN_GRACE_MS,
    DEFAULT_WORKER_CANCEL_GRACE_MS,
    DEFAULT_WORKER_START_TIMEOUT_MS,
    PROTOCOL,
    ControlSpec,
    PlatformSpec,
    RunSpec,
    ident_from_json,
)
from kookabug_core.win import Job, Process, ProcessId, current, run_job_name, spawn
from kookabug_sdk.pipe import PipeConnection, PipeListener, new_key, new_pipe_name
from kookabug_sdk.rpc import INVALID_PARAMS, METHOD_NOT_FOUND, PeerLost, RpcError, RpcPeer

__all__ = [
    "DEFAULT_DEADLINE_MS",
    "HARD_STOP_EXIT_CODE",
    "ControlError",
    "RunHandle",
    "RunOutcome",
    "StartOptions",
    "Supervisor",
]

DEFAULT_DEADLINE_MS: Final = 30 * 60 * 1000
"""실행 전체 기한 기본값 30분 (구현 계획 M0b 2.11)."""
HARD_STOP_EXIT_CODE: Final = 4
HELLO_TIMEOUT_S: Final = 30.0
CONTROL_CALL_TIMEOUT_S: Final = 5.0
LAUNCHER_EXIT_WAIT_S: Final = 5.0
"""runner가 끝난 뒤 띄운 프로세스(venv 런처)가 따라 끝나기를 기다리는 시간."""
_POLL_S: Final = 0.02


class ControlError(Exception):
    """제어 요청(`run.pause`·`run.resume`)의 답을 받지 못했다."""


@dataclass(frozen=True, slots=True)
class StartOptions:
    """실행 하나의 조건 (`RunSpec`에서 감독자가 정하는 값을 뺀 것)."""

    deadline_ms: int = DEFAULT_DEADLINE_MS
    profile: str | None = None
    settings: Mapping[str, Any] = field(default_factory=dict[str, Any])
    plugin_modules: tuple[str, ...] = ()
    platform: PlatformSpec = field(default_factory=PlatformSpec)
    runs_dir: Path | None = None
    """실행 폴더를 만들 곳 (기본: 워크스페이스의 `runs/`)."""
    worker_cancel_grace_ms: int = DEFAULT_WORKER_CANCEL_GRACE_MS
    worker_start_timeout_ms: int = DEFAULT_WORKER_START_TIMEOUT_MS
    shutdown_grace_ms: int = DEFAULT_SHUTDOWN_GRACE_MS
    self_kill_margin_ms: int = DEFAULT_SELF_KILL_MARGIN_MS


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """runner가 끝나고 복구 경로까지 돈 결과."""

    run_id: str
    run_dir: Path
    exit_code: int | None
    """runner 종료 코드 (모르면 None). `0` 정상 마무리, `4` 하드 종료·자기 종료."""
    hard_stopped: bool
    channel_lost: bool
    start_error: str | None
    recovered: RecoverResult | None
    recover_error: str | None
    """복구 경로의 기록 오류 (Job은 이미 정리됐다)."""
    run_end: dict[str, Any] | None
    run_json: dict[str, Any] | None

    @property
    def verdict(self) -> str | None:
        return None if self.run_end is None else self.run_end.get("verdict")


class Supervisor:
    """runner를 띄우는 방법(명령·환경). 실행마다 `start()`가 `RunHandle`을 준다.

    `runner_cmd` 기본값은 `sys.executable -m kookabug_core.runner`(M0b 공유 환경). `env`가 None이면
    이 프로세스의 환경을 물려준다. 입력 임대권 이름·상태 폴더는 runner와 같은 환경 값으로 복구한다.

    검사용: `supervisor`는 runner에 알릴 감독자 식별(기본: 이 프로세스), `hard_stop=False`는 하드
    종료를 하지 않는 감독자(runner 자기 종료 감시자 검사), `trace`는 제어 채널 메시지 훅.
    """

    def __init__(
        self,
        *,
        runner_cmd: Sequence[str | os.PathLike[str]] | None = None,
        env: Mapping[str, str] | None = None,
        hello_timeout: float = HELLO_TIMEOUT_S,
        supervisor: ProcessId | None = None,
        hard_stop: bool = True,
        trace: Callable[[str, bytes], None] | None = None,
    ) -> None:
        self.runner_cmd = [
            str(a) for a in (runner_cmd or (sys.executable, "-m", "kookabug_core.runner"))
        ]
        self.env = None if env is None else dict(env)
        self.hello_timeout = hello_timeout
        self.supervisor = supervisor
        self.hard_stop = hard_stop
        self.trace = trace

    def start(
        self,
        workspace_root: str | os.PathLike[str],
        graph: str,
        options: StartOptions | None = None,
    ) -> RunHandle:
        """실행을 시작한다. runner가 hello를 하지 못해도 예외 대신 `start_error`가 있는 핸들을
        준다(이미 하드 종료했고 `wait()`가 기록을 마무리한다). 실행 폴더·Job을 못 만들면 예외."""
        opts = options or StartOptions()
        root = Path(workspace_root).resolve()
        folder = create_run_folder(opts.runs_dir or root / "runs", graph)
        started_at = format_t(datetime.now(UTC))
        job = Job.create(run_job_name(folder.run_id))
        try:
            listener = PipeListener(new_pipe_name("control"))
        except BaseException:
            job.close()
            raise
        key = new_key()
        spec = RunSpec(
            run_id=folder.run_id,
            run_dir=folder.path,
            workspace_root=root,
            graph=graph,
            control=ControlSpec(listener.name, key),
            job_name=run_job_name(folder.run_id),
            supervisor=self.supervisor or current(),
            deadline_ms=opts.deadline_ms,
            profile=opts.profile,
            settings=dict(opts.settings),
            plugin_modules=tuple(opts.plugin_modules),
            platform=opts.platform,
            worker_cancel_grace_ms=opts.worker_cancel_grace_ms,
            worker_start_timeout_ms=opts.worker_start_timeout_ms,
            shutdown_grace_ms=opts.shutdown_grace_ms,
            self_kill_margin_ms=opts.self_kill_margin_ms,
        )
        handle = RunHandle(self, spec, folder, job, started_at)
        handle._launch(listener, key)
        return handle


class RunHandle:
    """실행 하나. 제어(`cancel`·`pause`·`resume`·`force_stop`)와 끝 기다리기(`wait`)."""

    def __init__(
        self, owner: Supervisor, spec: RunSpec, folder: RunFolder, job: Job, started_at: str
    ) -> None:
        self.spec = spec
        self.folder = folder
        self.job: Job | None = job
        self.started_at = started_at
        self.launcher: subprocess.Popen[bytes] | None = None
        """띄운 프로세스 (venv 런처면 runner의 부모)."""
        self.runner: Process | None = None
        """hello로 받은 runner (종료 권한). hello 전에 실패했으면 띄운 프로세스."""
        self.peer: RpcPeer | None = None
        self.stopping: list[str] = []
        """받은 `runner.stopping`의 사유."""
        self.hard_stopped = False
        self.channel_lost = False
        self.start_error: str | None = None
        self._env = owner.env
        self._cmd = owner.runner_cmd
        self._hello_timeout = owner.hello_timeout
        self._hard_stop = owner.hard_stop
        self._trace = owner.trace
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._closing = False
        self._spec_writer: threading.Thread | None = None
        self._finish_lock = threading.Lock()
        """복구·Job 정리·결과 게시를 한 주체만 한다 (`wait`·`recover`·`force_stop`이 겹쳐도)."""
        self._finisher: int | None = None
        """지금 마무리 중인 스레드 (같은 스레드의 재진입 — 신호 처리기 — 을 막는다)."""
        self._outcome: RunOutcome | None = None

    @property
    def run_id(self) -> str:
        return self.spec.run_id

    @property
    def run_dir(self) -> Path:
        return self.folder.path

    @property
    def runner_ident(self) -> ProcessId | None:
        return None if self.runner is None else self.runner.ident

    # ------------------------------------------------------------ 시작

    def _launch(self, listener: PipeListener, key: bytes) -> None:
        # 시작 기한 하나: 띄우기 전부터 hello까지. 사양 송신이 막혀도 이 기한이 지나면 끝낸다
        deadline = time.monotonic() + self._hello_timeout
        accepted: queue.Queue[PipeConnection | BaseException] = queue.Queue()

        def accept() -> None:
            try:
                accepted.put(listener.accept(key, timeout=self._hello_timeout))
            except BaseException as exc:
                accepted.put(exc)

        threading.Thread(target=accept, name="supervisor-accept", daemon=True).start()
        logs = self.folder.logs
        try:
            self.launcher = spawn(
                self._cmd,
                stdout=logs / "runner.stdout.log",
                stderr=logs / "runner.stderr.log",
                env=self._env,
                stdin=subprocess.PIPE,
            )
        except BaseException:
            listener.close()
            self._clean_job()
            raise
        # stdin 쓰기에는 기한이 없다(자식이 읽지 않으면 파이프 버퍼가 찬 채 막힌다). 그래서 따로
        # 스레드에서 보내고, 막히면 시작 실패 정리가 자식을 끝내 쓰기를 깨운다
        self._spec_writer = threading.Thread(
            target=_send_spec,
            args=(self.launcher, json.dumps(self.spec.to_json()).encode("utf-8")),
            name="supervisor-spec",
            daemon=True,
        )
        self._spec_writer.start()
        try:
            conn = self._wait_connected(accepted, deadline)
            self.peer = RpcPeer(conn, name="supervisor-control", trace=self._trace).start()
            self.runner = self._wait_hello(self.peer, deadline)
        except _StartFailed as exc:
            listener.close()
            self.start_error = str(exc)
            self._fail_start()
            return
        threading.Thread(target=self._dispatch, name="supervisor-dispatch", daemon=True).start()

    def _wait_connected(
        self, accepted: queue.Queue[PipeConnection | BaseException], deadline: float
    ) -> PipeConnection:
        assert self.launcher is not None
        while True:
            try:
                result = accepted.get(timeout=_POLL_S)
            except queue.Empty:
                code = self.launcher.poll()
                if code is not None:
                    raise _StartFailed(
                        f"runner가 제어 채널에 붙기 전에 끝났다 (종료 코드 {code})"
                    ) from None
                if time.monotonic() >= deadline:
                    raise _StartFailed("runner가 기한 안에 제어 채널에 붙지 않았다") from None
                continue
            if isinstance(result, BaseException):
                raise _StartFailed(f"제어 채널 연결 실패: {result}") from result
            return result

    def _wait_hello(self, peer: RpcPeer, deadline: float) -> Process:
        try:
            item = peer.incoming.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            raise _StartFailed("runner가 기한 안에 runner.hello를 보내지 않았다") from None
        if isinstance(item, PeerLost):
            raise _StartFailed(f"runner.hello 전에 제어 채널을 잃었다: {item}")
        if item.method != "runner.hello" or item.is_notification:
            raise _StartFailed(f"runner.hello가 아니다: {item.method}")
        problem = self._check_hello(item.params)
        if problem is None:
            try:
                runner = Process.open(ident_from_json(item.params["runner"]), terminate=True)
            except (ProcessLookupError, OSError) as exc:
                problem = f"hello의 runner 프로세스를 열 수 없다: {exc}"
            else:
                with contextlib.suppress(PeerLost):
                    peer.respond(item, {})
                return runner
        with contextlib.suppress(PeerLost):
            peer.respond_error(item, INVALID_PARAMS, problem)
        raise _StartFailed(problem)

    def _check_hello(self, params: Mapping[str, Any]) -> str | None:
        if params.get("protocol") != PROTOCOL:
            return f"제어 프로토콜이 다르다: {params.get('protocol')!r} (감독자 {PROTOCOL})"
        if params.get("run_id") != self.run_id:
            return f"run_id가 다르다: {params.get('run_id')!r}"
        try:
            ident = ident_from_json(params["runner"])
        except KeyError, TypeError, ValueError:
            return "runner 식별이 없다"
        # runner는 hello 전에 실행 Job에 자기를 넣는다. 아니면 이 실행의 runner가 아니다
        assert self.job is not None
        try:
            inside = self.job.contains(ident.pid)
        except OSError:
            inside = False
        return None if inside else f"runner(PID {ident.pid})가 실행 Job 안에 없다"

    def _fail_start(self) -> None:
        """hello 전 실패: 띄운 프로세스와 Job 안의 프로세스를 끝낸다 (Job 핸들은 복구 경로가
        닫는다)."""
        self._closing = True
        if self.peer is not None:
            self.peer.close()
        assert self.launcher is not None
        try:
            self.runner = Process.open(self.launcher.pid, terminate=True)
        except ProcessLookupError:
            self.runner = None
        # 시작하지 못한 runner는 감독자 설정(`hard_stop`)과 무관하게 끝낸다
        if self.runner is not None and self.runner.alive():
            self.hard_stopped = True
            with contextlib.suppress(OSError):
                self.runner.terminate(HARD_STOP_EXIT_CODE)
        if self.job is not None:
            with contextlib.suppress(OSError):
                self.job.terminate(HARD_STOP_EXIT_CODE)
        # TerminateProcess는 끝내기를 요청만 한다. 핸들을 돌려주기 전에 실제로 끝나기를 기다린다
        if self.runner is not None:
            with contextlib.suppress(OSError):
                self.runner.wait(LAUNCHER_EXIT_WAIT_S)
        # 자식이 끝나면 막혀 있던 사양 쓰기도 실패로 풀린다
        if self._spec_writer is not None:
            self._spec_writer.join(LAUNCHER_EXIT_WAIT_S)

    # ------------------------------------------------------------ 제어 채널

    def _dispatch(self) -> None:
        peer = self.peer
        assert peer is not None
        while True:
            item = peer.incoming.get()
            if isinstance(item, PeerLost):
                with self._lock:
                    self.channel_lost = True
                    after_stopping = bool(self.stopping)
                if not self._closing and not after_stopping:
                    self.hard_stop()  # 더 제어할 수 없다: 곧바로 하드 종료
                return
            if item.method == "runner.stopping":
                with self._lock:
                    self.stopping.append(str(item.params.get("reason")))
                self._arm()
            elif not item.is_notification:
                with contextlib.suppress(PeerLost):
                    peer.respond_error(item, METHOD_NOT_FOUND, f"모르는 메서드 {item.method}")

    def _call(self, method: str) -> ControlState:
        peer = self.peer
        if peer is None:
            raise ControlError("제어 채널이 없다 (runner가 시작하지 못했다)")
        try:
            reply = peer.call(method, timeout=CONTROL_CALL_TIMEOUT_S)
        except (PeerLost, TimeoutError, RpcError) as exc:
            raise ControlError(f"{method}: {exc}") from exc
        return reply["state"]

    def cancel(self) -> ControlState | None:
        """취소를 요청하고 하드 종료 타이머를 건다. runner의 답(상태)을 주고, 답을 못 받으면
        None (그래도 타이머·채널 상실 규칙이 runner를 끝낸다)."""
        self._arm()
        try:
            return self._call("run.cancel")
        except ControlError:
            return None

    def pause(self) -> ControlState:
        return self._call("run.pause")

    def resume(self) -> ControlState:
        return self._call("run.resume")

    def _arm(self) -> None:
        if not self._hard_stop:
            return
        with self._lock:
            if self._timer is not None:
                return
            self._timer = threading.Timer(self.spec.shutdown_grace_ms / 1000, self.hard_stop)
            self._timer.daemon = True
            self._timer.start()

    def _disarm(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()

    def hard_stop(self) -> None:
        """`TerminateProcess(runner, 4)` (살아 있을 때만). 기다리지 않고 바로 돌아온다 — 신호
        처리기(Ctrl+C)는 이것만 부른다."""
        if not self._hard_stop:
            return
        runner = self.runner
        if runner is not None and runner.alive():
            self.hard_stopped = True
            with contextlib.suppress(OSError):
                runner.terminate(HARD_STOP_EXIT_CODE)

    def force_stop(self, timeout: float | None = None) -> RunOutcome:
        """runner를 곧바로 끝내고(`hard_stop`, 즉시) 마무리 결과를 기다린다(`wait`). 다른 스레드가
        이미 마무리 중이면 그 결과를 같이 받는다."""
        self.hard_stop()
        return self.wait(timeout)

    def close_control(self) -> None:
        """제어 채널을 감독자 쪽에서 일부러 닫는다 (하드 종료하지 않는다 — 검사용)."""
        self._closing = True
        if self.peer is not None:
            self.peer.close()

    def abandon(self) -> None:
        """감독자가 이 실행을 놓는다 (감독자 사망 흉내 — 검사용): 하드 종료·타이머를 끄고 Job
        핸들을 닫는다. 그 뒤 복구는 하지 않는다."""
        self._hard_stop = False
        self._disarm()
        if self.job is not None:
            self.job.close()
            self.job = None

    # ------------------------------------------------------------ 끝

    def wait_exit(self, timeout: float | None = None) -> int | None:
        """runner 종료를 기다려 종료 코드를 준다. 기한을 넘기면 `TimeoutError`."""
        runner = self.runner
        if runner is None:
            return None
        code = runner.wait(timeout)
        if code is None:
            raise TimeoutError(f"runner(PID {runner.pid})가 {timeout}초 안에 끝나지 않았다")
        self._disarm()
        return code

    @contextlib.contextmanager
    def _finishing(self) -> Iterator[None]:
        """마무리 구간: 한 번에 한 스레드만 들어간다. 같은 스레드가 마무리 중에 다시 들어오면
        (신호 처리기에서 `wait`·`force_stop`·`recover`) 두 번째 작성자가 되므로 거부한다."""
        me = threading.get_ident()
        if self._finisher == me:
            raise RuntimeError(
                "이 스레드가 이미 실행을 마무리하는 중이다 (신호 처리기에서는 hard_stop()만 부른다)"
            )
        with self._finish_lock:
            self._finisher = me
            try:
                yield
            finally:
                self._finisher = None

    def recover(self) -> RecoverResult:
        """복구 경로 (`kookabug_core.recovery.recover`). runner 종료를 확인한 뒤에만 쓴다.
        여러 번 불러도 결과가 같고, 여러 스레드가 겹쳐 불러도 한 번에 하나만 쓴다. Job 핸들은 첫
        호출이 닫는다."""
        with self._finishing():
            return self._recover()

    def _recover(self) -> RecoverResult:
        if self.runner is None:
            raise RuntimeError("runner 프로세스를 모른다")
        env: Mapping[str, str] = os.environ if self._env is None else self._env
        result = recover(
            self.run_dir,
            self.runner,
            self.job,
            backend=supervisor_backend(self.spec.platform.to_json(), self.run_id),
            seed={"run_id": self.run_id, "graph": self.spec.graph, "started_at": self.started_at},
            lease_name=env.get(LEASE_NAME_ENV),
            lease_dir=env.get(STATE_DIR_ENV),
        )
        self.job = None
        return result

    def wait(self, timeout: float | None = None) -> RunOutcome:
        """runner 종료 → 복구 경로 → 결과. 마무리는 처음 들어온 한 스레드만 하고, 겹쳐 부른
        나머지와 이후 호출은 같은 결과 객체를 받는다."""
        outcome = self._outcome
        if outcome is not None:
            return outcome
        exit_code = self.wait_exit(timeout)  # 여러 스레드가 같이 기다려도 된다 (쓰지 않는다)
        with self._finishing():
            if self._outcome is None:
                self._outcome = self._finish(exit_code)
            return self._outcome

    def _finish(self, exit_code: int | None) -> RunOutcome:
        recovered: RecoverResult | None = None
        recover_error: str | None = None
        if self.runner is not None:
            try:
                recovered = self._recover()
            except Exception as exc:  # 기록 오류: Job은 이미 정리됐다. 결과로만 알린다
                recover_error = f"{type(exc).__name__}: {exc}"
        else:
            self._clean_job()
        self.close()
        view = read_run(self.run_dir)
        return RunOutcome(
            run_id=self.run_id,
            run_dir=self.run_dir,
            exit_code=exit_code,
            hard_stopped=self.hard_stopped,
            channel_lost=self.channel_lost,
            start_error=self.start_error,
            recovered=recovered,
            recover_error=recover_error,
            run_end=view.run_end,
            run_json=read_run_json(self.folder.run_json),
        )

    def close(self) -> None:
        """제어 채널을 닫고 띄운 프로세스(런처)가 끝나기를 잠깐 기다린다."""
        self._closing = True
        self._disarm()
        if self.peer is not None:
            self.peer.close()
        if self.launcher is not None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.launcher.wait(LAUNCHER_EXIT_WAIT_S)

    def _clean_job(self) -> None:
        if self.job is not None:
            with contextlib.suppress(OSError):
                self.job.terminate(1)
            self.job.close()
            self.job = None


class _StartFailed(Exception):
    pass


def _send_spec(launcher: subprocess.Popen[bytes], data: bytes) -> None:
    """실행 사양을 runner의 stdin에 쓰고 닫는다. 자식이 먼저 끝나 쓰기가 실패하면 버린다 (hello
    대기가 판정한다)."""
    stdin = launcher.stdin
    assert stdin is not None
    with contextlib.suppress(OSError, ValueError):
        stdin.write(data)
    with contextlib.suppress(OSError, ValueError):
        stdin.close()
