"""rpc 메타스키마 뼈대 (공통 봉투)와 SDK 피어가 실제로 보내는 메시지 (구현 계획 M0b 2.2), M1 ctx
메서드의 params·result와 오류 종류 (M1 2.8)."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kookabug_core.schema import check_shape, metaschema
from kookabug_sdk import ObservationTimeout, StaleObservation, rpc
from kookabug_sdk.codec import encode
from kookabug_sdk.pipe import PipeConnection, PipeListener, connect, new_key, new_pipe_name
from kookabug_sdk.types import (
    FrameRef,
    Image,
    Match,
    OcrLine,
    OcrResult,
    Point,
    ProcessRef,
    Rect,
    Secret,
    Target,
    WindowInfo,
    WindowRef,
)
from kookabug_sdk.worker import WorkerContext

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


# ---------------------------------------------------------------- M1 ctx 메서드 (구현 계획 M1 2.8)

WIN = WindowRef(0x10, "Sample Game", pid=4001, process_created="1337", binding="b1")
FRAME = Image(1024, 640, frame=3, capture_id=11)
MATCH = Match(
    Rect(1, 2, 3, 4),
    0.9,
    WIN,
    3,
    scale=1.1,
    method="template",
    frame_info=FrameRef("wgc", (1024, 640), 96, 11, 1.5),
    target="targets/a.target.json",
    click=Point(2, 4),
)

# 메서드 → (params 부분 스키마, result 부분 스키마, runner가 줄 결과)
M1_METHODS: dict[str, tuple[str, str, dict[str, Any]]] = {
    "ctx.capture": ("CtxCaptureParams", "CtxCaptureResult", {"image": encode(FRAME)}),
    "ctx.vision.find": ("CtxVisionFindParams", "CtxVisionFindResult", {"match": encode(MATCH)}),
    "ctx.vision.diff": ("CtxVisionDiffParams", "CtxVisionDiffResult", {"value": 0.25}),
    "ctx.ocr.read": (
        "CtxOcrReadParams",
        "CtxOcrReadResult",
        {
            "result": encode(
                OcrResult(Secret("pw"), (OcrLine(Secret("pw"), Rect(0, 0, 9, 9), 0.8),))
            )
        },
    ),
    "ctx.windows.find": ("CtxWindowsFindParams", "CtxWindowResult", {"window": encode(WIN)}),
    "ctx.windows.info": (
        "CtxWindowParams",
        "CtxWindowsInfoResult",
        {
            "info": encode(
                WindowInfo(WIN, "Sample Game", "python.exe", "TkTopLevel", (1024, 640), (0, 0), 96)
            )
        },
    ),
    "ctx.windows.set_client_size": (
        "CtxWindowsSetClientSizeParams",
        "CtxWindowsSetClientSizeResult",
        {"ok": True},
    ),
    "ctx.windows.activate": ("CtxWindowParams", "EmptyResult", {}),
    "ctx.process.launch": (
        "CtxProcessLaunchParams",
        "CtxProcessLaunchResult",
        {"process": encode(ProcessRef(4001, "game.exe"))},
    ),
    "ctx.process.close": ("CtxProcessCloseParams", "CtxProcessCloseResult", {"closed": False}),
    "ctx.process.find_window": ("CtxProcessFindWindowParams", "CtxWindowResult", {"window": None}),
    "ctx.set_window": ("CtxWindowParams", "EmptyResult", {}),
    "ctx.input.click": ("CtxInputClickParams", "EmptyResult", {}),
    "ctx.input.drag": ("CtxInputDragParams", "EmptyResult", {}),
    "ctx.input.scroll": ("CtxInputScrollParams", "EmptyResult", {}),
    "ctx.input.key": ("CtxInputKeyParams", "EmptyResult", {}),
}


class SchemaRunner:
    """워커 ctx 요청을 받아 params를 스키마로 검사하고 정해 둔 결과(역시 스키마로 검사)를 준다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail: rpc.RpcError | None = None

    def __call__(self, method: str, params: dict[str, Any]) -> Any:
        self.calls.append((method, params))
        params_ref, result_ref, result = M1_METHODS[method]
        assert check_shape(params, "rpc", ref=f"#/$defs/{params_ref}") == [], (method, params)
        assert check_shape(result, "rpc", ref=f"#/$defs/{result_ref}") == [], (method, result)
        if self.fail is not None:
            raise self.fail
        return json.loads(json.dumps(result))


def worker_ctx(runner: SchemaRunner) -> WorkerContext:
    return WorkerContext(
        request=runner,
        cancel=threading.Event(),
        files_root=Path("snap"),
        config={},
        window=WIN,
        deadline_remaining_ms=60_000,
    )


def test_m1_worker_ctx_requests_and_results_match_schema() -> None:
    runner = SchemaRunner()
    ctx = worker_ctx(runner)
    deadline = ctx.deadline(5_000)
    region = Rect(0, 0, 100, 50)
    frame = ctx.capture(region, deadline=deadline)
    assert frame == FRAME and frame.capture_id == 11
    assert (
        ctx.vision.find(frame, Target("a", Path("targets/a.target.json")), region=region) == MATCH
    )
    assert ctx.vision.diff(frame, frame, region=region) == 0.25
    text = ctx.ocr.read(frame, region=region, sensitive=True, deadline=deadline).text
    assert isinstance(text, Secret) and text.reveal() == "pw"
    assert ctx.windows.find("/Sample/", None, owned=True) == WIN
    assert ctx.windows.info(WIN).class_name == "TkTopLevel"
    assert ctx.windows.set_client_size(WIN, 1024, 640) is True
    ctx.windows.activate(WIN)
    process = ctx.process.launch("C:/game/game.exe", ["--size", "1024x640"], cwd=None)
    assert process == ProcessRef(4001, "game.exe")
    assert ctx.process.close(process, 3000) is False
    assert ctx.process.find_window(process, "Sample", deadline=deadline) is None
    ctx.set_window(WIN)
    assert ctx.window == WIN  # 이 노드의 창은 그대로 (다음 스텝부터 바뀐다)
    ctx.input.click(MATCH, button="left", count=2)
    ctx.input.drag(Point(0, 0), MATCH, duration_ms=300)
    ctx.input.scroll(Point(5, 5), -3)
    ctx.input.key("shift", hold_ms=250)
    assert {m for m, _ in runner.calls} == set(M1_METHODS)
    calls = dict(runner.calls)
    # 노드 기한은 남은 시간으로 실린다. 기한을 주지 않은 관측에는 싣지 않는다
    assert 0 < calls["ctx.capture"]["deadline_ms"] <= 5_000
    assert "deadline_ms" not in calls["ctx.vision.find"]
    assert calls["ctx.ocr.read"]["sensitive"] is True
    assert calls["ctx.input.click"]["count"] == 2 and calls["ctx.input.key"]["hold_ms"] == 250


def test_m1_passed_deadline_not_requested() -> None:
    runner = SchemaRunner()
    ctx = worker_ctx(runner)
    passed = ctx.deadline(0)
    for call in (
        lambda: ctx.capture(deadline=passed),
        lambda: ctx.vision.find(FRAME, Target("a"), deadline=passed),
        lambda: ctx.ocr.read(FRAME, deadline=passed),
        lambda: ctx.process.find_window(ProcessRef(1), deadline=passed),
    ):
        with pytest.raises(ObservationTimeout):
            call()
    assert runner.calls == []


@pytest.mark.parametrize(
    ("code", "kind"),
    [(rpc.OBSERVATION_TIMEOUT, ObservationTimeout), (rpc.STALE_OBSERVATION, StaleObservation)],
)
def test_m1_error_kinds_in_schema_and_restored_in_worker(
    code: int, kind: type[BaseException]
) -> None:
    reply = {"error": {"code": code, "message": "x"}, "id": 4, "jsonrpc": "2.0"}
    assert check_shape(reply, "rpc") == []
    runner = SchemaRunner()
    runner.fail = rpc.RpcError(code, "노드 기한 100ms 안에 끝나지 않았다")
    ctx = worker_ctx(runner)
    with pytest.raises(kind, match="100ms"):
        ctx.vision.find(FRAME, Target("a"))
    with pytest.raises(kind):
        ctx.input.click(MATCH)


@pytest.mark.parametrize(
    ("ref", "params"),
    [
        ("CtxInputClickParams", {"at": None, "button": "left", "invoke": 1, "count": 0}),
        ("CtxInputKeyParams", {"key": "a", "invoke": 1, "hold_ms": -1}),
        ("CtxCaptureParams", {"region": None, "invoke": 1, "deadline_ms": 1.5}),
        ("CtxOcrReadParams", {"image": None, "region": None, "invoke": 1}),
        ("CtxWindowsSetClientSizeParams", {"window": None, "width": 0, "height": 1, "invoke": 1}),
        ("CtxVisionDiffResult", {"value": 1.5}),
        ("CtxProcessLaunchParams", {"path": "a", "args": [1], "cwd": None, "invoke": 1}),
    ],
)
def test_m1_schema_rejects_bad_params(ref: str, params: dict[str, Any]) -> None:
    assert check_shape(params, "rpc", ref=f"#/$defs/{ref}") != []
