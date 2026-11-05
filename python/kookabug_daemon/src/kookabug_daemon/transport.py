"""WebSocket 전송 (M2 계획 2.4).

- 127.0.0.1에만 바인드한다. 업그레이드 요청의 `Host`가 `127.0.0.1:<포트>`가 아니거나 `Origin`이
  있으면 403으로 거부한다 (DNS 재바인딩·브라우저 페이지 차단)
- 텍스트 프레임 하나 = JSON-RPC 메시지 하나. 바이너리 프레임은 연결을 닫는다(1003). 상한 16 MiB를
  넘는 프레임은 websockets가 닫는다(1009). 읽을 수 없는 프레임(값 규칙 위반 포함)은 `parse_error`를
  보낸 뒤 닫는다(1007)
- 첫 메시지는 기한(5초) 안의 `session.hello`여야 한다. 아니면 `unauthenticated`를 보내고
  닫는다(1008)
- 봉투가 틀린 요청은 `invalid_request`로 답하고 처리하지 않는다. 요청은 동시에 처리하고 응답은 id로
  짝짓는다
- **송신 큐**(연결마다): 상한 8 MiB 또는 메시지 10,000개. 실행 이벤트(`run_id`를 붙인 알림)가 넘치면
  큐에 남은 그 실행의 이벤트를 버리고 `run.lagged`를 보낸다. 그 뒤 그 실행의 알림은 다시 구독할
  때까지(`resume_run`) 보내지 않는다. 일반 응답·알림이 넘치면 연결을 끊는다
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any, Final, Literal, Protocol

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.permissions import TOOLSETS, Principal
from kookabug_daemon.methods import Call, DaemonContext, MethodSpec
from kookabug_daemon.methods.session import InvalidHello, hello
from kookabug_daemon.methods.tools import Authorizer
from kookabug_daemon.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    MAX_FRAME,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL,
    InvalidParams,
    RequestFailed,
    decode,
    diagnostics_data,
    encode,
    error_message,
    methods,
    notification_problems,
    params_problems,
    request_problems,
    response_problems,
    result_problems,
    success_message,
    utf8_size,
)
from kookabug_daemon.protocol import request_id as protocol_request_id

__all__ = [
    "CLOSE_BINARY",
    "CLOSE_GOING_AWAY",
    "CLOSE_PARSE_ERROR",
    "CLOSE_POLICY",
    "Connection",
    "Host",
    "Limits",
    "Outbox",
    "Transport",
]

log = logging.getLogger(__name__)

CLOSE_GOING_AWAY: Final = 1001
CLOSE_BINARY: Final = 1003
CLOSE_PARSE_ERROR: Final = 1007
CLOSE_POLICY: Final = 1008


@dataclass(frozen=True, slots=True)
class Limits:
    max_frame: int = MAX_FRAME
    hello_timeout_s: float = 5.0
    queue_bytes: int = 8 * 1024 * 1024
    queue_messages: int = 10_000
    # 닫기 전에 큐에 남은 응답을 보낼 시간
    flush_timeout_s: float = 2.0
    close_timeout_s: float = 2.0


type PutResult = Literal["queued", "lagged", "overflow", "dropped"]
type MarkResult = Literal["queued", "duplicate", "overflow"]


@dataclass(frozen=True, slots=True)
class _Item:
    text: str
    size: int
    run_id: str | None = None
    marker: bool = False
    """`run.lagged` 알림 (그 실행의 이벤트를 비울 때 남긴다)."""


class Outbox:
    """연결 하나의 송신 큐. 이벤트 루프 안에서만 쓴다.

    상한(개수·UTF-8 바이트)은 모든 메시지에 걸린다. `run.lagged`도 예외가 아니다. 실행마다
    큐에 남은 `run.lagged`는 하나뿐이다(같은 실행이 다시 넘쳐도 더 넣지 않는다)."""

    def __init__(self, limits: Limits) -> None:
        self.limits = limits
        self._items: deque[_Item] = deque()
        self._bytes = 0
        self._ready = asyncio.Event()
        self._drained = asyncio.Event()
        self._drained.set()
        self.lagged: set[str] = set()
        """`run.lagged`를 보낸 뒤 다시 구독하지 않은 실행."""

    def __len__(self) -> int:
        return len(self._items)

    @property
    def size(self) -> int:
        return self._bytes

    def _fits(self, size: int) -> bool:
        return (
            len(self._items) < self.limits.queue_messages
            and self._bytes + size <= self.limits.queue_bytes
        )

    def _append(self, item: _Item) -> None:
        self._items.append(item)
        self._bytes += item.size
        self._ready.set()
        self._drained.clear()

    def put(self, text: str, run_id: str | None = None) -> PutResult:
        """응답·알림 하나. 실행 이벤트(`run_id`)가 넘치면 큐에 남은 그 실행의 이벤트를 버리고
        "lagged"를 돌려준다 — 호출자가 `put_marker`로 `run.lagged`를 넣는다."""
        if run_id is not None and run_id in self.lagged:
            return "dropped"
        size = utf8_size(text)
        if self._fits(size):
            self._append(_Item(text, size, run_id))
            return "queued"
        if run_id is None:
            return "overflow"
        kept = deque(i for i in self._items if i.marker or i.run_id != run_id)
        self._bytes = sum(i.size for i in kept)
        self._items = kept
        self.lagged.add(run_id)
        if not self._items:
            self._drained.set()
        return "lagged"

    def put_marker(self, text: str, run_id: str) -> MarkResult:
        """그 실행의 `run.lagged`. 이미 큐에 있으면 넣지 않고, 상한을 넘으면 "overflow"."""
        if any(i.marker and i.run_id == run_id for i in self._items):
            return "duplicate"
        size = utf8_size(text)
        if not self._fits(size):
            return "overflow"
        self._append(_Item(text, size, run_id, marker=True))
        return "queued"

    async def get(self) -> str:
        while not self._items:
            self._ready.clear()
            await self._ready.wait()
        item = self._items.popleft()
        self._bytes -= item.size
        if not self._items:
            self._drained.set()
        return item.text

    async def drained(self) -> None:
        await self._drained.wait()


class Connection:
    """WebSocket 연결 하나와 그 주체."""

    def __init__(self, ws: ServerConnection, number: int, limits: Limits) -> None:
        self.ws = ws
        self.number = number
        self.limits = limits
        self.outbox = Outbox(limits)
        self.principal: Principal | None = None
        """`session.hello`가 정한 주체 (인증 전에는 None)."""
        self.client_kind = "agent"
        """`session.hello`의 `client.kind` (인증 전에는 `agent` — 가장 좁게 본다)."""
        self.client_name = ""
        """`session.hello`의 `client.name` (에이전트 연결 목록 표시용)."""
        self.toolsets: frozenset[str] = frozenset()
        """켜진 MCP 툴셋 (M5 계획 D3). agent 연결은 hello 때 daemon 기본값(core), ui는 전부."""
        self.mismatch = False
        self.tasks: set[asyncio.Task[None]] = set()
        self.lag_listeners: list[Callable[[str], None]] = []
        """송신 큐가 넘쳐 실행 구독이 끊길 때 부른다 (인자: run_id). 실행 구독(T5)이 쓴다."""
        self._closing = False

    @property
    def authenticated(self) -> bool:
        return self.principal is not None

    def send(self, message: Mapping[str, Any]) -> None:
        """응답 하나를 큐에 넣는다. 봉투·값 규칙을 어긴 응답은 내부 오류로 바꾼다."""
        if self._closing:
            return
        text = _encode_response(message)
        if text is None:
            return
        if self.outbox.put(text) == "overflow":
            self.abort("송신 큐 초과")

    def queue_notification(self, text: str, run_id: str | None) -> bool:
        """알림 하나. 큐에 넣었으면 True. 닫는 중인 연결에는 넣지 않는다."""
        if self._closing:
            return False
        result = self.outbox.put(text, run_id)
        if result == "queued":
            return True
        if result == "lagged" and run_id is not None:
            log.warning("연결 %d: 송신 큐가 차서 실행 %s 구독을 끊는다", self.number, run_id)
            for listener in list(self.lag_listeners):
                listener(run_id)
            lagged = encode(
                {"jsonrpc": "2.0", "method": "run.lagged", "params": {"run_id": run_id}}
            )
            # 그 실행의 이벤트를 비워도 run.lagged를 넣을 자리가 없으면(일반 응답으로 참)
            # 클라이언트가 커서를 다시 맞출 수 없으므로 연결을 끊는다
            if self.outbox.put_marker(lagged, run_id) == "overflow":
                self.abort("송신 큐 초과 (run.lagged를 넣을 자리가 없음)")
        elif result == "overflow":
            self.abort("송신 큐 초과")
        return False

    def resume_run(self, run_id: str) -> None:
        """다시 구독: 그 실행의 알림을 다시 보낸다."""
        self.outbox.lagged.discard(run_id)

    async def writer(self) -> None:
        try:
            while True:
                text = await self.outbox.get()
                await self.ws.send(text)
        except ConnectionClosed:
            pass

    def abort(self, reason: str) -> None:
        """곧바로 끊는다. 상대가 읽지 않아 쓰기 버퍼가 찬 연결이라 닫기 프레임도 보낼 수 없다
        (`close()`는 버퍼가 빌 때까지 기다린다)."""
        if self._closing:
            return
        self._closing = True
        log.warning("연결 %d를 끊는다: %s", self.number, reason)
        self.ws.transport.abort()

    async def close(self, code: int, reason: str) -> None:
        """큐에 남은 메시지를 보낸 뒤(기한 안에서) 닫는다."""
        if self._closing:
            return
        self._closing = True
        try:
            await asyncio.wait_for(self.outbox.drained(), self.limits.flush_timeout_s)
        except TimeoutError:
            log.warning("연결 %d: 닫기 전에 큐를 다 보내지 못했다", self.number)
        await self.ws.close(code, reason)


def _encode_response(message: Mapping[str, Any]) -> str | None:
    problems = response_problems(message)
    if not problems:
        try:
            return encode(message)
        except (TypeError, ValueError) as exc:
            log.error("보낼 수 없는 응답 (값 규칙): %s", exc)
    else:
        log.error("계약에 맞지 않는 응답: %s", [d.message for d in problems])
    request_id = message.get("id")
    fallback = error_message(
        request_id if isinstance(request_id, int) else None,
        INTERNAL_ERROR,
        "daemon이 계약에 맞지 않는 응답을 만들었다",
    )
    return encode(fallback)


class Host(Protocol):
    """전송이 보는 daemon."""

    @property
    def context(self) -> DaemonContext: ...

    @property
    def authorizer(self) -> Authorizer: ...

    @property
    def shutting_down(self) -> bool: ...

    @property
    def agent_toolsets(self) -> frozenset[str]:
        """agent 연결이 hello 때 갖는 툴셋 (M5 계획 D3, 기본 core)."""
        ...

    def credentials(self) -> tuple[str, str, str] | None:
        """(토큰, start_id, 워크스페이스). 아직 세션을 정하지 않았으면 None."""
        ...

    def connections_changed(self) -> None: ...

    def connection_closed(self, number: int) -> None:
        """연결이 끝났다 (그 연결이 쥔 문서 참조 등을 푼다)."""
        ...

    def connection_authenticated(self, number: int) -> None:
        """연결이 인증됐다 (hello 응답을 큐에 넣은 뒤). 그 연결에 지금 상태 알림을 보낼 수 있다."""
        ...


@dataclass
class Transport:
    host: Host
    registry: Mapping[str, MethodSpec]
    limits: Limits = field(default_factory=Limits)
    port: int = 0
    server: Server | None = None
    connections: set[Connection] = field(default_factory=set[Connection])
    _numbers: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    def serve(self) -> Any:
        """`async with transport.serve() as server:` — 포트 0(OS가 고름)으로 연다."""
        return serve(
            self.handler,
            "127.0.0.1",
            0,
            process_request=self.process_request,
            compression=None,
            server_header=None,
            max_size=self.limits.max_frame,
            close_timeout=self.limits.close_timeout_s,
        )

    def bound(self, server: Server) -> int:
        self.server = server
        self.port = int(server.sockets[0].getsockname()[1])
        return self.port

    # ---------------------------------------------------------------- 접속 검사

    def process_request(self, connection: ServerConnection, request: Request) -> Response | None:
        headers: Headers = request.headers
        hosts = headers.get_all("Host")
        if hosts != [f"127.0.0.1:{self.port}"]:
            log.warning("Host 헤더가 틀린 연결을 거부한다: %r", hosts)
            return connection.respond(HTTPStatus.FORBIDDEN, "Host must be 127.0.0.1:<port>\n")
        if "Origin" in headers:
            log.warning("Origin 헤더가 있는 연결을 거부한다: %r", headers.get_all("Origin"))
            return connection.respond(HTTPStatus.FORBIDDEN, "Origin header is not accepted\n")
        return None

    # ---------------------------------------------------------------- 연결

    def count(self) -> int:
        return len(self.connections)

    def find(self, number: int) -> Connection | None:
        """연결 번호로 찾는다 (끝난 연결이면 None)."""
        return next((c for c in self.connections if c.number == number), None)

    def ui_connections(self) -> list[Connection]:
        """인증된 UI 연결 (`client.kind: ui`, 판이 맞는 것)."""
        return [
            c
            for c in self.connections
            if c.authenticated and not c.mismatch and c.client_kind == "ui"
        ]

    async def handler(self, ws: ServerConnection) -> None:
        conn = Connection(ws, next(self._numbers), self.limits)
        self.connections.add(conn)
        self.host.connections_changed()
        writer = asyncio.create_task(conn.writer())
        try:
            if await self._hello(conn):
                await self._serve(conn)
        finally:
            for task in list(conn.tasks):
                task.cancel()
            await asyncio.gather(*conn.tasks, return_exceptions=True)
            # 남은 응답은 닫는 쪽(`Connection.close`)이 이미 보냈다. 연결이 끊겼으면 보낼 곳이 없다
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
            self.connections.discard(conn)
            self.host.connection_closed(conn.number)
            self.host.connections_changed()

    async def _refuse(self, conn: Connection, message: Mapping[str, Any], code: int) -> bool:
        conn.send(message)
        await conn.close(code, "session.hello failed")
        return False

    async def _hello(self, conn: Connection) -> bool:
        try:
            frame = await asyncio.wait_for(conn.ws.recv(), self.limits.hello_timeout_s)
        except TimeoutError:
            failed = RequestFailed(
                "unauthenticated",
                f"{self.limits.hello_timeout_s:g}초 안에 session.hello가 오지 않았다",
                protocol=PROTOCOL,
            )
            return await self._refuse(conn, error_message(None, **_fields(failed)), CLOSE_POLICY)
        except ConnectionClosed:
            return False
        if isinstance(frame, bytes):
            await conn.close(CLOSE_BINARY, "binary frames are not accepted")
            return False
        try:
            message = decode(frame)
        except ValueError as exc:
            return await self._refuse(
                conn,
                error_message(None, PARSE_ERROR, f"JSON으로 읽을 수 없다: {exc}"),
                CLOSE_PARSE_ERROR,
            )
        request_id = protocol_request_id(message)
        if problems := _envelope_problems(message, request_id):
            return await self._refuse(
                conn,
                error_message(
                    request_id, INVALID_REQUEST, "요청 형식이 틀렸다", diagnostics_data(problems)
                ),
                CLOSE_POLICY,
            )
        assert request_id is not None  # _envelope_problems가 확인했다
        credentials = self.host.credentials()
        if self.host.shutting_down or credentials is None:
            failed = _shutting_down()
            return await self._refuse(
                conn, error_message(request_id, **_fields(failed)), CLOSE_GOING_AWAY
            )
        if message["method"] != "session.hello":
            failed = RequestFailed(
                "unauthenticated", "첫 메시지는 session.hello여야 한다", protocol=PROTOCOL
            )
            return await self._refuse(
                conn, error_message(request_id, **_fields(failed)), CLOSE_POLICY
            )
        token, start_id, workspace = credentials
        try:
            outcome = hello(
                message.get("params", {}),
                token=token,
                start_id=start_id,
                workspace=workspace,
                connection=conn.number,
            )
        except RequestFailed as failed:
            log.warning("연결 %d: 인증 실패 (%s)", conn.number, failed.code)
            return await self._refuse(
                conn, error_message(request_id, **_fields(failed)), CLOSE_POLICY
            )
        except InvalidHello as exc:
            return await self._refuse(
                conn,
                error_message(request_id, INVALID_PARAMS, str(exc), diagnostics_data(exc.problems)),
                CLOSE_POLICY,
            )
        conn.principal = outcome.principal
        conn.client_kind = outcome.client_kind
        conn.client_name = outcome.client_name
        conn.toolsets = (
            self.host.agent_toolsets if outcome.principal.kind == "agent" else frozenset(TOOLSETS)
        )
        if outcome.mismatch is not None:
            conn.mismatch = True
            log.warning("연결 %d: 프로토콜 판이 다르다. daemon.shutdown만 받는다", conn.number)
            conn.send(error_message(request_id, **_fields(outcome.mismatch)))
            return True
        log.info(
            "연결 %d: 인증됨 (%s %r, attended=%s)",
            conn.number,
            outcome.principal.kind,
            outcome.principal.id,
            outcome.principal.attended,
        )
        self._respond(conn, request_id, "session.hello", outcome.result)
        self.host.connection_authenticated(conn.number)
        return True

    async def _serve(self, conn: Connection) -> None:
        try:
            async for frame in conn.ws:
                if isinstance(frame, bytes):
                    await conn.close(CLOSE_BINARY, "binary frames are not accepted")
                    return
                try:
                    message = decode(frame)
                except ValueError as exc:
                    conn.send(error_message(None, PARSE_ERROR, f"JSON으로 읽을 수 없다: {exc}"))
                    await conn.close(CLOSE_PARSE_ERROR, "parse error")
                    return
                task = asyncio.create_task(self._request(conn, message))
                conn.tasks.add(task)
                task.add_done_callback(conn.tasks.discard)
        except ConnectionClosed:
            pass

    async def _request(self, conn: Connection, message: Any) -> None:
        request_id = protocol_request_id(message)

        def fail(code: int, text: str, data: Mapping[str, Any] | None = None) -> None:
            conn.send(error_message(request_id, code, text, data))

        if problems := _envelope_problems(message, request_id):
            fail(INVALID_REQUEST, "요청 형식이 틀렸다", diagnostics_data(problems))
            return
        assert request_id is not None  # _envelope_problems가 확인했다
        method: str = message["method"]
        params: dict[str, Any] = message.get("params", {})
        if conn.mismatch and method != "daemon.shutdown":
            failed = RequestFailed(
                "protocol_mismatch",
                "프로토콜 판이 달라 daemon.shutdown만 받는다",
                protocol=PROTOCOL,
            )
            conn.send(error_message(request_id, **_fields(failed)))
            return
        if method not in methods():
            fail(METHOD_NOT_FOUND, f"계약에 없는 메서드 {method!r}")
            return
        if method == "session.hello":
            fail(INVALID_REQUEST, "이미 인증된 연결이다")
            return
        if problems := params_problems(method, params):
            fail(INVALID_PARAMS, f"{method} params 형식이 틀렸다", diagnostics_data(problems))
            return
        spec = self.registry.get(method)
        if spec is None:
            fail(METHOD_NOT_FOUND, f"이 daemon에는 아직 {method}가 없다")
            return
        try:
            if self.host.shutting_down:
                raise _shutting_down()
            assert conn.principal is not None
            call = Call(
                self.host.context,
                conn.principal,
                conn.number,
                method,
                params,
                client_kind=conn.client_kind,
            )
            # 판정 전 거부 (AGENT_DENIED·툴셋 꺼짐): 스스로 판정하는 메서드도 여기서 막는다
            self.host.authorizer.gate(conn.principal, method, conn.toolsets)
            arg = spec.arg(call)
            if not spec.self_authorized:
                await asyncio.to_thread(self.host.authorizer.require, conn.principal, method, arg)
            result = await spec.handler(call)
        except RequestFailed as failed:
            conn.send(error_message(request_id, **_fields(failed)))
            return
        except InvalidParams as exc:
            fail(INVALID_PARAMS, exc.message, exc.data or None)
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("연결 %d: %s 처리 중 오류", conn.number, method)
            fail(INTERNAL_ERROR, f"{method} 처리 중 daemon 내부 오류")
            return
        self._respond(conn, request_id, method, result)

    def _respond(self, conn: Connection, request_id: int, method: str, result: Any) -> None:
        if problems := result_problems(method, result):
            log.error("%s 결과가 계약에 맞지 않는다: %s", method, [d.message for d in problems])
            conn.send(
                error_message(request_id, INTERNAL_ERROR, f"{method} 결과가 계약에 맞지 않는다")
            )
            return
        conn.send(success_message(request_id, result))

    # ---------------------------------------------------------------- 알림

    def notify(
        self, conn: Connection, method: str, params: Mapping[str, Any], *, run_id: str | None = None
    ) -> bool:
        """알림 하나를 그 연결의 큐에 넣는다. 이름·params(실행 이벤트 본문 포함)를 계약으로
        검사하고, 어긴 알림은 보내지 않는다. 큐에 넣었으면 True."""
        if not conn.authenticated or conn.mismatch:
            return False
        if problems := notification_problems(method, dict(params)):
            log.error("계약에 맞지 않는 알림 %s: %s", method, [d.message for d in problems])
            return False
        try:
            text = encode({"jsonrpc": "2.0", "method": method, "params": dict(params)})
        except (TypeError, ValueError) as exc:
            log.error("보낼 수 없는 알림 %s (값 규칙): %s", method, exc)
            return False
        return conn.queue_notification(text, run_id)

    def broadcast(self, method: str, params: Mapping[str, Any]) -> None:
        for conn in list(self.connections):
            self.notify(conn, method, params)

    async def close_all(self, reason: str) -> None:
        await asyncio.gather(
            *(conn.close(CLOSE_GOING_AWAY, reason) for conn in list(self.connections)),
            return_exceptions=True,
        )


def _envelope_problems(message: Any, request_id: int | None) -> list[Diagnostic]:
    """`Request` 봉투 검사 + 요청 ID를 정수로 읽을 수 있는가. 둘 다 통과해야 처리한다."""
    problems = request_problems(message)
    if not problems and request_id is None:
        problems = [Diagnostic("error", "invalid_id", "id는 1 이상 2^53-1 이하의 정수여야 한다")]
    return problems


def _shutting_down() -> RequestFailed:
    text = "daemon이 끝나는 중이다"
    return RequestFailed("shutting_down", text, message=text)


def _fields(failed: RequestFailed) -> dict[str, Any]:
    error = failed.error()
    return {"code": error["code"], "message": error["message"], "data": error["data"]}
