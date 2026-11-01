"""runner 조립: 시작 순서, 주 스레드 실행, 정상 마무리 (구현 계획 M0b 2.6).

**시작 순서**

1. Job에 자기 넣기(어떤 자식도 띄우기 전에), 제어 채널 연결·`runner.hello`
2. 자기 종료 감시자 시작(감독자 프로세스 핸들) → 제어 스레드 시작. 이때부터 취소·감독자 사망·
   전체 기한(runner 시작부터, 멈춘 시간을 뺀 활성 시계 — M3 2.2) 감시가 동작한다
3. `run.json`(`running`)·저널, `run.start` → 고장 지점 `runner.after_hello`
4. 스냅샷 (파일 참조만 따라가므로 레지스트리가 필요 없다)
5. `plugin_modules`가 있으면 워커를 띄우고 hello → 원격 노드 등록
6. 스냅샷 프로그램의 의미 검증(코어 + 원격). 오류면 `run.end`(`error`/`graph_invalid`, 진단은
   `run.json`)
7. 플랫폼 (M1 T9): `windows`는 DPI 인식(PMv2) 확인 → `WindowsPlatform`(창 수명 추적기·WGC
   캡처·프레임 저장소·비전·OCR·창·프로세스), 장면 `fake`(`platform.scenario`)는 `ScenarioPlatform`
   (+ 저장소·엔진), 그 밖은 `RunnerPlatform`(프레임 파일). 모두 입력은 공용 입력 서비스를 거친다
8. `input` 효과 노드가 있고 플랫폼이 `fake`·`windows`면 입력 임대권(앞 소유자 복구 포함) → 입력
   액터 시작 → 플랫폼의 입력 서비스에 붙임. `windows`는 SendInput 백엔드 + 입력 직전 확인
9. `Executor.run` (주 스레드). 워커 노드의 `ctx` 요청도 주 스레드가 처리한다

**정상 마무리** (주 스레드만): 종료 단계 진입(감시자 무장, 감독자에 `runner.stopping`) → 워커
`shutdown` → 액터 `STOP`·`join`(유예의 절반) → (quiesced면) 플랫폼 닫기(캡처 세션·추적기 스레드)
→ `run.end` → `run.json` 완료 → quiesced였으면 임대권
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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, cast

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
    SystemClock,
)
from kookabug_core.engine.context import InputObserver, ObservationLimits
from kookabug_core.engine.errors import EngineError
from kookabug_core.engine.scenario import FakeScenario, ScenarioError, ScenarioPlatform
from kookabug_core.inputs import (
    InputActor,
    InputGuard,
    InputLease,
    InputLeaseBusy,
    LeaseOwner,
    PlatformUnavailable,
    create_backend,
)
from kookabug_core.inputs.service import InputService, InputSink
from kookabug_core.loader import Program
from kookabug_core.record import FileArtifacts, Journal, write_run_json
from kookabug_core.record.artifacts import FrameRegistry
from kookabug_core.record.runfolder import RUN_FORMAT, RunFolder, finished_run_json
from kookabug_core.record.snapshot import GRAPH_PREFIX, SnapshotError, take_snapshot
from kookabug_core.registry import Registry, default_registry
from kookabug_core.runner.clock import ActiveClock
from kookabug_core.runner.control import Controller, PauseGate, PollPoint
from kookabug_core.runner.spec import MIB, PROTOCOL, RunSpec, ident_to_json
from kookabug_core.runner.watchdog import Watchdog
from kookabug_core.validate import validate
from kookabug_core.win import Job, ProcessId, current, dpi
from kookabug_core.workerhost import WorkerInvoker, WorkerProcess, WorkerStartError
from kookabug_core.workspace import RunOptions, SettingLookup, Workspace, WorkspaceError
from kookabug_sdk import _faults
from kookabug_sdk.context import InputApi
from kookabug_sdk.pipe import connect
from kookabug_sdk.rpc import RpcPeer
from kookabug_sdk.types import Image, Match, OcrResult, Rect, Target, WindowRef

if TYPE_CHECKING:
    from kookabug_platform.tracker import WindowTracker

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


class _NoInput:
    """입력 액터가 없는 실행(`none`, 또는 `input` 효과 노드가 없음)의 입력 싱크."""

    def __init__(self, reason: str | None = None) -> None:
        self._reason = reason

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        if self._reason is None:
            raise PlatformUnavailable
        raise PlatformUnavailable(self._reason)


class _ActorSink:
    """공용 입력 서비스의 싱크 → 입력 액터 큐 (`attach`로 액터가 붙기 전에는 입력 없음)."""

    def __init__(self, reason: str | None = None) -> None:
        self.actor: InputActor | None = None
        self._reason = reason

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(_NoInput(self._reason) if self.actor is None else self.actor, name)


class RunnerPlatform:
    """runner의 M0b 플랫폼(`none`, 사양 `frames`의 `fake`): 캡처는 프레임 파일 차례(픽셀은 파일
    그대로), 입력은 공용 입력 서비스 → 입력 액터 큐(창 없음 — 창 확인·재검증 없이 클릭 지점으로).
    `engines`(`kookabug_platform.engines.RunEngines`)가 있으면 프레임 파일에서 실제로 찾고 읽는다.
    창·프로세스는 없다(`platform_unavailable`).

    `reason`을 주면 캡처·찾기·입력이 그 사유의 `platform_unavailable`이다 (`windows`인데 플랫폼
    패키지가 없을 때 — 플랫폼 기능을 쓰지 않는 그래프는 그대로 돈다)."""

    def __init__(
        self, frames: Sequence[str], *, engines: Any = None, reason: str | None = None
    ) -> None:
        self._frames = FakePlatform(frames) if frames else None
        self.engines = engines
        self._reason = reason
        self._sink = _ActorSink(reason)
        self.service = InputService(cast(InputSink, self._sink))

    def attach_input(self, actor: InputActor) -> None:
        self._sink.actor = actor

    @property
    def input(self) -> InputApi:
        raise PlatformUnavailable("runner 입력은 스텝 ctx로만 보낸다")

    def input_for(
        self,
        step: str,
        window: WindowRef | None,
        observer: InputObserver,
        sleep: Callable[[int], None],
    ) -> InputApi:
        return self.service.for_step(step, window, observer, sleep=sleep)

    def capture(self, window: WindowRef | None, region: Rect | None) -> Image:
        if self._frames is None:
            raise PlatformUnavailable(self._reason or "이 플랫폼에서는 화면을 캡처할 수 없다")
        return self._frames.capture(window, region)

    def _engines(self) -> Any:
        if self.engines is None:
            raise PlatformUnavailable(self._reason or "이 플랫폼에는 비전·OCR 엔진이 없다")
        return self.engines

    def find(
        self, image: Image, target: Target, *, region: Rect | None, limits: ObservationLimits
    ) -> Match | None:
        return self._engines().find(image, target, region=region, limits=limits)

    def diff(self, a: Image, b: Image, *, region: Rect | None) -> float:
        return self._engines().diff(a, b, region=region)

    def read_text(
        self, image: Image, *, region: Rect | None, sensitive: bool, limits: ObservationLimits
    ) -> OcrResult:
        return self._engines().read_text(image, region=region, sensitive=sensitive, limits=limits)


def _platform_engines(store: Any, workspace: Workspace) -> Any:
    """`kookabug_platform`의 실행 엔진. 패키지가 없으면 None (`fake`·`none` 실행은 opencv 없이)."""
    try:
        from kookabug_platform.engines import RunEngines
    except ImportError:
        return None
    engine, options = _ocr_settings(workspace)
    return RunEngines(store, ocr_engine=engine, ocr_options=options)


def _fake_store(budget_bytes: int, output_refs: int) -> tuple[Any, Any]:
    """장면 가짜 실행의 프레임 저장소와 PNG 풀기. 플랫폼 패키지가 없으면 둘 다 None (프레임 파일
    그대로 — M0b)."""
    try:
        from kookabug_platform.frames import FrameStore, decode_image
    except ImportError:
        return None, None
    return FrameStore(budget_bytes=budget_bytes, output_refs=output_refs), decode_image


def _ocr_settings(workspace: Workspace) -> tuple[str, dict[str, Any]]:
    """`kookabug.json`의 `ocr`: 엔진 이름(`engine`, 기본 `rapidocr`)과 그 엔진 설정(나머지)."""
    block = workspace.config.get("ocr")
    options: dict[str, Any] = (
        dict(cast(Mapping[str, Any], block)) if isinstance(block, dict) else {}
    )
    engine = options.pop("engine", "rapidocr")
    return str(engine), options


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
        """시작 시각 (실제 단조 시간 — `run.end.duration_ms`)."""
        self.token = CancelToken()
        self.clock = ActiveClock(self.token)
        """활성 시계: 멈춘 시간을 뺀 기한 시계 (제어 스레드·실행기 런타임이 같이 본다, M3 2.2)."""
        self.started_ms = self.clock.now_ms()
        self.deadline_at_ms = self.started_ms + spec.deadline_ms
        """전체 기한 시각 (활성 시계 ms, runner 시작부터)."""
        self.pause = PauseGate(self.token, self.clock, spec.breakpoints)
        self.peer: RpcPeer | None = None
        self.watchdog: Watchdog | None = None
        self.controller: Controller | None = None
        self.journal: Journal | None = None
        self.worker: WorkerProcess | None = None
        self.actor: InputActor | None = None
        self.lease: InputLease | None = None
        self.job: Job | None = None
        self.platform: Any = None
        """실행 플랫폼 (`RunnerPlatform`·`ScenarioPlatform`·`WindowsPlatform`)."""
        self.frames: FrameRegistry | None = None
        """프레임 저장소 (`windows`·장면 `fake`. M0b 프레임 파일 실행은 없음)."""
        self.platform_missing: str | None = None
        """`windows`인데 플랫폼 패키지가 없는 사유 (입력 노드가 있으면 시작 때 그 사유로 끝낸다)."""
        self.registry: Registry | None = None
        self._run_json: dict[str, Any] = {}

    @property
    def window_tracker(self) -> WindowTracker | None:
        """`kind: windows`의 창 수명 추적기 (아직 쓰지 않았으면 None)."""
        return getattr(self.platform, "started_tracker", None)

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
        job = self.job = Job.open(spec.job_name).keep_until_exit()
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
            deadline_at_ms=self.deadline_at_ms,
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
        if self.clock.now_ms() >= self.deadline_at_ms:
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

        # 7. 플랫폼 (windows: DPI 인식 확인 → 추적기·캡처·저장소·엔진)
        # 엔진 설정(`ocr`)은 실행 정의의 복사본에서 읽는다 (원본은 스냅샷 뒤에 바뀌었을 수 있다)
        refused = self._open_platform(snap.workspace)
        if refused is not None:
            return refused

        # 8. 입력 임대권 → 입력 액터
        if _uses_input(program, registry) and spec.platform.kind in ("fake", "windows"):
            refused = self._start_input()
            if refused is not None:
                return refused
        self._check()

        # 9. 실행
        return self._run_program(program, registry)

    def _open_platform(self, workspace: Workspace) -> _End | None:
        spec = self.spec
        kind = spec.platform.kind
        budget = spec.frame_budget_mib * MIB
        if kind == "windows":
            reason = dpi.startup_error()
            if reason is not None:
                return _End.error(dpi.CODE, f"DPI 인식을 Per-Monitor V2로 둘 수 없다: {reason}")
            try:
                # 플랫폼 패키지는 이 종류일 때만 불러온다 (fake·none 실행은 opencv 등 없이 돈다)
                from kookabug_platform.frames import FrameStore
                from kookabug_platform.platform import WindowsPlatform
            except ImportError as exc:
                # 플랫폼 기능(캡처·창·입력)을 쓰는 노드만 그 사유로 끝난다
                reason = f"Windows 플랫폼 패키지(kookabug-platform)를 쓸 수 없다: {exc}"
                self.platform = RunnerPlatform((), reason=reason)
                self.platform_missing = reason
                return None
            store = FrameStore(budget_bytes=budget, output_refs=spec.frame_output_refs)
            self.frames = store
            self.platform = WindowsPlatform(
                run_id=spec.run_id,
                job=self.job,
                store=store,
                engines=_platform_engines(store, workspace),
            )
            return None
        if kind == "fake" and spec.platform.scenario is not None:
            try:
                scenario = FakeScenario.load(spec.platform.scenario)
            except ScenarioError as exc:
                return _End.error("platform_invalid", str(exc))
            store, decode = _fake_store(budget, spec.frame_output_refs)
            self.frames = store
            self.platform = ScenarioPlatform(
                scenario, decode=decode, engines=_platform_engines(store, workspace)
            )
            return None
        engines = _platform_engines(None, workspace) if kind == "fake" else None
        self.platform = RunnerPlatform(spec.platform.frames, engines=engines)
        return None

    def _start_input(self) -> _End | None:
        spec = self.spec
        assert self.controller is not None
        if self.platform_missing is not None:
            return _End.error("platform_unavailable", self.platform_missing)
        gate = threading.Event()
        backend = create_backend(
            spec.platform.kind,
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
        guard: InputGuard | None = None
        if spec.platform.kind == "windows":
            from kookabug_platform.sendinput import WindowInputGuard

            guard = WindowInputGuard(self.platform.tracker)
        # 액터의 기록 실패는 액터가 알아야 한다(입력을 막는다): 조용히 버리지 않는 쓰기를 준다
        self.actor = InputActor(backend, emit=self._emit, gate=gate, guard=guard).start()
        self.controller.attach_actor(self.actor)
        self.platform.attach_input(self.actor)
        return None

    def _run_program(self, program: Program, registry: Registry) -> _End:
        assert self.journal is not None
        remaining_ms = max(1, self.deadline_at_ms - self.clock.now_ms())
        executor = Executor(
            registry,
            platform=self.platform,
            # 기한은 활성 시계(제어 스레드와 같은 시계), 경과는 실제 단조 시계 (M3 2.2)
            clock=self.clock,
            wall=SystemClock(self.token),
            cancel=self.token,
            artifacts=FileArtifacts(self.folder.path),
            sink=_JournalSink(self.journal),
            invoker=RoutingInvoker(None if self.worker is None else WorkerInvoker(self.worker)),
            before_step=lambda point: self.pause.at_boundary(point, self._emit),
            pause_point=PollPoint(self.pause, self._emit),
            # 관측 세대: 멈춤 게이트가 재개할 때 올리고 실행기가 읽는다 (M3 2.4)
            epochs=self.pause.epochs,
            on_setting=self._record_setting,
            frames=self.frames,
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
                    capture_timeout_ms=self.spec.capture_timeout_ms,
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
        if end is not None and end.diagnostics:
            # 진단은 run.end에 없다. run.end 뒤 하드 종료돼 감독자가 run.json을 다시 만들 때
            # (실행 중 run.json이 바탕) 잃지 않게, 마무리를 시작하기 전에 먼저 남긴다
            self._run_json["diagnostics"] = [d.to_dict() for d in end.diagnostics]
            self._save_running()
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
        close = getattr(self.platform, "close", None)
        if close is not None and quiesced:
            # 액터가 멈춘 뒤에만 (멈춘 액터는 입력 직전 확인으로 추적기를 더 부르지 않는다).
            # 캡처 세션을 멈추고 추적기 스레드를 멈춘다
            with contextlib.suppress(Exception):
                close()

        run_end: dict[str, Any] | None = None
        if end is not None and self.journal is not None:
            # 취소가 시작됐으면 cancel.requested가 확정된 뒤에 run.end를 쓴다 (run.end 뒤의 쓰기는
            # 거부된다). 쓰기가 멈추면 run.end도 쓸 수 없으므로 기다림의 끝은 감시자의 자기 종료다
            self.controller.record_cancel()
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
        try:
            write_run_json(self.folder.run_json, data)
        except Exception:
            traceback.print_exc()

        _faults.fault_point("runner.before_lease_release")
        self._release_lease(quiesced)
        self._close()
        return EXIT_OK

    def _run_end_event(self, end: _End) -> dict[str, Any]:
        duration_ms = int((time.monotonic() - self.started) * 1000)
        paused_ms = self.clock.paused_ms
        event: dict[str, Any] = {
            "event": "run.end",
            "verdict": end.verdict,
            "code": end.code,
            "reason": end.reason,
            "failure_step": end.failure_step,
            "failure_path": end.failure_path,
            "duration_ms": duration_ms,
            # 실제 경과에서 멈춘 시간을 뺀 경과 (M3 2.2). run.json에도 옮긴다
            "active_duration_ms": max(0, duration_ms - paused_ms),
            "paused_ms": paused_ms,
            "debug_intervened": self.pause.intervened,
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
