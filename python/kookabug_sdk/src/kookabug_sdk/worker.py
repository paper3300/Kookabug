"""워커 호스트: 플러그인 노드를 runner와 다른 프로세스에서 실행한다 (구현 계획 M0b 2.5).

    python -m kookabug_sdk.worker     (환경 변수 KOOKABUG_RPC_PIPE·KOOKABUG_RPC_KEY)

runner가 만든 파이프에 붙어 상호 인증한 뒤 JSON-RPC로 대화한다.

- `worker.hello`(runner → 워커): 받은 `modules`를 import해 `@node` 노드를 플러그인별 노드 스키마로
  돌려준다. runner는 플러그인 코드를 import하지 않고 이 스키마로 원격 노드를 등록한다
- `node.invoke`: 노드 하나를 실행한다. 결과는 SDK가 선언과 대조한 뒤 보내고, runner도 다시 대조한다
- `cancel`(알림): 이후 `ctx` 호출·`ctx.sleep`·`ctx.check_cancel`이 `Cancelled`. 응답하지 않는
  노드는 runner가 유예 뒤 프로세스를 끝낸다
- `worker.shutdown`: 응답하고 끝난다

`ctx`의 캡처·입력·기록·변수·설정은 runner에 요청한다(입력·캡처의 주체는 runner). `ctx.path()`는
실행 스냅샷 루트(`files_root`) 기준이다. stdout·stderr는 runner가 로그 파일로 받으므로
노드의 `print()`가 통신을 깨지 않는다. 연결을 잃으면(runner가 죽음) 곧바로 끝난다.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import queue
import sys
import threading
import time
import traceback
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Final, Protocol

from kookabug_sdk import _faults
from kookabug_sdk.codec import CodecError, decode, encode
from kookabug_sdk.console import utf8_stdio
from kookabug_sdk.context import (
    ArtifactsApi,
    Cancelled,
    ContextViolation,
    Deadline,
    InputApi,
    LogApi,
    VarsApi,
)
from kookabug_sdk.decorators import NodeFunction
from kookabug_sdk.pipe import connect
from kookabug_sdk.result import NodeContractError, Result
from kookabug_sdk.rpc import (
    CANCELLED,
    CONTEXT_VIOLATION,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    NODE_CONTRACT,
    NODE_ERROR,
    PROTOCOL_VERSION,
    Incoming,
    PeerLost,
    RpcError,
    RpcPeer,
)
from kookabug_sdk.schema import FORMAT
from kookabug_sdk.types import Image, Match, Point, Rect, Secret, WindowRef

__all__ = [
    "DEV_VERSION",
    "ENV_KEY",
    "ENV_PIPE",
    "EXIT_LOST",
    "PROTOCOL",
    "RunDeadline",
    "WorkerContext",
    "collect_plugins",
    "error_reply",
    "files_path",
    "main",
]

PROTOCOL: Final = 1
ENV_PIPE: Final = "KOOKABUG_RPC_PIPE"
ENV_KEY: Final = "KOOKABUG_RPC_KEY"
DEV_VERSION: Final = "0+dev"
"""설치된 배포판을 찾지 못한 플러그인 모듈의 버전 (개발용 `--plugin-module`)."""
EXIT_LOST: Final = 2
"""runner와의 연결을 잃고 끝날 때의 종료 코드."""
_SHUTDOWN_FLUSH_S: Final = 2.0
# 원격 ctx 오류의 예외 이름 → 다시 던질 예외 (노드 코드가 잡을 수 있는 흔한 것만)
_REMOTE_ERRORS: Final[dict[str, type[Exception]]] = {
    "KeyError": KeyError,
    "ValueError": ValueError,
    "TypeError": TypeError,
}


class RunDeadline(Cancelled):
    """테스트 전체 기한을 넘었다 (runner의 `DeadlineExceeded`에 해당)."""


# ---------------------------------------------------------------- 노드 모으기


def collect_plugins(modules: Sequence[str]) -> list[dict[str, Any]]:
    """`modules`를 import해 `@node` 노드를 플러그인 ID별 노드 스키마 문서로 모은다.

    결과: `[{id, version, schema}]` (ID 순). 버전은 모듈의 최상위 패키지를 설치한 배포판의 버전,
    없으면 `DEV_VERSION`.
    """
    found: dict[int, NodeFunction] = {}
    versions: dict[str, str] = {}
    distributions: Mapping[str, list[str]] | None = None
    for name in modules:
        _faults.fault_point("worker.in_import")
        module = importlib.import_module(name)
        for value in vars(module).values():
            if isinstance(value, NodeFunction):
                found.setdefault(id(value), value)
                if value.spec.plugin not in versions:
                    if distributions is None:
                        distributions = metadata.packages_distributions()  # 느리다: 한 번만
                    versions[value.spec.plugin] = _version_of(name, distributions)
    by_plugin: dict[str, list[NodeFunction]] = defaultdict(list)
    for fn in found.values():
        by_plugin[fn.spec.plugin].append(fn)
    plugins: list[dict[str, Any]] = []
    for plugin in sorted(by_plugin):
        nodes = sorted(by_plugin[plugin], key=lambda f: f.spec.type)
        version = versions[plugin]
        plugins.append(
            {
                "id": plugin,
                "version": version,
                "schema": {
                    "format": FORMAT,
                    "nodes": [f.schema() for f in nodes],
                    "plugin": {"id": plugin, "version": version},
                },
            }
        )
    return plugins


def _version_of(module: str, distributions: Mapping[str, list[str]]) -> str:
    top = module.split(".", 1)[0]
    for dist in distributions.get(top, []):
        with contextlib.suppress(metadata.PackageNotFoundError):
            return metadata.version(dist)
    return DEV_VERSION


def functions_of(modules: Iterable[str]) -> dict[str, NodeFunction]:
    """import한 모듈의 노드 (타입 → 함수)."""
    out: dict[str, NodeFunction] = {}
    for name in modules:
        for value in vars(sys.modules[name]).values():
            if isinstance(value, NodeFunction):
                out.setdefault(value.spec.type, value)
    return out


# ---------------------------------------------------------------- ctx


def files_path(root: Path, rel: str) -> Path:
    """`ctx.path(rel)`: 실행 스냅샷 루트 기준 경로('/' 구분). 밖으로 나가면(`..`·절대 경로) 오류.

    core `Workspace.resolve`와 같은 규칙이다.
    """
    bad = not isinstance(rel, str) or not rel or "\\" in rel or rel.startswith("/") or ":" in rel
    parts = [] if bad else rel.split("/")
    if bad or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"'{rel}'은(는) 워크스페이스 기준 경로가 아니다")
    return root.joinpath(*parts)


class Requester(Protocol):
    def __call__(self, method: str, params: dict[str, Any]) -> Any: ...


class _Clock:
    """실제 시계 (단조 시간, ms). `sleep`은 취소로 깬다."""

    def __init__(self, ctx: WorkerContext) -> None:
        self._ctx = ctx

    def now_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000

    def sleep(self, ms: int) -> None:
        self._ctx.sleep(ms)


class WorkerContext:
    """워커 안의 `ctx`. 노드에는 SDK `guard()`로 감싼 것이 간다 (`NodeFunction.invoke`).

    `node.invoke` 하나에만 쓴다: 모든 요청에 그 실행 번호(`invoke`)를 싣고, 실행이 끝나면
    `close()`로 닫는다. 닫힌 ctx(노드가 보관해 둔 이전 ctx, 노드가 남긴 스레드)로는 runner에
    요청하지 않는다 — 다음 노드의 선언·기록 정책으로 처리되면 안 된다.
    """

    def __init__(
        self,
        *,
        request: Requester,
        cancel: threading.Event,
        files_root: Path,
        config: Mapping[str, Any],
        window: WindowRef | None,
        deadline_remaining_ms: int,
        invoke: int = 1,
    ) -> None:
        self._request = request
        self._cancel = cancel
        self._files_root = files_root
        self._config = config
        self._window = window
        self._clock = _Clock(self)
        self._run_end = self._clock.now_ms() + max(0, deadline_remaining_ms)
        self.invoke = invoke
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def call(self, method: str, params: dict[str, Any]) -> Any:
        """runner에 `ctx` 요청을 보내고 응답을 기다린다. runner의 오류는 같은 종류로 다시 던진다."""
        if self._closed:
            raise ContextViolation(f"끝난 노드 실행의 ctx로 {method}을(를) 부를 수 없다")
        self.check_cancel()
        try:
            return self._request(method, {**params, "invoke": self.invoke})
        except RpcError as exc:
            raise _remote_error(exc) from None

    @property
    def config(self) -> Mapping[str, Any]:
        return self._config

    @property
    def window(self) -> WindowRef | None:
        return self._window

    @property
    def vars(self) -> VarsApi:
        return _RemoteVars(self)

    @property
    def log(self) -> LogApi:
        return _RemoteLog(self)

    @property
    def artifacts(self) -> ArtifactsApi:
        return _RemoteArtifacts(self)

    @property
    def input(self) -> InputApi:
        return _RemoteInput(self)

    def capture(self, region: Rect | None = None) -> Image:
        image = decode(self.call("ctx.capture", {"region": encode(region)})["image"])
        if not isinstance(image, Image):
            raise ContextViolation("runner가 캡처 결과로 이미지가 아닌 값을 줬다")
        return image

    def deadline(self, ms: int) -> Deadline:
        return Deadline(self._clock, self._clock.now_ms() + ms)

    def sleep(self, ms: int) -> None:
        """기다린다. 취소되면 바로 깨고, 전체 기한을 넘는 만큼은 기다리지 않는다."""
        self.check_cancel()
        if ms < 0:
            raise ValueError(f"sleep 시간은 0 이상이다: {ms}")
        remaining = self._run_end - self._clock.now_ms()
        if self._cancel.wait(min(ms, max(remaining, 0)) / 1000):
            self.check_cancel()
        if ms >= remaining:
            raise RunDeadline("테스트 전체 기한을 넘었다")
        self.check_cancel()

    def check_cancel(self) -> None:
        if self._cancel.is_set():
            raise Cancelled("실행이 취소됐다")
        if self._clock.now_ms() >= self._run_end:
            raise RunDeadline("테스트 전체 기한을 넘었다")

    def setting(self, key: str) -> Any:
        return decode(self.call("ctx.setting", {"key": key})["value"])

    def path(self, rel: str) -> Path:
        return files_path(self._files_root, rel)


def _remote_error(exc: RpcError) -> BaseException:
    if exc.code == CANCELLED:
        return Cancelled(exc.message)
    if exc.code == CONTEXT_VIOLATION:
        return ContextViolation(exc.message)
    if exc.code == NODE_CONTRACT:
        return NodeContractError(exc.message)
    data = exc.data if isinstance(exc.data, dict) else {}
    kind = _REMOTE_ERRORS.get(str(data.get("type")), RuntimeError)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    return kind(exc.message)


class _RemoteVars:
    def __init__(self, ctx: WorkerContext) -> None:
        self._ctx = ctx

    def _get(self, name: str) -> tuple[bool, Any]:
        reply = self._ctx.call("ctx.vars.get", {"name": name})
        return bool(reply["found"]), decode(reply["value"])

    def get(self, name: str, default: Any = ...) -> Any:
        found, value = self._get(name)
        if found:
            return value
        if default is ...:
            raise KeyError(f"변수 '{name}'이(가) 없다")
        return default

    def has(self, name: str) -> bool:
        return self._get(name)[0]

    def set(self, name: str, value: Any) -> None:
        self._ctx.call("ctx.vars.set", {"name": name, "value": encode(value)})


class _RemoteLog:
    def __init__(self, ctx: WorkerContext) -> None:
        self._ctx = ctx

    def _log(self, level: str, message: object) -> None:
        # str()로 보내므로 비밀값은 가려진다 (runner의 StepLog와 같다)
        self._ctx.call("ctx.log", {"level": level, "message": str(message)})

    def debug(self, message: object) -> None:
        self._log("debug", message)

    def info(self, message: object) -> None:
        self._log("info", message)

    def warn(self, message: object) -> None:
        self._log("warn", message)

    def error(self, message: object) -> None:
        self._log("error", message)


class _RemoteArtifacts:
    def __init__(self, ctx: WorkerContext) -> None:
        self._ctx = ctx

    def save(self, image: Image, name: str) -> str | None:
        path = self._ctx.call("ctx.artifacts.save", {"image": encode(image), "name": name})["path"]
        return path if isinstance(path, str) else None


class _RemoteInput:
    def __init__(self, ctx: WorkerContext) -> None:
        self._ctx = ctx

    def click(self, at: Point | Rect | Match, *, button: str = "left") -> None:
        self._ctx.call("ctx.input.click", {"at": encode(at), "button": button})

    def key(self, key: str) -> None:
        self._ctx.call("ctx.input.key", {"key": key})

    def type_text(self, text: str | Secret) -> None:
        self._ctx.call("ctx.input.type_text", {"text": encode(text)})


# ---------------------------------------------------------------- 오류 응답


@dataclass(frozen=True, slots=True)
class ErrorReply:
    code: int
    message: str
    data: dict[str, Any]


def error_reply(exc: BaseException) -> ErrorReply:
    """노드 실행 중 예외 → 오류 응답 (runner가 엔진의 `error_code()` 분류로 되돌린다)."""
    message = str(exc)
    if isinstance(exc, Cancelled):
        reason = "deadline" if isinstance(exc, RunDeadline) else "cancelled"
        return ErrorReply(CANCELLED, message or "실행이 취소됐다", {"reason": reason})
    data: dict[str, Any] = {"type": type(exc).__name__}
    if isinstance(exc, ContextViolation):
        return ErrorReply(CONTEXT_VIOLATION, message or type(exc).__name__, data)
    if isinstance(exc, NodeContractError):
        return ErrorReply(NODE_CONTRACT, message or type(exc).__name__, data)
    data["message"] = message
    data["traceback"] = "".join(traceback.format_exception(exc))
    text = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
    return ErrorReply(NODE_ERROR, text, data)


# ---------------------------------------------------------------- 호스트


class _Stop:
    pass


class WorkerHost:
    """연결 하나를 맡는다. 주 스레드가 hello·invoke·shutdown을 차례로 처리하고, 분배 스레드가
    받은 메시지를 나눈다(취소 알림은 노드 실행 중에도 바로 반영)."""

    def __init__(self, peer: RpcPeer, *, on_lost: Callable[[], None]) -> None:
        self.peer = peer
        self.cancel = threading.Event()
        self._on_lost = on_lost
        self._jobs: queue.Queue[Incoming | _Stop] = queue.Queue()
        self._modules: tuple[str, ...] | None = None
        self._functions: dict[str, NodeFunction] = {}
        self._files_root = Path()
        self._closing = threading.Event()
        """정상 종료를 시작했다: 이후의 연결 상실(자기 `close()` 포함)은 외부 상실이 아니다."""

    def serve(self) -> int:
        threading.Thread(target=self._dispatch, name="worker-dispatch", daemon=True).start()
        while True:
            job = self._jobs.get()
            if isinstance(job, _Stop):
                return EXIT_LOST
            try:
                match job.method:
                    case "worker.hello":
                        self._hello(job)
                    case "node.invoke":
                        self._invoke(job)
                    case "worker.shutdown":
                        # 닫기 전에 표시한다: close()가 incoming에 넣는 PeerLost를 분배 스레드가
                        # 연결 상실(os._exit(EXIT_LOST))로 처리하지 않게
                        self._closing.set()
                        with contextlib.suppress(PeerLost):
                            self.peer.respond(job, {})
                        self.peer.close(flush_timeout=_SHUTDOWN_FLUSH_S)
                        return 0
                    case _:
                        message = f"모르는 메서드 {job.method}"
                        self.peer.respond_error(job, METHOD_NOT_FOUND, message)
            except PeerLost:
                return EXIT_LOST

    def _dispatch(self) -> None:
        while True:
            item = self.peer.incoming.get()
            if isinstance(item, PeerLost):
                if self._closing.is_set():
                    return  # 정상 종료: 주 스레드가 끝낸다
                self.cancel.set()
                self._jobs.put(_Stop())
                self._on_lost()
                return
            if item.method == "cancel":
                self.cancel.set()
            elif item.method in ("worker.hello", "node.invoke", "worker.shutdown"):
                self._jobs.put(item)
            elif not item.is_notification:
                with contextlib.suppress(PeerLost):
                    self.peer.respond_error(item, METHOD_NOT_FOUND, f"모르는 메서드 {item.method}")

    def _hello(self, job: Incoming) -> None:
        params = job.params
        protocol = params.get("protocol")
        if protocol != PROTOCOL:
            self.peer.respond_error(
                job,
                PROTOCOL_VERSION,
                f"프로토콜 {protocol!r}을(를) 모른다 (이 워커는 {PROTOCOL})",
                {"protocol": PROTOCOL},
            )
            return
        modules = params.get("modules")
        if not isinstance(modules, list) or not all(isinstance(m, str) for m in modules):  # pyright: ignore[reportUnknownVariableType]
            self.peer.respond_error(job, INVALID_PARAMS, "hello의 modules는 문자열 목록이다")
            return
        names: list[str] = modules  # pyright: ignore[reportUnknownVariableType]
        try:
            plugins = collect_plugins(names)
        except Exception as exc:
            reply = error_reply(exc)
            self.peer.respond_error(
                job, NODE_ERROR, f"플러그인 모듈을 import할 수 없다: {reply.message}", reply.data
            )
            return
        self._modules = tuple(names)
        self._functions = functions_of(names)
        self._files_root = Path(str(params.get("files_root", ".")))
        _faults.fault_point("worker.before_hello_reply")
        self.peer.respond(job, {"protocol": PROTOCOL, "plugins": plugins})

    def _invoke(self, job: Incoming) -> None:
        params = job.params
        fn = self._functions.get(str(params.get("type")))
        if self._modules is None or fn is None:
            self.peer.respond_error(
                job, NODE_CONTRACT, f"워커에 노드 '{params.get('type')}'이(가) 없다"
            )
            return
        try:
            result = self._run(fn, params)
            reply = {
                "exit": result.exit,
                "kind": result.kind,
                "outputs": encode(dict(result.outputs)),
                "message": result.message,
            }
        except BaseException as exc:  # 노드 코드의 어떤 예외도 오류 응답으로 (워커는 계속 산다)
            reply_error = error_reply(exc)
            self.peer.respond_error(job, reply_error.code, reply_error.message, reply_error.data)
            return
        try:
            self.peer.respond(job, reply)
        except (TypeError, ValueError) as exc:  # JSON으로 보낼 수 없는 출력 (큰 정수·NaN 등)
            self.peer.respond_error(
                job, NODE_CONTRACT, f"{fn.spec.type}: 출력을 runner로 보낼 수 없다: {exc}"
            )

    def _run(self, fn: NodeFunction, params: dict[str, Any]) -> Result:
        spec = fn.spec
        if bool(params.get("pure")) != spec.pure or sorted(params.get("effects", [])) != sorted(
            spec.effects
        ):
            raise NodeContractError(f"{spec.type}: runner가 아는 선언과 워커의 선언이 다르다")
        try:
            inputs = decode(params.get("inputs", {}))
            config = decode(params.get("config", {}))
            window = decode(params.get("window"))
        except CodecError as exc:
            raise NodeContractError(f"{spec.type}: 입력을 읽을 수 없다: {exc}") from exc
        if not isinstance(inputs, dict) or not isinstance(config, dict):
            raise NodeContractError(f"{spec.type}: inputs·config는 객체다")
        if window is not None and not isinstance(window, WindowRef):
            raise NodeContractError(f"{spec.type}: window가 창 값이 아니다")
        invoke = params.get("invoke")
        if isinstance(invoke, bool) or not isinstance(invoke, int) or invoke < 1:
            raise NodeContractError(f"{spec.type}: 실행 번호(invoke)가 없다")
        remaining = params.get("deadline_remaining_ms")
        ctx = WorkerContext(
            request=self._request,
            cancel=self.cancel,
            files_root=self._files_root,
            config=config,  # pyright: ignore[reportUnknownArgumentType]
            window=window,
            deadline_remaining_ms=remaining if isinstance(remaining, int) else 0,
            invoke=invoke,
        )
        try:
            return fn.invoke(ctx, inputs)  # pyright: ignore[reportUnknownArgumentType]
        finally:
            ctx.close()

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        try:
            return self.peer.request(method, params).result()
        except PeerLost as exc:
            raise RuntimeError(f"runner와의 연결을 잃었다: {exc}") from exc


def _flush_stdio() -> None:
    """프로세스의 실제 stdout·stderr(로그 파일) 버퍼를 비운다. 플러그인이 `sys.stdout`을 바꿔
    끼웠어도 그 객체는 부르지 않는다 — 워커 종료가 플러그인 코드에 막히지 않게."""
    for stream in (sys.__stdout__, sys.__stderr__):
        if stream is not None:
            with contextlib.suppress(Exception):
                stream.flush()


def _exit_lost() -> None:
    """runner를 잃었다: 노드가 아직 돌고 있어도 끝낸다 (print 버퍼만 비우고)."""
    _flush_stdio()
    os._exit(EXIT_LOST)


def main() -> None:
    utf8_stdio()
    _faults.set_role("worker")
    name = os.environ.get(ENV_PIPE)
    key = os.environ.get(ENV_KEY)
    if not name or not key:
        print(f"{ENV_PIPE}·{ENV_KEY}가 없다 (runner가 띄우는 프로세스다)", file=sys.stderr)
        sys.exit(EXIT_LOST)
    peer = RpcPeer(connect(name, bytes.fromhex(key)), name="worker").start()
    code = WorkerHost(peer, on_lost=_exit_lost).serve()
    # 프로세스를 끝내는 곳은 여기 하나다 (정상 종료). 분배 스레드는 정상 종료 중에는 끝내지 않는다
    _flush_stdio()
    os._exit(code)


if __name__ == "__main__":
    main()
