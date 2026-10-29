"""워커 노드 실행: 실행 위치, `ctx` 대리, `ctx.path` 루트, 효과·결과 재검사, 로그, 예외, 비밀값
(구현 계획 M0b 2.5)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder, link, make_workspace, secret
from helpers.run import tk
from helpers.worker import WorkerHarness, worker_env

from kookabug_core.engine import InProcessInvoker, NodeInvoker, RunResult
from kookabug_core.ir import Node
from kookabug_core.registry import NodeDef
from kookabug_sdk import Result
from kookabug_sdk.context import Context

pytestmark = pytest.mark.process

TEST = "tests/t.graph.json"
FRAME = "frames/title.png"


def harness(tmp_path: Path, graph: GraphBuilder, **kw: Any) -> WorkerHarness:
    settings = kw.pop("settings", None)
    ws = make_workspace(tmp_path / "ws", settings=settings)
    graph.write(ws, TEST)
    kw.setdefault("env", worker_env(tmp_path))
    return WorkerHarness(ws, TEST, tmp_path, **kw)


def end_of(result: RunResult, node: str) -> dict[str, Any]:
    (start,) = [e for e in result.events if e["event"] == "step.start" and e["node"] == node]
    (end,) = [e for e in result.events if e["event"] == "step.end" and e["step"] == start["step"]]
    return end


class Spy:
    def __init__(self, inner: NodeInvoker) -> None:
        self.inner = inner
        self.types: list[str] = []

    def invoke(
        self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
    ) -> Result:
        self.types.append(nodedef.type)
        return self.inner.invoke(nodedef, node, ctx, inputs)


def test_plugin_node_in_worker_core_node_in_process(tmp_path: Path) -> None:
    graph = (
        tk()
        .entry("n_read")
        .node("n_read", "testkit.read_text", inputs={"text": "hi"}, next={"done": "n_log"})
        .node(
            "n_log",
            "core.log.message",
            inputs={"text": link("n_read.text")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    h = harness(tmp_path, graph)
    h.prepare()
    h.start_worker()
    local = Spy(InProcessInvoker())
    assert h.remote is not None
    remote = Spy(h.remote)
    h.local, h.remote = local, remote
    try:
        result = h.run()
    finally:
        h.shutdown()
    assert result.verdict == "pass", result.reason
    assert remote.types == ["testkit.read_text"]
    assert "core.log.message" in local.types
    assert not any(t.startswith("testkit.") for t in local.types)
    assert h.events.has_log("hi")


def test_ctx_roundtrip_capture_vars_log(tmp_path: Path) -> None:
    value = {"a": [1, 2.5, None, True], "$kb": "user"}
    graph = (
        tk()
        .entry("n_rt")
        .node(
            "n_rt",
            "testkit.ctx_roundtrip",
            inputs={"value": {"$literal": value}, "message": "hello", "setting_key": "server"},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    h = harness(tmp_path, graph, frames=[FRAME], settings={"server": "qa-01"})
    result = h.run_all()
    assert result.verdict == "pass", result.reason
    end = end_of(result, "n_rt")
    outputs = end["outputs"]
    assert outputs["value"] == value
    assert outputs["value_type"] == "dict"
    assert outputs["has_missing"] is False
    assert outputs["setting"] == "qa-01"
    assert outputs["image"]["path"] == FRAME
    # 캡처는 runner 플랫폼에서 (runner가 붙인 capture_id가 워커를 거쳐 저장까지 유지)
    assert h.platform.captured == 1
    (saved,) = h.artifacts.saved.values()
    assert saved.path == Path(FRAME) and saved.capture_id == 1
    assert end["artifacts"] == [outputs["saved"]]
    assert h.events.has_log(f"hello: {value}")


def test_ctx_path_uses_files_root(tmp_path: Path) -> None:
    graph = (
        tk()
        .entry("n_read")
        .node("n_read", "testkit.read_file", inputs={"rel": "data/x.txt"}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = harness(tmp_path, graph)
    (h.ws.root / "data").mkdir()
    (h.ws.root / "data/x.txt").write_text("원본", encoding="utf-8")
    h.prepare()
    (h.files_root / "data").mkdir()
    (h.files_root / "data/x.txt").write_text("스냅샷", encoding="utf-8")
    h.start_worker()
    try:
        first = h.run()
        (h.ws.root / "data/x.txt").write_text("바뀐 원본", encoding="utf-8")
        second = h.run()
    finally:
        h.shutdown()
    assert end_of(first, "n_read")["outputs"]["text"] == "스냅샷"
    assert end_of(second, "n_read")["outputs"]["text"] == "스냅샷"


@pytest.mark.parametrize("rel", ["../ws/data/x.txt", "data/../../x.txt", "C:/x.txt", "/x.txt"])
def test_ctx_path_outside_files_root_is_error(tmp_path: Path, rel: str) -> None:
    graph = (
        tk()
        .entry("n_read")
        .node("n_read", "testkit.read_file", inputs={"rel": rel}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    result = harness(tmp_path, graph).run_all()
    assert result.verdict == "error"
    end = end_of(result, "n_read")
    assert end["error"]["code"] == "node_error"
    assert "ValueError" in end["error"]["message"]


def test_pure_plugin_node_ctx_violation_in_worker(tmp_path: Path) -> None:
    graph = (
        tk()
        .entry("n_check")
        .node("n_pure", "testkit.pure.log")
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": link("n_pure.ok"), "op": "==", "b": True},
            next={"ok": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    result = harness(tmp_path, graph).run_all()
    assert result.verdict == "error"
    end = end_of(result, "n_check")
    assert end["error"]["code"] == "context_violation"
    assert "log.info" in end["error"]["message"]


@pytest.mark.parametrize("swallow", [False, True])
def test_runner_rejects_undeclared_effect_ctx_request(tmp_path: Path, swallow: bool) -> None:
    # 워커가 SDK 제한을 건너뛰어 캡처를 요청해도 runner가 선언으로 다시 막는다. 노드가 그 오류를
    # 삼키고 정상으로 끝나도 error
    graph = (
        tk()
        .entry("n_sneak")
        .node("n_sneak", "testkit.ctx_sneak", inputs={"swallow": swallow}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = harness(tmp_path, graph, frames=[FRAME])
    result = h.run_all()
    assert result.verdict == "error"
    end = end_of(result, "n_sneak")
    assert end["error"]["code"] == "context_violation"
    assert "capture" in end["error"]["message"]
    assert h.platform.captured == 0


def test_runner_rechecks_result_against_declaration(tmp_path: Path) -> None:
    graph = tk().entry("n_liar").node("n_liar", "testkit.liar", next={"done": "n_pass"})
    graph.node("n_pass", "core.test.pass")
    result = harness(tmp_path, graph).run_all()
    assert result.verdict == "error"
    end = end_of(result, "n_liar")
    assert end["error"]["code"] == "node_contract"
    assert "'other'" in end["error"]["message"]


def test_print_goes_to_log_file(tmp_path: Path) -> None:
    graph = (
        tk()
        .entry("n_rt")
        .node(
            "n_rt",
            "testkit.ctx_roundtrip",
            inputs={"message": "출력 한글"},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    h = harness(tmp_path, graph, frames=[FRAME])
    result = h.run_all()
    assert result.verdict == "pass", result.reason
    assert "print: 출력 한글" in h.log_text("stdout")


def test_node_exception_error_with_traceback(tmp_path: Path) -> None:
    graph = (
        tk()
        .entry("n_boom")
        .node("n_boom", "testkit.boom", inputs={"message": "터짐"}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = harness(tmp_path, graph)
    result = h.run_all()
    assert result.verdict == "error"
    end = end_of(result, "n_boom")
    assert end["error"] == {"code": "node_error", "message": "RuntimeError: 터짐"}
    traces = [
        e["message"]
        for e in result.events
        if e["event"] == "log" and e["step"] == end["step"] and e["level"] == "error"
    ]
    assert len(traces) == 1
    assert "Traceback" in traces[0] and "def boom" not in traces[0]
    assert "in boom" in traces[0] and "RuntimeError: 터짐" in traces[0]
    # 워커는 계속 산다 (마무리에서 정상 종료)
    (exit,) = h.events.of("worker.exit")
    assert exit["reason"] == "shutdown"


def test_secret_input_reaches_node_masked_in_events(tmp_path: Path) -> None:
    graph = (
        tk()
        .entry("n_rt")
        .node(
            "n_rt",
            "testkit.ctx_roundtrip",
            inputs={"value": secret("accounts.pw"), "message": "pw"},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    raw = "s3cr3t-값"
    messages: list[bytes] = []
    h = harness(
        tmp_path,
        graph,
        frames=[FRAME],
        secrets={"accounts.pw": raw},
        trace=lambda _, body: messages.append(body),
    )
    result = h.run_all()
    assert result.verdict == "pass", result.reason
    end = end_of(result, "n_rt")
    # 노드는 Secret으로 받고(변수 왕복 뒤에도), 기록에는 가린 값만
    assert end["outputs"]["value_type"] == "secret"
    assert end["outputs"]["value"] == "***"
    assert h.events.has_log("pw: ***")
    assert raw not in repr(result.events) and raw not in repr(h.events.all)
    # 비밀값 스텝의 스크린샷은 정책으로 생략
    assert end["outputs"]["saved"] is None
    assert end["omitted"][0]["reason"] == "secret_input"
    # 원문은 인증된 파이프로만 (워커가 노드에 Secret을 줘야 하므로)
    assert any(raw.encode() in m for m in messages)


def test_image_output_keeps_capture_identity(tmp_path: Path) -> None:
    # 워커 출력의 이미지를 다음 노드가 저장해도 runner가 붙인 capture_id로 정책을 찾는다
    graph = (
        tk()
        .entry("n_rt")
        .node(
            "n_rt", "testkit.ctx_roundtrip", next={"done": "n_shot"}, record={"screenshots": "off"}
        )
        .node(
            "n_shot",
            "testkit.shot",
            inputs={"captures": 0, "save": True, "image": link("n_rt.image")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    h = harness(tmp_path, graph, frames=[FRAME])
    result = h.run_all()
    assert result.verdict == "pass", result.reason
    out = end_of(result, "n_rt")["outputs"]["image"]
    assert isinstance(out, dict) and out["capture_id"] == 1
    assert end_of(result, "n_shot")["omitted"][0]["reason"] == "capture_policy"
    assert not h.artifacts.saved


STALE_PLUGIN = """
import threading

from kookabug_sdk import Context, Exit, Output, Result, node

saved = None
go = threading.Event()
late: list[str] = []


@node(type="stale.remember", version=1, title="ctx 보관", exits=[Exit("done", "ok")])
def remember(ctx: Context) -> Result:
    global saved
    saved = ctx.inner
    return Result.ok("done")


@node(
    type="stale.later",
    version=1,
    title="보관한 ctx로 캡처",
    exits=[Exit("done", "ok")],
    effects={"capture"},
)
def later(ctx: Context) -> Result:
    image = saved.capture()
    saved.artifacts.save(image, "old-context")
    return Result.ok("done")


def _late_call() -> None:
    go.wait(10)
    try:
        saved.log.info("late")
    except Exception as exc:
        late.append(f"{type(exc).__name__}: {exc}")


@node(type="stale.stray", version=1, title="스레드를 남기고 끝남", exits=[Exit("done", "ok")])
def stray(ctx: Context) -> Result:
    global saved, worker
    saved = ctx.inner
    worker = threading.Thread(target=_late_call)
    worker.start()
    return Result.ok("done")


@node(
    type="stale.collect",
    version=1,
    title="남은 스레드 결과",
    exits=[Exit("done", "ok")],
    outputs={"late": str},
    effects={"capture"},
)
def collect(ctx: Context) -> Result:
    go.set()
    worker.join(10)
    return Result.ok("done", late=late[0] if late else "")
"""


def stale_harness(tmp_path: Path, graph: GraphBuilder) -> WorkerHarness:
    (tmp_path / "stale_plugin.py").write_text(STALE_PLUGIN, encoding="utf-8")
    env = worker_env(tmp_path)
    env["PYTHONPATH"] += os.pathsep + str(tmp_path)
    return harness(tmp_path, graph, env=env, modules=["stale_plugin"], frames=[FRAME])


def test_old_ctx_rejected_after_invoke_ends(tmp_path: Path) -> None:
    # 효과 선언이 없고 스크린샷이 꺼진 노드의 ctx를 보관했다가, 캡처를 선언한 다음 노드가 그 ctx로
    # 캡처·저장한다 → 다음 노드의 선언·기록 정책으로 처리되면 안 된다 (검수 T8-1 High 1)
    graph = (
        GraphBuilder(plugins={"stale": "0+dev"})
        .entry("n_first")
        .node("n_first", "stale.remember", next={"done": "n_second"}, record={"screenshots": "off"})
        .node("n_second", "stale.later", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = stale_harness(tmp_path, graph)
    result = h.run_all()
    assert result.code == "context_violation"
    assert "끝난 노드 실행" in end_of(result, "n_second")["error"]["message"]
    assert h.platform.captured == 0
    assert not h.artifacts.saved


def test_late_ctx_request_from_leftover_thread_rejected(tmp_path: Path) -> None:
    # 노드가 남긴 스레드가 노드가 끝난 뒤(다음 노드 실행 중) ctx를 부른다
    graph = (
        GraphBuilder(plugins={"stale": "0+dev"})
        .entry("n_stray")
        .node("n_stray", "stale.stray", next={"done": "n_collect"})
        .node("n_collect", "stale.collect", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = stale_harness(tmp_path, graph)
    result = h.run_all()
    assert result.verdict == "pass", result.reason
    assert end_of(result, "n_collect")["outputs"]["late"].startswith("ContextViolation")
    assert not h.events.has_log("late")


@pytest.mark.parametrize("offset", [-1, 1])
def test_runner_rejects_ctx_request_of_other_invoke(tmp_path: Path, offset: int) -> None:
    # 워커가 실행 번호를 속여도(앞 실행·없는 실행) runner가 처리하지 않는다. 앞 노드로 실행 번호
    # 1을 쓰고, 재현 노드는 2번 실행이다
    graph = (
        tk()
        .entry("n_read")
        .node("n_read", "testkit.read_text", next={"done": "n_replay"})
        .node("n_replay", "testkit.ctx_replay", inputs={"offset": offset}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = harness(tmp_path, graph, frames=[FRAME])
    result = h.run_all()
    assert result.verdict == "pass", result.reason
    rejected = end_of(result, "n_replay")["outputs"]["rejected"]
    assert rejected is not None and "context_violation" in rejected
    assert h.platform.captured == 0
