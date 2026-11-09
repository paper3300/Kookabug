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
  runner도 같은 규칙이다. runner의 자기 종료 감시자(`self_kill_margin_ms` 뒤)는 그 뒤의 안전망이다.
  `run.cancel`에는 타이머의 기한(절대 단조 시각 `hard_stop_at_mono` + 남은 시간 `hard_stop_in_ms`)을
  실어 runner가 마무리 예산을 그 기한에 맞추게 한다 (타이머는 미루지 않는다)
- **영상 마무리 단계**(R1 F1): runner가 `run.end`를 쓴 뒤 `runner.video_finishing{wait_ms}`을 청하면
  (인코더 준비가 아직이라 실행 중 모은 프레임을 쓰려고) 한 번만 타이머를 지금 + `wait_ms`(최대
  `VIDEO_FINISH_MAX_MS`) + 유예로 다시 걸고 그 기한을 답한다. 외부 취소를 받았거나 이미 하드
  종료했으면 거절한다. 단계 중 외부 취소가 오면 타이머를 지금 + 유예로 당긴다 (판정·`run.end`는
  이미 정해졌다)
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

**DPI 인식**(구현 계획 M1 2.2): 감독자는 프로세스의 DPI 인식 수준을 바꾸지 않는다. 좌표를 쓰는 창·
캡처·입력은 전부 runner가 하고(runner 진입점이 Per-Monitor V2로 정한다), 감독자 복구의 떼기는
좌표가 없다(마우스 버튼은 그 순간 커서 위치에서 뗀다). 감독자는 CLI·서비스 안에서 돌고 검사에서는
pytest 프로세스 안에서도 돌므로, 한 번만 정할 수 있는 프로세스 수준을 여기서 바꾸지 않는다.
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
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from kookabug_core.engine.debug import Breakpoint, ResumeMode
from kookabug_core.inputs.lease import LEASE_NAME_ENV, STATE_DIR_ENV
from kookabug_core.permissions import Decision
from kookabug_core.plugins.runtime import release_markers
from kookabug_core.record import read_run, read_run_json
from kookabug_core.record.journal import format_t
from kookabug_core.record.runfolder import RunFolder, create_run_folder
from kookabug_core.recovery import RecoverResult, recover, supervisor_backend
from kookabug_core.runner.control import NOT_PAUSED, ControlState
from kookabug_core.runner.spec import (
    DEFAULT_CAPTURE_TIMEOUT_MS,
    DEFAULT_FRAME_BUDGET_MIB,
    DEFAULT_FRAME_OUTPUT_REFS,
    DEFAULT_SELF_KILL_MARGIN_MS,
    DEFAULT_SHUTDOWN_GRACE_MS,
    DEFAULT_WORKER_CANCEL_GRACE_MS,
    DEFAULT_WORKER_START_TIMEOUT_MS,
    PROTOCOL,
    VIDEO_FINISH_MAX_MS,
    BoundWindow,
    ControlSpec,
    PlatformSpec,
    RunSpec,
    ident_from_json,
)
from kookabug_core.schema import check_shape
from kookabug_core.win import Job, Process, ProcessId, current, run_job_name, spawn
from kookabug_sdk.pipe import PipeConnection, PipeListener, new_key, new_pipe_name
from kookabug_sdk.rpc import INVALID_PARAMS, METHOD_NOT_FOUND, PeerLost, RpcError, RpcPeer

__all__ = [
    "DEFAULT_DEADLINE_MS",
    "EXIT_ERROR",
    "EXIT_FAIL",
    "EXIT_INVALID",
    "EXIT_PASS",
    "EXIT_SKIPPED",
    "HARD_STOP_EXIT_CODE",
    "ControlError",
    "ResumeRefused",
    "RunHandle",
    "RunOutcome",
    "StartOptions",
    "Supervisor",
    "run_exit_code",
]

DEFAULT_DEADLINE_MS: Final = 30 * 60 * 1000
"""실행 전체 기한 기본값 30분 (구현 계획 M0b 2.11)."""

# 실행 판정 → 종료 코드 (CLI `run`의 종료 코드, daemon `run.ended`의 `exit_code`)
EXIT_PASS: Final = 0
EXIT_FAIL: Final = 1
EXIT_ERROR: Final = 2
"""오류: 취소·기한 초과·runner 죽음·입력 임대권 거부·기록 마무리 실패 포함."""
EXIT_SKIPPED: Final = 3
EXIT_INVALID: Final = 4
"""실행 전 검증 오류 (`run.end` 코드 `graph_invalid`)."""
_VERDICT_EXIT: Final = {
    "pass": EXIT_PASS,
    "fail": EXIT_FAIL,
    "error": EXIT_ERROR,
    "skipped": EXIT_SKIPPED,
}
_INVALID_CODES: Final = frozenset({"graph_invalid"})


def run_exit_code(run_end: Mapping[str, Any] | None, *, recover_error: str | None = None) -> int:
    """`run.end` 판정 → 종료 코드. 감독자가 기록을 마무리하지 못했으면(`recover_error`) 그래프
    판정과 무관하게 오류다 — `run.json`이 `running`으로 남았을 수 있다."""
    if run_end is None or recover_error is not None:
        return EXIT_ERROR
    verdict = run_end.get("verdict")
    if verdict == "error" and run_end.get("code") in _INVALID_CODES:
        return EXIT_INVALID
    return _VERDICT_EXIT.get(str(verdict), EXIT_ERROR)


HARD_STOP_EXIT_CODE: Final = 4
HELLO_TIMEOUT_S: Final = 30.0
CONTROL_CALL_TIMEOUT_S: Final = 5.0
LAUNCHER_EXIT_WAIT_S: Final = 5.0
"""runner가 끝난 뒤 띄운 프로세스(venv 런처)가 따라 끝나기를 기다리는 시간."""
_POLL_S: Final = 0.02


class ControlError(Exception):
    """제어 요청(`run.pause`·`run.resume`·`run.breakpoints`)의 답을 받지 못했다."""


class ResumeRefused(ControlError):
    """runner가 Step 재개를 거절했다: 멈춰 있지 않다 (`state`는 그때 runner 상태)."""

    def __init__(self, message: str, state: ControlState | None) -> None:
        super().__init__(message)
        self.state = state


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
    run_id: str | None = None
    """미리 정한 실행 ID (daemon이 시작 예약에 쓴 ID). 이미 쓰였으면 시작하지 않고 `RuntimeError`.
    없으면 감독자가 겹치지 않는 ID를 뽑는다."""
    worker_cancel_grace_ms: int = DEFAULT_WORKER_CANCEL_GRACE_MS
    worker_start_timeout_ms: int = DEFAULT_WORKER_START_TIMEOUT_MS
    shutdown_grace_ms: int = DEFAULT_SHUTDOWN_GRACE_MS
    self_kill_margin_ms: int = DEFAULT_SELF_KILL_MARGIN_MS
    capture_timeout_ms: int = DEFAULT_CAPTURE_TIMEOUT_MS
    frame_budget_mib: int = DEFAULT_FRAME_BUDGET_MIB
    frame_output_refs: int = DEFAULT_FRAME_OUTPUT_REFS
    breakpoints: tuple[Breakpoint, ...] = ()
    """시작할 때의 브레이크포인트 (M3 2.1). daemon이 사람이 UI에서 시작한 실행에만 채운다. CLI·
    에이전트 실행은 비워 둔다."""
    graph_value: Mapping[str, Any] | None = None
    """루트 그래프 값 (M5 에이전트 제어 실행 — daemon 내부 진입점만 채운다). `graph`는 그 값을 둘
    스냅샷 안 경로다."""
    source: str | None = None
    agent: Mapping[str, Any] | None = None
    record_override: Mapping[str, Any] | None = None
    """실행별 기록 강제 (M7 R2, `record.policy.AGENT_CONTROL_RECORD` — daemon 내부 진입점만)."""
    bound_window: BoundWindow | None = None
    """에이전트 제어 실행의 대상 창 바인딩 (M7 R1 — daemon 내부 진입점만)."""
    unattended: bool = False
    """사람 없는 Agent 연결이 시작한 실행 (M8 3.5 치트 무인 분류 — daemon이 주체로 정한다)."""
    overlay: Mapping[str, bytes] | None = None
    """작업 기준 덧씌움 (M8 3.6, daemon이 시작 때 고정한 바이트). 감독자가 실행 폴더
    `overlay/<n>.bin`에 쓰고 사양에는 경로·sha만 넣는다."""
    basis: Mapping[str, Any] | None = None
    """`run.json basis` 기록 (M8 3.6)."""
    job: str | None = None
    """이 실행을 낸 작업 ID (M8)."""


def _write_overlay(run_dir: Path, overlay: Mapping[str, bytes]) -> dict[str, dict[str, str]]:
    """덧씌움 바이트를 실행 폴더에 고정한다 (runner가 sha를 다시 확인한다)."""
    import hashlib

    folder = run_dir / "overlay"
    # 새 실행 폴더 안에 처음 만든다 — 이미 있으면(링크·정션 포함) 쓰지 않는다
    folder.mkdir(exist_ok=False)
    out: dict[str, dict[str, str]] = {}
    for n, (rel, data) in enumerate(sorted(overlay.items())):
        name = f"overlay/{n}.bin"
        with open(run_dir / name, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        out[rel] = {"file": name, "sha256": hashlib.sha256(data).hexdigest()}
    return out


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
        runs = opts.runs_dir or root / "runs"
        if opts.run_id is None:
            folder = create_run_folder(runs, graph)
        else:
            folder = create_run_folder(runs, graph, new_id=_only(opts.run_id))
        started_at = format_t(datetime.now(UTC))
        overlay = None if not opts.overlay else _write_overlay(folder.path, opts.overlay)
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
            capture_timeout_ms=opts.capture_timeout_ms,
            frame_budget_mib=opts.frame_budget_mib,
            frame_output_refs=opts.frame_output_refs,
            breakpoints=tuple(opts.breakpoints),
            graph_value=opts.graph_value,
            source=opts.source,
            agent=opts.agent,
            record_override=opts.record_override,
            bound_window=opts.bound_window,
            unattended=opts.unattended,
            overlay=overlay,
            basis=opts.basis,
            job=opts.job,
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
        self.decision: Decision | None = None
        """이 실행을 허용한 권한 판정 (`WorkspaceService.start_run`이 집행한 그 판정)."""
        self._env = owner.env
        self._cmd = owner.runner_cmd
        self._hello_timeout = owner.hello_timeout
        self._hard_stop = owner.hard_stop
        self._trace = owner.trace
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._stop_at: float | None = None
        """하드 종료 타이머가 끝내는 실제 단조 시각 (`run.cancel`에 실어 보낸다)."""
        self._cancel_requested = False
        self._video_granted = False
        """영상 마무리 단계를 허락했다 (한 번만, 타이머를 다시 걸었다)."""
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
            elif item.method == "runner.video_finishing" and not item.is_notification:
                self._grant_video_finishing(peer, item)
            elif not item.is_notification:
                with contextlib.suppress(PeerLost):
                    peer.respond_error(item, METHOD_NOT_FOUND, f"모르는 메서드 {item.method}")

    def _call(self, method: str, params: dict[str, Any] | None = None) -> ControlState:
        peer = self.peer
        if peer is None:
            raise ControlError("제어 채널이 없다 (runner가 시작하지 못했다)")
        try:
            reply = peer.call(method, params, timeout=CONTROL_CALL_TIMEOUT_S)
        except RpcError as exc:
            data = exc.data if isinstance(exc.data, dict) else {}
            if exc.code == INVALID_PARAMS and data.get("reason") == NOT_PAUSED:
                raise ResumeRefused(f"{method}: {exc.message}", data.get("state")) from exc
            raise ControlError(f"{method}: {exc}") from exc
        except (PeerLost, TimeoutError) as exc:
            raise ControlError(f"{method}: {exc}") from exc
        return reply["state"]

    def cancel(self) -> ControlState | None:
        """취소를 요청하고 하드 종료 타이머를 건다. runner의 답(상태)을 주고, 답을 못 받으면
        None (그래도 타이머·채널 상실 규칙이 runner를 끝낸다).

        타이머가 있으면 그 기한을 같이 보낸다: 절대 단조 시각(`hard_stop_at_mono` — 같은 PC의
        `time.monotonic`은 시스템 전역 QPC라 runner와 원점이 같다는 계약)과 보내기 직전에 잰 남은
        시간(`hard_stop_in_ms`). runner는 취소를 늦게 받거나 늦게 처리해도 이 기한 전에 `run.end`·
        `run.json`을 쓰도록 녹화 기다림을 줄인다. 타이머는 미루지 않는다 (먼저 건 타이머가
        그대로). 영상 마무리 단계로 다시 건 타이머가 지금 + 유예보다 늦으면 그리로 당긴다."""
        with self._lock:
            self._cancel_requested = True
        self._arm(shorten=True)
        at = self.hard_stop_at_mono()
        params = None
        if at is not None:
            left = max(0, int((at - time.monotonic()) * 1000))
            params = {"hard_stop_at_mono": at, "hard_stop_in_ms": left}
        try:
            return self._call("run.cancel", params)
        except ControlError:
            return None

    def hard_stop_at_mono(self) -> float | None:
        """걸린 하드 종료 타이머가 끝내는 단조 시각 (`time.monotonic` 초, 타이머가 없으면 None)."""
        with self._lock:
            return self._stop_at

    def hard_stop_in_ms(self) -> int | None:
        """걸린 하드 종료 타이머까지 남은 실제 시간 (ms, 타이머가 없으면 None)."""
        at = self.hard_stop_at_mono()
        return None if at is None else max(0, int((at - time.monotonic()) * 1000))

    def pause(self) -> ControlState:
        return self._call("run.pause")

    def resume(self, mode: ResumeMode = "continue") -> ControlState:
        """재개 (M3 2.3). `continue`는 M0b 호출과 같다(params 없이 보낸다). Step(`step_*`)을 멈추지
        않은 runner가 거절하면 `ResumeRefused`."""
        if mode == "continue":
            return self._call("run.resume")
        return self._call("run.resume", {"mode": mode})

    def set_breakpoints(self, breakpoints: Iterable[Breakpoint]) -> ControlState:
        """브레이크포인트 목록 전체를 바꾼다 (runner가 다음 경계부터 쓴다)."""
        items = [bp.to_json() for bp in sorted(set(breakpoints))]
        return self._call("run.breakpoints", {"breakpoints": items})

    def _arm(self, *, shorten: bool = False) -> None:
        """하드 종료 타이머를 지금 + 유예로 건다. 이미 걸렸으면 미루지 않는다. `shorten`(외부
        취소)이면 영상 마무리 단계로 늦춰 둔 타이머를 지금 + 유예로 당긴다."""
        if not self._hard_stop:
            return
        with self._lock:
            at = time.monotonic() + self.spec.shutdown_grace_ms / 1000
            if self._timer is not None and not (
                shorten and self._stop_at is not None and self._stop_at > at
            ):
                return
            self._set_timer(at)

    def _set_timer(self, at: float) -> None:
        """(잠금 안) 타이머를 `at`(단조)에 끝내도록 새로 건다."""
        if self._timer is not None:
            self._timer.cancel()
        self._stop_at = at
        self._timer = threading.Timer(max(0.0, at - time.monotonic()), self.hard_stop)
        self._timer.daemon = True
        self._timer.start()

    def _grant_video_finishing(self, peer: RpcPeer, item: Any) -> None:
        """`runner.video_finishing`: run.end 뒤 영상 마무리 단계를 한 번만 허락한다 (모듈 설명)."""
        params = item.params
        if check_shape(params, "rpc", ref="#/$defs/RunnerVideoFinishingParams"):
            with contextlib.suppress(PeerLost):
                peer.respond_error(item, INVALID_PARAMS, "runner.video_finishing params 형식")
            return
        wait_s = min(int(params["wait_ms"]), VIDEO_FINISH_MAX_MS) / 1000
        result: dict[str, Any] = {"granted": False}
        with self._lock:
            if not (self._cancel_requested or self._video_granted or self.hard_stopped):
                self._video_granted = True
                result["granted"] = True
                if self._hard_stop:
                    self._set_timer(time.monotonic() + wait_s + self.spec.shutdown_grace_ms / 1000)
            at = self._stop_at if self._hard_stop else None
        if at is not None:
            result["hard_stop_at_mono"] = at
            result["hard_stop_in_ms"] = max(0, int((at - time.monotonic()) * 1000))
        with contextlib.suppress(PeerLost):
            peer.respond(item, result)

    def _disarm(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._stop_at = None

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
            ident = self.runner.ident
            try:
                recovered = self._recover()
            except Exception as exc:  # 기록 오류: Job은 이미 정리됐다. 결과로만 알린다
                recover_error = f"{type(exc).__name__}: {exc}"
            # 설치 플러그인 환경의 사용 표식 (runner가 죽어 놓지 못한 것, M6 3.6). runner는
            # 이미 끝났다 — 정상 마무리였으면 지울 것이 없다
            with contextlib.suppress(OSError):
                release_markers(self.spec.workspace_root, ident)
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


def _only(run_id: str) -> Callable[[], str]:
    """`create_run_folder`의 ID 뽑기: 그 ID 한 번만. 이미 쓰인 ID라 다시 뽑으면 실패한다."""
    used = False

    def pick() -> str:
        nonlocal used
        if used:
            raise RuntimeError(f"실행 ID {run_id}이(가) 이미 쓰였다")
        used = True
        return run_id

    return pick


def _send_spec(launcher: subprocess.Popen[bytes], data: bytes) -> None:
    """실행 사양을 runner의 stdin에 쓰고 닫는다. 자식이 먼저 끝나 쓰기가 실패하면 버린다 (hello
    대기가 판정한다)."""
    stdin = launcher.stdin
    assert stdin is not None
    with contextlib.suppress(OSError, ValueError):
        stdin.write(data)
    with contextlib.suppress(OSError, ValueError):
        stdin.close()
