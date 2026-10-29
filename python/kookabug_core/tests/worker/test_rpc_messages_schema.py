"""실제 워커 세션에서 주고받은 메시지가 `rpc.schema.json`(봉투 + 메서드별 params·result)에
맞는다."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.graphs import make_workspace, secret
from helpers.run import tk
from helpers.worker import Background, WorkerHarness, worker_env

from kb_testing.proc import wait_until
from kookabug_core.schema import check_shape

pytestmark = pytest.mark.process

TEST = "tests/t.graph.json"
CANCEL_TEST = "tests/cancel.graph.json"

# 메서드 → (params 부분 스키마, result 부분 스키마). None = params 없음 / 알림
METHODS: Final[dict[str, tuple[str | None, str | None]]] = {
    "worker.hello": ("WorkerHelloParams", "WorkerHelloResult"),
    "node.invoke": ("NodeInvokeParams", "NodeInvokeResult"),
    "worker.shutdown": (None, "EmptyResult"),
    "cancel": ("CancelParams", None),
    "ctx.capture": ("CtxCaptureParams", "CtxCaptureResult"),
    "ctx.log": ("CtxLogParams", "EmptyResult"),
    "ctx.vars.get": ("CtxVarsGetParams", "CtxVarsGetResult"),
    "ctx.vars.set": ("CtxVarsSetParams", "EmptyResult"),
    "ctx.artifacts.save": ("CtxArtifactsSaveParams", "CtxArtifactsSaveResult"),
    "ctx.input.click": ("CtxInputClickParams", "EmptyResult"),
    "ctx.input.key": ("CtxInputKeyParams", "EmptyResult"),
    "ctx.input.type_text": ("CtxInputTypeTextParams", "EmptyResult"),
    "ctx.setting": ("CtxSettingParams", "CtxSettingResult"),
}


class Recorder:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.messages: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, direction: str, body: bytes) -> None:
        with self.lock:
            self.messages.append((direction, json.loads(body)))


def ref(name: str) -> str:
    return f"#/$defs/{name}"


def check_session(messages: list[tuple[str, dict[str, Any]]]) -> set[str]:
    """모든 메시지를 검사하고 본 메서드 이름을 돌려준다."""
    # 보낸 쪽별 요청 id → 메서드 (runner가 보낸 요청의 응답은 recv, 워커가 보낸 요청의 응답은 send)
    pending: dict[tuple[str, int], str] = {}
    seen: set[str] = set()
    for direction, msg in messages:
        assert check_shape(msg, "rpc") == [], msg
        if "method" in msg:
            method = msg["method"]
            seen.add(method)
            params_ref, _ = METHODS[method]
            if params_ref is None:
                assert "params" not in msg, msg
            else:
                assert check_shape(msg.get("params", {}), "rpc", ref=ref(params_ref)) == [], msg
            if "id" in msg:
                pending[(direction, msg["id"])] = method
            continue
        asker = "recv" if direction == "send" else "send"
        method = pending.pop((asker, msg["id"]))
        if "result" in msg:
            result_ref = METHODS[method][1]
            assert result_ref is not None
            assert check_shape(msg["result"], "rpc", ref=ref(result_ref)) == [], msg
            if method == "worker.hello":
                for plugin in msg["result"]["plugins"]:
                    assert check_shape(plugin["schema"], "node-schema") == []
    return seen


def test_recorded_session_messages_validate(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path / "ws", settings={"server": "qa"})
    (
        tk()
        .entry("n_rt")
        .node(
            "n_rt",
            "testkit.ctx_roundtrip",
            inputs={"value": {"$literal": {"$kb": 1, "list": [1, 2]}}, "setting_key": "server"},
            next={"done": "n_tap"},
        )
        .node("n_tap", "testkit.input.tap", inputs={"x": 1, "y": 2}, next={"done": "n_hold"})
        .node(
            "n_hold",
            "testkit.input.hold",
            inputs={"key": "a", "text": secret("pw")},
            next={"done": "n_boom"},
        )
        .node("n_boom", "testkit.boom")
        .write(ws, TEST)
    )
    (
        tk()
        .entry("n_block")
        .node("n_block", "testkit.block", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
        .write(ws, CANCEL_TEST)
    )
    recorder = Recorder()

    def harness(rel: str, sub: str) -> WorkerHarness:
        return WorkerHarness(
            ws,
            rel,
            tmp_path / sub,
            env=worker_env(tmp_path),
            frames=["frames/a.png"],
            secrets={"pw": "pw-원문"},
            trace=recorder,
        )

    first = harness(TEST, "a").run_all()
    assert first.code == "node_error"  # 오류 응답도 세션에 들어간다

    h = harness(CANCEL_TEST, "b")
    h.prepare()
    h.start_worker()
    running = Background(h.run)
    wait_until(lambda: h.events.has_log("blocking"))
    h.cancel.cancel()
    try:
        assert running.join().code == "cancelled"
    finally:
        h.shutdown()

    with recorder.lock:
        messages = list(recorder.messages)
    seen = check_session(messages)
    assert seen == set(METHODS)
    errors = {m["error"]["code"] for _, m in messages if "error" in m}
    assert {-32001, -32002} <= errors  # cancelled, node_error
