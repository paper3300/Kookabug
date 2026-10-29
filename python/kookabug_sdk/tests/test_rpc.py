"""JSON-RPC 피어 (구현 계획 M0b 2.2): 요청 짝짓기·양방향·송신 큐·연결 잃기·오류 코드."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from kookabug_sdk import rpc
from kookabug_sdk.pipe import PipeConnection, PipeListener, connect, new_key, new_pipe_name
from kookabug_sdk.rpc import Incoming, PeerLost, RpcError, RpcPeer

pytestmark = pytest.mark.process

type Handler = Callable[[RpcPeer, Incoming], None]


@pytest.fixture
def peers(pipe_pair: Any) -> Iterator[Callable[..., tuple[RpcPeer, RpcPeer]]]:
    made: list[RpcPeer] = []

    def factory(**kwargs: Any) -> tuple[RpcPeer, RpcPeer]:
        server, client = pipe_pair()
        a = RpcPeer(server, name="a", **kwargs).start()
        b = RpcPeer(client, name="b", **kwargs).start()
        made.extend((a, b))
        return a, b

    yield factory
    for peer in made:
        peer.close()


@pytest.fixture
def stalled(pipe_pair: Any) -> Iterator[Callable[..., tuple[RpcPeer, PipeConnection]]]:
    """(피어, 읽지 않는 상대 끝). 상대 버퍼는 4 KiB."""
    made: list[RpcPeer | PipeConnection] = []

    def factory(**kwargs: Any) -> tuple[RpcPeer, PipeConnection]:
        name, key = new_pipe_name("stall"), new_key()
        listener = PipeListener(name, buffer_size=4096)
        accepted: list[PipeConnection] = []
        thread = threading.Thread(target=lambda: accepted.append(listener.accept(key, timeout=10)))
        thread.start()
        raw = connect(name, key, timeout=10)
        thread.join(10)
        peer = RpcPeer(accepted[0], name="stalled", **kwargs).start()
        made.extend((peer, raw))
        return peer, raw

    yield factory
    for item in made:
        item.close()


def serve(peer: RpcPeer, handler: Handler) -> threading.Thread:
    """받은 요청·알림을 `handler`로 처리하는 스레드 (연결을 잃으면 끝난다)."""

    def loop() -> None:
        while True:
            item = peer.incoming.get()
            if isinstance(item, PeerLost):
                return
            handler(peer, item)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread


def wait_for(condition: Callable[[], object], timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "조건이 기한 안에 맞지 않았다"
        time.sleep(0.005)


def raw_message(conn: PipeConnection) -> dict[str, Any]:
    return json.loads(conn.recv_frame(5))


def send_raw(conn: PipeConnection, message: object) -> None:
    conn.send_frame(json.dumps(message).encode())


# ── 요청·응답 ─────────────────────────────────────────────────────────


def test_request_response_out_of_order(peers: Any) -> None:
    a, b = peers()
    held: list[Incoming] = []

    def reverse(peer: RpcPeer, msg: Incoming) -> None:
        held.append(msg)
        if len(held) == 3:  # 셋을 다 받은 뒤 거꾸로 응답한다
            for item in reversed(held):
                peer.respond(item, {"echo": item.params["n"]})

    serve(b, reverse)
    calls = [a.request("echo", {"n": n}) for n in (1, 2, 3)]
    assert [c.id for c in calls] == [1, 2, 3]
    assert [c.result(5) for c in calls] == [{"echo": 1}, {"echo": 2}, {"echo": 3}]
    assert [m.id for m in held] == [1, 2, 3]


def test_both_sides_send_requests(peers: Any) -> None:
    # node.invoke 처리 중에 상대에게 ctx 요청을 보내고 그 응답을 받은 뒤 원래 요청에 응답한다
    a, b = peers()
    logged: list[tuple[int | None, str]] = []
    invoked: list[int | None] = []

    def runner_side(peer: RpcPeer, msg: Incoming) -> None:
        assert msg.method == "ctx.log"
        logged.append((msg.id, msg.params["message"]))
        peer.respond(msg, {"ok": True})

    def worker_side(peer: RpcPeer, msg: Incoming) -> None:
        assert msg.method == "node.invoke"
        invoked.append(msg.id)
        replies = [peer.call("ctx.log", {"message": f"step {i}"}, timeout=5) for i in range(3)]
        peer.respond(msg, {"exit": "done", "replies": replies})

    serve(a, runner_side)
    serve(b, worker_side)
    result = a.call("node.invoke", {"type": "x"}, timeout=10)
    assert result == {"exit": "done", "replies": [{"ok": True}] * 3}
    # 양쪽 id는 따로 센다
    assert logged == [(1, "step 0"), (2, "step 1"), (3, "step 2")]
    assert invoked == [1]


def test_notification_no_response(pipe_pair: Any) -> None:
    server, raw = pipe_pair()
    peer = RpcPeer(server).start()
    try:
        send_raw(raw, {"jsonrpc": "2.0", "method": "run.cancel", "params": {"reason": "x"}})
        send_raw(raw, {"jsonrpc": "2.0", "id": 7, "method": "ping"})
        first = peer.incoming.get(timeout=5)
        assert isinstance(first, Incoming)
        assert first.is_notification and first.method == "run.cancel"
        with pytest.raises(ValueError, match="알림"):
            peer.respond(first, None)
        second = peer.incoming.get(timeout=5)
        assert isinstance(second, Incoming)
        peer.respond(second, "pong")
        # 알림에는 아무것도 오지 않았으므로 처음 오는 프레임이 ping의 응답이다
        assert raw_message(raw) == {"id": 7, "jsonrpc": "2.0", "result": "pong"}

        peer.notify("run.pause")
        assert raw_message(raw) == {"jsonrpc": "2.0", "method": "run.pause"}
    finally:
        peer.close()


def test_call_timeout_drops_late_response(peers: Any) -> None:
    a, b = peers()
    held: list[Incoming] = []

    def handler(peer: RpcPeer, msg: Incoming) -> None:
        if msg.method == "slow":
            held.append(msg)
        else:
            peer.respond(msg, "fresh")

    serve(b, handler)
    with pytest.raises(TimeoutError):
        a.call("slow", timeout=0.2)
    wait_for(lambda: held)
    b.respond(held[0], "late")  # 버려진다
    assert a.call("fast", timeout=5) == "fresh"


# ── 송신 큐 ───────────────────────────────────────────────────────────


def test_send_never_blocks_caller_when_peer_stalled(stalled: Any) -> None:
    peer, _raw = stalled(write_timeout=None)
    blob = "x" * (512 * 1024)  # 상대 버퍼(4 KiB)보다 훨씬 크다: 첫 쓰기부터 끝나지 않는다
    durations = []
    for i in range(20):
        started = time.monotonic()
        peer.notify("run.cancel", {"i": i, "blob": blob})
        durations.append(time.monotonic() - started)
    assert max(durations) < 0.5, durations
    # 송신 스레드는 쓰기에서 막혀 있고, 호출한 쪽은 그와 무관하게 돌아왔다
    assert peer.queued >= 19
    assert peer.lost is None

    # 제어 스레드처럼 다른 스레드에서 보내도 바로 돌아온다
    done = threading.Event()
    threading.Thread(target=lambda: (peer.notify("run.pause"), done.set()), daemon=True).start()
    assert done.wait(2)


def test_queue_full_marks_peer_lost(stalled: Any) -> None:
    peer, _raw = stalled(queue_size=4, write_timeout=None)
    pending = peer.request("node.invoke", {"blob": "x" * (512 * 1024)})
    sent = 0
    with pytest.raises(PeerLost, match="송신 큐"):
        for sent in range(1, 10):
            peer.notify("log", {"i": sent})
    assert sent <= 5  # 쓰는 중 하나 + 큐 4개를 넘는 순간
    assert peer.lost is not None
    with pytest.raises(PeerLost):
        pending.result(5)
    lost = peer.incoming.get(timeout=5)
    assert isinstance(lost, PeerLost)
    with pytest.raises(PeerLost):
        peer.notify("after")


def test_write_timeout_marks_peer_lost(stalled: Any) -> None:
    peer, _raw = stalled(write_timeout=0.3)
    pending = peer.request("node.invoke", {"blob": "x" * (512 * 1024)})
    with pytest.raises(PeerLost, match="기한"):
        pending.result(10)
    assert isinstance(peer.incoming.get(timeout=5), PeerLost)


# ── 연결 잃기 ─────────────────────────────────────────────────────────


def test_peer_lost_fails_pending_requests(peers: Any) -> None:
    a, b = peers()
    calls = [a.request("node.invoke", {"n": n}) for n in range(3)]
    wait_for(lambda: b.incoming.qsize() == 3)  # b는 받기만 하고 응답하지 않는다
    b.close()
    for call in calls:
        with pytest.raises(PeerLost):
            call.result(5)
    assert isinstance(a.incoming.get(timeout=5), PeerLost)
    assert a.lost is not None
    with pytest.raises(PeerLost):
        a.request("again")
    with pytest.raises(PeerLost):
        a.notify("again")
    a.join(5)
    b.join(5)


def test_close_flushes_queued_responses(peers: Any) -> None:
    a, b = peers()

    def answer_then_close(peer: RpcPeer, msg: Incoming) -> None:
        peer.respond(msg, {"bye": True})
        peer.close(flush_timeout=5)  # 마지막 응답을 보내고 닫는다

    serve(b, answer_then_close)
    assert a.call("worker.shutdown", timeout=5) == {"bye": True}
    assert isinstance(a.incoming.get(timeout=5), PeerLost)


# ── 오류 ─────────────────────────────────────────────────────────────


def test_error_codes_roundtrip(peers: Any) -> None:
    a, b = peers()

    def fail(peer: RpcPeer, msg: Incoming) -> None:
        params = msg.params
        peer.respond_error(msg, params["code"], params["message"], params.get("data"))

    serve(b, fail)
    data = {"type": "ValueError", "message": "값이 틀렸다", "traceback": "Traceback ...\n"}
    for code, name in rpc.ERROR_CODES.items():
        with pytest.raises(RpcError) as caught:
            a.call("x", {"code": code, "message": f"{name} 메시지", "data": data}, timeout=5)
        assert (caught.value.code, caught.value.message, caught.value.data) == (
            code,
            f"{name} 메시지",
            data,
        )
        assert name in str(caught.value)
    # data 없는 오류
    with pytest.raises(RpcError) as caught:
        a.call("x", {"code": rpc.CANCELLED, "message": "취소"}, timeout=5)
    assert caught.value.data is None


def test_invalid_messages_get_standard_errors(pipe_pair: Any) -> None:
    server, raw = pipe_pair()
    peer = RpcPeer(server).start()
    try:
        send_raw(raw, {"jsonrpc": "1.0", "id": 1, "method": "x"})
        assert raw_message(raw) == {
            "error": {"code": rpc.INVALID_REQUEST, "message": "JSON-RPC 2.0 메시지가 아니다"},
            "id": None,
            "jsonrpc": "2.0",
        }
        send_raw(raw, {"jsonrpc": "2.0", "id": 3, "method": "x", "params": [1, 2]})
        reply = raw_message(raw)
        assert (reply["id"], reply["error"]["code"]) == (3, rpc.INVALID_PARAMS)
        send_raw(raw, {"jsonrpc": "2.0", "id": "a", "method": "x"})
        assert raw_message(raw)["error"]["code"] == rpc.INVALID_REQUEST
        # 봉투에 없는 필드가 붙은 요청(요청이면서 응답인 메시지)은 처리기에 넘기지 않는다
        send_raw(raw, {"jsonrpc": "2.0", "id": 8, "method": "ctx.capture", "result": 123})
        reply = raw_message(raw)
        assert (reply["id"], reply["error"]["code"]) == (8, rpc.INVALID_REQUEST)
        assert "result" in reply["error"]["message"]
        send_raw(raw, {"jsonrpc": "2.0", "id": 9, "method": "Node Invoke"})
        reply = raw_message(raw)
        assert (reply["id"], reply["error"]["code"]) == (9, rpc.INVALID_REQUEST)
        # 잘못된 알림은 답 없이 버린다
        send_raw(raw, {"jsonrpc": "2.0", "method": "Bad Name"})
        send_raw(raw, {"jsonrpc": "2.0", "method": "run.cancel", "extra": 1})
        # 짝이 없는 응답은 버린다
        send_raw(raw, {"jsonrpc": "2.0", "id": 99, "result": 1})
        # 잘못된 메시지 뒤에도 피어는 그대로 동작한다
        send_raw(raw, {"jsonrpc": "2.0", "id": 4, "method": "ok"})
        msg = peer.incoming.get(timeout=5)
        assert isinstance(msg, Incoming) and msg.id == 4
        assert peer.incoming.empty()
        assert peer.lost is None
        peer.respond(msg, "fine")
        assert raw_message(raw) == {"id": 4, "jsonrpc": "2.0", "result": "fine"}
    finally:
        peer.close()


def nested(depth: int) -> str:
    return "[" * depth + "0" + "]" * depth


UNREADABLE = {
    "not_json": b"{not json",
    "invalid_utf8": b'{"jsonrpc":"2.0","id":1,"result":"\xff"}',
    "nan": b'{"jsonrpc":"2.0","id":1,"result":NaN}',
    "infinity": b'{"jsonrpc":"2.0","id":1,"result":-Infinity}',
    "exponent_overflow": b'{"jsonrpc":"2.0","id":1,"result":1e400}',
    "unsafe_integer": b'{"jsonrpc":"2.0","id":1,"result":9007199254740992}',
    # 파서가 재귀 한도로 실패하는 깊이 (16 MiB 상한보다 훨씬 작다)
    "recursion": ('{"jsonrpc":"2.0","id":1,"result":' + nested(100_000) + "}").encode(),
    # 파서는 읽지만 중첩 한도(MAX_DEPTH)를 넘는 깊이: 봉투 1단 + 리스트 MAX_DEPTH단
    "too_deep": ('{"jsonrpc":"2.0","id":1,"result":' + nested(rpc.MAX_DEPTH) + "}").encode(),
}


@pytest.mark.parametrize("name", UNREADABLE)
def test_unreadable_frame_sends_parse_error_and_loses_peer(
    pipe_pair: Any, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    # 어느 요청의 응답인지 알 수 없으므로 연결을 잃은 것으로 하고 대기 중인 요청을 끝낸다.
    # 읽기 스레드가 예외로 조용히 죽어 요청이 영영 남는 일이 없어야 한다
    crashed: list[str] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: crashed.append(repr(args.exc_value)))
    server, raw = pipe_pair()
    peer = RpcPeer(server, name="unreadable").start()
    try:
        pending = peer.request("node.invoke")
        assert raw_message(raw)["id"] == pending.id
        raw.send_frame(UNREADABLE[name])
        reply = raw_message(raw)
        assert (reply["id"], reply["error"]["code"]) == (None, rpc.PARSE_ERROR)
        with pytest.raises(PeerLost, match="JSON으로 읽을 수 없다"):
            pending.result(5)
        assert isinstance(peer.incoming.get(timeout=5), PeerLost)
        peer.join(5)
        assert not [t for t in threading.enumerate() if t.name.startswith("unreadable-")]
        assert crashed == []
    finally:
        peer.close()


def test_nesting_limit_same_for_send_and_receive(peers: Any) -> None:
    a, b = peers()
    serve(b, lambda peer, msg: peer.respond(msg, msg.params["value"]))
    # 요청: 봉투 1단 + params 1단 + 리스트 126단 = 128단 (한도). 응답: 봉투 1단 + 리스트 126단
    deepest = json.loads(nested(rpc.MAX_DEPTH - 2))
    assert a.call("echo", {"value": deepest}, timeout=5) == deepest
    with pytest.raises(ValueError, match="중첩"):
        a.notify("echo", {"value": json.loads(nested(rpc.MAX_DEPTH - 1))})
    assert a.lost is None


def test_invalid_response_fails_matching_call(pipe_pair: Any) -> None:
    server, raw = pipe_pair()
    peer = RpcPeer(server).start()
    bad_responses: list[dict[str, Any]] = [
        {"result": 1, "extra": True},
        {"result": 1, "error": {"code": rpc.INTERNAL_ERROR, "message": "x"}},
        {"error": {"code": -1, "message": "모르는 코드"}},
        {"error": {"code": rpc.NODE_ERROR}},
        {"error": {"code": rpc.NODE_ERROR, "message": "x", "stack": []}},
        {"error": "boom"},
    ]
    try:
        for body in bad_responses:
            pending = peer.request("node.invoke")
            assert raw_message(raw)["id"] == pending.id
            send_raw(raw, {"jsonrpc": "2.0", "id": pending.id, **body})
            with pytest.raises(rpc.InvalidResponse):
                pending.result(5)
        # 연결은 그대로다
        pending = peer.request("node.invoke")
        assert raw_message(raw)["id"] == pending.id
        send_raw(raw, {"jsonrpc": "2.0", "id": pending.id, "result": {"exit": "done"}})
        assert pending.result(5) == {"exit": "done"}
        assert peer.lost is None
    finally:
        peer.close()


def test_unencodable_message_rejected_without_losing_peer(pipe_pair: Any) -> None:
    server, raw = pipe_pair()
    peer = RpcPeer(server).start()
    try:
        with pytest.raises(ValueError):
            peer.notify("x", {"nan": float("nan")})
        with pytest.raises(ValueError):
            peer.notify("x", {"inf": float("inf")})
        with pytest.raises(ValueError, match=r"2\^53"):
            peer.notify("x", {"big": 2**53})
        with pytest.raises(TypeError):
            peer.notify("x", {"obj": object()})
        with pytest.raises(TypeError, match="키"):
            peer.notify("x", {"map": {1: "a"}})
        with pytest.raises(ValueError, match="프레임 상한"):
            peer.notify("x", {"blob": "x" * (16 * 1024 * 1024)})
        # 봉투 규칙: method 형식, params는 객체, 오류 코드는 정해진 값
        with pytest.raises(ValueError, match="method"):
            peer.notify("Node Invoke")
        with pytest.raises(ValueError, match="method"):
            peer.request("node..invoke")
        with pytest.raises(TypeError, match="params"):
            peer.request("node.invoke", [1])  # pyright: ignore[reportArgumentType]
        send_raw(raw, {"jsonrpc": "2.0", "id": 5, "method": "ctx.capture"})
        request = peer.incoming.get(timeout=5)
        assert isinstance(request, Incoming)
        with pytest.raises(ValueError, match="오류 코드"):
            peer.respond_error(request, -1, "unknown code")
        with pytest.raises(ValueError, match="오류 코드"):
            peer.respond_error(request, True, "bool")
        with pytest.raises(TypeError, match="message"):
            peer.respond_error(request, rpc.NODE_ERROR, None)  # pyright: ignore[reportArgumentType]
        assert peer.lost is None
        # 거부한 것은 하나도 나가지 않았다: 처음 도착하는 프레임이 이 응답이다
        peer.respond_error(request, rpc.CONTEXT_VIOLATION, "순수 노드")
        assert raw_message(raw) == {
            "error": {"code": rpc.CONTEXT_VIOLATION, "message": "순수 노드"},
            "id": 5,
            "jsonrpc": "2.0",
        }
    finally:
        peer.close()
