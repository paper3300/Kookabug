"""실행기: 그래프를 한 프로세스 안에서 실행하고 판정한다.

    program = load_program(workspace, "tests/inventory_open.graph.json")
    result = Executor(platform=FakePlatform(frames=[...]), clock=FakeClock()).run(program)
    result.verdict  # "pass" | "fail" | "skipped" | "error"

- 실행 전 검증을 통과한 그래프만 받는다 (`ExecOptions(validate=False)`는 런타임 방어 테스트용)
- exec 흐름: entry에서 출구의 `next`를 따라간다. 연결 안 된 출구 = 경로 끝
- 연결 안 된 fail 출구 → 즉시 처리되지 않은 fail. 연결된 fail 출구 → 프레임의 대기 중인 fail 목록에
  더하고 분기한다. 종료 노드·공개 exit에 닿으면 해소, 경로 끝에서 남아 있으면 처리되지 않은 fail
  (원인은 목록의 첫 스텝). 대기 목록은 다른 스텝이 성공해도 지우지 않는다 (G14)
- error·취소·전체 기한 초과는 호출 스택을 따라 바로 위로 전파한다
- 서브그래프 호출은 새 프레임 (변수는 이어받지 않고, 현재 대상 창은 이어받는다)
- 반복(`loops`): 반복 노드에 도착할 때마다 스텝 하나, 경로 끝은 가장 안쪽 반복 노드로 돌아간다
  (그 범위의 출력을 지운다). 반복 안 스텝의 이벤트에 `iteration`
- 재시도(`retry`): 노드 함수가 재시도 출구로 나오면 출구를 확정하기 전에 다시 부른다. 중간 시도는
  `attempt.end`, 재시도 끝 성공은 `step.end`의 `retried: true`
- 기록 정책: 프레임마다 실효 정책(`Frame.record_policy`), 스텝마다 노드 `record`와 입력의 비밀값을
  더해 `Recorder`가 집행한다. 노드가 error로 끝나면 그 스텝의 마지막 캡처를 예외 스크린샷으로.
  생략은 `step.end.omitted` (스키마 v0 6장 "화면에 찍힌 비밀값")
- 공통 입력 `window` (M1 2.8): 노드 함수 인자·서브그래프 입력·출력으로 넘기지 않고 떼어 그 스텝의
  대상 창(서브그래프 호출이면 안쪽 프레임의 시작 창)으로만 쓴다. `ctx.set_window`는 호출 프레임의
  현재 창을 다음 스텝부터 바꾼다
- 입력 직전 재검증 실패(`StaleObservation`)는 출구 없는 처리되지 않은 fail(`stale_observation`)이다.
  노드가 삼키고 끝내도 같다
- 관측 세대 (M3 2.4, `engine.provenance`): 값 옆에 출처(가장 오래된 관측의 세대)를 붙여 출력 표·
  순수 노드 계산·변수·호출 경계로 옮긴다. 스텝 입력을 계산한 직후 노드를 부르기 전에 디버거 재개
  전 관측에서 온 입력이 있으면(예외 목록·`input` 노드의 `Match` 제외) 노드를 부르지 않고
  `stale_observation`이다. 출력 출처는 그 스텝의 관측 바닥이다
- 프레임 저장소 (M1 2.7): 스텝 출력에 든 캡처는 출력 참조로 표시하고, 서브그래프 안 스텝이 닫힐 때
  그 마지막 캡처를 부른 스텝의 증거로 넘긴다
- 실패 증거 (M1 2.15): fail 출구로 나간 스텝(서브그래프 호출이면 그 호출 스텝)과 재검증 실패
  스텝은 그 스텝 아래(자기와 안쪽 스텝)의 마지막 캡처를 `steps/<스텝>_fail.png`로 한 번 남긴다.
  처리되지 않은 fail의 원인 스텝(실패 위치)은 늘 이 스텝들 중 하나다 — 연결 안 된 출구로 바로
  확정되든, 연결된 분기가 경로 끝에서 확정되든. 연결된 fail 분기가 뒤에서 처리돼도 그 스텝의
  증거는 남는다(fail 출구로 나간 사실의 증거). 안쪽에서 확정돼 올라오는 fail은 지나가는 호출
  스텝이 다시 남기지 않는다
- 증거 프레임·썸네일 (M3 2.6, `Recorder`): 실패·예외 증거를 남기는 스텝은 첫·중간 캡처와
  `step.end.evidence`(코어 찾기·대기 노드의 fail 출구면 매칭 후보도), 직접 캡처한 스텝은 닫을 때
  썸네일. 반복이 새 회차를 시작하면 그 범위의 두 회차 전 썸네일을 지운다
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final, Literal

from kookabug_core.diagnostics import Diagnostic, has_errors
from kookabug_core.engine.cancel import Cancelled, CancelToken, DeadlineExceeded
from kookabug_core.engine.clock import Clock, SystemClock
from kookabug_core.engine.context import (
    DEFAULT_CAPTURE_TIMEOUT_MS,
    ArtifactStore,
    Mark,
    Platform,
    PreparingPlatform,
    Runtime,
    StepContext,
)
from kookabug_core.engine.debug import PausePoint, StepPoint
from kookabug_core.engine.errors import EngineError, error_code
from kookabug_core.engine.events import EventSink, classified_value, mark_secret
from kookabug_core.engine.frame import Frame, FrameExit
from kookabug_core.engine.invoker import InProcessInvoker, NodeInvoker
from kookabug_core.engine.loops import (
    REENTRY_INPUTS,
    LoopScopes,
    enter,
    iteration,
    path_end,
    resuming,
)
from kookabug_core.engine.platform_fake import FakePlatform, MemoryArtifacts
from kookabug_core.engine.provenance import Epochs, Origin, StepTrace
from kookabug_core.engine.pure import nodedef_of, resolve_traced
from kookabug_core.engine.retry import retry_policy
from kookabug_core.engine.verdict import Cause, Facts, Judgement, Terminal, Verdict, judge
from kookabug_core.ir import GRAPH_CALL, GRAPH_ENTRY, Node
from kookabug_core.loader import MAX_CALL_DEPTH, Program
from kookabug_core.record.artifacts import CANDIDATE_NODES, FrameRegistry, Recorder
from kookabug_core.record.policy import (
    RecordPolicy,
    VideoMode,
    graph_source,
    node_inputs_source,
    node_source,
    workspace_policy,
)
from kookabug_core.record.video import VideoGate
from kookabug_core.registry import NodeDef, Registry, default_registry
from kookabug_core.validate import validate
from kookabug_core.validate.pins import COMMON_WINDOW, node_pins
from kookabug_core.workspace import WORKSPACE_FILE, SettingLookup
from kookabug_sdk import Result, Secret, SecretMessage
from kookabug_sdk.context import Deadline
from kookabug_sdk.errors import StaleObservation
from kookabug_sdk.types import FrameRef, WindowRef

if TYPE_CHECKING:
    from kookabug_core.agents.judge import JudgeEnv

__all__ = [
    "DEFAULT_DEADLINE_MS",
    "ExecOptions",
    "Executor",
    "GraphInvalid",
    "RunResult",
    "run_record_policy",
]

DEFAULT_DEADLINE_MS: Final = 30 * 60 * 1000
"""테스트 전체 기한 기본값 30분 (G11). 노드별 타임아웃과 별개다."""

_TERMINALS: Final[dict[str, Terminal]] = {
    "test_pass": "pass",
    "test_fail": "fail",
    "test_skip": "skip",
}
_LOOPS: Final = frozenset({"repeat", "while"})
STALE_OBSERVATION: Final = "stale_observation"
"""입력 직전 재검증 실패의 원인 코드 (처리되지 않은 fail, 출구 없음 — M1 2.4)."""


def run_record_policy(program: Program, root: Any | None = None) -> RecordPolicy:
    """실행의 기본 기록 정책: 워크스페이스 `record` 위에 테스트 그래프의 `record` (스텝 층 전).
    워크스페이스에 `record.video`가 없으면 영상은 `failed_only` (M3). runner가 첫 스텝 전 인코더
    준비를 기다릴지(영상이 꺼진 실행은 기다리지 않음)도 이것으로 정한다."""
    root = program.graphs.get(program.root) if root is None else root
    workspace_record = program.workspace.config.get("record")
    policy = workspace_policy(
        workspace_record if isinstance(workspace_record, Mapping) else None,
        graph_source(WORKSPACE_FILE),
    )
    return policy if root is None else policy.layer(root.record, graph_source(root.path))


@dataclass(frozen=True, slots=True)
class ExecOptions:
    """실행기 옵션. 설정값(`$setting`)·프로필은 로더 옵션(`RunOptions`)이다.

    `graph_prefix`는 `step.end.graph`(서브그래프 경로) 앞에 붙인다. runner는 스냅샷에서 읽은
    프로그램을 돌리므로 실행 폴더 기준 `snapshot/`을 준다.

    `collect_events=False`면 이벤트를 `RunResult.events`에 모으지 않고 싱크로만 보낸다 (runner:
    긴 실행에서 메모리가 이벤트 수에 비례해 늘지 않게).

    `capture_timeout_ms`는 관측 호출의 설정 기한(`run.capture_timeout_ms`, M1 2.6)이다.
    """

    deadline_ms: int = DEFAULT_DEADLINE_MS
    validate: bool = True
    run_id: str | None = None
    graph_prefix: str = ""
    collect_events: bool = True
    capture_timeout_ms: int = DEFAULT_CAPTURE_TIMEOUT_MS


@dataclass(frozen=True)
class RunResult:
    """실행 결과. `failure_step`·`failure_path`는 판정 원인 스텝 (pass면 None)."""

    run: str
    verdict: Verdict
    code: str
    reason: str
    failure_step: str | None
    failure_path: tuple[str, ...] | None
    events: list[dict[str, Any]]
    diagnostics: list[Diagnostic] = field(default_factory=list[Diagnostic])
    recorder: Recorder | None = None
    """스텝별 기록 정책 (실행 뒤 영상 정리 `video_allowed` 등에 쓴다)."""
    reason_secret: bool = False
    """`reason`에 비밀값이 들어 있다 (`run.end.secret_paths`, 에이전트용 분류 M5)."""


class GraphInvalid(Exception):
    """실행 전 검증 오류가 있어 실행하지 않았다."""

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        errors = [d for d in diagnostics if d.severity == "error"]
        summary = "; ".join(f"{d.code} {d.file or ''}{d.pointer or ''}" for d in errors[:5])
        super().__init__(f"실행 전 검증 오류 {len(errors)}건: {summary}")
        self.diagnostics = diagnostics


class Executor:
    def __init__(
        self,
        registry: Registry | None = None,
        *,
        platform: Platform | None = None,
        clock: Clock | None = None,
        cancel: CancelToken | None = None,
        artifacts: ArtifactStore | None = None,
        sink: EventSink | None = None,
        invoker: NodeInvoker | None = None,
        before_step: Callable[[StepPoint], None] | None = None,
        on_setting: Callable[[SettingLookup], None] | None = None,
        frames: FrameRegistry | None = None,
        wall: Clock | None = None,
        pause_point: PausePoint | None = None,
        epochs: Epochs | None = None,
        video: VideoGate | None = None,
        on_observed: Callable[[FrameRef], None] | None = None,
        judge_env: JudgeEnv | None = None,
    ) -> None:
        """`sink`는 이벤트를 더 보낼 곳이다 (`RunResult.events`에는 `collect_events`일 때 모인다).

        `invoker`는 노드 함수 실행 경계다 (기본: 같은 프로세스, M0b: 워커 프로세스).
        `before_step(위치)`는 스텝을 시작하기 직전(`step.start` 전) 확인 지점에서 불린다 — runner의
        경계 멈춤이 여기서 기다린다. `Cancelled`를 던지면 그 스텝은 시작하지 않고 실행이 끝난다.
        `pause_point`가 있으면 코어 노드의 `ctx.sleep`이 폴링 확인 지점이다(M3 2.2).
        `on_setting(조회 결과)`는 노드가 `ctx.setting()`으로 설정을 읽을 때마다 불린다
        (실행 조건 기록).
        `frames`는 프레임 저장소다(M1 2.7). 주면 캡처 픽셀을 저장소에 두고 노드에는 참조 이미지를
        준다(플랫폼이 `PixelPlatform`일 때).
        시계를 주지 않으면 취소로 깨는 `SystemClock`이다. `clock`은 기한 시계, `wall`은 경과
        (`duration_ms`) 시계다 — 주지 않으면 `clock`으로 잰다. runner는 `clock`에 멈춘 시간을 뺀
        활성 시계, `wall`에 실제 단조 시계를 준다.
        `epochs`는 관측 세대다(M3 2.4) — runner는 멈춤 게이트가 재개할 때 올리는 것을 준다. 주지
        않으면 실행마다 새로 0에서 시작하고 오르지 않는다(멈춤 없는 실행 = M1 동작).
        `video`는 녹화 게이트다(M3 2.5): 스텝마다 `step.start` 전에 보류로 바꾸고, 입력 계산·비밀값
        분류 뒤 그 스텝의 영상 정책으로 정하고, 스텝이 닫히면(정상·예외·취소) 스택에서 뺀다.
        `on_observed(관측)`은 실행에서 처음 창을 관측했을 때 한 번 불린다(캡처 방식·클라이언트
        크기·DPI — runner가 `run.json.observed`로 남긴다, M3 2.6).
        플랫폼이 `PreparingPlatform`이면 노드 함수를 부르기 직전(시도마다, 노드가 자기 기한을 만들기
        전)에 `before_node`로 그 노드가 쓸 엔진 준비를 기다린다 (OCR, M2 사람 확인 S 결함 ②).
        `judge_env`는 판단 노드의 바깥(사용자 설정 폴더·비밀값·임시 폴더, M5 3.11)이다 — 주지 않으면
        이 프로세스 환경에서 정한다.
        """
        self.registry = registry or default_registry()
        self.invoker: NodeInvoker = invoker or InProcessInvoker()
        self.platform: Platform = platform or FakePlatform()
        self.cancel = cancel or CancelToken()
        self.clock: Clock = clock or SystemClock(self.cancel)
        self.artifacts: ArtifactStore = artifacts or MemoryArtifacts()
        self.sink = sink
        self.before_step = before_step
        self.on_setting = on_setting
        self.frames = frames
        self.wall = wall
        self.pause_point = pause_point
        self.epochs = epochs
        self.video = video
        self.on_observed = on_observed
        self.judge_env = judge_env

    def run(self, program: Program, options: ExecOptions | None = None) -> RunResult:
        options = options or ExecOptions()
        diagnostics: list[Diagnostic] = []
        if options.validate:
            diagnostics = validate(program, self.registry)
            if has_errors(diagnostics):
                raise GraphInvalid(diagnostics)
        root = program.graphs.get(program.root)
        if root is None:
            raise GraphInvalid(program.diagnostics)

        events: list[dict[str, Any]] = []
        collect = options.collect_events

        def emit(event: dict[str, Any]) -> None:
            if collect:
                events.append(event)
            if self.sink is not None:
                self.sink.emit(event)

        run_id = options.run_id or uuid.uuid4().hex[:8]
        # 증거 시각은 경과 시계로 잰다 (스텝 시작·캡처·끝 모두 같은 벽시계, M3 2.6)
        wall = self.wall if self.wall is not None else self.clock
        recorder = Recorder(self.artifacts, self.frames, clock=wall.now_ms)
        runtime = Runtime(
            run=run_id,
            program=program,
            registry=self.registry,
            invoker=self.invoker,
            platform=self.platform,
            recorder=recorder,
            clock=self.clock,
            cancel=self.cancel,
            deadline=Deadline(self.clock, self.clock.now_ms() + options.deadline_ms),
            deadline_ms=options.deadline_ms,
            emit_to=emit,
            on_setting=self.on_setting,
            capture_timeout_ms=options.capture_timeout_ms,
            wall=self.wall,
            pause_point=self.pause_point,
            epochs=self.epochs if self.epochs is not None else Epochs(),
            on_observed=self.on_observed,
            judge_env=self.judge_env,
        )
        policy = run_record_policy(program, root)
        recorder.redact_secrets = policy.redact_secrets
        top = Frame(root, (), None, 0, {}, record_policy=policy)
        if self.video is not None:
            self.video.set_base(policy.video)
        judgement = _Run(runtime, options.graph_prefix, self.before_step, self.video).execute(top)
        cause = judgement.cause if judgement.verdict != "pass" else None
        return RunResult(
            run=run_id,
            verdict=judgement.verdict,
            code=judgement.code,
            reason=judgement.reason,
            failure_step=cause.step if cause is not None else None,
            failure_path=cause.path if cause is not None else None,
            events=events,
            diagnostics=diagnostics,
            recorder=recorder,
            reason_secret=judgement.secret,
        )


# ---------------------------------------------------------------- 전파


class _Halt(Exception):
    """프레임을 끝내고 위로 올라가는 것. 지나가는 호출 스텝은 `status`로 끝난다."""

    status: Literal["success", "fail", "error", "cancelled"]

    def __init__(self, cause: Cause) -> None:
        super().__init__(cause.message)
        self.cause = cause


class _Error(_Halt):
    def __init__(self, cause: Cause) -> None:
        super().__init__(cause)
        self.status = "cancelled" if cause.code == "cancelled" else "error"


class _Unhandled(_Halt):
    status = "fail"


class _Terminal(_Halt):
    status = "success"

    def __init__(self, kind: Terminal, cause: Cause) -> None:
        super().__init__(cause)
        self.kind: Terminal = kind


@dataclass(frozen=True, slots=True)
class _TerminalEnd:
    kind: Terminal
    reason: str | None
    secret: bool = False
    """`reason`이 비밀값이었다."""


type _Outcome = Result | FrameExit | _TerminalEnd


def _with_reason(cancel: CancelToken, exc: BaseException) -> BaseException:
    """다른 곳(입력 액터 게이트 등)이 던진 `Cancelled`도 실행의 취소 사유로 기록한다: 기한 초과로
    취소됐으면 `DeadlineExceeded`."""
    if (
        isinstance(exc, Cancelled)
        and not isinstance(exc, DeadlineExceeded)
        and cancel.reason == "deadline_exceeded"
    ):
        return DeadlineExceeded("테스트 전체 기한을 넘었다")
    return exc


def _cause_of(step: str | None, path: tuple[str, ...], exc: BaseException) -> Cause:
    if isinstance(exc, DeadlineExceeded):
        return Cause(step, path, "deadline_exceeded", str(exc) or "테스트 전체 기한을 넘었다")
    if isinstance(exc, Cancelled):
        return Cause(step, path, "cancelled", "실행이 취소됐다")
    assert isinstance(exc, Exception)
    if isinstance(exc, EngineError):
        return Cause(step, path, exc.code, exc.message)
    text = str(exc)
    message = f"{type(exc).__name__}: {text}" if text else type(exc).__name__
    return Cause(step, path, error_code(exc), message)


# ---------------------------------------------------------------- 실행 하나


class _Run:
    def __init__(
        self,
        runtime: Runtime,
        graph_prefix: str,
        before_step: Callable[[StepPoint], None] | None = None,
        video: VideoGate | None = None,
    ) -> None:
        self.rt = runtime
        self.graph_prefix = graph_prefix
        self.before_step = before_step
        self.video = video
        self.steps = 0
        self.assertions = 0
        self.scopes = LoopScopes(runtime.program, runtime.registry)

    def _value(self, value: Any, event: dict[str, Any], field: str) -> Any:
        """이벤트 `event`의 `field`(pointer)에 남길 값 (비밀값은 `record.redact_secrets`가 켜진
        실행만 가린다, D3). 비밀값이 있던 자리는 `secret_paths`로 표시한다 (M5 3.8)."""
        value, paths = classified_value(
            value, redact=self.rt.recorder.redact_secrets, pointer=field
        )
        mark_secret(event, paths)
        return value

    def _message(
        self, message: str | SecretMessage | None, event: dict[str, Any] | None = None
    ) -> str | None:
        """노드 메시지 (비밀값 메시지는 가림이 켜진 실행만 가린 글, D3). `event`를 주면 비밀값
        메시지일 때 그 이벤트의 `/message`를 표시한다."""
        if isinstance(message, SecretMessage):
            if event is not None:
                mark_secret(event, ["/message"])
            return message.masked if self.rt.recorder.redact_secrets else message.raw
        return message

    def execute(self, frame: Frame) -> Judgement:
        try:
            self._run_frame(frame)
            facts = Facts(assertions_passed=self.assertions)
        except _Terminal as halt:
            facts = Facts(
                terminal=halt.kind, terminal_cause=halt.cause, assertions_passed=self.assertions
            )
        except _Unhandled as halt:
            facts = Facts(unhandled_fail=halt.cause, assertions_passed=self.assertions)
        except _Error as halt:
            facts = Facts(error=halt.cause, assertions_passed=self.assertions)
        return judge(facts)

    # ------------------------------------------------------------ 프레임

    def _run_frame(self, frame: Frame) -> FrameExit | None:
        """프레임을 entry부터 실행한다. 공개 exit로 끝나면 그 출구, 경로 끝이면 None."""
        entries = [n for n in frame.graph.nodes.values() if n.type == GRAPH_ENTRY]
        if len(entries) != 1:
            raise _Error(
                Cause(
                    None,
                    frame.path,
                    "entry_count",
                    f"'{frame.graph.path}'에 core.graph.entry가 {len(entries)}개다",
                )
            )
        node: Node | None = entries[0]
        while node is not None:
            outcome = self._step(frame, node)
            if isinstance(outcome, FrameExit):
                return outcome
            node = outcome if outcome is not None else self._end_of_path(frame)
        return None

    def _end_of_path(self, frame: Frame) -> Node | None:
        """경로 끝. 대기 중인 fail이 남았으면 처리되지 않은 fail, 아니면 이어 갈 노드(반복)."""
        if frame.pending:
            first = frame.pending[0]
            raise _Unhandled(
                replace(
                    first,
                    message=f"{first.message} (연결된 fail 분기가 종료 노드에 닿지 않고 끝났다)",
                )
            )
        return self._path_end(frame)

    def _path_end(self, frame: Frame) -> Node | None:
        """반복 범위 안의 경로 끝이면 가장 안쪽 반복 노드로 돌아간다 (암묵적 귀환)."""
        loop = path_end(frame)
        return frame.graph.nodes[loop] if loop is not None else None

    def _iteration(self, frame: Frame, node: Node) -> int | None:
        """반복 안 스텝의 회차 (0부터)."""
        return iteration(frame, node.id)

    # ------------------------------------------------------------ 스텝

    def _step(self, frame: Frame, node: Node) -> Node | FrameExit | None:
        """노드 하나를 실행한다. 다음 노드(경로 끝이면 None) 또는 프레임 끝을 돌려준다."""
        rt = self.rt
        self.steps += 1
        step = f"s{self.steps}"
        path = frame.node_path(node.id)
        start: dict[str, Any] = {
            "attempt": 1,
            "event": "step.start",
            "node": node.id,
            "parent": frame.parent,
            "path": list(path),
            "step": step,
        }
        end: dict[str, Any] = {"attempt": 1, "event": "step.end", "step": step}
        iteration = self._iteration(frame, node)
        if iteration is not None:
            start["iteration"] = end["iteration"] = iteration
        if self.before_step is not None:
            try:
                entry = node.type == GRAPH_ENTRY
                self.before_step(StepPoint(step, node.id, frame.graph.path, path, entry=entry))
            except Cancelled as exc:
                # 시작하지 않은 스텝: step.start·step.end 없이 위로 (원인 스텝 없음)
                raise _Error(_cause_of(None, frame.path, _with_reason(rt.cancel, exc))) from exc
        gate = self.video
        if gate is None:
            return self._open_step(frame, node, step, path, start, end)
        # 녹화 게이트: step.start 전에 보류 차단, 스텝이 스택에서 빠질 때(정상·예외·취소) 뺀다
        gate.hold(step)
        try:
            return self._open_step(frame, node, step, path, start, end)
        finally:
            gate.release(step)

    def _open_step(
        self,
        frame: Frame,
        node: Node,
        step: str,
        path: tuple[str, ...],
        start: dict[str, Any],
        end: dict[str, Any],
    ) -> Node | FrameExit | None:
        rt = self.rt
        rt.emit(start)
        rt.recorder.open_step(
            step,
            frame.record_policy.layer(node.record, node_source(frame.graph.path, node.id)),
            call=node.type == GRAPH_CALL,
            loops=frame.loop_chain(node.id),
        )
        began = rt.mark()

        try:
            try:
                rt.check()
                nodedef = nodedef_of(rt, node)
                if nodedef.pure:
                    raise EngineError(
                        "exec_into_pure",
                        f"'{node.id}'은(는) 순수 노드라 exec 흐름으로 실행할 수 없다",
                    )
                inputs, origins = resolve_traced(
                    rt, frame, node, step, self._recompute(frame, node, nodedef)
                )
                rt.recorder.note_inputs(step, inputs, node_inputs_source(frame.graph.path, node.id))
                trace = StepTrace(
                    node.type,
                    input_effect="input" in nodedef.effects,
                    inputs=origins,
                    values=inputs,
                )
                window, inputs = self._common_window(frame, node, nodedef, inputs)
                if self.video is not None:
                    # 비밀값 분류가 끝났다: 보류를 이 스텝의 영상 정책으로 정한다 (M3 2.5)
                    policy = rt.recorder.policy(step)
                    self.video.classify(
                        step,
                        self._video_mode(frame, node, policy.policy),
                        secret=policy.secret is not None,
                        window=window if window is not None else frame.current_window,
                    )
                # 스텝 입력 검사: 디버거 재개 전 관측에서 온 입력이면 노드를 부르지 않는다 (M3 2.4)
                stale = trace.stale_inputs(rt.epoch)
                if stale is not None:
                    raise StaleObservation(stale)
                rt.check()
                outcome = self._dispatch(frame, node, nodedef, step, inputs, end, trace, window)
                # 노드가 돌아온 뒤에도 본다: 실행 중 생긴 취소·기한 초과를 성공으로 확정하지 않는다
                rt.check()
                target = self._target(frame, node, outcome)
            except _Halt:
                raise
            except StaleObservation as exc:
                # 입력 직전 재검증 실패: 출구 없는 처리되지 않은 fail (노드가 잡지 않는다)
                detail = str(exc) or "관측 뒤 창이 바뀌어 입력하지 않았다"
                raise _Unhandled(Cause(step, path, STALE_OBSERVATION, detail)) from exc
            except (Cancelled, Exception) as exc:
                raise _Error(_cause_of(step, path, _with_reason(rt.cancel, exc))) from exc
        except _Halt as halt:
            # 이 스텝의 고장이거나, 호출한 서브그래프 안에서 올라오는 것
            end.update(status=halt.status, exit=None, outputs={})
            if isinstance(halt, _Error):
                end["error"] = {"code": halt.cause.code, "message": halt.cause.message}
                if halt.cause.secret:
                    mark_secret(end, ["/error/message"])
                if halt.status == "error" and halt.cause.step == step:
                    # 이 스텝의 오류만. 서브그래프 안쪽 오류는 안쪽 스텝이 이미 처리했다
                    self._evidence(node, step, "예외 스크린샷", self.rt.recorder.error_screenshot)
            elif isinstance(halt, _Unhandled):
                end["message"] = halt.cause.message
                if halt.cause.secret:
                    mark_secret(end, ["/message"])
                if halt.cause.step == step:
                    # 이 스텝에서 확정된 것만. 안쪽에서 올라오는 것은 안쪽 스텝이 이미 남겼다
                    if halt.cause.code == STALE_OBSERVATION:
                        end["message"] = f"{STALE_OBSERVATION}: {halt.cause.message}"
                    self._evidence(node, step, "실패 증거", self.rt.recorder.fail_screenshot)
            self._finish(end, began, frame, node)
            raise

        if isinstance(outcome, _TerminalEnd):
            end.update(status="success", exit=None, outputs={})
            self._finish(end, began, frame, node)
            default = {
                "pass": "core.test.pass에 도달했다",
                "fail": "core.test.fail에 도달했다",
                "skip": "core.test.skip에 도달했다",
            }[outcome.kind]
            cause = Cause(
                step,
                path,
                f"test_{outcome.kind}",
                outcome.reason or default,
                secret=outcome.secret and bool(outcome.reason),
            )
            raise _Terminal(outcome.kind, cause)
        if isinstance(outcome, FrameExit):
            end.update(status="success", exit=None)
            end["outputs"] = self._value(outcome.outputs, end, "/outputs")
            self._finish(end, began, frame, node)
            return outcome

        # 출력 출처 = 스텝 관측 바닥 (끝난 시각의 세대가 아니다, M3 2.4)
        frame.record(node.id, outcome.outputs, trace.output_origins(outcome.outputs))
        rt.recorder.note_outputs(outcome.outputs)
        if nodedef.assertion and outcome.kind == "ok":
            self.assertions += 1
        if outcome.kind == "ok" and end["attempt"] > 1:
            # 마지막 확인까지 통과해 성공이 확정된 뒤에만 표시한다 (중단된 스텝에는 없다)
            end["retried"] = True
        end.update(status="success" if outcome.kind == "ok" else "fail", exit=outcome.exit)
        end["outputs"] = self._value(outcome.outputs, end, "/outputs")
        secret_message = isinstance(outcome.message, SecretMessage)
        message = self._message(outcome.message)
        if outcome.kind == "fail" and message:
            end["message"] = message
            if secret_message:
                mark_secret(end, ["/message"])
        if outcome.kind == "fail":
            # fail 출구로 나간 스텝은 연결과 상관없이 자기(와 안쪽) 프레임으로 증거를 남긴다 —
            # 연결된 분기가 경로 끝에서 처리되지 않은 fail이 되면 이 스텝이 실패 위치다 (M1 2.15).
            # 코어 찾기·대기 노드는 마지막 찾기의 매칭 후보도 (M3 2.6)
            candidates = node.type in CANDIDATE_NODES
            self._evidence(
                node,
                step,
                "실패 증거",
                lambda s: self.rt.recorder.fail_screenshot(s, candidates=candidates),
            )
        self._finish(end, began, frame, node)
        if outcome.kind == "fail":
            cause = Cause(
                step,
                path,
                "fail",
                message or f"'{node.id}'이(가) fail 출구 '{outcome.exit}'로 나갔다",
                secret=secret_message and bool(message),
            )
            if target is None:
                raise _Unhandled(cause)
            frame.pending.append(cause)
        return target

    def _video_mode(self, frame: Frame, node: Node, policy: RecordPolicy) -> VideoMode:
        """그 스텝 구간의 영상 정책. 호출 스텝이면 서브그래프 파일의 `record`까지 더한다 — 분류부터
        서브그래프 첫 스텝까지의 순간에도 켜지지 않게 (`_graph_call`의 `restrict`와 같은 값)."""
        if node.type == GRAPH_CALL:
            callee = self.rt.program.callee(frame.graph.path, node.id)
            if callee is not None:
                return policy.layer(callee.record, graph_source(callee.path)).video
        return policy.video

    def _target(self, frame: Frame, node: Node, outcome: _Outcome) -> Node | None:
        if not isinstance(outcome, Result) or outcome.exit is None:
            return None
        target = node.next.get(outcome.exit)
        if target is None:
            return None
        found = frame.graph.nodes.get(target)
        if found is None:
            raise EngineError(
                "dangling_next",
                f"'{node.id}'의 출구 '{outcome.exit}'이(가) 없는 노드 '{target}'로 간다",
            )
        return found

    def _evidence(self, node: Node, step: str, what: str, save: Callable[[str], object]) -> None:
        """예외 스크린샷·실패 증거·OCR 글자 기록. 저장이 실패해도(디스크·버린 프레임 등) 원래
        결과를 덮지 않는다. 경고 로그만 남긴다."""
        try:
            save(step)
        except Exception as exc:
            self.rt.emit(
                {
                    "event": "log",
                    "level": "warn",
                    "message": f"{what}을(를) 남기지 못했다: {type(exc).__name__}: {exc}",
                    "node": node.id,
                    "step": step,
                }
            )

    def _finish(self, end: dict[str, Any], began: Mark, frame: Frame, node: Node) -> None:
        step = end["step"]
        recorder = self.rt.recorder
        self._evidence(node, step, "썸네일", recorder.thumbnail)
        self._evidence(node, step, "OCR 글자 기록", recorder.ocr_artifact)
        evidence = recorder.evidence(step)
        # 에이전트용 분류 (M5 3.8): 입력·출력에 비밀값이 있던 스텝, 가림이 켜져 있었다면 빠졌을
        # 증거. 노드 쪽이 비밀값을 가린 필드(판단 노드의 답 속 인증값)도 같은 표시로
        mark_secret(end, recorder.secret_fields(step))
        if any(p.startswith("/outputs") for p in end.get("secret_paths", ())):
            recorder.mark_secret(step)
        secret, withhold = recorder.agent_marks(step)
        if secret:
            end["secret"] = True
        if withhold:
            end["agent_withhold"] = withhold
        # 서브그래프 안 스텝의 마지막 캡처는 부른 스텝의 증거로 넘어간다 (실패 증거, M1 2.15)
        artifacts, omitted = recorder.close_step(step, parent=frame.parent)
        if artifacts:
            end["artifacts"] = artifacts
        if omitted:
            end["omitted"] = omitted
        if evidence is not None:
            end["evidence"] = evidence
        # duration_ms는 실제 경과, 그 구간에 멈춤이 있었으면 멈춘 시간을 뺀 경과도 (M3 2.2)
        end["duration_ms"], active = self.rt.elapsed(began)
        if active is not None:
            end["active_duration_ms"] = active
        self.rt.emit(end)

    def _common_window(
        self, frame: Frame, node: Node, nodedef: NodeDef, inputs: dict[str, Any]
    ) -> tuple[WindowRef | None, dict[str, Any]]:
        """공통 입력 `in.window`를 떼어 낸다 (M1 2.8). 노드 함수 인자·서브그래프 입력·서브그래프
        출력으로 넘기지 않고, 그 스텝의 대상 창(서브그래프 호출이면 안쪽 프레임의 시작 창)으로만
        쓴다. 노드가 `window`라는 입력을 직접 선언했으면 그 입력이다(떼지 않는다)."""
        if COMMON_WINDOW.name not in inputs:
            return None, inputs
        pins = node_pins(self.rt.program, frame.graph, node, nodedef).inputs
        if pins is None or pins.get(COMMON_WINDOW.name) is not COMMON_WINDOW:
            return None, inputs
        rest = dict(inputs)
        window = rest.pop(COMMON_WINDOW.name)
        return (window if isinstance(window, WindowRef) else None), rest

    def _dispatch(
        self,
        frame: Frame,
        node: Node,
        nodedef: NodeDef,
        step: str,
        inputs: dict[str, Any],
        end: dict[str, Any],
        trace: StepTrace,
        window: WindowRef | None = None,
    ) -> _Outcome:
        engine = nodedef.engine
        if engine is None:
            return self._attempt(frame, node, nodedef, step, inputs, end, trace, window)
        if engine == "graph_entry":
            # 서브그래프 입력의 출처를 핀별로 옮긴다
            trace.outputs = frame.input_origins
            return Result("start", "ok", copy.deepcopy(dict(frame.inputs)))
        if engine == "graph_exit":
            return self._graph_exit(frame, node, inputs, trace)
        if engine == "graph_call":
            return self._graph_call(frame, node, step, inputs, end, trace, window)
        if engine in _TERMINALS:
            reason = inputs.get("reason")
            secret = isinstance(reason, Secret)
            if isinstance(reason, Secret):
                # 비밀값 가림이 켜진 실행만 판정 사유·기록에 가린 값 (P12, D3)
                reason = str(reason) if self.rt.recorder.redact_secrets else reason.reveal()
            return _TerminalEnd(
                _TERMINALS[engine], reason if isinstance(reason, str) else None, secret
            )
        if engine in _LOOPS:
            trace.outputs = {}  # 회차 번호(`index`)는 관측과 무관하다
            return self._loop(frame, node, nodedef, step, inputs)
        raise EngineError("unknown_engine", f"'{node.id}': 실행기가 모르는 engine '{engine}'")

    def _attempt(
        self,
        frame: Frame,
        node: Node,
        nodedef: NodeDef,
        step: str,
        inputs: Mapping[str, Any],
        end: dict[str, Any],
        trace: StepTrace,
        window: WindowRef | None = None,
    ) -> Result:
        """노드 함수를 실행한다. 재시도 출구로 나오면 출구를 확정하기 전에 다시 부른다.

        입력은 스텝 시작 때 계산한 값을 시도마다 깊은 복사해 준다 (다시 계산하지 않고, 앞 시도가
        고친 값이 다음 시도로 새지 않는다). ctx는 시도마다 새로 (노드 기한이 새로 시작한다).
        그 스텝의 대상 창(`window`, 없으면 스텝 시작 때 호출 프레임의 현재 창)은 시도 전에 한 번
        정해 모든 시도가 같이 쓴다 — 앞 시도의 `set_window`는 다음 스텝부터다.
        """
        rt = self.rt
        policy = retry_policy(nodedef, node)
        config = nodedef.effective_config(node.config)
        step_window = window if window is not None else frame.current_window
        attempt = 1
        while True:
            end["attempt"] = attempt
            if attempt > 1:
                # 시도 사이(이벤트 싱크 처리 포함)에 생긴 취소·기한 초과면 다시 부르지 않는다
                rt.check()
            if isinstance(rt.platform, PreparingPlatform):
                # 노드 기한(ctx.deadline)은 노드 함수 안에서 만든다 — 그 전에 엔진 준비를 기다린다
                rt.platform.before_node(node.type, rt.check)
            began = rt.wall_clock.now_ms()
            trace.begin_attempt()
            ctx = StepContext(rt, frame, node, step, config, step_window, trace=trace)
            result = rt.invoker.invoke(nodedef, node, ctx, copy.deepcopy(dict(inputs)))
            if ctx.stale is not None:
                # 노드가 재검증 실패를 삼키고 끝났어도 그 입력은 하지 않았다
                raise ctx.stale
            if not policy.again(result, attempt):
                break
            # 시도 중에 생긴 취소·기한 초과는 중간 실패로 남기지 않고 이 스텝의 error로 전파한다
            rt.check()
            record: dict[str, Any] = {
                "attempt": attempt,
                "duration_ms": rt.wall_clock.now_ms() - began,
                "event": "attempt.end",
                "exit": result.exit,
                "status": "fail",
                "step": step,
            }
            record["outputs"] = self._value(result.outputs, record, "/outputs")
            if "secret_paths" in record:
                rt.recorder.mark_secret(step)
            if "iteration" in end:
                record["iteration"] = end["iteration"]
            if result.message:
                record["message"] = self._message(result.message, record)
            rt.emit(record)
            attempt += 1
        return result

    def _recompute(self, frame: Frame, node: Node, nodedef: NodeDef) -> frozenset[str] | None:
        """이번 스텝에서 계산할 입력 (None = 전부).

        본문 끝에서 돌아온 반복 노드는 한도를 다시 계산하지 않는다 (`REENTRY_INPUTS`).
        """
        engine = nodedef.engine
        if engine in _LOOPS and resuming(frame, node.id):
            return REENTRY_INPUTS[engine]
        return None

    def _loop(
        self, frame: Frame, node: Node, nodedef: NodeDef, step: str, inputs: Mapping[str, Any]
    ) -> Result:
        """`core.flow.repeat`·`while`: 이번에 나갈 출구(`body`·`done`·`limit`)를 정한다."""
        engine = nodedef.engine
        assert engine is not None
        scope = self.scopes.of(frame.graph).get(node.id, frozenset[str]())
        result = enter(frame, node, engine, inputs, scope)
        if result.exit == "body":
            # 새 회차: 그 반복 범위의 두 회차 전 썸네일을 지운다 (첫·마지막 두 회차만, M3 2.6)
            self.rt.recorder.loop_iteration(frame.loops[-1].serial, result.outputs["index"])
        return result

    # ------------------------------------------------------------ 그래프 경계

    def _graph_call(
        self,
        frame: Frame,
        node: Node,
        step: str,
        inputs: Mapping[str, Any],
        end: dict[str, Any],
        trace: StepTrace,
        window: WindowRef | None = None,
    ) -> Result:
        callee = self.rt.program.callee(frame.graph.path, node.id)
        if callee is None:
            raise EngineError("call_target_missing", f"'{node.id}': 부를 서브그래프를 읽지 못했다")
        if frame.depth + 1 > MAX_CALL_DEPTH:
            raise EngineError(
                "call_depth", f"'{node.id}': 서브그래프 호출이 {MAX_CALL_DEPTH}단계를 넘는다"
            )
        interface = callee.interface or {}
        values: dict[str, Any] = {}
        origins: dict[str, Origin | None] = {}
        for name, decl in interface.get("inputs", {}).items():
            if name in inputs:
                values[name] = inputs[name]
                origins[name] = trace.inputs.get(name)
            elif "default" in decl:
                values[name] = copy.deepcopy(decl["default"])
            else:
                raise EngineError(
                    "missing_required_input", f"'{node.id}': 서브그래프 입력 '{name}'이(가) 없다"
                )
        end["graph"] = self.graph_prefix + callee.path
        # 호출 노드의 record까지 더한 정책 위에 서브그래프의 record (비밀값 입력 표시는 잇지 않는다)
        policy = self.rt.recorder.policy(step).policy.layer(
            callee.record, graph_source(callee.path)
        )
        if self.video is not None:
            # 서브그래프의 영상 끄기는 호출 스텝 구간 전체다 (자식 스텝 사이에도 켜지지 않는다)
            self.video.restrict(step, policy.video)
        inner = Frame(
            callee,
            frame.node_path(node.id),
            step,
            frame.depth + 1,
            values,
            current_window=window if window is not None else frame.current_window,
            record_policy=policy,
            input_origins=origins,
            outer_loops=frame.loop_chain(node.id),
        )
        done = self._run_frame(inner)
        if done is None:
            raise EngineError(
                "subgraph_path_open",
                f"서브그래프 '{callee.path}'이(가) 공개 exit 없이 끝났다 "
                "(어느 출구로 나갈지 모른다)",
            )
        trace.outputs = done.origins  # exit 입력의 출처가 호출 노드 출력으로
        message = (
            f"서브그래프 '{callee.path}'이(가) fail 출구 '{done.exit}'로 나갔다"
            if done.kind == "fail"
            else None
        )
        return Result(done.exit, done.kind, dict(done.outputs), message)

    def _graph_exit(
        self, frame: Frame, node: Node, inputs: Mapping[str, Any], trace: StepTrace
    ) -> FrameExit:
        graph = frame.graph
        if graph.kind != "subgraph":
            raise EngineError(
                "graph_exit_in_test", f"'{node.id}': 테스트에서는 core.graph.exit로 끝낼 수 없다"
            )
        interface = graph.interface or {}
        name = node.config.get("exit")
        decl = interface.get("exits", {}).get(name) if isinstance(name, str) else None
        if not isinstance(name, str) or decl is None:
            raise EngineError(
                "exit_name_unknown", f"'{node.id}': config.exit {name!r}이(가) interface에 없다"
            )
        outputs: dict[str, Any] = {}
        for out, out_decl in interface.get("outputs", {}).items():
            if out in inputs:
                outputs[out] = inputs[out]
            elif out_decl.get("nullable", False):
                outputs[out] = None
            else:
                raise EngineError(
                    "exit_missing_required_output",
                    f"'{node.id}': nullable 아닌 출력 '{out}'을(를) 주지 않았다",
                )
        origins = {out: trace.inputs.get(out) for out in outputs}
        return FrameExit(name, decl["kind"], outputs, origins)
