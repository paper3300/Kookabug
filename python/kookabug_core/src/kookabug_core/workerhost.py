"""runner 쪽 워커: 띄우기·hello·원격 노드 실행·`ctx` 대리·취소·죽음 감지 (구현 계획 M0b 2.5).

    worker = WorkerProcess.start(modules=[...], files_root=..., registry=registry, emit=..., ...)
    invoker = RoutingInvoker(WorkerInvoker(worker))       # core 노드는 같은 프로세스
    ... Executor(registry, invoker=invoker).run(program) ...
    worker.shutdown()

- 시작: 파이프를 만들고 워커(`python -m kookabug_sdk.worker`)를 띄워 `worker.hello`. hello 기한을
  넘기면 `worker_start_timeout`, hello 전에 죽으면 `worker_died`, 프로토콜이 다르면
  `protocol_version`. 기다리는 동안에도 취소·전체 기한(`check`)을 본다
- 등록: hello가 준 노드 스키마를 원격 노드(`NodeDef.function = None`)로 레지스트리에 넣는다.
  runner는 플러그인 코드를 import하지 않는다
- 실행(`WorkerInvoker`): `node.invoke`를 보내고 응답을 기다리는 동안 **같은 스레드**(runner 주
  스레드)가 워커의 `ctx` 요청을 처리한다(`CtxServer`). 실행 상태(프레임 변수·이벤트)를 한
  스레드만 고친다. `ctx` 요청은 그 노드의 `pure`·`effects`로 다시 검사하고, 결과는 레지스트리
  선언으로 다시 대조한다 — 워커를 믿지 않는다
- 취소(`WorkerProcess.cancel`): `cancel` 알림을 송신 큐에 넣고 유예 타이머를 건다. 유예 시각에
  노드가 아직 끝나지 않았으면 워커를 끝낸다. 알림이 실제로 보내졌는지와 무관하다(송신이 막혀도
  타이머는 돈다)
- 죽음: 실행 중 워커가 끝나거나 연결이 끊기면 그 스텝은 `error`/`worker_died`(종료 코드). 다시
  띄우지 않는다
- 이벤트: `worker.start{pid}`, `worker.exit{pid, exit_code, reason}`를 `emit`으로 (한 번씩)
"""

from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Literal, NoReturn

from kookabug_core.engine.cancel import DeadlineExceeded
from kookabug_core.engine.errors import EngineError
from kookabug_core.ir import Node
from kookabug_core.registry import (
    MISSING,
    DynamicExitsDecl,
    ExitDecl,
    NodeDef,
    Registry,
    RegistryError,
)
from kookabug_core.win.process import ProcessId, identify, spawn
from kookabug_sdk import NodeContractError, Result
from kookabug_sdk.codec import CodecError, decode, encode
from kookabug_sdk.context import (
    Cancelled,
    Context,
    ContextViolation,
    EffectContext,
    GuardedContext,
)
from kookabug_sdk.pipe import PipeConnection, PipeListener, new_key, new_pipe_name
from kookabug_sdk.pure import PureContext
from kookabug_sdk.rpc import (
    CANCELLED,
    CONTEXT_VIOLATION,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    NODE_CONTRACT,
    NODE_ERROR,
    PROTOCOL_VERSION,
    Call,
    Incoming,
    PeerLost,
    RpcError,
    RpcPeer,
)
from kookabug_sdk.types import Image, Match, Point, Rect, Secret
from kookabug_sdk.worker import ENV_KEY, ENV_PIPE, PROTOCOL

__all__ = [
    "DEFAULT_CANCEL_GRACE_MS",
    "DEFAULT_START_TIMEOUT_MS",
    "PROTOCOL",
    "CtxServer",
    "ExitReason",
    "WorkerInvoker",
    "WorkerProcess",
    "WorkerStartError",
    "check_remote_result",
]

DEFAULT_START_TIMEOUT_MS: Final = 30_000
"""`run.worker_start_timeout_ms` 기본값."""
DEFAULT_CANCEL_GRACE_MS: Final = 2_000
"""`run.worker_cancel_grace_ms` 기본값."""
DEFAULT_SHUTDOWN_GRACE_MS: Final = 2_000
KILLED_EXIT_CODE: Final = 1
"""runner가 워커를 끝낼 때 주는 종료 코드 (`TerminateProcess`)."""
_POLL_S: Final = 0.02
_EXIT_WAIT_S: Final = 5.0

type ExitReason = Literal[
    "shutdown", "killed_after_grace", "unexpected", "start_timeout", "start_failed", "cancelled"
]
type Emit = Callable[[dict[str, Any]], None]
type StartErrorCode = Literal[
    "worker_start_timeout", "worker_died", "protocol_version", "worker_start_failed"
]


class WorkerStartError(Exception):
    """워커를 쓸 수 없다 (hello 기한 초과·hello 전 사망·프로토콜 불일치·플러그인 등록 실패).
    runner는 이 `code`로 실행을 `error`로 끝낸다."""

    def __init__(self, code: StartErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code: StartErrorCode = code
        self.message = message


# ---------------------------------------------------------------- 프로세스


class WorkerProcess:
    """워커 프로세스 하나 (실행당 하나). `start()`로 만든다."""

    def __init__(
        self,
        proc: subprocess.Popen[bytes],
        *,
        emit: Emit,
        cancel_grace_ms: int,
    ) -> None:
        self.proc = proc
        self.ident: ProcessId | None = identify(proc.pid)
        self.peer: RpcPeer | None = None
        self.plugins: list[dict[str, Any]] = []
        self._emit = emit
        self._cancel_grace_ms = cancel_grace_ms
        self._lock = threading.Lock()
        self._busy = False
        self._invokes = 0
        self._cancel_at: float | None = None
        self._exit_reason: ExitReason | None = None
        self._exit_emitted = False
        self._exit_lock = threading.Lock()  # `worker.exit` 차지·기록을 한 번에 (`_exited`)
        self._timer: threading.Timer | None = None

    @property
    def pid(self) -> int:
        return self.proc.pid

    @classmethod
    def start(
        cls,
        *,
        modules: Sequence[str],
        files_root: Path,
        log_dir: Path,
        run_id: str,
        workspace_id: str,
        registry: Registry,
        emit: Emit,
        check: Callable[[], None],
        start_timeout_ms: int = DEFAULT_START_TIMEOUT_MS,
        cancel_grace_ms: int = DEFAULT_CANCEL_GRACE_MS,
        env: Mapping[str, str] | None = None,
        protocol: int = PROTOCOL,
        trace: Callable[[str, bytes], None] | None = None,
    ) -> WorkerProcess:
        """워커를 띄우고 hello한 뒤 원격 노드를 `registry`에 등록한다.

        `check()`는 취소·전체 기한을 보고 `Cancelled`를 던지는 함수다(기다리는 동안 계속 부른다).
        실패하면 워커를 끝내고(`worker.exit`) `WorkerStartError`, 취소면 그 `Cancelled`를 던진다.
        `trace(방향, 프레임 본문)`은 주고받는 RPC 메시지를 본다(검사용).
        """
        deadline = time.monotonic() + start_timeout_ms / 1000
        key = new_key()
        listener = PipeListener(new_pipe_name("worker"))
        child_env = dict(os.environ if env is None else env)
        child_env[ENV_PIPE] = listener.name
        child_env[ENV_KEY] = key.hex()
        try:
            proc = spawn(
                [sys.executable, "-m", "kookabug_sdk.worker"],
                stdout=log_dir / "worker.stdout.log",
                stderr=log_dir / "worker.stderr.log",
                env=child_env,
            )
        except BaseException:
            listener.close()
            raise
        worker = cls(proc, emit=emit, cancel_grace_ms=cancel_grace_ms)
        emit({"event": "worker.start", "pid": proc.pid})
        try:
            worker._connect(listener, key, deadline, check, trace)
            worker._hello(
                {
                    "protocol": protocol,
                    "modules": list(modules),
                    "run_id": run_id,
                    "workspace_id": workspace_id,
                    "files_root": str(files_root),
                },
                deadline,
                check,
            )
            worker._register(registry)
        except BaseException:
            listener.close()
            if worker.proc.poll() is None:
                # 어떤 실패로 끝나든(KeyboardInterrupt 등) 살아 있는 워커를 남기지 않는다
                worker.kill("start_failed")
            raise
        return worker

    # ------------------------------------------------------------ 시작

    def _connect(
        self,
        listener: PipeListener,
        key: bytes,
        deadline: float,
        check: Callable[[], None],
        trace: Callable[[str, bytes], None] | None,
    ) -> None:
        accepted: list[Any] = []
        ready = threading.Event()

        def accept() -> None:
            try:
                accepted.append(listener.accept(key, timeout=max(0.0, deadline - time.monotonic())))
            except BaseException as exc:
                accepted.append(exc)
            finally:
                ready.set()

        thread = threading.Thread(target=accept, name="worker-accept", daemon=True)
        thread.start()
        try:
            self._wait_start(ready, deadline, check, "연결")
        finally:
            if not ready.is_set():
                listener.close()  # accept를 끊는다
            thread.join(_EXIT_WAIT_S)
        result = accepted[0] if accepted else None
        if not isinstance(result, PipeConnection):
            # 기한 안에 붙었지만 인증이 실패한 경우 등: 워커를 쓸 수 없다
            if self.proc.poll() is not None:
                self._fail_died()
            self._fail("worker_start_failed", "start_failed", f"워커 연결 실패: {result!r}")
        self.peer = RpcPeer(result, name="runner-worker", trace=trace).start()

    def _hello(self, params: dict[str, Any], deadline: float, check: Callable[[], None]) -> None:
        assert self.peer is not None
        try:
            call = self.peer.request("worker.hello", params)
        except PeerLost:
            self._fail_died()
        done = threading.Event()
        call.add_done_callback(lambda _: done.set())
        self._wait_start(done, deadline, check, "hello")
        try:
            reply: Any = call.result()
        except PeerLost:
            self._fail_died()
        except RpcError as exc:
            if exc.code == PROTOCOL_VERSION:
                self._fail("protocol_version", "start_failed", exc.message)
            self._fail("worker_start_failed", "start_failed", exc.message)
        if not isinstance(reply, dict) or reply.get("protocol") != PROTOCOL:  # pyright: ignore[reportUnknownMemberType]
            got: Any = reply.get("protocol") if isinstance(reply, dict) else reply  # pyright: ignore[reportUnknownMemberType]
            self._fail("protocol_version", "start_failed", f"워커 프로토콜 {got!r} ≠ {PROTOCOL}")
        plugins: Any = reply.get("plugins")  # pyright: ignore[reportUnknownMemberType]
        if not isinstance(plugins, list) or not all(isinstance(p, dict) for p in plugins):  # pyright: ignore[reportUnknownVariableType]
            self._fail("worker_start_failed", "start_failed", "hello의 plugins가 목록이 아니다")
        self.plugins = list(plugins)  # pyright: ignore[reportUnknownArgumentType]

    def _register(self, registry: Registry) -> None:
        try:
            for plugin in self.plugins:
                schema = plugin.get("schema")
                if not isinstance(schema, dict):
                    raise RegistryError(f"플러그인 {plugin.get('id')!r}에 노드 스키마가 없다")
                registry.add_remote(schema)  # pyright: ignore[reportUnknownArgumentType]
        except RegistryError as exc:
            self._fail("worker_start_failed", "start_failed", f"원격 노드 등록 실패: {exc}")

    def _wait_start(
        self, done: threading.Event, deadline: float, check: Callable[[], None], what: str
    ) -> None:
        while not done.wait(_POLL_S):
            if self.proc.poll() is not None:
                if done.is_set():
                    return
                self._fail_died()
            try:
                check()
            except Cancelled:
                self.kill("cancelled")
                raise
            if time.monotonic() >= deadline:
                message = f"워커 {what}이(가) 기한 안에 끝나지 않았다"
                self._fail("worker_start_timeout", "start_timeout", message)

    def _fail(self, code: StartErrorCode, reason: ExitReason, message: str) -> NoReturn:
        self.kill(reason)
        raise WorkerStartError(code, message)

    def _fail_died(self) -> NoReturn:
        """hello 전에 연결을 잃었다. 연결 상실은 종료의 증거가 아니므로 프로세스로 판정한다:
        끝났으면 `worker_died`, 아직 살아 있으면 끝내고(종료를 확인한 뒤 `worker.exit`)
        `worker_start_failed`."""
        exit_code = self._wait_exit()
        if exit_code is None:
            self.kill("start_failed")
            raise WorkerStartError(
                "worker_start_failed", "hello 전에 워커와의 연결이 끊겼다 (프로세스는 살아 있었다)"
            )
        self._exited("unexpected", exit_code)
        raise WorkerStartError("worker_died", f"워커가 hello 전에 끝났다 (종료 코드 {exit_code})")

    # ------------------------------------------------------------ 실행

    def next_invoke(self) -> int:
        """새 실행 번호 (이 워커 안에서 1부터, 겹치지 않는다). 워커의 `ctx` 요청은 이 번호를 싣고,
        runner는 지금 기다리는 실행의 번호와 다른 요청을 처리하지 않는다."""
        with self._lock:
            self._invokes += 1
            return self._invokes

    def request(self, params: dict[str, Any]) -> Call:
        """`node.invoke`를 보낸다. 연결을 잃었으면 `PeerLost`."""
        if self.peer is None:
            raise PeerLost("워커와 연결되지 않았다")
        return self.peer.request("node.invoke", params)

    def set_busy(self, busy: bool) -> None:
        with self._lock:
            self._busy = busy

    def cancel(self) -> None:
        """취소: `cancel` 알림(송신 큐) + 유예 타이머. 여러 번 불러도 한 번만 한다.

        유예 시각에 노드가 아직 끝나지 않았으면 워커를 끝낸다(알림이 보내졌는지와 무관)."""
        with self._lock:
            if self._cancel_at is not None:
                return
            self._cancel_at = time.monotonic()
            timer = threading.Timer(self._cancel_grace_ms / 1000, self._grace_expired)
            timer.daemon = True
            self._timer = timer
        timer.start()
        if self.peer is not None:
            with contextlib.suppress(PeerLost):
                self.peer.notify("cancel", {})

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_at is not None

    def _grace_expired(self) -> None:
        with self._lock:
            busy = self._busy
        if busy and self.proc.poll() is None:
            self.kill("killed_after_grace")

    def kill(self, reason: ExitReason) -> None:
        """워커를 끝내고(`TerminateProcess`) `worker.exit`를 남긴다."""
        with self._lock:
            if self._exit_reason is None:
                self._exit_reason = reason  # 먼저 정한 사유가 남는다 (죽음과 겹쳐도)
        with contextlib.suppress(OSError):
            self.proc.kill()
        self._exited(reason, self._wait_exit())
        if self.peer is not None:
            self.peer.close()

    def _wait_exit(self) -> int | None:
        try:
            return self.proc.wait(_EXIT_WAIT_S)
        except subprocess.TimeoutExpired:
            return None

    def _exited(self, reason: ExitReason, exit_code: int | None) -> None:
        """`worker.exit`는 한 번만. 먼저 기록된 사유가 이긴다.

        어느 호출이든 기록이 끝난 뒤에 돌아간다: 유예 타이머가 먼저 차지하고 아직 쓰지 못했을 때
        주 스레드의 `shutdown`이 먼저 돌아가 `run.end`를 쓰면 늦은 `worker.exit`가 버려진다."""
        with self._exit_lock:
            with self._lock:
                if self._exit_reason is not None and self._exit_reason != reason:
                    reason = self._exit_reason
                emitted = self._exit_emitted
                self._exit_emitted = True
                self._exit_reason = reason
            if emitted:
                return
            event: dict[str, Any] = {"event": "worker.exit", "pid": self.proc.pid, "reason": reason}
            if exit_code is not None:
                event["exit_code"] = exit_code
            self._emit(event)

    def died(self) -> EngineError:
        """실행 중 연결을 잃었다: 종료를 기다려 `worker.exit`를 남기고 스텝 오류를 만든다."""
        exit_code = self._wait_exit()
        if exit_code is None:
            # 연결만 끊긴 채 살아 있다: 더 쓸 수 없으므로 끝낸다
            self.kill("unexpected")
            exit_code = self.proc.poll()
        self._exited("unexpected", exit_code)
        if self._exit_reason == "killed_after_grace":
            return EngineError(
                "worker_died", f"워커가 취소 유예를 넘겨 끝났다 (종료 코드 {exit_code})"
            )
        return EngineError("worker_died", f"워커 프로세스가 끝났다 (종료 코드 {exit_code})")

    @property
    def exit_reason(self) -> ExitReason | None:
        return self._exit_reason

    def shutdown(self, grace_ms: int = DEFAULT_SHUTDOWN_GRACE_MS) -> None:
        """마무리: `worker.shutdown`을 보내고 유예 안에 끝나기를 기다린다. 넘기면 끝낸다."""
        with self._lock:
            timer = self._timer
        if timer is not None:
            timer.cancel()
        if self.proc.poll() is not None:
            self._exited("unexpected", self._wait_exit())
            return
        if self.peer is not None:
            with contextlib.suppress(PeerLost):
                self.peer.request("worker.shutdown")
        try:
            exit_code = self.proc.wait(grace_ms / 1000)
        except subprocess.TimeoutExpired:
            self.kill("killed_after_grace")
            return
        self._exited("shutdown", exit_code)
        if self.peer is not None:
            self.peer.close()


# ---------------------------------------------------------------- 결과 대조


def check_remote_result(nodedef: NodeDef, result: Result, config: Mapping[str, Any]) -> Result:
    """워커가 준 결과를 레지스트리 선언으로 다시 대조한다 (SDK `NodeFunction.check_result`와 같은
    규칙). nullable 출력을 빠뜨렸으면 None으로 채운 결과를 돌려준다."""
    name = nodedef.type
    if nodedef.pure:
        if result.exit is not None or result.kind is not None:
            raise NodeContractError(f"{name}: 순수 노드는 출구 없이 출력만 준다")
        return Result(None, None, _check_outputs(nodedef, dict(result.outputs), None))
    if not isinstance(result.exit, str) or result.kind not in ("ok", "fail"):
        raise NodeContractError(f"{name}: exec 노드는 Result.ok/fail을 반환한다")
    exit = _find_exit(nodedef, result.exit, config)
    if exit.kind != result.kind:
        raise NodeContractError(
            f"{name}: 출구 '{exit.name}'은(는) {exit.kind} 출구다 (Result.{result.kind}로 반환함)"
        )
    outputs = _check_outputs(nodedef, dict(result.outputs), exit)
    return Result(result.exit, result.kind, outputs, result.message)


def _find_exit(nodedef: NodeDef, name: str, config: Mapping[str, Any]) -> ExitDecl:
    exits = nodedef.exits
    found: ExitDecl | None = None
    if isinstance(exits, tuple):
        found = next((e for e in exits if e.name == name), None)
    elif isinstance(exits, DynamicExitsDecl):
        found = next((e for e in exits.extra if e.name == name), None)
        dynamic = config.get(exits.from_config)
        if found is None and isinstance(dynamic, list) and name in dynamic:
            found = ExitDecl(name, exits.kind, exits.outputs)
    if found is None:
        raise NodeContractError(f"{nodedef.type}: 선언하지 않은 출구 '{name}'")
    return found


def _check_outputs(
    nodedef: NodeDef, outputs: dict[str, Any], exit: ExitDecl | None
) -> dict[str, Any]:
    if isinstance(nodedef.outputs, str):
        return outputs
    declared = {p.name: p for p in nodedef.outputs}
    allowed = declared.keys() if exit is None else set(exit.outputs)
    where = "" if exit is None else f" (출구 '{exit.name}')"
    for name in outputs:
        if name not in declared:
            raise NodeContractError(f"{nodedef.type}: 선언하지 않은 출력 '{name}'")
        if name not in allowed:
            raise NodeContractError(
                f"{nodedef.type}: 출력 '{name}'은(는) 이 출구가 주지 않는다{where}"
            )
    for name in allowed:
        if name in outputs:
            continue
        if not declared[name].nullable:
            raise NodeContractError(f"{nodedef.type}: 출력 '{name}'이(가) 빠졌다{where}")
        outputs[name] = None
    return outputs


# ---------------------------------------------------------------- ctx 대리


class _BadParams(Exception):
    pass


class _UnknownMethod(Exception):
    pass


_LOG_LEVELS: Final = frozenset({"debug", "info", "warn", "error"})


def _kind(exc: BaseException) -> dict[str, Any]:
    """오류 응답의 `data`: 예외 이름 (워커가 같은 종류로 다시 던진다)."""
    return {"type": type(exc).__name__}


def _param[T](params: Mapping[str, Any], name: str, kind: type[T]) -> T:
    value = params.get(name, MISSING)
    if not isinstance(value, kind) or (isinstance(value, bool) and kind is not bool):
        raise _BadParams(f"'{name}'은(는) {kind.__name__}이어야 한다")
    return value


def _decoded[T](params: Mapping[str, Any], name: str, kinds: tuple[type[T], ...]) -> T:
    try:
        value = decode(params.get(name))
    except CodecError as exc:
        raise _BadParams(f"'{name}': {exc}") from exc
    if not isinstance(value, kinds):
        raise _BadParams(f"'{name}'의 값 종류가 틀렸다: {type(value).__name__}")
    return value


class CtxServer:
    """노드 하나를 실행하는 동안 워커의 `ctx` 요청을 처리한다.

    실행 ctx를 그 노드의 선언으로 다시 감싸(순수 → `PureContext`, exec → 선언한 효과만) 같은 API를
    부른다. 그래서 워커가 SDK 제한을 건너뛰어도 runner가 막고, 막힌 호출은 `violations`에 남는다.

    요청은 `invoke`(이 실행의 번호)가 같아야 처리한다. 끝난 실행의 ctx 요청(노드가 보관해 둔 이전
    ctx, 늦게 온 요청, 재시도 앞 시도의 요청)은 이 노드의 선언·기록 정책으로 처리하지 않고
    거부한다. 순수 노드는 소비 스텝 ID를 같이 쓰므로 스텝이 아니라 실행 번호로 가른다.
    """

    def __init__(self, nodedef: NodeDef, ctx: Context, invoke: int) -> None:
        self.invoke = invoke
        self.ctx: GuardedContext = (
            PureContext(ctx) if nodedef.pure else EffectContext(ctx, nodedef.effects)
        )

    @property
    def violations(self) -> list[ContextViolation]:
        return self.ctx.violations

    @staticmethod
    def reject_stale(peer: RpcPeer, request: Incoming) -> None:
        """지금 기다리는 실행의 것이 아닌 `ctx` 요청을 처리하지 않고 거부한다."""
        if request.is_notification:
            return
        message = f"끝났거나 다른 노드 실행(invoke {request.params.get('invoke')!r})의 ctx 요청이다"
        with contextlib.suppress(PeerLost):
            peer.respond_error(request, CONTEXT_VIOLATION, message, {"type": "ContextViolation"})

    def handle(self, peer: RpcPeer, request: Incoming) -> None:
        """요청 하나를 처리하고 응답한다. 응답을 보낼 수 없으면(워커가 죽음) 조용히 넘어간다 —
        기다리던 `node.invoke`가 `PeerLost`로 끝난다."""
        if request.is_notification:
            return
        invoke = request.params.get("invoke")
        if isinstance(invoke, bool) or invoke != self.invoke:
            self.reject_stale(peer, request)
            return
        with contextlib.suppress(PeerLost):
            try:
                result = self._call(request.method, request.params)
            except Cancelled as exc:
                peer.respond_error(request, CANCELLED, str(exc) or "실행이 취소됐다")
                return
            except ContextViolation as exc:
                peer.respond_error(request, CONTEXT_VIOLATION, str(exc), _kind(exc))
                return
            except _UnknownMethod as exc:
                peer.respond_error(request, METHOD_NOT_FOUND, str(exc))
                return
            except _BadParams as exc:
                peer.respond_error(request, INVALID_PARAMS, f"{request.method}: {exc}")
                return
            except Exception as exc:
                peer.respond_error(request, NODE_ERROR, str(exc) or type(exc).__name__, _kind(exc))
                return
            try:
                peer.respond(request, result)
            except (TypeError, ValueError) as exc:  # JSON으로 보낼 수 없는 값
                peer.respond_error(request, NODE_ERROR, f"결과를 보낼 수 없다: {exc}", _kind(exc))

    def _call(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        ctx = self.ctx
        match method:
            case "ctx.capture":
                region = _decoded(params, "region", (Rect, type(None)))
                return {"image": encode(ctx.capture(region))}
            case "ctx.log":
                level = _param(params, "level", str)
                if level not in _LOG_LEVELS:
                    raise _BadParams(f"모르는 level {level!r}")
                getattr(ctx.log, level)(_param(params, "message", str))
                return {}
            case "ctx.vars.get":
                name = _param(params, "name", str)
                found = ctx.vars.has(name)
                return {"found": found, "value": encode(ctx.vars.get(name) if found else None)}
            case "ctx.vars.set":
                value = _decoded(params, "value", (object,))
                ctx.vars.set(_param(params, "name", str), value)
                return {}
            case "ctx.artifacts.save":
                image = _decoded(params, "image", (Image,))
                return {"path": ctx.artifacts.save(image, _param(params, "name", str))}
            case "ctx.input.click":
                at = _decoded(params, "at", (Point, Rect, Match))
                ctx.input.click(at, button=_param(params, "button", str))
                return {}
            case "ctx.input.key":
                ctx.input.key(_param(params, "key", str))
                return {}
            case "ctx.input.type_text":
                ctx.input.type_text(_decoded(params, "text", (str, Secret)))
                return {}
            case "ctx.setting":
                return {"value": encode(ctx.setting(_param(params, "key", str)))}
            case _:
                raise _UnknownMethod(f"모르는 ctx 메서드 {method}")


# ---------------------------------------------------------------- 실행 경계


# 응답 도착을 `incoming` 대기에서 바로 알아채기 위한 표지 (처리하지 않고 버린다)
_WAKE: Final = Incoming("$wake")


class WorkerInvoker:
    """원격 노드를 워커에서 실행한다 (`NodeInvoker`). runner 주 스레드가 부른다."""

    def __init__(self, worker: WorkerProcess) -> None:
        self.worker = worker

    def invoke(
        self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
    ) -> Result:
        worker = self.worker
        invoke = worker.next_invoke()
        server = CtxServer(nodedef, ctx, invoke)
        config = dict(ctx.config)
        try:
            params = {
                "invoke": invoke,
                "type": nodedef.type,
                "node_id": node.id,
                "step": _step_of(ctx),
                "inputs": encode(dict(inputs)),
                "config": encode(config),
                "window": encode(ctx.window),
                "pure": nodedef.pure,
                "effects": sorted(nodedef.effects),
                "deadline_remaining_ms": _remaining_ms(ctx),
            }
        except CodecError as exc:
            message = f"'{node.id}': 입력을 워커로 보낼 수 없다: {exc}"
            raise EngineError("input_unsendable", message) from exc
        worker.set_busy(True)
        try:
            try:
                call = worker.request(params)
            except PeerLost:
                ctx.check_cancel()
                raise worker.died() from None
            except (TypeError, ValueError) as exc:
                raise EngineError(
                    "input_unsendable", f"'{node.id}': 입력을 워커로 보낼 수 없다: {exc}"
                ) from exc
            cancelled = self._serve(call, server, ctx)
        finally:
            worker.set_busy(False)
        return self._outcome(nodedef, call, server, ctx, config, cancelled)

    def _serve(self, call: Call, server: CtxServer, ctx: Context) -> Cancelled | None:
        """응답이 올 때까지 워커의 `ctx` 요청을 처리한다. 그 사이 취소·기한을 보면 워커 취소를
        시작하고(유예 타이머) 계속 기다린다 — 워커가 취소로 답하거나 유예 뒤 끝난다."""
        peer = self.worker.peer
        assert peer is not None
        call.add_done_callback(lambda _: peer.incoming.put(_WAKE))
        cancelled: Cancelled | None = None
        while not call.done():
            try:
                item = peer.incoming.get(timeout=_POLL_S)
            except queue.Empty:
                item = None
            if isinstance(item, Incoming) and item is not _WAKE:
                server.handle(peer, item)
            if cancelled is None and not call.done():
                try:
                    ctx.check_cancel()
                except Cancelled as exc:
                    cancelled = exc
                    self.worker.cancel()
        # 실행이 끝난 뒤 남은 ctx 요청(노드가 남긴 스레드 등)은 이 실행의 것이 아니다
        while True:
            try:
                item = peer.incoming.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, Incoming) and item is not _WAKE:
                CtxServer.reject_stale(peer, item)
        return cancelled

    def _outcome(
        self,
        nodedef: NodeDef,
        call: Call,
        server: CtxServer,
        ctx: Context,
        config: Mapping[str, Any],
        cancelled: Cancelled | None,
    ) -> Result:
        try:
            reply = call.result()
        except PeerLost:
            if cancelled is not None:
                raise cancelled from None
            ctx.check_cancel()
            raise self.worker.died() from None
        except RpcError as exc:
            if cancelled is not None:
                raise cancelled from None
            if server.violations:
                raise server.violations[0] from None
            raise self._remote_error(exc, ctx) from None
        if server.violations:
            # 노드가 runner의 거부를 삼키고 정상으로 끝냈어도 error다
            raise server.violations[0]
        try:
            result = Result(
                reply["exit"],
                reply["kind"],
                decode(reply["outputs"]),
                reply.get("message"),
            )
        except (KeyError, TypeError, CodecError) as exc:
            raise NodeContractError(f"{nodedef.type}: 워커 결과를 읽을 수 없다: {exc!r}") from exc
        if not isinstance(result.outputs, dict):
            raise NodeContractError(f"{nodedef.type}: 워커 결과의 outputs가 객체가 아니다")
        return check_remote_result(nodedef, result, config)

    def _remote_error(self, exc: RpcError, ctx: Context) -> BaseException:
        if exc.code == CANCELLED:
            ctx.check_cancel()  # runner 쪽 취소·기한이면 그 종류로 (DeadlineExceeded 포함)
            data = exc.data if isinstance(exc.data, dict) else {}
            if data.get("reason") == "deadline":  # pyright: ignore[reportUnknownMemberType]
                return DeadlineExceeded(exc.message)
            return Cancelled(exc.message)
        if exc.code == CONTEXT_VIOLATION:
            return ContextViolation(exc.message)
        if exc.code == NODE_CONTRACT:
            return NodeContractError(exc.message)
        if exc.code == NODE_ERROR:
            data = exc.data if isinstance(exc.data, dict) else {}
            trace = data.get("traceback")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if isinstance(trace, str) and trace:
                with contextlib.suppress(Exception):
                    ctx.log.error(trace)
            return EngineError("node_error", exc.message)
        return EngineError("worker_protocol", f"워커가 알 수 없는 오류로 답했다: {exc}")


def _step_of(ctx: Context) -> str | None:
    step = getattr(ctx, "step", None)
    return step if isinstance(step, str) else None


def _remaining_ms(ctx: Context) -> int:
    remaining = getattr(ctx, "run_remaining_ms", None)
    return remaining if isinstance(remaining, int) else 2**31 - 1
