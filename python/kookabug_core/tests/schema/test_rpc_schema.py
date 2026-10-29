"""rpc 메타스키마 뼈대 (공통 봉투)와 SDK 피어가 실제로 보내는 메시지 (구현 계획 M0b 2.2)."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from kookabug_core.schema import check_shape, metaschema
from kookabug_sdk import rpc
from kookabug_sdk.pipe import PipeConnection, PipeListener, connect, new_key, new_pipe_name

VALID = {
    "request": {"id": 1, "jsonrpc": "2.0", "method": "node.invoke", "params": {"step": "s1"}},
    "request_no_params": {"id": 9007199254740991, "jsonrpc": "2.0", "method": "worker.shutdown"},
    "notification": {"jsonrpc": "2.0", "method": "run.cancel", "params": {"reason": "cancelled"}},
    "success": {"id": 2, "jsonrpc": "2.0", "result": None},
    "success_object": {"id": 2, "jsonrpc": "2.0", "result": {"exit": "done", "outputs": {}}},
    "error": {
        "error": {"code": -32002, "data": {"type": "ValueError"}, "message": "boom"},
        "id": 3,
        "jsonrpc": "2.0",
    },
    "error_null_id": {
        "error": {"code": -32700, "message": "JSON이 아니다"},
        "id": None,
        "jsonrpc": "2.0",
    },
}


@pytest.mark.parametrize("name", VALID)
def test_envelope_samples_validate(name: str) -> None:
    assert check_shape(VALID[name], "rpc") == []


INVALID = {
    "wrong_version": {"id": 1, "jsonrpc": "1.0", "method": "x"},
    "zero_id": {"id": 0, "jsonrpc": "2.0", "method": "x"},
    "string_id": {"id": "1", "jsonrpc": "2.0", "method": "x"},
    "array_params": {"id": 1, "jsonrpc": "2.0", "method": "x", "params": [1]},
    "bad_method": {"jsonrpc": "2.0", "method": "Node Invoke"},
    "unknown_field": {"id": 1, "jsonrpc": "2.0", "method": "x", "extra": 1},
    "unknown_error_code": {"error": {"code": -1, "message": "x"}, "id": 1, "jsonrpc": "2.0"},
    "result_and_error": {
        "error": {"code": -32603, "message": "x"},
        "id": 1,
        "jsonrpc": "2.0",
        "result": 1,
    },
    "response_without_id": {"jsonrpc": "2.0", "result": 1},
    "request_with_result": {"id": 8, "jsonrpc": "2.0", "method": "ctx.capture", "result": 123},
    "error_without_message": {"error": {"code": -32002}, "id": 1, "jsonrpc": "2.0"},
    "error_unknown_field": {
        "error": {"code": -32002, "message": "x", "stack": []},
        "id": 1,
        "jsonrpc": "2.0",
    },
    "unsafe_integer": {"id": 1, "jsonrpc": "2.0", "result": 9007199254740992},
}


@pytest.mark.parametrize("name", INVALID)
def test_envelope_rejects(name: str) -> None:
    assert check_shape(INVALID[name], "rpc") != []


def test_sdk_error_codes_match_schema() -> None:
    assert sorted(metaschema("rpc")["$defs"]["ErrorCode"]["enum"]) == sorted(rpc.ERROR_CODES)


@pytest.fixture
def raw_peer() -> Iterator[tuple[rpc.RpcPeer, PipeConnection]]:
    """(SDK 피어, 상대 끝 원시 연결)."""
    name, key = new_pipe_name("schema"), new_key()
    listener = PipeListener(name)
    accepted: list[PipeConnection] = []
    thread = threading.Thread(target=lambda: accepted.append(listener.accept(key, timeout=10)))
    thread.start()
    raw = connect(name, key, timeout=10)
    thread.join(10)
    peer = rpc.RpcPeer(accepted[0]).start()
    yield peer, raw
    peer.close()
    raw.close()


def send_raw(raw: PipeConnection, message: dict[str, Any]) -> None:
    raw.send_frame(json.dumps(message).encode())


def received(raw: PipeConnection) -> dict[str, Any]:
    """피어가 보낸 프레임 하나. 스키마에 맞아야 한다."""
    message = json.loads(raw.recv_frame(5))
    assert check_shape(message, "rpc") == [], message
    return message


def incoming(peer: rpc.RpcPeer) -> rpc.Incoming:
    item = peer.incoming.get(timeout=5)
    assert isinstance(item, rpc.Incoming)
    return item


@pytest.mark.process
@pytest.mark.parametrize("name", [n for n in INVALID if n != "unsafe_integer"])
def test_peer_rejects_what_schema_rejects(
    raw_peer: tuple[rpc.RpcPeer, PipeConnection], name: str
) -> None:
    # 스키마가 거부하는 봉투는 피어도 처리기에 넘기지 않고, 짝지은 요청은 오류로 끝낸다.
    # 피어가 그 사이에 보내는 프레임(오류 응답 등)은 모두 스키마에 맞는다
    peer, raw = raw_peer
    message = dict(INVALID[name])
    is_response = "method" not in message
    pending = peer.request("node.invoke") if is_response else None
    if pending is not None:
        assert received(raw)["id"] == pending.id
        if "id" in message:
            message["id"] = pending.id
    send_raw(raw, message)
    if pending is not None and "id" in message:
        with pytest.raises(rpc.InvalidResponse):
            pending.result(5)

    # 정상 요청 하나를 보내 그것이 처리기에 들어오는 첫 메시지인지 본다
    send_raw(raw, {"id": 1000, "jsonrpc": "2.0", "method": "sentinel"})
    first = incoming(peer)
    assert (first.method, first.id) == ("sentinel", 1000)
    peer.respond(first, "ok")
    while (reply := received(raw)).get("id") != 1000:
        assert "error" in reply  # 잘못된 요청에 대한 오류 응답만 먼저 올 수 있다
    assert reply["result"] == "ok"
    assert peer.lost is None


@pytest.mark.process
def test_peer_rejects_unsafe_number_as_unreadable(
    raw_peer: tuple[rpc.RpcPeer, PipeConnection],
) -> None:
    # 값 규칙(숫자) 위반은 읽을 수 없는 프레임과 같다: parse_error를 보낸 뒤 연결을 잃는다
    peer, raw = raw_peer
    pending = peer.request("node.invoke")
    message = dict(INVALID["unsafe_integer"], id=received(raw)["id"])
    send_raw(raw, message)
    assert received(raw)["error"]["code"] == rpc.PARSE_ERROR
    with pytest.raises(rpc.PeerLost):
        pending.result(5)


@pytest.mark.process
def test_peer_refuses_to_send_what_schema_rejects(
    raw_peer: tuple[rpc.RpcPeer, PipeConnection],
) -> None:
    peer, raw = raw_peer
    with pytest.raises(ValueError):
        peer.notify(INVALID["bad_method"]["method"])
    with pytest.raises(TypeError):
        peer.request("node.invoke", INVALID["array_params"]["params"])
    send_raw(raw, {"id": 3, "jsonrpc": "2.0", "method": "ctx.capture"})
    request = incoming(peer)
    with pytest.raises(ValueError):
        peer.respond_error(request, INVALID["unknown_error_code"]["error"]["code"], "x")
    with pytest.raises(ValueError):
        peer.respond(request, INVALID["unsafe_integer"]["result"])
    # 거부한 것은 하나도 나가지 않았다
    peer.respond(request, None)
    assert received(raw) == {"id": 3, "jsonrpc": "2.0", "result": None}


@pytest.mark.process
def test_peer_messages_validate(raw_peer: tuple[rpc.RpcPeer, PipeConnection]) -> None:
    # SDK 피어가 실제로 쓰는 모든 종류의 메시지를 상대 끝에서 원시 프레임으로 받아 검사한다
    peer, raw = raw_peer
    call = peer.request("node.invoke", {"step": "s1", "inputs": {"text": "한글"}})
    peer.request("worker.shutdown")
    peer.notify("run.cancel", {"reason": "cancelled"})
    send_raw(raw, {"jsonrpc": "2.0", "id": 1, "method": "ctx.log", "params": {"message": "m"}})
    peer.respond(incoming(peer), None)
    send_raw(raw, {"jsonrpc": "2.0", "id": 2, "method": "ctx.capture"})
    peer.respond_error(incoming(peer), rpc.CONTEXT_VIOLATION, "순수 노드", {"node": "n"})
    send_raw(raw, {"jsonrpc": "2.0", "id": call.id, "result": {"exit": "done"}})
    assert call.result(5) == {"exit": "done"}
    # 읽을 수 없는 프레임: parse_error(id null)를 보내고 연결을 잃는다
    raw.send_frame(b"not json")
    assert isinstance(peer.incoming.get(timeout=5), rpc.PeerLost)

    messages = [received(raw) for _ in range(6)]
    kinds = [
        "request"
        if "method" in m and "id" in m
        else "notification"
        if "method" in m
        else "error"
        if "error" in m
        else "success"
        for m in messages
    ]
    assert kinds == ["request", "request", "notification", "success", "error", "error"]
    assert (messages[-1]["id"], messages[-1]["error"]["code"]) == (None, rpc.PARSE_ERROR)
