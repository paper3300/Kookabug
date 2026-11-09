"""runner 조립: 시작 순서, 주 스레드 실행, 정상 마무리 (구현 계획 M0b 2.6).

**시작 순서**

1. Job에 자기 넣기(어떤 자식도 띄우기 전에), 제어 채널 연결·`runner.hello`
2. 자기 종료 감시자 시작(감독자 프로세스 핸들) → 제어 스레드 시작. 이때부터 취소·감독자 사망·
   전체 기한(runner 시작부터, 멈춘 시간을 뺀 활성 시계 — M3 2.2) 감시가 동작한다
3. `run.json`(`running`)·저널, `run.start` → 고장 지점 `runner.after_hello`
4. 스냅샷 (파일 참조만 따라가므로 레지스트리가 필요 없다)
5. 워커 (M6 3.6·D8): `plugin_modules`(개발 모듈, 사람 전용)가 있으면 그 워커. 그래프가 쓰는 나머지
   플러그인은 설치 플러그인 — `op.lock` 안에서 `kookabug.lock`을 읽어(스냅샷에 사본) 조건·환경을
   정하고 환경마다 사용 표식을 만든 뒤, 환경마다 워커(`<환경>\\Scripts\\python.exe -I`, 워커 전용
   중첩 Job)를 띄워 hello를 잠금(digest·permissions)과 대조 → 원격 노드 등록. 잠금에 없음·환경
   없음·조건 다름은 워커 없이 검증 오류(`plugin_*`). 사용 표식은 워커가 끝난 뒤 놓는다
6. 스냅샷 프로그램의 의미 검증(코어 + 원격). 오류면 `run.end`(`error`/`graph_invalid`, 진단은
   `run.json`)
7. 플랫폼 (M1 T9): `windows`는 DPI 인식(PMv2) 확인 → `WindowsPlatform`(창 수명 추적기·WGC
   캡처·프레임 저장소·비전·OCR·창·프로세스), 장면 `fake`(`platform.scenario`)는 `ScenarioPlatform`
   (+ 저장소·엔진), 그 밖은 `RunnerPlatform`(프레임 파일). 모두 입력은 공용 입력 서비스를 거친다
8. `input` 효과 노드가 있고 플랫폼이 `fake`·`windows`면 입력 임대권(앞 소유자 복구 포함) → 입력
   액터 시작 → 플랫폼의 입력 서비스에 붙임. `windows`는 SendInput 백엔드 + 입력 직전 확인
9. `Executor.run` (주 스레드). 워커 노드의 `ctx` 요청도 주 스레드가 처리한다

**정상 마무리** (주 스레드만): 종료 단계 진입(감시자 무장, 제어기 전체 기한 감시 끝 — 판정 확정 뒤
마무리에는 기한 취소가 붙지 않는다, 감독자에 `runner.stopping`) → 녹화 멈춤 신호(M3) → 워커
`shutdown` → 액터 `STOP`·`join`(유예의 절반) → 녹화 스레드 종료 확인(처음 보낸 `runner.stopping`부터
실제 시간 3초, 단 실제로 적용되는 가장 이른 종료 기한 — 감독자가 `run.cancel`로 알린 하드 종료,
감독자 사망 + 유예, `runner.stopping` + 유예 중 가장 이른 것(`Controller.finish_by`) — 에서
기록 여유 1초(유예가 2초 미만이면 유예의 절반)를 뺀 때를 넘지 않음 — 하드 종료 전에 영상 포기·기록이
끝나게) → (quiesced면) 플랫폼 닫기(캡처 세션·추적기 스레드) → `run.end`(녹화 스레드가 안
끝났으면 `omitted` `video`/`encoder_stuck` — 늦은 인코더 대기 중이면 붙이지 않는다) → **영상 마무리
단계**(녹화 스레드가 늦은 인코더 대기 중일 때만, R1 F1 3라운드) → 녹화 스레드가 끝났을 때만 영상
마무리 (`finalize_video` — 안 끝났으면 `video/`를 건드리지 않고 감독자가 runner 종료 뒤 마무리한다)
→ `run.json` 완료(영상 요약) → quiesced였으면 임대권 깨끗하게 놓기(아니면 놓지 않고 끝남 — 감독자
복구 경로·다음 획득자가 처리) → 저널 닫기 → 종료 코드 0. 워커·액터·녹화 기다림의 끝은 모두
그때 아는 종료 기한에서 기록 여유를 뺀 때(`_cutoff`)이고, 기다리는 도중 더 이른 기한이 알려지면
(제어기의 기한 갱신 신호) 바로 다시 잰다.

**영상 마무리 단계**: 실행이 인코더 열기 시험보다 먼저 끝나 녹화 스레드가 모은 프레임을 들고 시험을
기다리면(`VideoRecorder.awaiting_encoder`), `run.end`(판정 확정) 뒤 감독자에게
`runner.video_finishing{wait_ms}`을 청해 하드 종료 타이머를 다시 걸게 하고(자기 종료 감시자도 같이
미룸) 그 상한(`VIDEO_FINISH_MAX_MS`, 30초) 안에서 시험·쓰기를 기다린다. 판정·종료 코드·실행 기한은
그대로다. 상한을 넘기거나, 모은 프레임을 남길 까닭이 없거나(`failed_only`만인데 `pass`·`skipped`·
사용자 취소), 외부 취소·감독자 사망이거나, 감독자가 거절하면 녹화 스레드에 포기를 알린다 — 그
실행의 영상은 `status: omitted`/`encoder_not_ready`로 남는다. 단계 중 하드 종료되면 녹화 스레드의
대기 표식으로 감독자 마무리가 같은 상태를 남긴다.

**영상** (M3 2.5): 녹화 프레임을 줄 수 있는 플랫폼(`windows`, 장면 `fake`)이면 runner를 시작하자마자
인코더 열기 시험을 띄우고(`EncoderProbe`, 연결·기록 시작·스냅샷과 겹침), 영상이 꺼지지 않은
실행은 시험이 끝난 뒤(최대 `VIDEO_PROBE_WAIT_S`) 첫 스텝을 시작한다(R1 F1). 실행기를 시작할 때 녹화
게이트와 녹화 스레드를 붙인다.
멈춤 게이트가 멈춘 동안 녹화 게이트를 off로 둔다.
runner의 저널 쓰기는 `run.end`가 마지막이다.

종료 코드: `0` 주 스레드 정상 마무리, `2` 시작 실패(사양·Job·제어 채널), `3` 기록 실패(`run.end`를
쓰지 못함 — 감독자가 마무리한다), `4` 자기 종료(감시자)·감독자의 하드 종료.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import math
import os
import platform as host
import sys
import threading
import time
import traceback
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, cast

import kookabug_core
from kookabug_core import forbidden
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
from kookabug_core.engine.context import OCR_NODE_TYPES, InputObserver, ObservationLimits
from kookabug_core.engine.errors import EngineError
from kookabug_core.engine.executor import run_record_policy
from kookabug_core.engine.invoker import NodeInvoker, PluginRouter
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
from kookabug_core.plugins import runtime as plugin_runtime
from kookabug_core.plugins.layout import LOCK_FILE
from kookabug_core.qa import (
    QA_CONFIG,
    QA_INVALID,
    QA_NOT_APPLICABLE,
    QaTrace,
    not_applicable,
    run_qa,
)
from kookabug_core.record import FileArtifacts, Journal, write_run_json
from kookabug_core.record.artifacts import FindEvidence, FrameRegistry, find_with_report
from kookabug_core.record.finalize import (
    finalize_video,
    keep_failed_only,
    preview_video,
    video_summary,
)
from kookabug_core.record.runfolder import RUN_FORMAT, RunFolder, finished_run_json
from kookabug_core.record.snapshot import GRAPH_PREFIX, SnapshotError, take_snapshot
from kookabug_core.record.video import (
    STOP_GRACE_S,
    EncoderFactory,
    EncoderProbe,
    EncoderUnavailable,
    VideoGate,
    VideoRecorder,
    VideoSource,
    encoder_factory_from_env,
    finish_wait_from_env,
)
from kookabug_core.registry import Registry, RegistryError, default_registry
from kookabug_core.runner.clock import ActiveClock
from kookabug_core.runner.control import Controller, PauseGate, PollPoint
from kookabug_core.runner.spec import (
    MIB,
    PROTOCOL,
    VIDEO_FINISH_MAX_MS,
    RunSpec,
    bind_find_window,
    ident_to_json,
)
from kookabug_core.runner.watchdog import Watchdog
from kookabug_core.validate import validate
from kookabug_core.validate.plugins import plugin_diagnostics, used_plugins
from kookabug_core.win import Job, ProcessId, current, dpi
from kookabug_core.workerhost import WorkerInvoker, WorkerProcess, WorkerStartError
from kookabug_core.workspace import RunOptions, SettingLookup, Workspace, WorkspaceError
from kookabug_sdk import _faults
from kookabug_sdk.context import InputApi
from kookabug_sdk.pipe import connect
from kookabug_sdk.rpc import RpcPeer
from kookabug_sdk.types import FrameRef, Image, Match, OcrResult, Rect, Target, WindowRef

if TYPE_CHECKING:
    from kookabug_platform.tracker import WindowTracker

__all__ = [
    "EXIT_OK",
    "EXIT_RECORD_FAILED",
    "EXIT_START_FAILED",
    "FINISH_RESERVE_S",
    "VIDEO_PROBE_WAIT_S",
    "Runner",
    "RunnerPlatform",
    "finish_reserve_s",
    "unix_micros",
    "video_wait_s",
]

EXIT_OK: Final = 0
EXIT_START_FAILED: Final = 2
EXIT_RECORD_FAILED: Final = 3
HELLO_TIMEOUT_S: Final = 30.0
VIDEO_PROBE_WAIT_S: Final = 20.0
"""첫 스텝 전에 인코더 열기 시험을 기다리는 상한 (R1 F1 2라운드, 남은 기한의 절반도 넘지 않음)."""
_PROBE_POLL_S: Final = 0.05
_VIDEO_FINISH_CALL_S: Final = 2.0
"""`runner.video_finishing` 답을 기다리는 상한 (그때의 `_cutoff`도 넘지 않는다)."""
_CLOCK_SLACK_S: Final = 0.005
_FINISH_SLICE_S: Final = 0.05
"""마무리에서 끝을 신호로 받지 못하는 대상(액터 스레드)을 다시 보는 간격."""
FINISH_RESERVE_S: Final = 1.0
"""마무리 유예에서 녹화 기다림 뒤의 최종 기록(`run.end`·영상 마무리·`run.json`·임대권·채널 닫기)에
남겨 두는 실제 시간 (유예가 짧으면 그 절반)."""
_FILETIME_UNIX_EPOCH: Final = 116_444_736_000_000_000
_PACKAGES: Final = ("kookabug_core", "kookabug_sdk", "kookabug_nodes")


def finish_reserve_s(shutdown_grace_ms: int) -> float:
    """종료 기한 앞에 최종 기록용으로 남기는 실제 시간: 1초, 유예가 2초보다 짧으면 유예의 절반."""
    return min(FINISH_RESERVE_S, max(0.0, shutdown_grace_ms / 1000) / 2)


def video_wait_s(shutdown_grace_ms: int) -> float:
    """종료 기한이 `runner.stopping` + `shutdown_grace_ms`일 때(정상 마무리·기한 초과) 녹화 스레드
    종료를 기다리는 상한. 기본은 `STOP_GRACE_S`(3초)지만 감독자 하드 종료보다 먼저 영상 포기·
    `run.end`·`run.json`까지 끝나도록 유예에서 기록 여유를 뺀 시간을 넘지 않는다. 더 이른 기한
    (외부 취소·감독자 사망)이 알려져 있으면 `_finish`가 그 기한으로 더 줄인다."""
    grace_s = max(0.0, shutdown_grace_ms / 1000)
    return max(0.0, min(STOP_GRACE_S, grace_s - finish_reserve_s(shutdown_grace_ms)))


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

    def peek_frame(self, window: WindowRef | None) -> Image:
        """지금 프레임 (차례를 넘기지 않는다 — M8 금지 동작 판정용)."""
        if self._frames is None:
            raise PlatformUnavailable(self._reason or "이 플랫폼에서는 화면을 캡처할 수 없다")
        return self._frames.peek_frame(window)

    def _engines(self) -> Any:
        if self.engines is None:
            raise PlatformUnavailable(self._reason or "이 플랫폼에는 비전·OCR 엔진이 없다")
        return self.engines

    def find(
        self, image: Image, target: Target, *, region: Rect | None, limits: ObservationLimits
    ) -> Match | None:
        return self._engines().find(image, target, region=region, limits=limits)

    def find_report(
        self, image: Image, target: Target, *, region: Rect | None, limits: ObservationLimits
    ) -> tuple[Match | None, FindEvidence | None]:
        """찾기 + 매칭 후보 (M3 2.6)."""
        return find_with_report(self._engines(), image, target, region=region, limits=limits)

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
    secret: bool = False
    """`reason`에 비밀값이 들어 있다 (`run.end.secret_paths`, 에이전트용 분류 M5)."""

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
            secret=result.reason_secret,
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
    않는다). 재시도 끝에 성공한 스텝(`step.end.retried`)을 센다 (`run.json.retried_steps`, M3)."""

    def __init__(self, journal: Journal) -> None:
        self._journal = journal
        self.retried_steps = 0

    def emit(self, event: Mapping[str, Any]) -> None:
        self._journal.emit(event)
        if event.get("event") == "step.end" and event.get("retried") is True:
            self.retried_steps += 1


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
        self.workers: list[WorkerProcess] = []
        """워커들: 개발 모듈 하나 + 설치 플러그인 환경마다 하나 (M6 D8)."""
        self.routes: dict[str, NodeInvoker] = {}
        """플러그인 ID → 그 노드를 실행할 워커."""
        self.plugins: plugin_runtime.RunPlugins | None = None
        """설치 플러그인 (잠금 사본·환경·사용 표식, M6 3.6)."""
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
        self.video: VideoRecorder | None = None
        """녹화 스레드 (플랫폼이 녹화 프레임을 줄 때만, M3 2.5)."""
        self._video_factory: EncoderFactory | None = None
        self._video_probe: EncoderProbe | None = None
        self._run_json: dict[str, Any] = {}
        self._sink: _JournalSink | None = None

    @property
    def worker(self) -> WorkerProcess | None:
        """첫 워커 (워커가 없으면 None)."""
        return self.workers[0] if self.workers else None

    @property
    def window_tracker(self) -> WindowTracker | None:
        """`kind: windows`의 창 수명 추적기 (아직 쓰지 않았으면 None)."""
        return getattr(self.platform, "started_tracker", None)

    # ------------------------------------------------------------ 진입

    def run(self) -> int:
        # 인코더 열기 시험은 가장 먼저 띄운다: 연결·기록 시작·스냅샷과 겹쳐 첫 스텝 전 기다림을
        # 줄인다 (R1 F1 2라운드 — 첫 스텝은 시험이 끝난 뒤 시작한다, `_wait_video_probe`)
        self._begin_video_probe()
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
            # 에이전트용 비밀값 분류(이벤트 secret_paths·스텝 secret·agent_withhold)를 남기는
            # 기록이다 (M5 3.8). 없으면 daemon은 에이전트에게 안전 필드만 준다
            "agent_mask": 1,
        }
        # 에이전트 제어 실행 (M5 3.9): 기록 뷰어 배지·감사 기록
        if spec.source is not None:
            self._run_json["source"] = spec.source
        if spec.agent is not None:
            self._run_json["agent"] = dict(spec.agent)
        # 실행 기준 고정 (M8 3.6): 시작 때 감독자가 정한 기준·작업
        if spec.basis is not None:
            self._run_json["basis"] = dict(spec.basis)
        if spec.job is not None:
            self._run_json["job"] = spec.job
        if spec.record_override is not None:
            # 실행별 기록 강제 (M7 R2): 기록 뷰어 머리 줄 "이미지 기록 없음 · 비밀값 가림"
            self._run_json["record_override"] = dict(spec.record_override)
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

    def _overlay(self) -> dict[str, bytes] | None:
        """감독자가 실행 폴더에 고정한 덧씌움 바이트 (M8 3.6). sha가 사양과 다르면 시작하지 않는다
        (`snapshot_failed`) — 고정 뒤 바뀐 바이트로 실행하지 않는다."""
        import hashlib

        if not self.spec.overlay:
            return None
        out: dict[str, bytes] = {}
        for rel, item in self.spec.overlay.items():
            path = self.folder.path.joinpath(*str(item["file"]).split("/"))
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise SnapshotError(
                    "snapshot_failed", f"덧씌움 사본 '{item['file']}'을(를) 읽지 못했다: {exc}"
                ) from exc
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise SnapshotError(
                    "snapshot_failed", f"덧씌움 사본 '{item['file']}'이(가) 고정 뒤 바뀌었다"
                )
            out[rel] = data
        return out

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
                graph_value=spec.graph_value,
                overlay=self._overlay(),
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

        # 5. 워커: 개발 모듈(사람 전용) → 설치 플러그인 (잠금·환경·사용 표식, 환경마다 워커)
        registry = self.registry = default_registry()
        if spec.plugin_modules:
            refused = self._start_worker(registry, spec.plugin_modules)
            if refused is not None:
                return refused
        plugin_problems = self._acquire_plugins(program, registry)
        if plugin_problems is None and self.plugins is not None:
            # 환경 인터프리터는 격리(-I)하고, 이 프로세스의 venv 런처 표시도 넘기지 않는다. -B:
            # 실행 중에는 환경에 아무것도 쓰지 않는다(바이트코드 캐시도 — 실행 중 환경 불변)
            child_env = {k: v for k, v in os.environ.items() if k != "__PYVENV_LAUNCHER__"}
            for env in self.plugins.envs:
                refused = self._start_worker(
                    registry,
                    env.modules,
                    python=(str(env.python), "-I", "-B"),
                    env=child_env,
                    log_name=f"worker-{env.name}",
                    check_hello=lambda found, env=env: plugin_runtime.check_hello(env, found),
                )
                if refused is not None:
                    return refused
        self._run_json["plugins"] = self._plugins_json(registry)
        self._save_running()

        # 6. 의미 검증
        _faults.fault_point("runner.before_validate")
        self._check()
        diagnostics = validate(program, registry)
        if self.plugins is not None:
            diagnostics = [
                *diagnostics,
                *plugin_diagnostics(
                    program,
                    [(p.code, p.plugin, p.message) for p in self.plugins.problems],
                    self.plugins.versions,
                ),
            ]
        if has_errors(diagnostics):
            errors = [d for d in diagnostics if d.severity == "error"]
            summary = "; ".join(f"{d.code} {d.file or ''}{d.pointer or ''}" for d in errors[:5])
            if all(d.code == QA_INVALID for d in errors):
                # qa 설정 오류는 그래프 오류와 구분해 드러낸다 (M8 3.5 — skip으로 묻지 않음)
                self._set_qa(program, config_errors=[d.message for d in errors])
                return _End.error(
                    QA_CONFIG, f"qa 설정 오류 {len(errors)}건: {summary}", diagnostics=diagnostics
                )
            return _End.error(
                "graph_invalid",
                f"실행 전 검증 오류 {len(errors)}건: {summary}",
                diagnostics=diagnostics,
            )
        skip = not_applicable(program.qa, spec.profile)
        if skip is not None:
            self._set_qa(program, not_applicable_reason=skip)
            return _End("skipped", QA_NOT_APPLICABLE, skip)
        warnings = [d for d in diagnostics if d.severity == "warning"]
        if warnings:
            # 경고는 실행을 막지 않는다. run.json에 남겨 CLI 요약·기록이 보인다
            # (M4 T12 video_on_ineffective)
            self._run_json["diagnostics"] = [d.to_dict() for d in warnings]
            self._save_running()

        # 7. 플랫폼 (windows: DPI 인식 확인 → 추적기·캡처·저장소·엔진)
        # 엔진 설정(`ocr`)은 실행 정의의 복사본에서 읽는다 (원본은 스냅샷 뒤에 바뀌었을 수 있다)
        refused = self._open_platform(snap.workspace)
        if refused is not None:
            return refused
        if spec.bound_window is not None:
            # 에이전트 제어 실행 (M7 R1): daemon이 정한 그 창에만 붙는다 (다시 찾지 않음)
            bind_find_window(self.platform, spec.bound_window)
        installed = (
            set()
            if self.plugins is None
            else {p.id for env in self.plugins.envs for p in env.plugins}
        )
        forbidden_text = any(i.get("kind") == "text" for i in spec.forbidden or ())
        if forbidden_text or _uses_ocr(program, registry, installed):
            # 금지 문구 판정(M8 R6)도 입력 직전에 OCR을 쓴다 — 노드 기한 밖에서 미리 준비한다
            self._prepare_ocr()

        # 8. 입력 임대권 → 입력 액터
        if _uses_input(program, registry) and spec.platform.kind in ("fake", "windows"):
            refused = self._start_input()
            if refused is not None:
                return refused
        self._check()

        # 9. 실행 (영상을 남길 수 있으면 인코더 준비가 끝난 뒤 첫 스텝)
        self._wait_video_probe(program)
        return self._run_program(program, registry)

    def _start_worker(
        self,
        registry: Registry,
        modules: Sequence[str],
        *,
        python: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
        log_name: str = "worker",
        check_hello: Callable[[list[dict[str, Any]]], Any] | None = None,
    ) -> _End | None:
        """워커 하나를 띄워 원격 노드를 등록한다. 실패면 끝낼 사유."""
        spec = self.spec
        assert self.controller is not None
        try:
            worker = WorkerProcess.start(
                modules=modules,
                files_root=self.folder.snapshot,
                log_dir=self.folder.logs,
                run_id=spec.run_id,
                workspace_id=str(spec.workspace_root),
                registry=registry,
                emit=self._emit_quiet,
                check=self._check,
                start_timeout_ms=spec.worker_start_timeout_ms,
                cancel_grace_ms=spec.worker_cancel_grace_ms,
                python=python,
                env=env,
                log_name=log_name,
                check_hello=check_hello,
            )
        except WorkerStartError as exc:
            return _End.error(exc.code, exc.message)
        self.workers.append(worker)
        self.controller.attach_worker(worker)
        invoker = WorkerInvoker(worker)
        for plugin in worker.plugins:
            self.routes[str(plugin["id"])] = invoker
        return None

    def _acquire_plugins(self, program: Program, registry: Registry) -> bool | None:
        """그래프가 쓰는 설치 플러그인(코어·개발 모듈 밖)의 잠금을 `op.lock` 안에서 읽고 환경을
        정해 사용 표식을 만든다 (워커를 띄우기 전, M6 3.6). 잠금 사본은 스냅샷에. 문제가 있으면
        True (워커를 띄우지 않고 검증 진단으로 끝난다 — 노드는 커밋된 wheel의 스키마로 등록), 쓸
        것이 없거나 준비됐으면 None."""
        used = used_plugins(program) - set(registry.plugins)
        if not used:
            return None
        plugins = self.plugins = plugin_runtime.acquire(
            self.spec.workspace_root,
            used,
            self.ident,
            environ=os.environ,
            fault=lambda event: _faults.fault_point("runner.plugins", event=event),
        )
        if plugins.lock_bytes is not None:
            (self.folder.snapshot / LOCK_FILE).write_bytes(plugins.lock_bytes)
            self._run_json["conditions"]["plugin_lock_sha256"] = plugins.lock_sha256
        if not plugins.problems:
            return None
        plugins.release()
        plugins.envs = []
        for schema in plugins.unready.values():
            with contextlib.suppress(RegistryError):
                registry.add_remote(schema)
        return True

    def _plugins_json(self, registry: Registry) -> list[dict[str, Any]]:
        """`run.json plugins`: 설치 플러그인은 환경·wheel·스키마 해시까지 (M6 3.3)."""
        out: list[dict[str, Any]] = []
        for pid, version in sorted(registry.plugins.items()):
            locked = None if self.plugins is None else self.plugins.plugin(pid)
            if locked is not None and pid in self.routes:
                out.append(locked.run_json())
            else:
                out.append({"id": pid, "version": version})
        return out

    def _release_plugins(self) -> None:
        if self.plugins is not None:
            self.plugins.release()

    def _prepare_ocr(self) -> None:
        """OCR 노드를 쓰는 실행: OCR 엔진 준비(모델 확인·세션 만들기)를 지금 백그라운드로 시작한다
        (M2 사람 확인 S 결함 ②). 첫 OCR 스텝 전 스텝들과 겹쳐 끝나고, 덜 끝났으면 실행기가 그 OCR
        노드 함수를 부르기 전에 기다린다(`PreparingPlatform` — 노드 기한·설정 기한 밖). 오래
        걸렸으면 stderr에 남긴다(느린 PC 진단)."""
        engines = getattr(self.platform, "engines", None)
        prepare = getattr(engines, "prepare_ocr", None)
        if not callable(prepare):
            return

        def report(elapsed_ms: float, error: BaseException | None) -> None:
            if error is None and elapsed_ms >= OCR_PREPARE_NOTE_MS:
                print(f"OCR 엔진 준비에 {elapsed_ms / 1000:.1f}초 걸렸다", file=sys.stderr)

        prepare(report)

    def _wait_video_probe(self, program: Program) -> None:
        """영상을 남길 수 있는 실행은 인코더 열기 시험이 끝난 뒤 첫 스텝을 시작한다 (M3 사람 확인 R1
        F1 2라운드). 시험이 느리면(차가운 Media Foundation·PC 부하) 그동안 실행이 실패로 끝나 마무리
        기한 안에 인코더가 준비되지 않아 실패 영상 전체를 잃을 수 있다 — 마무리 기한을 늘리는 대신
        앞에서 기다린다. 보통은 스냅샷·워커 시작과 겹쳐 이미 끝나 있다. 상한은
        `VIDEO_PROBE_WAIT_S` 또는 남은 기한의 절반, 취소·기한은 그대로 확인한다. 상한을 넘기면 녹화
        스레드의 준비 중 모으기가 잇고, 실행이 먼저 끝나면 run.end 뒤 영상 마무리 단계가 모은
        프레임을 쓴다(그 메모리 상한은 전체 HD로 몇 초뿐이라 앞부분 영상은 이 기다림이 지킨다)."""
        probe = self._video_probe
        if probe is None or probe.done.is_set():
            return
        if not callable(getattr(self.platform, "video_frame", None)):
            return  # 녹화 프레임을 줄 수 없는 플랫폼: 녹화 스레드가 없다
        if run_record_policy(program, override=self.spec.record_override).video == "off":
            return  # 기본 정책이 끔이면 게이트가 늘 off다
        remaining_s = max(0.0, (self.deadline_at_ms - self.clock.now_ms()) / 1000)
        until = time.monotonic() + min(VIDEO_PROBE_WAIT_S, remaining_s / 2)
        started = time.monotonic()
        while not probe.done.wait(_PROBE_POLL_S):
            self._check()
            if time.monotonic() >= until:
                break
        waited = time.monotonic() - started
        if waited >= 1.0:
            ready = "준비됨" if probe.done.is_set() else "아직 준비 안 됨 (준비 중 모으기로 잇는다)"
            print(f"영상 인코더 준비를 {waited:.1f}초 기다렸다: {ready}", file=sys.stderr)

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
                scenario = FakeScenario.load(
                    spec.platform.scenario, state_file=spec.platform.state_file
                )
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

    def _begin_video_probe(self) -> None:
        """인코더 열기 시험을 시작 순서와 겹쳐 띄운다 (녹화 프레임을 줄 수 있는 플랫폼만, M3 2.5).
        Media Foundation을 쓸 수 없어도 기동은 계속한다 (결과는 녹화 스레드가 `unavailable`로)."""
        kind = self.spec.platform.kind
        if kind != "windows" and (kind != "fake" or self.spec.platform.scenario is None):
            return
        try:
            factory, unavailable = encoder_factory_from_env()
        except Exception as exc:
            factory, unavailable = None, EncoderUnavailable("encoder_open_failed", str(exc))
        self._video_factory = factory
        self._video_probe = EncoderProbe(factory, unavailable)

    def _start_video(self) -> VideoGate | None:
        """녹화 스레드 (M3 2.5). 플랫폼이 녹화 프레임을 주지 못하면(프레임 파일·`none`) 영상 없음.
        인코더를 쓸 수 없어도 실행은 영상 없이 돈다(녹화 스레드가 `unavailable`로 남긴다)."""
        source = self.platform
        probe = self._video_probe
        if probe is None or not callable(getattr(source, "video_frame", None)):
            return None
        gate = VideoGate()
        self.video = VideoRecorder(
            self.folder.path,
            gate,
            cast(VideoSource, source),
            self._video_factory,
            probe=probe,
            capture_timeout_ms=self.spec.capture_timeout_ms,
            late_wait_s=None,  # 늦은 인코더 대기의 포기는 마무리가 정한다 (영상 마무리 단계)
        ).start()
        self.pause.on_pause = gate.set_paused
        return gate

    def _run_program(self, program: Program, registry: Registry) -> _End:
        assert self.journal is not None
        gate = self._start_video()
        remaining_ms = max(1, self.deadline_at_ms - self.clock.now_ms())
        sink = self._sink = _JournalSink(self.journal)
        executor = Executor(
            registry,
            platform=self.platform,
            # 기한은 활성 시계(제어 스레드와 같은 시계), 경과는 실제 단조 시계 (M3 2.2)
            clock=self.clock,
            wall=SystemClock(self.token),
            cancel=self.token,
            artifacts=FileArtifacts(self.folder.path),
            sink=sink,
            invoker=RoutingInvoker(PluginRouter(self.routes) if self.routes else None),
            before_step=lambda point: self.pause.at_boundary(point, self._emit),
            pause_point=PollPoint(self.pause, self._emit),
            # 관측 세대: 멈춤 게이트가 재개할 때 올리고 실행기가 읽는다 (M3 2.4)
            epochs=self.pause.epochs,
            on_setting=self._record_setting,
            on_observed=self._record_observed,
            frames=self.frames,
            video=gate,
        )
        try:
            return self._run_executor(executor, program, remaining_ms)
        finally:
            if gate is not None and self.video is not None:
                # 판정이 정해졌다: 녹화 멈춤까지 기본 정책으로 다시 켜지지 않게
                # (취소로 비밀값 스텝이 풀린 뒤의 화면 포함)
                gate.close()
                self.video.request_stop()

    def _input_guard(self) -> Callable[[WindowRef | None], None] | None:
        """Agent 주체 실행의 금지 동작 판정 (M8 3.7·R6). 사양에 금지 목록이 없거나 비면 None."""
        items = forbidden.from_spec(self.spec.forbidden or ())
        if not items:
            return None
        root = self.spec.workspace_root
        platform = self.platform

        def guard(window: WindowRef | None) -> None:
            engines: Any = getattr(platform, "engines", None)
            sight: forbidden.PixelSight | None
            try:
                if engines is None:
                    raise PlatformUnavailable("이 플랫폼에는 비전·OCR 엔진이 없다")
                # 가짜 장면은 차례를 넘기지 않고 지금 화면을 본다 (실제 창은 캡처 한 장)
                peek = getattr(platform, "peek_frame", None)
                image = peek(window) if peek is not None else platform.capture(window, None)
                pixels = engines.pixels_of(image)
            except Exception:
                sight = None  # 프레임 없음 → 확인 못 함(거부)
            else:
                reader = None
                with contextlib.suppress(Exception):
                    reader = engines.text_reader()
                sight = forbidden.PixelSight(root, pixels, reader=reader)
            refusal = forbidden.judge(items, sight)
            if refusal is not None:
                # 걸린 항목(정책 값)과 고정 사유만 — 화면 글자는 남기지 않는다
                raise EngineError(refusal.code, refusal.message())

        return guard

    def _run_executor(self, executor: Executor, program: Program, remaining_ms: int) -> _End:
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
                    record_override=self.spec.record_override,
                    unattended=self.spec.unattended,
                    input_guard=self._input_guard(),
                ),
            )
            self._set_qa(program, trace=result.qa)
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

    def _set_qa(
        self,
        program: Program,
        *,
        trace: QaTrace | None = None,
        config_errors: Sequence[str] = (),
        not_applicable_reason: str | None = None,
    ) -> None:
        """`run.json.qa` (M8 3.5): 검증 노드 실행·통과, 쓴 치트, 설정 오류·미적용."""
        qa = run_qa(
            program,
            trace,
            config_errors=config_errors,
            not_applicable_reason=not_applicable_reason,
        )
        if qa is not None:
            self._run_json["qa"] = qa

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

    def _record_observed(self, seen: FrameRef) -> None:
        """실행에서 처음 관측한 창 (주 스레드, 한 번): 캡처 방식·클라이언트 크기·DPI를 바로
        남긴다 — runner가 죽어도 감독자가 다시 만드는 `run.json`에 남는다 (M3 2.6)."""
        self._run_json["observed"] = {
            "backend": seen.backend or "unknown",
            "client_size": [max(0, int(seen.client_size[0])), max(0, int(seen.client_size[1]))],
            "dpi": max(1, int(seen.dpi)),
        }
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
        # 판정이 확정됐다: 이 뒤로 전체 기한 감시를 끝낸다 (마무리는 판정을 바꾸지 않는다. 마무리의
        # 실제 시간 유예·감독자 사망 감시는 그대로)
        self.controller.finishing()
        self.controller.notify_stopping(self.controller.cancel_reason or "finish")
        # 녹화를 멈춘다 (신호만 먼저 — 녹화 기다림은 워커·액터 정리와 겹친다). 3초는 처음 보낸
        # `runner.stopping`부터 재고, 끝은 실제로 적용되는 가장 이른 종료 기한(감독자가 알린 하드
        # 종료·감독자 사망 뒤 자기 종료·stopping + 유예)에서 기록 여유를 뺀 때를 넘지 않는다
        recorder = self.video
        stop_at = self.controller.stopping_at or time.monotonic()
        if recorder is not None:
            recorder.request_stop()
        # 마무리의 모든 기다림(워커·액터·녹화)은 고정 예산이 아니라 `cutoff()`까지다. 기다리는
        # 동안 더 이른 종료 기한(마무리 중 도착한 외부 취소·감독자 사망)이 알려지면 제어기가
        # `wake`를 세워 바로 다시 잰다
        wake = threading.Event()
        self.controller.add_deadline_listener(wake)
        try:
            _faults.fault_point("runner.before_worker_shutdown")
            for worker in self.workers:
                with contextlib.suppress(Exception):
                    worker.shutdown(
                        spec.worker_cancel_grace_ms, cutoff=lambda: self._cutoff(stop_at)
                    )
            # 워커가 다 끝난 뒤 사용 표식을 놓는다 (runner가 죽으면 감독자가)
            self._release_plugins()
            quiesced = True
            if self.actor is not None:
                self.actor.stop(0)
                actor = self.actor
                self._wait_until(
                    lambda: actor.join(0),
                    time.monotonic() + spec.shutdown_grace_ms / 2 / 1000,
                    stop_at,
                    wake,
                    slice_s=_FINISH_SLICE_S,
                )
                quiesced = actor.quiesced
            # 녹화 스레드가 끝났는지 실제 시간 3초(`stopping_at`부터)까지, 단 `cutoff()`까지만
            # 본다. 안 끝났으면 그 실행의 영상을 포기하고 video/ 파일을 건드리지 않는다 (runner
            # 종료를 확인한 감독자가 지운다, 2차 검수 N2). 하드 종료보다 먼저 `run.end`·`run.json`을
            # 쓰게 한다. 녹화 스레드가 끝나거나 늦은 인코더 대기에 들어가도 `wake`가 선다 — 늦은
            # 대기는 멈춘 것이 아니므로 run.end 뒤 영상 마무리 단계로 넘긴다
            writer_done = True
            late = False
            if recorder is not None:
                recorder.notify_on_exit(wake)
                self._wait_until(
                    lambda: recorder.exited or recorder.awaiting_encoder,
                    stop_at + STOP_GRACE_S,
                    stop_at,
                    wake,
                )
                writer_done = recorder.exited and recorder.join(_FINISH_SLICE_S)
                late = not writer_done and recorder.awaiting_encoder
        finally:
            self.controller.remove_deadline_listener(wake)
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
            if not writer_done and not late:
                event["omitted"] = [{"kind": "video", "reason": "encoder_stuck"}]
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

        if late:
            writer_done = self._finish_video_late(run_end, stop_at)
        video = self._finalize_video(run_end, writer_done)
        _faults.fault_point("runner.before_run_json_final")
        assert end is not None
        data = finished_run_json(self._run_json, run_end)
        data["pause_count"] = self.pause.count
        data["retried_steps"] = 0 if self._sink is None else self._sink.retried_steps
        if video is not None:
            data["video"] = video
        try:
            write_run_json(self.folder.run_json, data)
        except Exception:
            traceback.print_exc()

        _faults.fault_point("runner.before_lease_release")
        self._release_lease(quiesced)
        self._close()
        return EXIT_OK

    def _finalize_video(
        self, run_end: Mapping[str, Any], writer_done: bool
    ) -> dict[str, Any] | None:
        """`run.json`의 영상 요약. 녹화 스레드가 끝났을 때만 마무리한다(`finalize_video`)."""
        if self.video is None:
            return None
        if not writer_done:
            # 파일은 건드리지 않는다: 감독자가 runner 종료를 확인한 뒤 같은 함수로 마무리한다.
            # 요약은 그 마무리가 낼 색인을 미리 계산한 것이라 복구 뒤에도 같다 (vreview_3)
            try:
                index = preview_video(self.folder.path, run_end)
            except Exception:
                traceback.print_exc()
                index = None
            return None if index is None else video_summary(index)
        try:
            index = finalize_video(self.folder.path, run_end)
        except Exception:
            traceback.print_exc()
            return None  # 감독자 복구 경로가 다시 마무리한다
        return None if index is None else video_summary(index)

    def _finish_video_late(self, run_end: Mapping[str, Any], stop_at: float) -> bool:
        """영상 마무리 단계 (모듈 설명). `run.end` 뒤라 판정·종료 코드는 바뀌지 않는다. 녹화
        스레드가 끝났으면(조각을 썼든 포기를 기록했든) True — 그때만 `finalize_video`를 부른다."""
        recorder = self.video
        assert recorder is not None and self.controller is not None
        keep, _ = keep_failed_only(run_end)
        wanted = keep or "on" in recorder.late_modes
        wait_s = finish_wait_from_env() or VIDEO_FINISH_MAX_MS / 1000
        wake = threading.Event()
        self.controller.add_deadline_listener(wake)
        recorder.notify_on_exit(wake)
        controller = self.controller
        try:
            granted = False
            if wanted and not controller.external_stop:
                granted = self._request_video_finishing(wait_s, stop_at)
            if granted:
                print(
                    f"영상 인코더가 아직 준비되지 않아 run.end 뒤 최대 {wait_s:.0f}초 더 기다려 "
                    "모은 프레임을 쓴다",
                    file=sys.stderr,
                )
                began = time.monotonic()
                # 외부 취소·감독자 사망이 오면 남은 기한까지 기다리지 않고 바로 포기한다
                self._wait_until(
                    lambda: recorder.exited or controller.external_stop,
                    began + wait_s,
                    stop_at,
                    wake,
                )
            if not recorder.exited:
                recorder.abandon_encoder_wait()
                if granted:
                    print(
                        "영상 마무리 단계가 끝나도 인코더가 준비되지 않아 모은 프레임을 버렸다 "
                        "(video: omitted/encoder_not_ready)",
                        file=sys.stderr,
                    )
                # 포기는 대기에서 바로 풀린다. 그새 시험이 끝나 쓰는 중이면 남은 기한까지 본다
                self._wait_until(lambda: recorder.exited, math.inf, stop_at, wake)
        finally:
            self.controller.remove_deadline_listener(wake)
        return recorder.exited and recorder.join(_FINISH_SLICE_S)

    def _request_video_finishing(self, wait_s: float, stop_at: float) -> bool:
        """감독자에게 영상 마무리 단계를 청한다. 허락되면 감독자가 다시 건 하드 종료 기한을 제어기·
        자기 종료 감시자에 알리고 True. 답이 없거나(채널 끊김·기한) 거절이면 False."""
        assert self.controller is not None and self.watchdog is not None
        peer = self.peer
        timeout = min(_VIDEO_FINISH_CALL_S, self._cutoff(stop_at) - time.monotonic())
        if peer is None or timeout <= 0:
            return False
        try:
            reply = peer.call(
                "runner.video_finishing", {"wait_ms": max(1, int(wait_s * 1000))}, timeout=timeout
            )
        except Exception:
            return False
        received = time.monotonic()
        if not isinstance(reply, dict) or reply.get("granted") is not True:
            return False
        grace_s = self.spec.shutdown_grace_ms / 1000
        # 기한은 run.cancel과 같은 규칙: 절대 시각과 받은 시각 + 남은 시간 중 이른 쪽, 말이 안
        # 되는 절대 시각(이미 지남·청한 것보다 멂)은 믿지 않는다 (감독자가 타이머를 쓰지 않으면
        # 청한 만큼)
        at = received + wait_s + grace_s
        left = cast(dict[str, Any], reply).get("hard_stop_in_ms")
        absolute = cast(dict[str, Any], reply).get("hard_stop_at_mono")
        if isinstance(left, int) and not isinstance(left, bool):
            at = min(at, received + left / 1000)
        if isinstance(absolute, (int, float)) and not isinstance(absolute, bool):
            if absolute <= received or absolute > received + wait_s + grace_s + _CLOCK_SLACK_S:
                return False
            at = min(at, float(absolute))
        self.controller.extend_finish(at)
        self.watchdog.extend(at)
        return True

    def _cutoff(self, stop_at: float) -> float:
        """마무리 기다림의 끝 (단조 시각): 지금 아는 가장 이른 종료 기한에서 기록 여유를 뺀 때."""
        grace_ms = self.spec.shutdown_grace_ms
        assert self.controller is not None
        finish_by = self.controller.finish_by(grace_ms)
        if finish_by is None:
            finish_by = stop_at + grace_ms / 1000
        return finish_by - finish_reserve_s(grace_ms)

    def _wait_until(
        self,
        done: Callable[[], bool],
        cap_at: float,
        stop_at: float,
        wake: threading.Event,
        *,
        slice_s: float | None = None,
    ) -> bool:
        """`done()`이 참이 되거나 `min(cap_at, cutoff())`가 지날 때까지 기다린다. `done()`을 준다.

        `wake`가 서면(종료 기한 갱신·기다리는 대상의 끝) 바로 깨어 다시 잰다. 신호를 놓치지 않게
        상태를 읽기 전에 지운다. `done`의 변화를 신호로 받지 못하는 대상은 `slice_s`마다 본다."""
        while True:
            wake.clear()
            if done():
                return True
            left = min(cap_at, self._cutoff(stop_at)) - time.monotonic()
            if left <= 0:
                return done()
            wake.wait(left if slice_s is None else min(left, slice_s))

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
        if end.secret:
            event["secret_paths"] = ["/reason"]
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
        for worker in self.workers:
            worker.close_job()  # 남은 워커 자손을 끝낸다 (shutdown이 이미 닫았으면 아무것도 안 함)
        self._release_plugins()
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


OCR_PREPARE_NOTE_MS: Final = 1000
"""OCR 엔진 준비가 이만큼 넘게 걸리면 runner stderr에 남긴다."""


def _uses_ocr(program: Program, registry: Registry, installed: Collection[str]) -> bool:
    """글자를 읽는 코어 노드, 또는 `capture` 효과의 설치 플러그인 노드(워커가 `ctx.ocr`를 부를 수
    있다 — BACKLOG sfix_2: 첫 OCR 준비가 노드 기한 안에서 흐르지 않게 시작 때 준비하고, 실행기가
    그 노드 전에 기다린다). 개발 모듈 노드는 지금처럼 준비를 걸지 않는다."""
    for graph in program.graphs.values():
        for node in graph.nodes.values():
            if node.type in OCR_NODE_TYPES:
                return True
            nodedef = registry.get(node.type)
            if nodedef is not None and nodedef.plugin in installed and "capture" in nodedef.effects:
                return True
    return False


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
