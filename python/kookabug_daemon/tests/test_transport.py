"""WebSocket 전송: 바인드·Host·Origin·hello·봉투·값 규칙·송신 큐 (M2 계획 2.4)."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from websockets.sync.client import connect

from kb_testing.daemon import ThreadDaemon, make_workspace
from kb_testing.proc import wait_until
from kookabug_core.permissions import Principal
from kookabug_daemon.client import ConnectionLost, DaemonClient, DaemonError
from kookabug_daemon.methods import registry
from kookabug_daemon.protocol import encode, utf8_size
from kookabug_daemon.transport import (
    CLOSE_BINARY,
    CLOSE_PARSE_ERROR,
    CLOSE_POLICY,
    Connection,
    Limits,
    Outbox,
)

pytestmark = pytest.mark.process

STEP_END: dict[str, Any] = {
    "event": "step.end",
    "run": "abcd1234",
    "seq": 7,
    "t": "2026-10-29T06:02:11.104Z",
    "attempt": 1,
    "duration_ms": 12,
    "exit": "done",
    "outputs": {"text": "x"},
    "status": "success",
    "step": "s2",
}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return make_workspace(tmp_path / "ws")


@pytest.fixture
def daemon(root: Path, tmp_path: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(root, environ={"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "u")}) as d:
        yield d


def hello_params(d: ThreadDaemon, **override: Any) -> dict[str, Any]:
    return {
        "token": d.session.token,
        "protocol": 1,
        "client": {"kind": "ui", "name": "test", "version": "0"},
        **override,
    }


def request(method: str, params: Any = None, request_id: Any = 1) -> str:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return json.dumps(message)


def handshake_status(port: int, headers: dict[str, str]) -> int:
    """WebSocket 업그레이드 요청을 직접 보내 HTTP 상태 코드를 읽는다."""
    lines = [
        "GET / HTTP/1.1",
        *(f"{name}: {value}" for name, value in headers.items()),
        "Upgrade: websocket",
        "Connection: Upgrade",
        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==",
        "Sec-WebSocket-Version: 13",
        "",
        "",
    ]
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall("\r\n".join(lines).encode("ascii"))
        data = sock.recv(4096)
    return int(data.split(b" ", 2)[1])


def test_bind_loopback_only(daemon: ThreadDaemon) -> None:
    transport = daemon.daemon.transport
    assert transport.port == daemon.port and transport.server is not None
    server = transport.server
    addresses = daemon.call_in_loop(lambda: [s.getsockname()[0] for s in server.sockets])
    assert addresses == ["127.0.0.1"]
    # 루프백이 아닌 이 PC의 주소로는 붙지 못한다
    others = {
        info[4][0]
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        if not str(info[4][0]).startswith("127.")
    }
    for address in others:
        with pytest.raises(OSError):
            socket.create_connection((str(address), daemon.port), timeout=2).close()


@pytest.mark.parametrize(
    "host",
    ["localhost:{port}", "127.0.0.1:1", "evil.example:{port}", "127.0.0.1", "[::1]:{port}"],
)
def test_host_header_mismatch_rejected(daemon: ThreadDaemon, host: str) -> None:
    good = {"Host": f"127.0.0.1:{daemon.port}"}
    assert handshake_status(daemon.port, good) == 101
    assert handshake_status(daemon.port, {"Host": host.format(port=daemon.port)}) == 403


@pytest.mark.parametrize("origin", ["http://evil.example", "null", "file://", "app://kookabug"])
def test_origin_header_rejected(daemon: ThreadDaemon, origin: str) -> None:
    headers = {"Host": f"127.0.0.1:{daemon.port}", "Origin": origin}
    assert handshake_status(daemon.port, headers) == 403


def test_hello_required_within_5s(root: Path) -> None:
    assert Limits().hello_timeout_s == 5.0
    with ThreadDaemon(root, limits=Limits(hello_timeout_s=0.3)) as d:
        # 아무것도 보내지 않으면 기한 뒤 unauthenticated를 받고 닫힌다
        client = DaemonClient.open(d.port)
        assert client.wait_closed(10) == CLOSE_POLICY
        error = client.next_unmatched(5)["error"]
        assert error["code"] == -32100 and error["data"]["code"] == "unauthenticated"
        # 첫 메시지가 hello가 아니면 같다 (처리하지 않는다)
        client = DaemonClient.open(d.port)
        with pytest.raises(DaemonError) as caught:
            client.call("daemon.shutdown", {}, timeout=10)
        assert caught.value.kind == "unauthenticated"
        assert client.wait_closed(10) == CLOSE_POLICY
        assert d.is_running()


def test_wrong_token_unauthenticated_then_closed(daemon: ThreadDaemon) -> None:
    for token in ("0" * 64, "x", None):
        client = DaemonClient.open(daemon.port, check=False)
        params = hello_params(daemon, token=token)
        with pytest.raises(DaemonError) as caught:
            client.call("session.hello", params, timeout=10)
        assert caught.value.kind == "unauthenticated"
        assert caught.value.data["protocol"] == 1
        assert client.wait_closed(10) == CLOSE_POLICY
    with daemon.client() as ok:
        assert ok.hello_result is not None


def test_protocol_mismatch_error(daemon: ThreadDaemon) -> None:
    client = DaemonClient.open(daemon.port, check=False)
    with pytest.raises(DaemonError) as caught:
        client.call("session.hello", hello_params(daemon, protocol=2), timeout=10)
    assert caught.value.kind == "protocol_mismatch"
    assert caught.value.data["protocol"] == 1
    # 연결은 남고, daemon.shutdown만 받는다 (앱의 "daemon 다시 시작")
    assert not client.closed.is_set()
    with pytest.raises(DaemonError) as other:
        client.call("run.list", {"limit": 1}, timeout=10)
    assert other.value.kind == "protocol_mismatch"
    assert client.call("daemon.shutdown", {}, timeout=10) == {}
    assert daemon.finished() == "daemon.shutdown"


def test_protocol_mismatch_agent_cannot_shutdown(daemon: ThreadDaemon) -> None:
    client = DaemonClient.open(daemon.port, check=False)
    agent = {"kind": "agent", "name": "a", "version": "0", "id": "agent-1"}
    with pytest.raises(DaemonError):
        client.call("session.hello", hello_params(daemon, protocol=9, client=agent), timeout=10)
    with pytest.raises(DaemonError) as caught:
        client.call("daemon.shutdown", {}, timeout=10)
    assert caught.value.kind == "permission_denied"
    assert daemon.is_running()


@pytest.mark.parametrize("before_hello", [True, False])
def test_binary_frame_closes(daemon: ThreadDaemon, before_hello: bool) -> None:
    client = DaemonClient.open(daemon.port) if before_hello else daemon.client()
    client.send_bytes(request("daemon.shutdown", {}).encode("utf-8"))
    assert client.wait_closed(10) == CLOSE_BINARY
    assert daemon.is_running()


def test_oversize_frame_closes(daemon: ThreadDaemon) -> None:
    assert Limits().max_frame == 16 * 1024 * 1024
    client = daemon.client()
    big = request("daemon.shutdown", {"force": False, "pad": "x" * (16 * 1024 * 1024)})
    with pytest.raises(ConnectionLost):
        client.send_text(big)
        client.call("daemon.shutdown", {}, timeout=10)
    assert client.wait_closed(10) == 1009
    assert daemon.is_running()


@pytest.mark.parametrize(
    "text",
    [
        '{"jsonrpc": "2.0", "id": 1, "method": "daemon.shutdown", "params": {"x": NaN}}',
        '{"jsonrpc": "2.0", "id": 1, "method": "daemon.shutdown", "params": {"x": Infinity}}',
        '{"jsonrpc": "2.0", "id": 1, "method": "daemon.shutdown", "params": {"x": 1e999}}',
        '{"jsonrpc": "2.0", "id": 1, "method": "daemon.shutdown", '
        '"params": {"x": 9007199254740992}}',
        '{"jsonrpc": "2.0", "id": 1, "method": "daemon.shutdown", "params": {"x": '
        + "[" * 200
        + "]" * 200
        + "}}",
        '{"jsonrpc": "2.0", "id": 1,',
    ],
    ids=["nan", "infinity", "overflow", "unsafe_int", "deep", "truncated"],
)
@pytest.mark.parametrize("before_hello", [True, False])
def test_nan_and_deep_json_parse_error_then_closed(
    daemon: ThreadDaemon, text: str, before_hello: bool
) -> None:
    client = DaemonClient.open(daemon.port) if before_hello else daemon.client()
    client.send_text(text)
    assert client.wait_closed(10) == CLOSE_PARSE_ERROR
    response = client.next_unmatched(5)
    assert response["id"] is None and response["error"]["code"] == -32700
    assert daemon.is_running()  # 처리하지 않았다


@pytest.mark.parametrize(
    "message",
    [
        {"jsonrpc": "2.0", "id": 5, "method": "daemon.shutdown", "params": {}, "extra": 1},
        {"id": 5, "method": "daemon.shutdown", "params": {}},
        {"jsonrpc": "1.0", "id": 5, "method": "daemon.shutdown"},
        {"jsonrpc": "2.0", "id": 0, "method": "daemon.shutdown"},
        {"jsonrpc": "2.0", "id": "5", "method": "daemon.shutdown"},
        {"jsonrpc": "2.0", "method": "daemon.shutdown"},
        {"jsonrpc": "2.0", "id": 5, "method": "daemon.shutdown", "params": []},
        {"jsonrpc": "2.0", "id": 5, "method": "Daemon.Shutdown"},
        [{"jsonrpc": "2.0", "id": 5, "method": "daemon.shutdown"}],
    ],
    ids=[
        "extra_field",
        "no_jsonrpc",
        "wrong_version",
        "zero_id",
        "string_id",
        "no_id",
        "array_params",
        "bad_method",
        "batch",
    ],
)
def test_invalid_request_answered_not_processed(daemon: ThreadDaemon, message: Any) -> None:
    with daemon.client() as client:
        client.send_text(json.dumps(message))
        # 짝지을 요청이 없는 오류 응답 (id를 읽을 수 있으면 그 id, 아니면 null)
        response = client.next_unmatched(10)
        expected = message.get("id") if isinstance(message, dict) else None
        expected = expected if isinstance(expected, int) and expected >= 1 else None
        assert response["id"] == expected
        assert response["error"]["code"] == -32600
        assert response["error"]["data"]["diagnostics"]
        # 연결은 남고 daemon은 끝나지 않았다 (daemon.shutdown을 처리하지 않았다)
        with pytest.raises(DaemonError) as missing:
            client.call("x.noop", {}, timeout=10)
        assert missing.value.code == -32601
    assert daemon.is_running()


def test_invalid_params_and_unknown_method(daemon: ThreadDaemon) -> None:
    with daemon.client() as client:
        client.check = False
        with pytest.raises(DaemonError) as caught:
            client.call("daemon.shutdown", {"force": "yes"}, timeout=10)
        assert caught.value.code == -32602
        assert caught.value.data["diagnostics"]
        with pytest.raises(DaemonError) as hello_again:
            client.call("session.hello", hello_params(daemon), timeout=10)
        assert hello_again.value.code == -32600
    assert daemon.is_running()


def test_contract_method_missing_from_registry_not_found(root: Path) -> None:
    # 계약에 있지만 이 daemon의 메서드 표에 없는 메서드
    methods = {k: v for k, v in registry().items() if k != "run.list"}
    with ThreadDaemon(root, methods=methods) as d, d.client() as client:
        with pytest.raises(DaemonError) as later:
            client.call("run.list", {"limit": 1}, timeout=10)
        assert later.value.code == -32601
        assert d.is_running()


def test_slow_reader_queue_limit_drops_connection(
    root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("WARNING", logger="kookabug_daemon")
    limits = Limits(queue_messages=20, queue_bytes=256 * 1024)
    with ThreadDaemon(root, limits=limits) as d:
        # 받은 프레임을 1개만 버퍼에 두고 그 뒤로는 소켓을 읽지 않는 클라이언트
        ws = connect(
            f"ws://127.0.0.1:{d.port}",
            proxy=None,
            compression=None,
            legacy=True,
            max_queue=1,
            max_size=None,
        )
        ws.send(request("session.hello", hello_params(d)))
        wait_until(lambda: d.daemon.transport.count() == 1)
        long_method = "x." + "a" * 8000  # 오류 응답이 이 이름을 담아 크다
        try:
            for i in range(4000):
                ws.send(request(long_method, {}, i + 2))
                if d.daemon.transport.count() == 0:
                    break
        except Exception:
            pass  # daemon이 끊었다
        wait_until(lambda: d.daemon.transport.count() == 0, timeout=30)
        assert any("송신 큐 초과" in r.getMessage() for r in caplog.records)
        ws.close_socket()
        # daemon은 계속 돌고 다른 연결은 정상이다
        with d.client() as other, pytest.raises(DaemonError):
            other.call("x.noop", {}, timeout=10)
        assert d.is_running()


def test_outbox_limits_lagged_and_overflow() -> None:
    assert (Limits().queue_bytes, Limits().queue_messages) == (8 * 1024 * 1024, 10_000)

    class FakeTransport:
        aborted = 0

        def abort(self) -> None:
            FakeTransport.aborted += 1

    class FakeWs:
        transport = FakeTransport()

        async def send(self, text: str) -> None:
            return None

    async def scenario() -> None:
        conn = Connection(FakeWs(), 1, Limits(queue_messages=4, queue_bytes=10**6))  # pyright: ignore[reportArgumentType]
        conn.principal = Principal("user", "ui:1", attended=True)
        lagged: list[str] = []
        conn.lag_listeners.append(lagged.append)
        assert conn.queue_notification("e1", "run00001")
        assert conn.queue_notification("e2", "run00001")
        assert conn.queue_notification("o1", "run00002")
        conn.send({"jsonrpc": "2.0", "id": 1, "result": {}})
        # 큐가 찼다: 그 실행의 남은 이벤트를 버리고 run.lagged를 넣는다. 연결은 끊지 않는다
        assert not conn.queue_notification("e3", "run00001")
        assert lagged == ["run00001"]
        items = [await conn.outbox.get() for _ in range(len(conn.outbox))]
        assert items[0] == "o1" and json.loads(items[1])["id"] == 1
        assert json.loads(items[2]) == {
            "jsonrpc": "2.0",
            "method": "run.lagged",
            "params": {"run_id": "run00001"},
        }
        # 다시 구독할 때까지 그 실행의 알림은 보내지 않는다
        assert not conn.queue_notification("e4", "run00001")
        conn.resume_run("run00001")
        assert conn.queue_notification("e5", "run00001")
        # 일반 응답이 넘치면 연결을 끊는다 (닫기 프레임 없이 바로)
        for i in range(3):
            conn.send({"jsonrpc": "2.0", "id": i + 2, "result": {}})
        assert FakeTransport.aborted == 0
        conn.send({"jsonrpc": "2.0", "id": 9, "result": {}})
        assert FakeTransport.aborted == 1

    asyncio.run(scenario())

    async def bytes_limit() -> None:
        box = Outbox(Limits(queue_messages=100, queue_bytes=12))
        assert box.put("12345") == "queued"
        assert box.put("12345678") == "overflow"
        assert box.put("한글", "run00003") == "queued"  # UTF-8로 6바이트
        assert box.size == 11
        assert box.put("ab", "run00003") == "lagged"
        assert (box.size, len(box)) == (5, 1)

    asyncio.run(bytes_limit())


def test_notification_contract_checked_including_run_event_body(daemon: ThreadDaemon) -> None:
    with daemon.client() as client:
        conn = next(iter(daemon.daemon.transport.connections))
        notify = daemon.daemon.transport.notify
        good = {"run_id": "abcd1234", "seq": 7, "event": STEP_END}
        assert daemon.call_in_loop(notify, conn, "run.event", good) is True
        received = client.notifications.get(timeout=10)
        assert received == {"jsonrpc": "2.0", "method": "run.event", "params": good}
        # 봉투는 맞지만 이벤트 본문이 events 스키마에 맞지 않으면 보내지 않는다
        for bad_event in ({**STEP_END, "outputs": "x"}, {**STEP_END, "event": "step.nope"}, {}):
            bad = {**good, "event": bad_event}
            assert daemon.call_in_loop(notify, conn, "run.event", bad) is False
        assert daemon.call_in_loop(notify, conn, "no.such", {}) is False
        assert daemon.call_in_loop(notify, conn, "run.lagged", {"run_id": "BAD"}) is False
        nan = {
            "run_id": "abcd1234",
            "seq": 8,
            "event": {**STEP_END, "outputs": {"x": float("nan")}},
        }
        assert daemon.call_in_loop(notify, conn, "run.event", nan) is False
        assert client.notifications.empty()


def test_big_float_sent_as_float(daemon: ThreadDaemon) -> None:
    # Python float는 repr 표기라 지수·소수점으로 나가 다시 float로 읽힌다 (2.4)
    text = encode({"jsonrpc": "2.0", "id": 1, "result": {"a": 1e20, "b": 9007199254740992.0}})
    assert '"a":1e+20' in text and '"b":9007199254740992.0' in text


# ---------------------------------------------------------------- 2라운드 회귀 (검수 T3_1)


def test_encode_escapes_lone_surrogates_only() -> None:
    # 짝 없는 대리 문자는 이스케이프로, 한글은 그대로. UTF-8 바이트로 크기를 잰다
    message = {"jsonrpc": "2.0", "id": 1, "result": {"s": "가\ud800나\udfff", "k\udc00": 1}}
    text = encode(message)
    assert "\\ud800" in text and "\\udfff" in text and "\\udc00" in text and "가" in text
    assert json.loads(text) == message
    assert utf8_size(text) == len(text.encode("utf-8"))


def test_surrogate_event_roundtrip(daemon: ThreadDaemon) -> None:
    with daemon.client() as client:
        conn = next(iter(daemon.daemon.transport.connections))
        params = {
            "run_id": "abcd1234",
            "seq": 7,
            "event": {**STEP_END, "outputs": {"text": "\ud800", "한글": "값\udfff"}},
        }
        assert daemon.call_in_loop(daemon.daemon.transport.notify, conn, "run.event", params)
        assert client.notifications.get(timeout=10)["params"] == params


def test_surrogate_agent_id_hello_roundtrip(daemon: ThreadDaemon) -> None:
    # Python 클라이언트 발신(hello params) → daemon 수신 → 응답(principal) → 클라이언트 수신
    client = {"kind": "agent", "name": "a\ud800", "version": "0", "id": "\ud800"}
    with daemon.client(client) as conn:
        assert conn.hello_result is not None
        assert conn.hello_result["principal"]["id"] == "\ud800"
    # 원문 소켓으로도 같다 (클라이언트 코덱과 무관)
    with socket_client(daemon) as ws:
        ws.send(request("session.hello", hello_params(daemon, client=client)))
        assert json.loads(ws.recv(timeout=10))["result"]["principal"]["id"] == "\ud800"


def socket_client(d: ThreadDaemon) -> Any:
    return connect(f"ws://127.0.0.1:{d.port}", proxy=None, compression=None, legacy=True)


@pytest.mark.parametrize("hello_id", [1, 1.0])
def test_float_request_id_normalized(daemon: ThreadDaemon, hello_id: Any) -> None:
    # 스키마의 integer는 2.0도 받는다: 정수로 읽어 같은 번호로 답한다 (무응답 금지)
    with socket_client(daemon) as ws:
        ws.send(request("session.hello", hello_params(daemon), hello_id))
        hello = json.loads(ws.recv(timeout=10))
        assert hello["id"] == 1 and "result" in hello
        ws.send(request("x.noop", {}, 2.0))
        response = json.loads(ws.recv(timeout=10))
        assert response["id"] == 2 and response["error"]["code"] == -32601
        # 정수값이 아닌 실수 ID는 봉투 오류이고 id는 null이다
        ws.send(request("x.noop", {}, 2.5))
        response = json.loads(ws.recv(timeout=10))
        assert response["id"] is None and response["error"]["code"] == -32600
    assert daemon.is_running()


def test_lag_markers_respect_queue_limits() -> None:
    class FakeTransport:
        aborted = 0

        def abort(self) -> None:
            FakeTransport.aborted += 1

    class FakeWs:
        transport = FakeTransport()

    async def full_of_responses() -> None:
        # 일반 응답으로 찬 큐: 실행 이벤트를 비워도 run.lagged 자리가 없다
        # → 상한을 넘기지 않고 끊는다
        conn = Connection(FakeWs(), 1, Limits(queue_messages=2, queue_bytes=1000))  # pyright: ignore[reportArgumentType]
        conn.principal = Principal("user", "ui:1", attended=True)
        conn.send({"jsonrpc": "2.0", "id": 1, "result": {}})
        conn.send({"jsonrpc": "2.0", "id": 2, "result": {}})
        for _ in range(20):
            conn.resume_run("abcd1234")
            conn.queue_notification("event", "abcd1234")
        assert len(conn.outbox) <= 2 and conn.outbox.size <= 1000
        assert FakeTransport.aborted == 1

    async def repeated_lag() -> None:
        # 같은 실행이 여러 번 넘쳐도 run.lagged는 큐에 하나뿐이고 상한 안이다
        limits = Limits(queue_messages=3, queue_bytes=1000)
        conn = Connection(FakeWs(), 2, limits)  # pyright: ignore[reportArgumentType]
        conn.principal = Principal("user", "ui:1", attended=True)
        lagged: list[str] = []
        conn.lag_listeners.append(lagged.append)
        for _ in range(20):
            conn.resume_run("abcd1234")
            for _ in range(5):
                conn.queue_notification("event", "abcd1234")
            assert len(conn.outbox) <= 3 and conn.outbox.size <= 1000
        items = [await conn.outbox.get() for _ in range(len(conn.outbox))]
        markers = [t for t in items if "run.lagged" in t]
        assert len(markers) == 1 and len(lagged) == 20
        assert FakeTransport.aborted == 1  # 앞 시나리오의 한 번뿐

    asyncio.run(full_of_responses())
    asyncio.run(repeated_lag())
