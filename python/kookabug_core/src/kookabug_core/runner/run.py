"""runner 조립: 시작 순서, 주 스레드 실행, 정상 마무리 (구현 계획 M0b 2.6).

**시작 순서**

1. Job에 자기 넣기(어떤 자식도 띄우기 전에), 제어 채널 연결·`runner.hello`
2. 자기 종료 감시자 시작(감독자 프로세스 핸들) → 제어 스레드 시작. 이때부터 취소·감독자 사망·
   전체 기한(runner 시작부터) 감시가 동작한다
3. `run.json`(`running`)·저널, `run.start` → 고장 지점 `runner.after_hello`
4. 스냅샷 (파일 참조만 따라가므로 레지스트리가 필요 없다)
5. `plugin_modules`가 있으면 워커를 띄우고 hello → 원격 노드 등록
6. 스냅샷 프로그램의 의미 검증(코어 + 원격). 오류면 `run.end`(`error`/`graph_invalid`, 진단은
   `run.json`)
7. `input` 효과 노드가 있으면 입력 임대권(앞 소유자 복구 포함) → 입력 액터 시작
8. `Executor.run` (주 스레드). 워커 노드의 `ctx` 요청도 주 스레드가 처리한다

**정상 마무리** (주 스레드만): 종료 단계 진입(감시자 무장, 감독자에 `runner.stopping`) → 워커
`shutdown` → 액터 `STOP`·`join`(유예의 절반) → `run.end` → `run.json` 완료 → quiesced였으면 임대권
깨끗하게 놓기(아니면 놓지 않고 끝남 — 감독자 복구 경로·다음 획득자가 처리) → 저널 닫기 →
종료 코드 0.
runner의 저널 쓰기는 `run.end`가 마지막이다.

종료 코드: `0` 주 스레드 정상 마무리, `2` 시작 실패(사양·Job·제어 채널), `3` 기록 실패(`run.end`를
쓰지 못함 — 감독자가 마무리한다), `4` 자기 종료(감시자)·감독자의 하드 종료.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import platform as host
import threading
import time
import traceback
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import kookabug_core
from kookabug_core.diagnostics import Diagnostic, has_errors
from kookabug_core.engine import (
    Cancelled,
    CancelToken,
    DeadlineExceeded,
    ExecOptions,
    Executor,
    FakePlatform,
    GraphInvalid,
    RoutingInvoker,
    RunResult,
)
from kookabug_core.engine.errors import EngineError
from kookabug_core.inputs import (
    InputActor,
    InputLease,
    InputLeaseBusy,
    LeaseOwner,
    PlatformUnavailable,
    create_backend,
)
from kookabug_core.loader import Program
from kookabug_core.record import FileArtifacts, Journal, write_run_json
from kookabug_core.record.runfolder import RUN_FORMAT, RunFolder, finished_run_json
from kookabug_core.record.snapshot import GRAPH_PREFIX, SnapshotError, take_snapshot
from kookabug_core.registry import Registry, default_registry
from kookabug_core.runner.control import Controller, PauseGate
from kookabug_core.runner.spec import PROTOCOL, RunSpec, ident_to_json
from kookabug_core.runner.watchdog import Watchdog
from kookabug_core.validate import validate
from kookabug_core.win import Job, ProcessId, current
from kookabug_core.workerhost import WorkerInvoker, WorkerProcess, WorkerStartError
from kookabug_core.workspace import RunOptions, SettingLookup, Workspace, WorkspaceError
from kookabug_sdk import _faults
from kookabug_sdk.context import InputApi
from kookabug_sdk.pipe import connect
from kookabug_sdk.rpc import RpcPeer
from kookabug_sdk.types import Image, Match, Point, Rect, Secret, WindowRef

__all__ = [
    "EXIT_OK",
    "EXIT_RECORD_FAILED",
    "EXIT_START_FAILED",
    "Runner",
    "RunnerPlatform",
    "unix_micros",
]

EXIT_OK: Final = 0
EXIT_START_FAILED: Final = 2
EXIT_RECORD_FAILED: Final = 3
HELLO_TIMEOUT_S: Final = 30.0
_FILETIME_UNIX_EPOCH: Final = 116_444_736_000_000_000
_PACKAGES: Final = ("kookabug_core", "kookabug_sdk", "kookabug_nodes")


def unix_micros(ident: ProcessId) -> int:
    """프로세스 생성 시각 FILETIME(1601년부터 100ns) → Unix 기준 UTC 마이크로초 (`ProcessInfo`)."""
    return max(0, (ident.created - _FILETIME_UNIX_EPOCH) // 10)


# ---------------------------------------------------------------- 플랫폼


class _ActorInput:
    """`ctx.input` → 입력 액터 큐 (스텝 ID와 함께). 액터가 백엔드를 부르는 유일한 스레드다."""

    def __init__(self, actor: InputActor, step: str) -> None:
        self._actor = actor
        self._step = step

    def click(self, at: Point | Rect | Match, *, button: str = "left") -> None:
        self._actor.click(at, button=button, step=self._step)

    def key(self, key: str) -> None:
        self._actor.key(key, step=self._step)

    def type_text(self, text: str | Secret) -> None:
        self._actor.type_text(text, step=self._step)


class _NoInput:
    def click(self, at: Point | Rect | Match, *, button: str = "left") -> None:
        raise PlatformUnavailable

    def key(self, key: str) -> None:
        raise PlatformUnavailable

    def type_text(self, text: str | Secret) -> None:
        raise PlatformUnavailable


class RunnerPlatform:
    """runner의 플랫폼: 캡처는 사양의 `frames`(가짜) 또는 없음, 입력은 입력 액터 큐로."""

    def __init__(self, frames: Sequence[str], actor: InputActor | None) -> None:
        self._frames = FakePlatform(frames) if frames else None
        self._actor = actor

    @property
    def input(self) -> InputApi:
        return _NoInput() if self._actor is None else _ActorInput(self._actor, "")

    def input_for(self, step: str) -> InputApi:
        return _NoInput() if self._actor is None else _ActorInput(self._actor, step)

    def capture(self, window: WindowRef | None, region: Rect | None) -> Image:
        if self._frames is None:
            raise PlatformUnavailable("이 플랫폼에서는 화면을 캡처할 수 없다")
        return self._frames.capture(window, region)


# ---------------------------------------------------------------- 결과


@dataclass(slots=True)
class _End:
    verdict: str
    code: str
    reason: str
    failure_step: str | None = None
    failure_path: list[str] | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list[Diagnostic])

    @classmethod
    def error(cls, code: str, reason: str, **extra: Any) -> _End:
        return cls("error", code, reason, **extra)

    @classmethod
    def of(cls, result: RunResult) -> _End:
        return cls(
            result.verdict,
            result.code,
            result.reason,
            result.failure_step,
            list(result.failure_path) if result.failure_path else None,
        )

    @classmethod
    def cancelled(cls, exc: Cancelled) -> _End:
        if isinstance(exc, DeadlineExceeded):
            return cls.error("deadline_exceeded", str(exc) or "테스트 전체 기한을 넘었다")
        return cls.error("cancelled", str(exc) or "실행이 취소됐다")


class _RecordBroken(Exception):
    """저널 쓰기가 실패했다. runner는 `run.end`를 쓰지 못하고 감독자가 마무리한다."""


class _JournalSink:
    """실행기 이벤트 → 저널. 쓰기 실패는 그대로 던져 실행을 멈춘다 (기록 없이 노드를 돌리지
    않는다)."""

    def __init__(self, journal: Journal) -> None:
        self._journal = journal

    def emit(self, event: Mapping[str, Any]) -> None:
        self._journal.emit(event)


# ---------------------------------------------------------------- runner


class Runner:
    def __init__(self, spec: RunSpec) -> None:
        self.spec = spec
        self.folder = RunFolder(spec.run_dir, spec.run_id)
        self.ident = current()
        self.started = time.monotonic()
        self.deadline_at = self.started + spec.deadline_ms / 1000
        self.token = CancelToken()
        self.pause = PauseGate(self.token)
        self.peer: RpcPeer | None = None
        self.watchdog: Watchdog | None = None
        self.controller: Controller | None = None
        self.journal: Journal | None = None
        self.worker: WorkerProcess | None = None
        self.actor: InputActor | None = None
        self.lease: InputLease | None = None
        self.registry: Registry | None = None
        self._run_json: dict[str, Any] = {}

    # ------------------------------------------------------------ 진입

    def run(self) -> int:
        try:
            self._connect()
        except Exception:
            traceback.print_exc()
            return EXIT_START_FAILED
        try:
            self._open_record()
        except Exception:
            traceback.print_exc()
            return EXIT_RECORD_FAILED
        _faults.fault_point("runner.after_hello")
        try:
            end = self._execute()
        except _RecordBroken:
            traceback.print_exc()
            end = None
        except Exception as exc:  # 예상하지 못한 runner 고장도 기록으로 남기고 정상 마무리한다
            traceback.print_exc()
            end = _End.error("runner_internal", f"{type(exc).__name__}: {exc}")
        return self._finish(end)

    # ------------------------------------------------------------ 1·2. 연결·감시

    def _connect(self) -> None:
        spec = self.spec
        job = Job.open(spec.job_name).keep_until_exit()
        job.assign_current()
        conn = connect(spec.control.pipe, spec.control.key)
        self.peer = RpcPeer(conn, name="runner-control").start()
        self.peer.call(
            "runner.hello",
            {"protocol": PROTOCOL, "run_id": spec.run_id, "runner": ident_to_json(self.ident)},
            timeout=HELLO_TIMEOUT_S,
        )
        self.watchdog = Watchdog(
            spec.supervisor,
            shutdown_grace_ms=spec.shutdown_grace_ms,
            self_kill_margin_ms=spec.self_kill_margin_ms,
        ).start()
        self.controller = Controller(
            cancel=self.token,
            watchdog=self.watchdog,
            pause=self.pause,
            deadline_at=self.deadline_at,
            peer=self.peer,
        ).start()

    # ------------------------------------------------------------ 3. 기록 시작

    def _open_record(self) -> None:
        spec = self.spec
        assert self.controller is not None
        self.journal = Journal(self.folder.events, spec.run_id, writer="runner")
        start = self.journal.emit(
            {
                "event": "run.start",
                "graph": spec.graph,
                "protocol": PROTOCOL,
                "runner": {
                    "version": kookabug_core.__version__,
                    "pid": self.ident.pid,
                    "created": unix_micros(self.ident),
                },
            }
        )
        self._run_json = {
            "format": RUN_FORMAT,
            "run_id": spec.run_id,
            "graph": spec.graph,
            "status": "running",
            "started_at": start["t"],
            "runner": {
                "version": kookabug_core.__version__,
                "python": host.python_version(),
                "pid": self.ident.pid,
            },
            "packages": _packages(),
            "plugins": [],
            "conditions": {
                "profile": spec.profile,
                "settings": {},
                "deadline_ms": spec.deadline_ms,
                "platform": spec.platform.kind,
            },
            "game_build": None,
        }
        write_run_json(self.folder.run_json, self._run_json)
        self.controller.journal_ready(self._emit_quiet)

    def _emit(self, event: Mapping[str, Any]) -> None:
        assert self.journal is not None
        self.journal.emit(event)

    def _emit_quiet(self, event: Mapping[str, Any]) -> None:
        """다른 스레드의 기록(워커 유예 타이머 등): `run.end` 뒤면 버린다."""
        if self.journal is not None:
            with contextlib.suppress(Exception):
                self.journal.emit(event)

    def _check(self) -> None:
        """시작 순서 사이의 취소·기한 확인 (주 스레드)."""
        assert self.controller is not None
        if time.monotonic() >= self.deadline_at:
            self.controller.cancel("deadline_exceeded")
        self.token.check()

    # ------------------------------------------------------------ 4~8. 실행

    def _execute(self) -> _End:
        try:
            return self._prepare_and_run()
        except Cancelled as exc:
            return _End.cancelled(exc)

    def _prepare_and_run(self) -> _End:
        spec = self.spec
        assert self.controller is not None and self.journal is not None
        self._check()

        # 4. 스냅샷
        try:
            workspace = Workspace.open(spec.workspace_root)
            snap = take_snapshot(
                workspace,
                spec.graph,
                self.folder.snapshot,
                options=RunOptions(settings=dict(spec.settings), profile=spec.profile),
            )
        except SnapshotError as exc:
            return _End.error(exc.code, str(exc))
        except WorkspaceError as exc:
            return _End.error("workspace_invalid", str(exc))
        program = snap.program
        # 실행 조건은 확정되는 대로 running 파일에 남긴다: runner가 죽어도 감독자 마무리가 쓴다
        self._run_json["conditions"]["settings"] = {
            key: _setting_use(lookup) for key, lookup in sorted(program.settings.items())
        }
        self._save_running()
        self._check()

        # 5. 워커
        registry = self.registry = default_registry()
        if spec.plugin_modules:
            try:
                self.worker = WorkerProcess.start(
                    modules=spec.plugin_modules,
                    files_root=self.folder.snapshot,
                    log_dir=self.folder.logs,
                    run_id=spec.run_id,
                    workspace_id=str(spec.workspace_root),
                    registry=registry,
                    emit=self._emit_quiet,
                    check=self._check,
                    start_timeout_ms=spec.worker_start_timeout_ms,
                    cancel_grace_ms=spec.worker_cancel_grace_ms,
                )
            except WorkerStartError as exc:
                return _End.error(exc.code, exc.message)
            self.controller.attach_worker(self.worker)
        self._run_json["plugins"] = [
            {"id": pid, "version": version} for pid, version in sorted(registry.plugins.items())
        ]
        self._save_running()

        # 6. 의미 검증
        _faults.fault_point("runner.before_validate")
        self._check()
        diagnostics = validate(program, registry)
        if has_errors(diagnostics):
            errors = [d for d in diagnostics if d.severity == "error"]
            summary = "; ".join(f"{d.code} {d.file or ''}{d.pointer or ''}" for d in errors[:5])
            return _End.error(
                "graph_invalid",
                f"실행 전 검증 오류 {len(errors)}건: {summary}",
                diagnostics=diagnostics,
            )

        # 7. 입력 임대권 → 입력 액터
        if _uses_input(program, registry) and spec.platform.kind == "fake":
            refused = self._start_input()
            if refused is not None:
                return refused
        self._check()

        # 8. 실행
        return self._run_program(program, registry)

    def _start_input(self) -> _End | None:
        spec = self.spec
        assert self.controller is not None
        gate = threading.Event()
        backend = create_backend(
            "fake",
            input_log=spec.platform.input_log,
            hooks=spec.platform.hooks,
            run=spec.run_id,
            by="runner",
            gate=gate,
        )
        owner = LeaseOwner.current(
            "runner", run_id=spec.run_id, run_dir=spec.run_dir, workspace=spec.workspace_root
        )
        lease = InputLease(owner, backend, emit=self._emit)
        try:
            lease.acquire(0)
        except InputLeaseBusy as exc:
            return _End.error(exc.code, str(exc))
        self.lease = lease
        # 액터의 기록 실패는 액터가 알아야 한다(입력을 막는다): 조용히 버리지 않는 쓰기를 준다
        self.actor = InputActor(backend, emit=self._emit, gate=gate).start()
        self.controller.attach_actor(self.actor)
        return None

    def _run_program(self, program: Program, registry: Registry) -> _End:
        assert self.journal is not None
        remaining_ms = max(1, int((self.deadline_at - time.monotonic()) * 1000))
        executor = Executor(
            registry,
            platform=RunnerPlatform(self.spec.platform.frames, self.actor),
            cancel=self.token,
            artifacts=FileArtifacts(self.folder.path),
            sink=_JournalSink(self.journal),
            invoker=RoutingInvoker(None if self.worker is None else WorkerInvoker(self.worker)),
            before_step=lambda step: self.pause.at_boundary(step, self._emit),
            on_setting=self._record_setting,
        )
        try:
            result = executor.run(
                program,
                ExecOptions(
                    deadline_ms=remaining_ms,
                    validate=False,
                    run_id=self.spec.run_id,
                    graph_prefix=GRAPH_PREFIX,
                    collect_events=False,
                ),
            )
        except GraphInvalid as exc:
            return _End.error("graph_invalid", str(exc), diagnostics=exc.diagnostics)
        except Cancelled:
            raise
        except EngineError as exc:
            return _End.error(exc.code, exc.message)
        except Exception as exc:
            if self.journal_broken:
                raise _RecordBroken(str(exc)) from exc
            raise
        return _End.of(result)

    @property
    def journal_broken(self) -> bool:
        return self.journal is None or self.journal.broken

    def _save_running(self) -> None:
        """실행 중 `run.json`을 지금 아는 정보로 원자적으로 바꾼다. 실패해도 실행은 계속한다
        (완료 때 다시 쓰고, 못 쓰면 감독자가 `run.end`에서 다시 만든다)."""
        try:
            write_run_json(self.folder.run_json, self._run_json)
        except Exception:
            traceback.print_exc()

    def _record_setting(self, lookup: SettingLookup) -> None:
        """노드가 `ctx.setting()`으로 읽은 설정 (주 스레드). 새로 쓰였거나 값이 바뀌면 바로
        남긴다."""
        settings: dict[str, Any] = self._run_json["conditions"]["settings"]
        use = _setting_use(lookup)
        if settings.get(lookup.key) == use:
            return
        settings[lookup.key] = use
        self._run_json["conditions"]["settings"] = dict(sorted(settings.items()))
        self._save_running()

    # ------------------------------------------------------------ 정상 마무리

    def _finish(self, end: _End | None) -> int:
        """주 스레드만 한다. `end`가 None이면 저널이 망가졌다(`run.end`를 쓰지 못한다)."""
        spec = self.spec
        assert self.watchdog is not None and self.controller is not None
        self.watchdog.arm()
        if end is not None and end.code == "deadline_exceeded":
            # 실행기가 제어 스레드보다 먼저 기한을 본 경우도 같은 취소 경로로 모은다
            # (cancel.requested·cancel_reason·runner.stopping이 남는다. 이미 시작됐으면 그대로)
            self.controller.cancel("deadline_exceeded")
        self.controller.notify_stopping(self.controller.cancel_reason or "finish")

        _faults.fault_point("runner.before_worker_shutdown")
        if self.worker is not None:
            with contextlib.suppress(Exception):
                self.worker.shutdown(spec.worker_cancel_grace_ms)
        quiesced = True
        if self.actor is not None:
            quiesced = self.actor.stop(spec.shutdown_grace_ms / 2 / 1000)

        run_end: dict[str, Any] | None = None
        if end is not None and self.journal is not None:
            if self.controller.cancel_reason is not None:
                # 취소가 시작됐으면 cancel.requested가 확정된 뒤에 run.end를 쓴다
                # (run.end 뒤의 쓰기는 거부된다)
                self.controller.wait_recorded(spec.shutdown_grace_ms / 2 / 1000)
            event = self._run_end_event(end)
            try:
                run_end = self.journal.emit(event)
            except Exception:
                traceback.print_exc()
        _faults.fault_point("runner.after_run_end")
        if run_end is None:
            # 기록이 망가졌다: run.json도 쓰지 않는다 (감독자 복구 경로가 저널에서 마무리한다)
            self._release_lease(quiesced)
            self._close()
            return EXIT_RECORD_FAILED

        _faults.fault_point("runner.before_run_json_final")
        assert end is not None
        data = finished_run_json(self._run_json, run_end)
        data["pause_count"] = self.pause.count
        if end.diagnostics:
            data["diagnostics"] = [d.to_dict() for d in end.diagnostics]
        try:
            write_run_json(self.folder.run_json, data)
        except Exception:
            traceback.print_exc()

        _faults.fault_point("runner.before_lease_release")
        self._release_lease(quiesced)
        self._close()
        return EXIT_OK

    def _run_end_event(self, end: _End) -> dict[str, Any]:
        event: dict[str, Any] = {
            "event": "run.end",
            "verdict": end.verdict,
            "code": end.code,
            "reason": end.reason,
            "failure_step": end.failure_step,
            "failure_path": end.failure_path,
            "duration_ms": int((time.monotonic() - self.started) * 1000),
            "finalized_by": "runner",
        }
        assert self.controller is not None
        reason = self.controller.cancel_reason
        if reason is not None:
            event["cancel_reason"] = reason
        return event

    def _release_lease(self, quiesced: bool) -> None:
        """quiesced일 때만 깨끗하게 놓는다. 아니면 놓지 않고 끝난다(프로세스 종료로 버려짐)."""
        if self.lease is None or not quiesced:
            return
        try:
            self.lease.release(self.actor)
        except Exception:
            traceback.print_exc()

    def _close(self) -> None:
        if self.journal is not None:
            with contextlib.suppress(Exception):
                self.journal.close()
        if self.controller is not None:
            self.controller.stop()
        if self.peer is not None:
            self.peer.close(flush_timeout=1.0)


def _setting_use(lookup: SettingLookup) -> dict[str, Any]:
    """`run.json`의 `SettingUse`: 찾은 계층과 값 (설정은 비밀값이 아니다)."""
    return {"layer": lookup.layer, "value": lookup.value}


def _uses_input(program: Program, registry: Registry) -> bool:
    for graph in program.graphs.values():
        for node in graph.nodes.values():
            nodedef = registry.get(node.type)
            if nodedef is not None and "input" in nodedef.effects:
                return True
    return False


def _packages() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in _PACKAGES:
        with contextlib.suppress(importlib.metadata.PackageNotFoundError):
            versions[name] = importlib.metadata.version(name)
    return versions
