"""JSON-RPC 2.0 피어 (구현 계획 M0b 2.2). 연결 하나에 읽기 스레드 하나와 송신 스레드 하나.

- 보내기(`request`·`notify`·`respond`)는 제한 있는 송신 큐에 넣기만 하고 바로 돌아온다. 호출한
  스레드는 파이프 I/O를 하지 않으므로, 상대가 읽지 않아도 막히지 않는다 (제어 스레드의 감시 타이머가
  송신 정체와 무관하게 돈다)
- 큐가 차거나 한 프레임 쓰기가 기한을 넘으면 연결을 잃은 것이다 → 대기 중인 요청은 모두 `PeerLost`
- 응답은 요청 id로 짝지어 대기 중인 요청에 준다 (보낸 순서와 무관)
- 받은 요청·알림은 `incoming` 큐로 간다. 처리하는 쪽(예: runner 주 스레드)이 꺼내 `respond`한다.
  연결을 잃으면 `incoming`에 `PeerLost` 하나가 들어간다
- 양쪽 모두 요청을 보낸다. id는 보낸 쪽마다 1부터 센다

메시지 형식의 단일 출처는 `packages/schema/rpc.schema.json`이다. SDK는 스키마를 읽지 않으므로
봉투 규칙(메시지 종류별 필드, method 형식, 오류 코드)을 여기서 같은 내용으로 검사한다.

- 보내기: 규칙에 맞지 않는 method·params·오류 코드·값은 큐에 넣기 전에 `ValueError`/`TypeError`
- 받기: 봉투가 틀린 요청은 `invalid_request`/`invalid_params`로 답하고 처리기에 넘기지 않는다
  (알림은 버린다). 봉투가 틀린 응답은 짝지은 요청을 `InvalidResponse`로 끝낸다
- 값: JSON 숫자만(NaN·Infinity·지수 넘침 금지), 정수는 ±(2^53-1) 안, 중첩은 `MAX_DEPTH`까지.
  받은 프레임이 JSON으로 읽히지 않으면(이 값 규칙 위반 포함) `parse_error`를 보내고 연결을 잃은
  것으로 한다 — 어느 요청의 응답인지 알 수 없어 대기 중인 요청이 끝나지 않기 때문이다
"""

from __future__ import annotations

import contextlib
import itertools
import json
import math
import queue
import re
import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, InvalidStateError
from dataclasses import dataclass, field
from typing import Any, Final, TypeIs

from kookabug_sdk.pipe import MAX_FRAME, WRITE_TIMEOUT, PipeConnection, PipeError

__all__ = [
    "CANCELLED",
    "CONTEXT_VIOLATION",
    "ERROR_CODES",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "MAX_DEPTH",
    "METHOD_NOT_FOUND",
    "NODE_CONTRACT",
    "NODE_ERROR",
    "PARSE_ERROR",
    "PROTOCOL_VERSION",
    "SEND_QUEUE_SIZE",
    "Call",
    "Incoming",
    "InvalidResponse",
    "PeerLost",
    "RpcError",
    "RpcPeer",
]

# 표준 오류 코드
PARSE_ERROR: Final = -32700
INVALID_REQUEST: Final = -32600
METHOD_NOT_FOUND: Final = -32601
INVALID_PARAMS: Final = -32602
INTERNAL_ERROR: Final = -32603
# 엔진의 error_code() 분류를 경계 너머로 옮기는 코드
CANCELLED: Final = -32001
NODE_ERROR: Final = -32002
CONTEXT_VIOLATION: Final = -32003
NODE_CONTRACT: Final = -32004
PROTOCOL_VERSION: Final = -32005

ERROR_CODES: Final[dict[int, str]] = {
    PARSE_ERROR: "parse_error",
    INVALID_REQUEST: "invalid_request",
    METHOD_NOT_FOUND: "method_not_found",
    INVALID_PARAMS: "invalid_params",
    INTERNAL_ERROR: "internal_error",
    CANCELLED: "cancelled",
    NODE_ERROR: "node_error",
    CONTEXT_VIOLATION: "context_violation",
    NODE_CONTRACT: "node_contract",
    PROTOCOL_VERSION: "protocol_version",
}

SEND_QUEUE_SIZE: Final = 256
# 메시지 전체의 객체·배열 중첩 한도 (봉투 2단 포함)
MAX_DEPTH: Final = 128
_MAX_SAFE_INTEGER: Final = 2**53 - 1
_METHOD: Final = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*")
_REQUEST_KEYS: Final = frozenset({"jsonrpc", "id", "method", "params"})
_ERROR_KEYS: Final = frozenset({"code", "message", "data"})


class RpcError(Exception):
    """상대가 오류로 응답했다."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"{ERROR_CODES.get(code, code)}: {message}")
        self.code = code
        self.message = message
        self.data = data


class InvalidResponse(RpcError):
    """상대의 응답이 봉투 형식에 맞지 않는다 (상대가 보낸 오류가 아니라 이쪽에서 판정)."""

    def __init__(self, problem: str) -> None:
        super().__init__(INVALID_REQUEST, f"응답 형식이 틀렸다: {problem}")


class PeerLost(Exception):
    """연결을 잃었다 (상대가 끊음·죽음, 송신 큐가 참, 쓰기 기한 초과, `close()`)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Incoming:
    """받은 요청(`id` 있음) 또는 알림(`id` 없음)."""

    method: str
    params: dict[str, Any] = field(default_factory=dict[str, Any])
    id: int | None = None

    @property
    def is_notification(self) -> bool:
        return self.id is None


class Call(Future[Any]):
    """보낸 요청 하나의 응답. `result()`는 응답 값이고, 오류 응답이면 `RpcError`, 연결을 잃으면
    `PeerLost`."""

    def __init__(self, request_id: int, method: str) -> None:
        super().__init__()
        self.id = request_id
        self.method = method


def _check_int(value: int) -> int:
    if abs(value) > _MAX_SAFE_INTEGER:
        raise ValueError(f"정수 {value}는 ±(2^53-1) 밖이다")
    return value


def _check_float(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{value}는 JSON 숫자가 아니다 (NaN·Infinity)")
    return value


def _check_value(value: object) -> None:
    """JSON 값 규칙 (숫자·키·중첩). 재귀하지 않으므로 아주 깊은 값에서도 스택이 넘치지 않는다."""
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, dict | list | tuple):
            if depth >= MAX_DEPTH:
                raise ValueError(f"중첩이 {MAX_DEPTH}단을 넘는다")
            if isinstance(item, dict):
                for key, child in item.items():  # pyright: ignore[reportUnknownVariableType]
                    if not isinstance(key, str):
                        raise TypeError(f"객체 키는 문자열이어야 한다: {key!r}")
                    stack.append((child, depth + 1))
            else:
                stack.extend((child, depth + 1) for child in item)  # pyright: ignore[reportUnknownVariableType]
        elif isinstance(item, bool) or item is None or isinstance(item, str):
            continue
        elif isinstance(item, int):
            _check_int(item)
        elif isinstance(item, float):
            _check_float(item)
        else:
            raise TypeError(f"JSON 값이 아니다: {type(item).__name__}")


def _encode(message: dict[str, Any]) -> bytes:
    _check_value(message)
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    data = body.encode("utf-8")
    if len(data) > MAX_FRAME:
        raise ValueError(f"메시지가 프레임 상한({MAX_FRAME}바이트)보다 크다: {len(data)}")
    return data


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name}는 JSON 숫자가 아니다")


def _decode(frame: bytes) -> Any:
    """프레임 본문 → JSON 값. 값 규칙을 어기거나 읽을 수 없으면 `ValueError`."""
    try:
        value = json.loads(
            frame.decode("utf-8"),
            parse_constant=_reject_constant,
            parse_float=lambda text: _check_float(float(text)),
            parse_int=lambda text: _check_int(int(text)),
        )
    except RecursionError as e:
        raise ValueError(f"중첩이 너무 깊다 (최대 {MAX_DEPTH}단)") from e
    _check_value(value)
    return value


def _is_id(value: object) -> TypeIs[int]:
    return (
        isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= _MAX_SAFE_INTEGER
    )


def _check_method(method: object) -> None:
    if not isinstance(method, str) or not _METHOD.fullmatch(method):
        raise ValueError(
            f"method는 점으로 나눈 소문자 이름이어야 한다 (예: node.invoke): {method!r}"
        )


def _check_params(params: object) -> None:
    if params is not None and not isinstance(params, dict):
        raise TypeError(f"params는 객체(dict)여야 한다: {type(params).__name__}")


def _check_error(code: object, message: object) -> None:
    if isinstance(code, bool) or code not in ERROR_CODES:
        raise ValueError(f"모르는 오류 코드 {code!r}. 가능한 값: {sorted(ERROR_CODES)}")
    if not isinstance(message, str):
        raise TypeError("오류 message는 문자열이어야 한다")


def _response_problem(msg: dict[str, Any]) -> str | None:
    """응답 봉투가 스키마(SuccessResponse·ErrorResponse)에 맞지 않으면 그 이유."""
    if "result" in msg and "error" in msg:
        return "result와 error가 함께 있다"
    expected = {"jsonrpc", "id", "result" if "result" in msg else "error"}
    if extra := sorted(set(msg) - expected):
        return f"알 수 없는 필드 {extra}"
    if "error" in msg:
        error = msg["error"]
        if not isinstance(error, dict):
            return "error가 객체가 아니다"
        if extra := sorted(set(error) - _ERROR_KEYS):  # pyright: ignore[reportUnknownArgumentType]
            return f"error에 알 수 없는 필드 {extra}"
        try:
            _check_error(error.get("code"), error.get("message"))  # pyright: ignore[reportUnknownMemberType]
        except (TypeError, ValueError) as e:
            return str(e)
    return None


class RpcPeer:
    """인증된 `PipeConnection` 위의 JSON-RPC 피어. `start()` 뒤에 쓴다."""

    def __init__(
        self,
        conn: PipeConnection,
        *,
        name: str = "rpc",
        queue_size: int = SEND_QUEUE_SIZE,
        write_timeout: float | None = WRITE_TIMEOUT,
        trace: Callable[[str, bytes], None] | None = None,
    ) -> None:
        """`trace("send"|"recv", 프레임 본문)`은 주고받는 메시지를 보는 검사용 훅이다
        (송신·읽기 스레드에서 불린다)."""
        self.name = name
        self._trace = trace
        self.incoming: queue.Queue[Incoming | PeerLost] = queue.Queue()
        self._conn = conn
        self._queue_size = queue_size
        self._write_timeout = write_timeout
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._sendable = threading.Condition(self._lock)
        self._outbox: deque[bytes] = deque()
        self._writing = False
        self._calls: dict[int, Call] = {}
        self._lost: PeerLost | None = None
        self._threads = [
            threading.Thread(target=self._read_loop, name=f"{name}-read", daemon=True),
            threading.Thread(target=self._send_loop, name=f"{name}-send", daemon=True),
        ]

    def start(self) -> RpcPeer:
        for thread in self._threads:
            thread.start()
        return self

    @property
    def lost(self) -> PeerLost | None:
        """연결을 잃었으면 그 사유."""
        return self._lost

    @property
    def queued(self) -> int:
        """아직 다 쓰지 못한 메시지 수 (쓰는 중인 것 포함)."""
        with self._lock:
            return len(self._outbox) + self._writing

    # ── 보내기 ───────────────────────────────────────────────────────

    def request(self, method: str, params: dict[str, Any] | None = None) -> Call:
        """요청을 송신 큐에 넣고 응답을 기다릴 `Call`을 돌려준다."""
        _check_method(method)
        _check_params(params)
        request_id = next(self._ids)
        call = Call(request_id, method)
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        data = _encode(message)
        with self._lock:
            self._check_alive()
            self._calls[request_id] = call
        try:
            self._enqueue(data)
        except PeerLost:
            self._forget(call)
            raise
        return call

    def call(
        self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None
    ) -> Any:
        """요청하고 응답 값을 기다린다. 기한을 넘기면 `TimeoutError`(늦은 응답은 버린다)."""
        pending = self.request(method, params)
        try:
            return pending.result(timeout)
        except TimeoutError:
            self._forget(pending)
            raise

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """알림 (응답 없음)."""
        _check_method(method)
        _check_params(params)
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._enqueue(_encode(message))

    def respond(self, request: Incoming, result: Any) -> None:
        if request.id is None:
            raise ValueError(f"알림에는 응답하지 않는다: {request.method}")
        self._enqueue(_encode({"jsonrpc": "2.0", "id": request.id, "result": result}))

    def respond_error(self, request: Incoming, code: int, message: str, data: Any = None) -> None:
        if request.id is None:
            raise ValueError(f"알림에는 응답하지 않는다: {request.method}")
        self._send_error(request.id, code, message, data)

    def _send_error(
        self, request_id: int | None, code: int, message: str, data: Any = None
    ) -> None:
        _check_error(code, message)
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        self._enqueue(_encode({"jsonrpc": "2.0", "id": request_id, "error": error}))

    def _enqueue(self, data: bytes) -> None:
        with self._lock:
            self._check_alive()
            full = len(self._outbox) >= self._queue_size
            if not full:
                self._outbox.append(data)
                self._sendable.notify_all()
        if full:
            reason = f"송신 큐가 찼다 ({self._queue_size}개): 상대가 읽지 않는다"
            self._lose(reason)
            raise PeerLost(reason)

    def _check_alive(self) -> None:
        if self._lost is not None:
            raise PeerLost(self._lost.reason)

    def _forget(self, call: Call) -> None:
        with self._lock:
            self._calls.pop(call.id, None)

    # ── 스레드 ───────────────────────────────────────────────────────

    def _send_loop(self) -> None:
        try:
            self._send_frames()
        except BaseException as e:  # 어떤 예외로 끝나도 대기 중인 요청이 남지 않게
            self._lose(f"송신 스레드가 예외로 끝났다: {e!r}")

    def _read_loop(self) -> None:
        try:
            self._read_frames()
        except BaseException as e:  # 어떤 예외로 끝나도 대기 중인 요청이 남지 않게
            self._lose(f"읽기 스레드가 예외로 끝났다: {e!r}")

    def _send_frames(self) -> None:
        while True:
            with self._lock:
                while not self._outbox and self._lost is None:
                    self._sendable.wait()
                if self._lost is not None:
                    return
                data = self._outbox.popleft()
                self._writing = True
            try:
                if self._trace is not None:
                    self._trace("send", data)
                self._conn.send_frame(data, self._write_timeout)
            except PipeError as e:
                self._lose(f"보내기 실패: {e}")
                return
            finally:
                with self._lock:
                    self._writing = False
                    self._sendable.notify_all()

    def _read_frames(self) -> None:
        while True:
            try:
                frame = self._conn.recv_frame()
            except PipeError as e:
                self._lose(f"받기 실패: {e}")
                return
            if self._trace is not None:
                self._trace("recv", frame)
            try:
                message = _decode(frame)
            except ValueError as e:
                self._abort(PARSE_ERROR, f"받은 프레임을 JSON으로 읽을 수 없다: {e}")
                return
            try:
                self._dispatch(message)
            except PeerLost:
                return

    def _dispatch(self, message: Any) -> None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            self._send_error(None, INVALID_REQUEST, "JSON-RPC 2.0 메시지가 아니다")
            return
        msg: dict[str, Any] = message
        if "method" in msg:
            self._on_request(msg)
        elif "result" in msg or "error" in msg:
            self._on_response(msg)
        else:
            self._send_error(None, INVALID_REQUEST, "method도 result·error도 없다")

    def _on_request(self, msg: dict[str, Any]) -> None:
        """Request·Notification 봉투를 검사하고 맞으면 `incoming`에 넣는다."""
        is_request = "id" in msg
        request_id = msg.get("id")
        if is_request and not _is_id(request_id):
            self._send_error(None, INVALID_REQUEST, "id는 1 이상의 정수여야 한다")
            return
        reply_id = request_id if is_request else None

        def reject(code: int, message: str) -> None:
            if is_request:  # 알림에는 오류로도 답하지 않는다
                self._send_error(reply_id, code, message)

        if extra := sorted(set(msg) - _REQUEST_KEYS):
            reject(INVALID_REQUEST, f"알 수 없는 필드 {extra}")
            return
        try:
            _check_method(msg["method"])
        except ValueError as e:
            reject(INVALID_REQUEST, str(e))
            return
        params = msg.get("params", {})
        if not isinstance(params, dict):
            reject(INVALID_PARAMS, "params는 객체여야 한다")
            return
        self.incoming.put(Incoming(msg["method"], params, reply_id))  # pyright: ignore[reportUnknownArgumentType]

    def _on_response(self, msg: dict[str, Any]) -> None:
        request_id = msg.get("id")
        if not _is_id(request_id):
            return  # 상대가 우리 메시지를 읽지 못했다는 응답 (id 없음): 짝지을 요청이 없다
        with self._lock:
            call = self._calls.pop(request_id, None)
        if call is None:
            return  # 기한이 지나 버린 요청의 늦은 응답
        problem = _response_problem(msg)
        with contextlib.suppress(InvalidStateError):  # 호출한 쪽이 이미 취소했다
            if problem is not None:
                call.set_exception(InvalidResponse(problem))
            elif "error" in msg:
                error = msg["error"]
                call.set_exception(RpcError(error["code"], error["message"], error.get("data")))
            else:
                call.set_result(msg["result"])

    def _abort(self, code: int, reason: str) -> None:
        """상대에게 오류(id null)를 알리고(최대 1초 기다림) 연결을 잃은 것으로 한다."""
        with contextlib.suppress(PeerLost):
            self._send_error(None, code, reason)
            self._flush(1.0)
        self._lose(reason)

    def _flush(self, timeout: float) -> None:
        with self._lock:
            self._sendable.wait_for(
                lambda: self._lost is not None or not (self._outbox or self._writing), timeout
            )

    # ── 잃기·닫기 ─────────────────────────────────────────────────────

    def _lose(self, reason: str) -> None:
        with self._lock:
            if self._lost is not None:
                return
            self._lost = PeerLost(reason)
            calls = list(self._calls.values())
            self._calls.clear()
            self._outbox.clear()
            self._sendable.notify_all()
        self._conn.close()
        for call in calls:
            with contextlib.suppress(InvalidStateError):  # 호출한 쪽이 이미 취소했다
                call.set_exception(PeerLost(reason))
        self.incoming.put(self._lost)

    def close(self, flush_timeout: float = 0.0) -> None:
        """닫는다. `flush_timeout` 초까지 송신 큐가 빌 때를 기다린 뒤(예: 마지막 응답) 연결을
        닫는다. 대기 중인 요청은 `PeerLost`로 끝난다."""
        if flush_timeout > 0:
            self._flush(flush_timeout)
        self._lose("이쪽에서 닫았다")

    def join(self, timeout: float | None = None) -> None:
        """읽기·송신 스레드가 끝날 때까지 기다린다 (닫은 뒤)."""
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout)
