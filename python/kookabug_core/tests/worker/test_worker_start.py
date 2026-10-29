"""워커 시작: hello·원격 스키마 등록·시작 기한·시작 중 사망·취소·프로토콜 (구현 계획 M0b 2.5)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder, make_workspace
from helpers.run import tk
from helpers.worker import TESTS_DIR, Background, WorkerHarness, worker_env

from kb_testing.proc import barrier
from kookabug_core import workerhost
from kookabug_core.diagnostics import has_errors
from kookabug_core.engine import Cancelled
from kookabug_core.workerhost import WorkerProcess, WorkerStartError

pytestmark = pytest.mark.process

TEST = "tests/t.graph.json"


def simple_graph() -> GraphBuilder:
    return (
        tk()
        .entry("n_read")
        .node("n_read", "testkit.read_text", inputs={"text": "hi"}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def harness(tmp_path: Path, faults: list[dict[str, Any]] | None = None, **kw: Any) -> WorkerHarness:
    ws = make_workspace(tmp_path / "ws")
    simple_graph().write(ws, TEST)
    return WorkerHarness(ws, TEST, tmp_path, env=worker_env(tmp_path, faults), **kw)


def fault(point: str, action: str) -> dict[str, Any]:
    return {"point": point, "role": "worker", "action": action}


def test_hello_registers_remote_schema_before_validation(tmp_path: Path) -> None:
    h = harness(tmp_path)
    h.prepare()
    # 워커 전: runner의 레지스트리는 testkit을 모른다 → 검증 오류
    before = h.validate()
    assert has_errors(before)
    assert {d.code for d in before} >= {"unknown_node_type"}
    worker = h.start_worker()
    try:
        nodedef = h.registry.get("testkit.read_text")
        assert nodedef is not None and nodedef.remote and nodedef.function is None
        assert h.registry.get("core.test.pass").function is not None  # type: ignore[union-attr]
        assert [p["id"] for p in worker.plugins] == ["testkit"]
        assert not has_errors(h.validate())
        result = h.run()
    finally:
        h.shutdown()
    assert result.verdict == "pass"
    lifecycle = [e["event"] for e in h.events.all if e["event"].startswith("worker.")]
    assert lifecycle == ["worker.start", "worker.exit"]
    (exit,) = h.events.of("worker.exit")
    assert exit["reason"] == "shutdown" and exit["exit_code"] == 0


def test_runner_does_not_import_plugin_modules(tmp_path: Path) -> None:
    # runner 역할을 별도 프로세스에서 하게 하고, 그 프로세스의 sys.modules에 testkit이 없음을 본다
    ws = make_workspace(tmp_path / "ws")
    simple_graph().write(ws, TEST)
    out = tmp_path / "out.json"
    script = TESTS_DIR / "procs" / "worker_runner.py"
    proc = subprocess.run(
        [sys.executable, str(script), str(ws.root), TEST, str(tmp_path / "harness"), str(out)],
        env=worker_env(tmp_path),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["verdict"] == "pass"
    assert "testkit.read_text" in result["remote"]
    assert all(t.startswith("testkit.") for t in result["remote"])
    assert result["imported"] == []


def test_hello_timeout_is_worker_start_timeout(tmp_path: Path) -> None:
    h = harness(tmp_path, [fault("worker.before_hello_reply", "hang")], start_timeout_ms=1500)
    h.prepare()
    began = time.monotonic()
    with pytest.raises(WorkerStartError) as info:
        h.start_worker()
    assert info.value.code == "worker_start_timeout"
    assert 1.4 <= time.monotonic() - began < 15
    (exit,) = h.events.of("worker.exit")
    assert exit["reason"] == "start_timeout"
    assert not h.registry.get("testkit.read_text")


def test_import_hang_is_worker_start_timeout(tmp_path: Path) -> None:
    h = harness(tmp_path, [fault("worker.in_import", "hang")], start_timeout_ms=1500)
    h.prepare()
    with pytest.raises(WorkerStartError) as info:
        h.start_worker()
    assert info.value.code == "worker_start_timeout"
    (exit,) = h.events.of("worker.exit")
    assert exit["reason"] == "start_timeout"


def test_worker_dies_before_hello_is_worker_died(tmp_path: Path) -> None:
    # 기한(30초)을 기다리지 않고 바로 알아챈다
    h = harness(tmp_path, [fault("worker.before_hello_reply", "exit:5")])
    h.prepare()
    began = time.monotonic()
    with pytest.raises(WorkerStartError) as info:
        h.start_worker()
    assert info.value.code == "worker_died"
    assert "5" in info.value.message
    assert time.monotonic() - began < 15
    (exit,) = h.events.of("worker.exit")
    assert (exit["reason"], exit["exit_code"]) == ("unexpected", 5)


def test_cancel_during_hello(tmp_path: Path) -> None:
    gate = barrier(tmp_path / "barriers" / "hello")
    h = harness(tmp_path, [fault("worker.before_hello_reply", gate.action)])
    h.prepare()
    starting = Background(h.start_worker)
    gate.wait_ready()
    began = time.monotonic()
    h.cancel.cancel()
    with pytest.raises(Cancelled):
        starting.join()
    assert time.monotonic() - began < 5
    assert h.worker is None
    (exit,) = h.events.of("worker.exit")
    assert exit["reason"] == "cancelled"
    assert not h.registry.get("testkit.read_text")


def test_protocol_version_mismatch(tmp_path: Path) -> None:
    h = harness(tmp_path)
    h.prepare()
    with pytest.raises(WorkerStartError) as info:
        WorkerProcess.start(
            modules=h.modules,
            files_root=h.files_root,
            log_dir=h.run_dir / "logs",
            run_id="r1",
            workspace_id="ws",
            registry=h.registry,
            emit=h.events.emit,
            check=h.check,
            env=h.env,
            protocol=99,
        )
    assert info.value.code == "protocol_version"
    assert "99" in info.value.message
    (exit,) = h.events.of("worker.exit")
    assert exit["reason"] == "start_failed"


def test_import_error_is_start_failure(tmp_path: Path) -> None:
    h = harness(tmp_path, modules=("testkit.no_such_module",))
    h.prepare()
    with pytest.raises(WorkerStartError) as info:
        h.start_worker()
    assert info.value.code == "worker_start_failed"
    assert "no_such_module" in info.value.message


def test_hello_disconnect_with_live_worker_terminates_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 인증 뒤 hello를 받고 연결만 끊은 채 살아 있는 워커: 연결 상실은 종료가 아니므로 끝내고,
    # 종료를 확인한 뒤 worker.exit를 남긴다 (검수 T8-1 High 2)
    real_spawn = workerhost.spawn
    children: list[subprocess.Popen[bytes]] = []

    def spawn_disconnecting(args: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        proc = real_spawn(
            [sys.executable, str(TESTS_DIR / "procs" / "disconnect_worker.py")], **kwargs
        )
        children.append(proc)
        return proc

    monkeypatch.setattr(workerhost, "spawn", spawn_disconnecting)
    h = harness(tmp_path)
    h.prepare()
    try:
        with pytest.raises(WorkerStartError) as info:
            h.start_worker()
        assert info.value.code == "worker_start_failed"
        (child,) = children
        assert child.poll() is not None
        (exit,) = h.events.of("worker.exit")
        assert exit["reason"] == "start_failed"
        assert exit["exit_code"] == child.returncode
    finally:
        for proc in children:
            if proc.poll() is None:
                proc.kill()
            proc.wait(10)


SLOW_STDOUT_PLUGIN = '''
import sys
import threading

from kookabug_sdk import Context, Exit, Result, node

original = sys.stdout


class SlowFlush:
    """주 스레드의 flush를 10초 붙잡는 stdout (플러그인이 바꿔 끼운 것)."""

    def flush(self):
        if threading.current_thread() is threading.main_thread():
            threading.Event().wait(10)
        original.flush()

    def __getattr__(self, name):
        return getattr(original, name)


sys.stdout = SlowFlush()


@node(type="slow.ok", version=1, title="정상", exits=[Exit("done", "ok")])
def ok(ctx: Context) -> Result:
    print("slow.ok 출력")
    return Result.ok("done")
'''


def test_normal_shutdown_exit_code_zero_with_plugin_stdout(tmp_path: Path) -> None:
    # 정상 종료는 주 스레드 한 곳에서 코드 0으로 끝난다: 자기 close가 연결 상실 처리(코드 2)를
    # 깨우지 않고, 플러그인이 바꿔 끼운 stdout에 종료가 막히지 않는다 (검수 T8-1 Mid)
    (tmp_path / "slow_plugin.py").write_text(SLOW_STDOUT_PLUGIN, encoding="utf-8")
    ws = make_workspace(tmp_path / "ws")
    graph = GraphBuilder(plugins={"slow": "0+dev"}).entry("n_ok")
    graph.node("n_ok", "slow.ok", next={"done": "n_pass"}).node("n_pass", "core.test.pass")
    graph.write(ws, TEST)
    env = worker_env(tmp_path)
    env["PYTHONPATH"] += os.pathsep + str(tmp_path)
    h = WorkerHarness(ws, TEST, tmp_path, env=env, modules=["slow_plugin"])
    result = h.run_all()
    assert result.verdict == "pass", result.reason
    (exit,) = h.events.of("worker.exit")
    assert (exit["reason"], exit["exit_code"]) == ("shutdown", 0)
    assert "slow.ok 출력" in h.log_text("stdout")
