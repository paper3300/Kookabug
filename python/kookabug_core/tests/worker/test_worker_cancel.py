"""워커 취소·유예 종료·죽음 감지 (구현 계획 M0b 2.5, 완료 기준 1·2)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder, make_workspace
from helpers.run import tk
from helpers.worker import Background, WorkerHarness, worker_env

from kb_testing.proc import wait_until
from kookabug_core.engine import RunResult
from kookabug_core.win import Process
from kookabug_sdk.pipe import WRITE_TIMEOUT

pytestmark = pytest.mark.process

TEST = "tests/t.graph.json"
FRAME = "frames/title.png"
GRACE_MS = 500


def single(node_type: str, inputs: dict[str, Any] | None = None) -> GraphBuilder:
    return (
        tk()
        .entry("n_work")
        .node("n_work", node_type, inputs=inputs, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def started(tmp_path: Path, graph: GraphBuilder, **kw: Any) -> WorkerHarness:
    ws = make_workspace(tmp_path / "ws")
    graph.write(ws, TEST)
    kw.setdefault("env", worker_env(tmp_path))
    kw.setdefault("cancel_grace_ms", GRACE_MS)
    h = WorkerHarness(ws, TEST, tmp_path, **kw)
    h.prepare()
    h.start_worker()
    return h


def finish(h: WorkerHarness, running: Background) -> RunResult:
    try:
        return running.join()
    finally:
        h.shutdown()


def work_end(result: RunResult) -> dict[str, Any]:
    (start,) = [e for e in result.events if e["event"] == "step.start" and e["node"] == "n_work"]
    (end,) = [e for e in result.events if e["event"] == "step.end" and e["step"] == start["step"]]
    return end


def test_cancel_while_node_in_ctx_sleep(tmp_path: Path) -> None:
    h = started(tmp_path, single("testkit.block"))
    running = Background(h.run)
    wait_until(lambda: h.events.has_log("blocking"))
    began = time.monotonic()
    h.cancel.cancel()
    result = finish(h, running)
    # 노드가 ctx.sleep에서 깨어 Cancelled로 끝났다: 유예 종료 없이, 워커는 살아서 정상 종료
    assert time.monotonic() - began < GRACE_MS / 1000 + 1
    assert result.verdict == "error" and result.code == "cancelled"
    assert work_end(result)["status"] == "cancelled"
    (exit,) = h.events.of("worker.exit")
    assert exit["reason"] == "shutdown"


def test_cancel_while_node_waits_on_ctx_request(tmp_path: Path) -> None:
    # 워커 노드가 runner의 캡처 응답을 기다리는 동안 취소가 들어온다
    entered, release = threading.Event(), threading.Event()

    def on_capture(_: int) -> None:
        entered.set()
        release.wait(10)

    graph = single("testkit.ctx_roundtrip")
    h = started(tmp_path, graph, frames=[FRAME], on_capture=on_capture)
    running = Background(h.run)
    assert entered.wait(10)
    h.cancel.cancel()  # 제어 스레드 역할: 주 스레드는 캡처 처리 중
    release.set()
    result = finish(h, running)
    assert result.code == "cancelled"
    assert work_end(result)["status"] == "cancelled"
    assert not h.artifacts.saved  # 취소 뒤에는 다음 ctx 요청(저장)을 하지 않았다
    (exit,) = h.events.of("worker.exit")
    assert exit["reason"] == "shutdown"


def test_hung_node_killed_after_grace(tmp_path: Path) -> None:
    h = started(tmp_path, single("testkit.hang", {"label": "hang"}))
    running = Background(h.run)
    assert h.worker is not None
    wait_until(lambda: h.events.has_log("hang"))  # 노드가 워커에서 ctx 없는 루프에 들어갔다
    began = time.monotonic()
    h.cancel.cancel()
    result = finish(h, running)
    elapsed = time.monotonic() - began
    assert GRACE_MS / 1000 - 0.05 <= elapsed < GRACE_MS / 1000 + 5
    assert result.code == "cancelled"
    assert work_end(result)["status"] == "cancelled"
    (exit,) = h.events.of("worker.exit")
    assert exit["reason"] == "killed_after_grace"
    assert h.worker.proc.poll() is not None


def test_grace_kill_independent_of_send(tmp_path: Path) -> None:
    # 워커가 GIL을 쥔 채 멈춰 파이프를 읽지 않는다 → 송신이 막힌다. 취소 알림이 큐에 갇혀도
    # 유예 시각에 워커를 끝낸다 (쓰기 기한 10초를 기다리지 않는다)
    graph = single("testkit.hang", {"hold_gil": True, "label": "hang"})
    h = started(tmp_path, graph)
    worker, peer = h.worker, h.worker.peer if h.worker else None
    assert worker is not None and peer is not None
    running = Background(h.run)
    wait_until(lambda: h.events.has_log("hang"))
    for _ in range(4):  # 파이프 버퍼(64 KiB)를 넘게 채운다
        peer.notify("test.filler", {"pad": "x" * 500_000})
    wait_until(lambda: peer.queued >= 4)
    began = time.monotonic()
    h.cancel.cancel()
    worker.cancel()  # 제어 스레드 역할
    assert peer.queued >= 5 and peer.lost is None  # 취소 알림은 아직 나가지 못했다
    result = finish(h, running)
    elapsed = time.monotonic() - began
    assert elapsed < GRACE_MS / 1000 + 3 < WRITE_TIMEOUT
    assert result.code == "cancelled"
    (exit,) = h.events.of("worker.exit")
    assert exit["reason"] == "killed_after_grace"


def test_worker_killed_externally_step_error_worker_died(tmp_path: Path) -> None:
    h = started(tmp_path, single("testkit.block"))
    assert h.worker is not None and h.worker.ident is not None
    running = Background(h.run)
    wait_until(lambda: h.events.has_log("blocking"))
    with Process.open(h.worker.ident, terminate=True) as proc:
        proc.terminate(7)
    result = finish(h, running)
    assert result.verdict == "error" and result.code == "worker_died"
    end = work_end(result)
    assert end["status"] == "error"
    assert end["error"]["code"] == "worker_died" and "7" in end["error"]["message"]
    (exit,) = h.events.of("worker.exit")
    assert (exit["reason"], exit["exit_code"]) == ("unexpected", 7)


def test_worker_crash_exit_code(tmp_path: Path) -> None:
    h = started(tmp_path, single("testkit.crash", {"code": 3}))
    result = finish(h, Background(h.run))
    assert result.code == "worker_died"
    assert "종료 코드 3" in work_end(result)["error"]["message"]
    (exit,) = h.events.of("worker.exit")
    assert (exit["reason"], exit["exit_code"]) == ("unexpected", 3)


def test_worker_dies_while_runner_handles_ctx_request(tmp_path: Path) -> None:
    # runner 주 스레드가 워커의 캡처 요청을 처리하는 중에 워커가 죽는다 → 응답을 못 보내도
    # 기다리던 노드 실행이 worker_died로 끝난다
    holder: dict[str, WorkerHarness] = {}

    def on_capture(_: int) -> None:
        worker = holder["h"].worker
        assert worker is not None
        worker.proc.kill()
        worker.proc.wait(10)

    h = started(tmp_path, single("testkit.ctx_roundtrip"), frames=[FRAME], on_capture=on_capture)
    holder["h"] = h
    result = finish(h, Background(h.run))
    assert result.code == "worker_died"
    assert work_end(result)["error"]["code"] == "worker_died"
    (exit,) = h.events.of("worker.exit")
    assert exit["reason"] == "unexpected"


def test_dead_worker_not_restarted(tmp_path: Path) -> None:
    # 죽은 워커는 다시 띄우지 않는다: 다음 워커 노드도 worker_died (fail 분기로 이어지지 않음)
    graph = (
        tk()
        .entry("n_work")
        .node("n_work", "testkit.crash", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = started(tmp_path, graph)
    first = finish(h, Background(h.run))
    assert first.code == "worker_died"
    second = h.run()
    assert second.code == "worker_died"
    assert len([e for e in h.events.all if e["event"] == "worker.start"]) == 1
