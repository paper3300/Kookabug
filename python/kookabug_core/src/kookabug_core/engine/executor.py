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

반복·재시도(T8)가 끼어들 자리: `_path_end`(경로 끝 → 반복 노드로 귀환), `Frame.invalidate`(회차
이동 때 범위 출력 지우기), `_attempt`(출구 확정 전 재시도), `_iteration`(이벤트 `iteration`).
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping
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
from kookabug_core.engine.platform_fake import FakePlatform, MemoryArtifacts
from kookabug_core.engine.pure import nodedef_of, resolve_inputs
from kookabug_core.engine.verdict import Cause, Facts, Judgement, Terminal, Verdict, judge
from kookabug_core.ir import GRAPH_ENTRY, Node
from kookabug_core.loader import MAX_CALL_DEPTH, Program
from kookabug_core.registry import NodeDef, Registry, default_registry
from kookabug_core.validate import validate
from kookabug_sdk import Result
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
    """실행기 옵션. 설정값(`$setting`)·프로필은 로더 옵션(`RunOptions`)이다."""

    deadline_ms: int = DEFAULT_DEADLINE_MS
    validate: bool = True
    run_id: str | None = None


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
    ) -> None:
        """`sink`는 이벤트를 더 보낼 곳이다 (`RunResult.events`에는 늘 모인다).

        `invoker`는 노드 함수 실행 경계다 (기본: 같은 프로세스, M0b: 워커 프로세스).
        """
        self.registry = registry or default_registry()
        self.invoker: NodeInvoker = invoker or InProcessInvoker()
        self.platform: Platform = platform or FakePlatform()
        self.clock: Clock = clock or SystemClock()
        self.cancel = cancel or CancelToken()
        self.artifacts: ArtifactStore = artifacts or MemoryArtifacts()
        self.sink = sink

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

        def emit(event: dict[str, Any]) -> None:
            events.append(event)
            if self.sink is not None:
                self.sink.emit(event)

        run_id = options.run_id or uuid.uuid4().hex[:8]
        runtime = Runtime(
            run=run_id,
            program=program,
            registry=self.registry,
            invoker=self.invoker,
            platform=self.platform,
            artifacts=self.artifacts,
            clock=self.clock,
            cancel=self.cancel,
            deadline=Deadline(self.clock, self.clock.now_ms() + options.deadline_ms),
            deadline_ms=options.deadline_ms,
            emit_to=emit,
        )
        judgement = _Run(runtime).execute(Frame(root, (), None, 0, {}))
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


def _cause_of(step: str, path: tuple[str, ...], exc: BaseException) -> Cause:
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
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime
        self.steps = 0
        self.assertions = 0

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
        """T8 훅: 반복 범위 안의 경로 끝이면 가장 안쪽 반복 노드로 돌아간다."""
        return None

    def _iteration(self, frame: Frame, node: Node) -> int | None:
        """T8 훅: 반복 안 스텝의 회차 (0부터)."""
        return None

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
        rt.emit(start)
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
                inputs = resolve_inputs(rt, frame, node, step)
                rt.check()
                outcome = self._dispatch(frame, node, nodedef, step, inputs, end)
                # 노드가 돌아온 뒤에도 본다: 실행 중 생긴 취소·기한 초과를 성공으로 확정하지 않는다
                rt.check()
                target = self._target(frame, node, outcome)
            except _Halt:
                raise
            except (Cancelled, Exception) as exc:
                raise _Error(_cause_of(step, path, exc)) from exc
        except _Halt as halt:
            # 이 스텝의 고장이거나, 호출한 서브그래프 안에서 올라오는 것
            end.update(status=halt.status, exit=None, outputs={})
            if isinstance(halt, _Error):
                end["error"] = {"code": halt.cause.code, "message": halt.cause.message}
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

    def _finish(self, end: dict[str, Any], began: int) -> None:
        artifacts = self.rt.step_artifacts.get(end["step"])
        if artifacts:
            end["artifacts"] = list(artifacts)
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
            return self._attempt(frame, node, nodedef, step, inputs)
        if engine == "graph_entry":
            return Result("start", "ok", copy.deepcopy(dict(frame.inputs)))
        if engine == "graph_exit":
            return self._graph_exit(frame, node, inputs)
        if engine == "graph_call":
            return self._graph_call(frame, node, step, inputs, end)
        if engine in _TERMINALS:
            reason = inputs.get("reason")
            return _TerminalEnd(_TERMINALS[engine], reason if isinstance(reason, str) else None)
        if engine in _LOOPS:
            return self._loop(frame, node, nodedef, step, inputs)
        raise EngineError("unknown_engine", f"'{node.id}': 실행기가 모르는 engine '{engine}'")

    def _attempt(
        self, frame: Frame, node: Node, nodedef: NodeDef, step: str, inputs: Mapping[str, Any]
    ) -> Result:
        """노드 함수를 한 번 실행한다. T8 훅: 재시도는 출구가 확정되기 전에 여기서 다시 부른다."""
        ctx = StepContext(self.rt, frame, node, step, nodedef.effective_config(node.config))
        return self.rt.invoker.invoke(nodedef, node, ctx, inputs)

    def _loop(
        self, frame: Frame, node: Node, nodedef: NodeDef, step: str, inputs: Mapping[str, Any]
    ) -> Result:
        """T8 훅: `core.flow.repeat`·`while`."""
        raise EngineError("loop_not_supported", f"'{node.id}': 반복 실행은 아직 없다 (M0a T8)")

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
        end["graph"] = callee.path
        inner = Frame(
            callee,
            frame.node_path(node.id),
            step,
            frame.depth + 1,
            values,
            current_window=frame.current_window,
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
