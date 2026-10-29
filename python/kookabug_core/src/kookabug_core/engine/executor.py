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
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal

from kookabug_core.diagnostics import Diagnostic, has_errors
from kookabug_core.engine.cancel import Cancelled, CancelToken, DeadlineExceeded
from kookabug_core.engine.clock import Clock, SystemClock
from kookabug_core.engine.context import ArtifactStore, Platform, Runtime, StepContext
from kookabug_core.engine.errors import EngineError, error_code
from kookabug_core.engine.events import EventSink, event_value
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
from kookabug_core.engine.pure import nodedef_of, resolve_inputs
from kookabug_core.engine.retry import retry_policy
from kookabug_core.engine.verdict import Cause, Facts, Judgement, Terminal, Verdict, judge
from kookabug_core.ir import GRAPH_ENTRY, Node
from kookabug_core.loader import MAX_CALL_DEPTH, Program
from kookabug_core.record.artifacts import Recorder
from kookabug_core.record.policy import (
    RecordPolicy,
    graph_source,
    node_inputs_source,
    node_source,
)
from kookabug_core.registry import NodeDef, Registry, default_registry
from kookabug_core.validate import validate
from kookabug_core.workspace import WORKSPACE_FILE, SettingLookup
from kookabug_sdk import Result, Secret
from kookabug_sdk.context import Deadline

__all__ = [
    "DEFAULT_DEADLINE_MS",
    "ExecOptions",
    "Executor",
    "GraphInvalid",
    "RunResult",
]

DEFAULT_DEADLINE_MS: Final = 30 * 60 * 1000
"""테스트 전체 기한 기본값 30분 (G11). 노드별 타임아웃과 별개다."""

_TERMINALS: Final[dict[str, Terminal]] = {
    "test_pass": "pass",
    "test_fail": "fail",
    "test_skip": "skip",
}
_LOOPS: Final = frozenset({"repeat", "while"})


@dataclass(frozen=True, slots=True)
class ExecOptions:
    """실행기 옵션. 설정값(`$setting`)·프로필은 로더 옵션(`RunOptions`)이다.

    `graph_prefix`는 `step.end.graph`(서브그래프 경로) 앞에 붙인다. runner는 스냅샷에서 읽은
    프로그램을 돌리므로 실행 폴더 기준 `snapshot/`을 준다.

    `collect_events=False`면 이벤트를 `RunResult.events`에 모으지 않고 싱크로만 보낸다 (runner:
    긴 실행에서 메모리가 이벤트 수에 비례해 늘지 않게).
    """

    deadline_ms: int = DEFAULT_DEADLINE_MS
    validate: bool = True
    run_id: str | None = None
    graph_prefix: str = ""
    collect_events: bool = True


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
        before_step: Callable[[str], None] | None = None,
        on_setting: Callable[[SettingLookup], None] | None = None,
    ) -> None:
        """`sink`는 이벤트를 더 보낼 곳이다 (`RunResult.events`에는 `collect_events`일 때 모인다).

        `invoker`는 노드 함수 실행 경계다 (기본: 같은 프로세스, M0b: 워커 프로세스).
        `before_step(스텝)`은 스텝을 시작하기 직전(`step.start` 전) 확인 지점에서 불린다 — runner의
        경계 멈춤이 여기서 기다린다. `Cancelled`를 던지면 그 스텝은 시작하지 않고 실행이 끝난다.
        `on_setting(조회 결과)`는 노드가 `ctx.setting()`으로 설정을 읽을 때마다 불린다
        (실행 조건 기록).
        시계를 주지 않으면 취소로 깨는 `SystemClock`이다.
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
        recorder = Recorder(self.artifacts)
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
        )
        workspace_record = program.workspace.config.get("record")
        policy = (
            RecordPolicy()
            .layer(
                workspace_record if isinstance(workspace_record, Mapping) else None,
                graph_source(WORKSPACE_FILE),
            )
            .layer(root.record, graph_source(root.path))
        )
        top = Frame(root, (), None, 0, {}, record_policy=policy)
        judgement = _Run(runtime, options.graph_prefix, self.before_step).execute(top)
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
        before_step: Callable[[str], None] | None = None,
    ) -> None:
        self.rt = runtime
        self.graph_prefix = graph_prefix
        self.before_step = before_step
        self.steps = 0
        self.assertions = 0
        self.scopes = LoopScopes(runtime.program, runtime.registry)

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
                self.before_step(step)
            except Cancelled as exc:
                # 시작하지 않은 스텝: step.start·step.end 없이 위로 (원인 스텝 없음)
                raise _Error(_cause_of(None, frame.path, _with_reason(rt.cancel, exc))) from exc
        rt.emit(start)
        rt.recorder.open_step(
            step, frame.record_policy.layer(node.record, node_source(frame.graph.path, node.id))
        )
        began = rt.clock.now_ms()

        try:
            try:
                rt.check()
                nodedef = nodedef_of(rt, node)
                if nodedef.pure:
                    raise EngineError(
                        "exec_into_pure",
                        f"'{node.id}'은(는) 순수 노드라 exec 흐름으로 실행할 수 없다",
                    )
                inputs = resolve_inputs(
                    rt, frame, node, step, self._recompute(frame, node, nodedef)
                )
                rt.recorder.note_inputs(step, inputs, node_inputs_source(frame.graph.path, node.id))
                rt.check()
                outcome = self._dispatch(frame, node, nodedef, step, inputs, end)
                # 노드가 돌아온 뒤에도 본다: 실행 중 생긴 취소·기한 초과를 성공으로 확정하지 않는다
                rt.check()
                target = self._target(frame, node, outcome)
            except _Halt:
                raise
            except (Cancelled, Exception) as exc:
                raise _Error(_cause_of(step, path, _with_reason(rt.cancel, exc))) from exc
        except _Halt as halt:
            # 이 스텝의 고장이거나, 호출한 서브그래프 안에서 올라오는 것
            end.update(status=halt.status, exit=None, outputs={})
            if isinstance(halt, _Error):
                end["error"] = {"code": halt.cause.code, "message": halt.cause.message}
                if halt.status == "error" and halt.cause.step == step:
                    # 이 스텝의 오류만. 서브그래프 안쪽 오류는 안쪽 스텝이 이미 처리했다
                    self._error_screenshot(node, step)
            elif isinstance(halt, _Unhandled):
                end["message"] = halt.cause.message
            self._finish(end, began)
            raise

        if isinstance(outcome, _TerminalEnd):
            end.update(status="success", exit=None, outputs={})
            self._finish(end, began)
            default = {
                "pass": "core.test.pass에 도달했다",
                "fail": "core.test.fail에 도달했다",
                "skip": "core.test.skip에 도달했다",
            }[outcome.kind]
            raise _Terminal(
                outcome.kind, Cause(step, path, f"test_{outcome.kind}", outcome.reason or default)
            )
        if isinstance(outcome, FrameExit):
            end.update(status="success", exit=None, outputs=event_value(outcome.outputs))
            self._finish(end, began)
            return outcome

        frame.record(node.id, outcome.outputs)
        if nodedef.assertion and outcome.kind == "ok":
            self.assertions += 1
        if outcome.kind == "ok" and end["attempt"] > 1:
            # 마지막 확인까지 통과해 성공이 확정된 뒤에만 표시한다 (중단된 스텝에는 없다)
            end["retried"] = True
        end.update(
            status="success" if outcome.kind == "ok" else "fail",
            exit=outcome.exit,
            outputs=event_value(outcome.outputs),
        )
        if outcome.kind == "fail" and outcome.message:
            end["message"] = outcome.message
        self._finish(end, began)
        if outcome.kind == "fail":
            cause = Cause(
                step,
                path,
                "fail",
                outcome.message or f"'{node.id}'이(가) fail 출구 '{outcome.exit}'로 나갔다",
            )
            if target is None:
                raise _Unhandled(cause)
            frame.pending.append(cause)
        return target

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

    def _error_screenshot(self, node: Node, step: str) -> None:
        """저장이 실패해도(디스크 등) 원래 오류를 덮지 않는다. 경고 로그만 남긴다."""
        try:
            self.rt.recorder.error_screenshot(step)
        except Exception as exc:
            self.rt.emit(
                {
                    "event": "log",
                    "level": "warn",
                    "message": f"예외 스크린샷을 남기지 못했다: {type(exc).__name__}: {exc}",
                    "node": node.id,
                    "step": step,
                }
            )

    def _finish(self, end: dict[str, Any], began: int) -> None:
        artifacts, omitted = self.rt.recorder.close_step(end["step"])
        if artifacts:
            end["artifacts"] = artifacts
        if omitted:
            end["omitted"] = omitted
        end["duration_ms"] = self.rt.clock.now_ms() - began
        self.rt.emit(end)

    def _dispatch(
        self,
        frame: Frame,
        node: Node,
        nodedef: NodeDef,
        step: str,
        inputs: dict[str, Any],
        end: dict[str, Any],
    ) -> _Outcome:
        engine = nodedef.engine
        if engine is None:
            return self._attempt(frame, node, nodedef, step, inputs, end)
        if engine == "graph_entry":
            return Result("start", "ok", copy.deepcopy(dict(frame.inputs)))
        if engine == "graph_exit":
            return self._graph_exit(frame, node, inputs)
        if engine == "graph_call":
            return self._graph_call(frame, node, step, inputs, end)
        if engine in _TERMINALS:
            reason = inputs.get("reason")
            if isinstance(reason, Secret):
                reason = str(reason)  # 판정 사유·기록에는 가린 값만 (P12)
            return _TerminalEnd(_TERMINALS[engine], reason if isinstance(reason, str) else None)
        if engine in _LOOPS:
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
    ) -> Result:
        """노드 함수를 실행한다. 재시도 출구로 나오면 출구를 확정하기 전에 다시 부른다.

        입력은 스텝 시작 때 계산한 값을 시도마다 깊은 복사해 준다 (다시 계산하지 않고, 앞 시도가
        고친 값이 다음 시도로 새지 않는다). ctx는 시도마다 새로 (노드 기한이 새로 시작한다).
        """
        rt = self.rt
        policy = retry_policy(nodedef, node)
        config = nodedef.effective_config(node.config)
        attempt = 1
        while True:
            end["attempt"] = attempt
            if attempt > 1:
                # 시도 사이(이벤트 싱크 처리 포함)에 생긴 취소·기한 초과면 다시 부르지 않는다
                rt.check()
            began = rt.clock.now_ms()
            ctx = StepContext(rt, frame, node, step, config)
            result = rt.invoker.invoke(nodedef, node, ctx, copy.deepcopy(dict(inputs)))
            if not policy.again(result, attempt):
                break
            # 시도 중에 생긴 취소·기한 초과는 중간 실패로 남기지 않고 이 스텝의 error로 전파한다
            rt.check()
            record: dict[str, Any] = {
                "attempt": attempt,
                "duration_ms": rt.clock.now_ms() - began,
                "event": "attempt.end",
                "exit": result.exit,
                "outputs": event_value(result.outputs),
                "status": "fail",
                "step": step,
            }
            if "iteration" in end:
                record["iteration"] = end["iteration"]
            if result.message:
                record["message"] = result.message
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
        return enter(frame, node, engine, inputs, scope)

    # ------------------------------------------------------------ 그래프 경계

    def _graph_call(
        self, frame: Frame, node: Node, step: str, inputs: Mapping[str, Any], end: dict[str, Any]
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
        for name, decl in interface.get("inputs", {}).items():
            if name in inputs:
                values[name] = inputs[name]
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
        inner = Frame(
            callee,
            frame.node_path(node.id),
            step,
            frame.depth + 1,
            values,
            current_window=frame.current_window,
            record_policy=policy,
        )
        done = self._run_frame(inner)
        if done is None:
            raise EngineError(
                "subgraph_path_open",
                f"서브그래프 '{callee.path}'이(가) 공개 exit 없이 끝났다 "
                "(어느 출구로 나갈지 모른다)",
            )
        message = (
            f"서브그래프 '{callee.path}'이(가) fail 출구 '{done.exit}'로 나갔다"
            if done.kind == "fail"
            else None
        )
        return Result(done.exit, done.kind, dict(done.outputs), message)

    def _graph_exit(self, frame: Frame, node: Node, inputs: Mapping[str, Any]) -> FrameExit:
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
        return FrameExit(name, decl["kind"], outputs)
