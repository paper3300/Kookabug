"""실행 메서드 (M2 계획 2.8, T5): 시작 순서·구독 순서와 커서·역압·취소·중복 방지 키.

daemon은 같은 프로세스의 다른 스레드에서 돈다(`ThreadDaemon`). runner·워커는 실제 프로세스이고
플랫폼은 가짜다. 순서를 맞추는 곳은 장벽(파일·고장 주입·`catchup_hook`)으로 강제한다.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from helpers.daemon_runs import TEST, EventLog, RunRig
from helpers.graphs import GraphBuilder, subgraph_interface
from helpers.run import tk
from websockets.sync.client import connect

from kb_testing.daemon import DaemonProcess, ThreadDaemon
from kb_testing.proc import Spawned, barrier, wait_until
from kookabug_core.record import read_run, read_run_json
from kookabug_daemon.client import UI_CLIENT, DaemonClient, DaemonError
from kookabug_daemon.runs import snapshot_calls
from kookabug_daemon.session import read_session
from kookabug_daemon.transport import Limits

pytestmark = [pytest.mark.process, pytest.mark.timeout(180)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-7"}


# ---------------------------------------------------------------- 그래프


def pass_graph() -> GraphBuilder:
    return (
        GraphBuilder()
        .entry("n_log")
        .node("n_log", "core.log.message", inputs={"text": "하나"}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def gate_graph(signal: Path) -> GraphBuilder:
    return (
        tk()
        .entry("n_log")
        .node("n_log", "core.log.message", inputs={"text": "앞"}, next={"done": "n_gate"})
        .node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_after"})
        .node("n_after", "core.log.message", inputs={"text": "뒤"}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def loop_graph(times: int, text: str, signal: Path | None = None) -> GraphBuilder:
    """`times`번 로그를 남긴다 (이벤트가 많은 실행). `signal`이 있으면 그 뒤 게이트에서 기다린다."""
    done = "n_gate" if signal is not None else "n_pass"
    g = (
        tk()
        .entry("n_loop")
        .node(
            "n_loop",
            "core.flow.repeat",
            inputs={"times": times},
            next={"body": "n_log", "done": done},
        )
        .node("n_log", "core.log.message", inputs={"text": text})
        .node("n_pass", "core.test.pass")
    )
    if signal is not None:
        g.node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_pass"})
    return g


def gate_logged(event: Any) -> bool:
    return event.get("event") == "log" and event.get("message") == "gate"


def file_events(run_dir: str | Path) -> list[dict[str, Any]]:
    return read_run(run_dir).events


def start_and_subscribe(client: DaemonClient, after: int = 0) -> tuple[dict[str, Any], EventLog]:
    started = client.call("run.start", {"path": TEST})
    client.call("run.subscribe", {"run_id": started["run_id"], "after_seq": after})
    return started, EventLog(client, started["run_id"], base=after)


# ---------------------------------------------------------------- 흐름


def test_start_streams_events_in_seq_order_until_run_ended(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, pass_graph())
    with rig.daemon() as d, d.client() as client:
        started, log = start_and_subscribe(client)
        assert started["graph"] == TEST
        assert Path(started["run_dir"]).parent == rig.root / "runs"
        log.until_ended()
        events = file_events(started["run_dir"])
        assert log.events == events
        assert log.seqs == list(range(1, len(events) + 1))
        assert log.kinds()[0] == "run.start" and "run.end" in log.kinds()
        ended = log.ended
        assert ended is not None
        assert ended["outcome"] == {"verdict": "pass", "exit_code": 0, "finalized_by": "runner"}
        assert ended["last_seq"] == events[-1]["seq"]
        status = client.call("run.status", {"run_id": started["run_id"]})
        assert status["state"] == "ended" and status["outcome"] == ended["outcome"]
        assert status["last_seq"] == ended["last_seq"] and status["graph"] == TEST
        assert d.daemon.runs.active_run() is None


def test_status_calls_from_snapshot_not_workspace(tmp_path: Path) -> None:
    # T11 검수 1차: 화면은 실행 중 강조를 실행한 그래프 파일(스냅샷)에 붙인다.
    # 실행 뒤 원본의 호출 대상을 바꿔도 run.status calls는 스냅샷 그대로다
    outer, inner = "subgraphs/outer.graph.json", "subgraphs/inner.graph.json"
    other = "subgraphs/other.graph.json"
    graph = (
        tk()
        .entry("n_c1")
        .call("n_c1", outer, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    rig = RunRig.make(tmp_path, graph)
    for rel, target in ((outer, inner), (other, None)):
        builder = GraphBuilder("subgraph", interface=subgraph_interface()).entry("n_x")
        if target is not None:
            builder.call("n_x", target, next={"done": "n_exit"})
        else:
            builder.node("n_x", "core.log.message", inputs={"text": "x"}, next={"done": "n_exit"})
        builder.exit("n_exit", "done").write(rig.root, rel)
    (
        GraphBuilder("subgraph", interface=subgraph_interface())
        .entry("n_y")
        .node("n_y", "core.log.message", inputs={"text": "안쪽"}, next={"done": "n_exit"})
        .exit("n_exit", "done")
        .write(rig.root, inner)
    )
    with rig.daemon() as d, d.client() as client:
        started, log = start_and_subscribe(client)
        log.until_ended()
        assert log.ended is not None and log.ended["outcome"]["verdict"] == "pass"
        expected = {TEST: {"n_c1": outer}, outer: {"n_x": inner}}
        assert client.call("run.status", {"run_id": started["run_id"]})["calls"] == expected
        # 원본을 고쳐도 스냅샷 기준이다
        source = rig.root / "tests" / "t.graph.json"
        source.write_text(
            source.read_text(encoding="utf-8").replace(outer, other), encoding="utf-8"
        )
        assert client.call("run.status", {"run_id": started["run_id"]})["calls"] == expected
        # 목록 요약에는 싣지 않는다 (실행마다 스냅샷을 읽지 않는다)
        listed = client.call("run.list", {})["runs"][0]
        assert "calls" not in listed


def test_snapshot_calls_skips_broken_files(tmp_path: Path) -> None:
    snap = tmp_path / "run" / "snapshot"
    (snap / "tests").mkdir(parents=True)
    (snap / "tests" / "a.graph.json").write_text(
        json.dumps({"nodes": {"c": {"config": {"graph": "subgraphs/s.graph.json"}}, "x": {}}}),
        encoding="utf-8",
    )
    (snap / "tests" / "bad.graph.json").write_text("{", encoding="utf-8")
    (snap / "tests" / "bom.graph.json").write_bytes(b"\xef\xbb\xbf{}")
    assert snapshot_calls(tmp_path / "run") == {
        "tests/a.graph.json": {"c": "subgraphs/s.graph.json"}
    }
    assert snapshot_calls(tmp_path / "missing") == {}


def wait_ended(client: DaemonClient, run_id: str, timeout: float = 60) -> dict[str, Any]:
    return wait_until(
        lambda: (s := client.call("run.status", {"run_id": run_id}))["state"] == "ended" and s,
        timeout=timeout,
        interval=0.1,
    )


def test_late_subscriber_gets_backfill_from_after_seq(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, pass_graph())
    with rig.daemon() as d, d.client() as client:
        started = client.call("run.start", {"path": TEST})
        status = wait_ended(client, started["run_id"])
        # 끝난 뒤 처음 붙은 연결: after_seq 3 다음부터 끝까지, 그다음 run.ended
        with d.client() as late:
            late.call("run.subscribe", {"run_id": started["run_id"], "after_seq": 3})
            log = EventLog(late, started["run_id"], base=3).until_ended()
        events = file_events(started["run_dir"])
        assert log.events == events[3:]
        assert log.ended is not None and log.ended["last_seq"] == status["last_seq"]


def test_reconnect_resume_no_gap_no_dup(tmp_path: Path) -> None:
    signal = tmp_path / "open"
    rig = RunRig.make(tmp_path, gate_graph(signal))
    with rig.daemon() as d:
        with d.client() as first:
            started, log1 = start_and_subscribe(first)
            log1.until_event(gate_logged)
        # 끊고(실행은 계속) 마지막으로 적용한 seq로 다시 구독한다
        applied = log1.last
        assert d.daemon.runs.active_run() == started["run_id"]
        with d.client() as second:
            second.call("run.subscribe", {"run_id": started["run_id"], "after_seq": applied})
            log2 = EventLog(second, started["run_id"], base=applied)
            signal.touch()
            log2.until_ended()
        combined = log1.seqs + log2.seqs
        events = file_events(started["run_dir"])
        assert combined == [e["seq"] for e in events] == list(range(1, len(events) + 1))
        assert log2.ended is not None and log2.ended["outcome"]["verdict"] == "pass"


def test_live_events_during_backfill_held_then_merged(tmp_path: Path) -> None:
    signal = tmp_path / "open"
    rig = RunRig.make(tmp_path, gate_graph(signal))
    with rig.daemon() as d, d.client() as client:
        manager = d.daemon.run_manager
        started = client.call("run.start", {"path": TEST})
        run_id, run_dir = started["run_id"], Path(started["run_dir"])
        wait_until(lambda: any(gate_logged(e) for e in file_events(run_dir)))
        seen: dict[str, int] = {}

        def hold_during_backfill(hooked: str, hwm: int) -> None:
            # 따라잡기가 과거분을 다 보낸 순간: 실행을 끝까지 진행시키고, 따라 읽기 스레드가 그
            # 이벤트를 전부 이 구독의 보류 목록에 넣을 때까지 전환을 붙잡는다
            assert hooked == run_id
            seen["hwm"] = hwm
            signal.touch()
            run = manager._runs[run_id]  # pyright: ignore[reportPrivateUsage]

            def all_pending() -> bool:
                view = read_run(run_dir)
                return view.run_end is not None and run.last_seq == view.last_seq

            wait_until(all_pending, timeout=60)
            seen["pending"] = sum(len(s.pending) for s in run.subs)
            seen["last"] = run.last_seq

        manager.catchup_hook = hold_during_backfill
        client.call("run.subscribe", {"run_id": run_id, "after_seq": 0})
        log = EventLog(client, run_id).until_ended()
        events = file_events(run_dir)
        assert log.events == events
        assert log.seqs == list(range(1, len(events) + 1))
        # 과거분 뒤에 실시간 이벤트가 보류됐다가 빈틈·중복 없이 합쳐졌다
        assert 0 < seen["hwm"] < seen["last"]
        assert seen["pending"] == seen["last"] - seen["hwm"]


# ---------------------------------------------------------------- 역압


class SlowReader:
    """소켓을 읽지 않고 버틸 수 있는 원시 연결 (받은 프레임은 1개만 버퍼에 둔다)."""

    def __init__(self, d: ThreadDaemon) -> None:
        self.ws = connect(
            f"ws://127.0.0.1:{d.port}",
            proxy=None,
            compression=None,
            legacy=True,
            max_queue=1,
            max_size=None,
        )
        self.ids = iter(range(1, 1_000_000))
        token = d.session.token
        self.call("session.hello", {"token": token, "protocol": 1, "client": dict(UI_CLIENT)})

    def send(self, method: str, params: dict[str, Any]) -> int:
        request_id = next(self.ids)
        message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        self.ws.send(json.dumps(message))
        return request_id

    def recv(self, timeout: float = 30) -> dict[str, Any]:
        return json.loads(self.ws.recv(timeout))

    def call(self, method: str, params: dict[str, Any]) -> Any:
        request_id = self.send(method, params)
        while True:
            message = self.recv()
            if message.get("id") == request_id:
                assert "result" in message, message
                return message["result"]

    def close(self) -> None:
        self.ws.close()


def test_queue_full_with_unsent_events_resubscribe_from_applied_seq(tmp_path: Path) -> None:
    signal = tmp_path / "open"
    rig = RunRig.make(tmp_path, loop_graph(600, "가" * 3000, signal))
    limits = Limits(queue_messages=64, queue_bytes=512 * 1024)
    with rig.daemon(limits=limits) as d:
        manager = d.daemon.run_manager
        reader = SlowReader(d)
        try:
            started = reader.call("run.start", {"path": TEST})
            run_id = started["run_id"]
            reader.send("run.subscribe", {"run_id": run_id, "after_seq": 0})
            # 읽지 않는 동안 송신 큐가 차서 구독이 끊긴다 (큐에 넣었지만 못 보낸 이벤트를 버림)
            wait_until(lambda: any(r.run_id == run_id for r in manager.lags), timeout=90)
            lag = next(r for r in manager.lags if r.run_id == run_id)
            signal.touch()
            applied: list[int] = []
            ended: dict[str, Any] | None = None
            applied_at_lag: list[int] = []
            while ended is None:
                message = reader.recv(60)
                method = message.get("method")
                params = message.get("params", {})
                if method == "run.event":
                    seq = params["seq"]
                    last = applied[-1] if applied else 0
                    if seq <= last:
                        continue  # 역행·중복은 버린다
                    assert seq == last + 1, f"빈틈: {last} 다음 {seq}"
                    applied.append(seq)
                elif method == "run.lagged":
                    # 커서 = 자기가 적용한 마지막 seq (daemon의 hwm이 아니다)
                    cursor = applied[-1] if applied else 0
                    applied_at_lag.append(cursor)
                    reader.send("run.subscribe", {"run_id": run_id, "after_seq": cursor})
                elif method == "run.ended":
                    ended = params
        finally:
            reader.close()
    events = file_events(started["run_dir"])
    assert applied == [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert ended["last_seq"] == len(events) and ended["outcome"]["verdict"] == "pass"
    assert applied_at_lag, "run.lagged를 받지 못했다"
    # 끊길 때 daemon은 클라이언트가 적용한 것보다 더 많이 큐에 넣었다 (못 보낸 이벤트가 있었다)
    assert lag.hwm > applied_at_lag[0]


def force_lag(conn: Any, run_id: str) -> None:
    """송신 큐가 넘친 것과 같은 처리 (`Connection.queue_notification`의 "lagged" 경로)."""
    conn.outbox.lagged.add(run_id)
    for listener in list(conn.lag_listeners):
        listener(run_id)
    marker = {"jsonrpc": "2.0", "method": "run.lagged", "params": {"run_id": run_id}}
    assert conn.outbox.put_marker(json.dumps(marker), run_id) == "queued"


def test_lagged_then_resubscribe_complete(tmp_path: Path) -> None:
    signal = tmp_path / "open"
    rig = RunRig.make(tmp_path, gate_graph(signal))
    with rig.daemon() as d, d.client() as client:
        started, log = start_and_subscribe(client)
        log.strict = False
        log.until_event(gate_logged)
        (conn,) = d.daemon.transport.connections
        d.call_in_loop(force_lag, conn, started["run_id"])
        log.pump(lambda log: log.lagged == 1)
        client.call("run.subscribe", {"run_id": started["run_id"], "after_seq": log.last})
        signal.touch()
        log.until_ended()
        events = file_events(started["run_dir"])
        assert log.seqs == [e["seq"] for e in events]


# ---------------------------------------------------------------- 종료 뒤 감독자 이벤트


def hold_graph() -> GraphBuilder:
    return (
        GraphBuilder()
        .entry("n_key")
        .node(
            "n_key",
            "core.input.key",
            inputs={"keys": "ctrl", "hold_ms": 60_000},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


def test_input_recovered_after_run_end_delivered_before_ended(
    tmp_path: Path, spawned: Spawned
) -> None:
    # ctrl을 누른 채 유지하는 중에 취소 → 노드는 취소로 끝나지만 액터가 ctrl을 떼다(before_up)
    # 멈춘다 → runner는 run.end를 쓰고, 액터가 멈추지 않아 임대권을 놓지 못한 채 끝난다 →
    # daemon(감독자) 복구가 run.end 뒤에 input.recovered를 더한다. 그 복구를 장벽으로 늦춘다
    # (daemon 프로세스의 고장 주입)
    gate = barrier(tmp_path / "barriers" / "input_recovery")
    rules = [
        {"point": "recovery.before_input_recovery", "role": "supervisor", "action": gate.action}
    ]
    rig = RunRig.make(
        tmp_path,
        hold_graph(),
        hooks={"before_up": {"ctrl": "hang"}},
        faults=rules,
        # runner가 run.end를 쓰는 시점(액터 정지 기다림 4초)이 감독자 하드 종료(8초)보다 먼저다
        run={"shutdown_grace_ms": 8_000, "worker_cancel_grace_ms": 500},
    )
    proc = DaemonProcess.start(spawned, rig.root, tmp_path / "d", *rig.daemon_args(), env=rig.env)
    assert proc.first_line()["status"] == "started", proc.output()
    info = read_session(rig.root)
    assert info is not None
    with DaemonClient.from_session(info) as client:
        started, log = start_and_subscribe(client)
        log.until_event(lambda e: e["event"] == "input.down")
        client.call("run.cancel", {"run_id": started["run_id"]})
        gate.wait_ready(60)
        run_end = log.until_event(lambda e: e["event"] == "run.end")
        assert run_end["finalized_by"] == "runner"
        # 감독자 마무리가 끝나지 않았다: run.ended는 아직 없다
        log.quiet(1.0)
        assert log.ended is None
        gate.go()
        log.until_ended()
        kinds = log.kinds()
        assert kinds[-1] == "input.recovered" and kinds.index("run.end") < len(kinds) - 1
        recovered = log.events[-1]
        assert recovered["by"] == {"kind": "supervisor"}
        assert recovered["inputs"] == [{"device": "keyboard", "key": "ctrl"}]
        assert log.ended is not None and log.ended["last_seq"] == recovered["seq"]
        assert log.ended["outcome"] == {
            "verdict": "error",
            "exit_code": 2,
            "finalized_by": "runner",
        }
        assert log.events == file_events(started["run_dir"])
        assert client.call("daemon.shutdown", {}) == {}
    assert proc.wait(30) == 0, proc.output()


# ---------------------------------------------------------------- 사전 검증·runner 검증


def test_prevalidation_failed_has_diagnostics_no_run_folder(tmp_path: Path) -> None:
    graph = GraphBuilder().entry("n").node("n", "core.no_such_node")
    rig = RunRig.make(tmp_path, graph)
    with rig.daemon() as d, d.client() as client:
        with pytest.raises(DaemonError) as caught:
            client.call("run.start", {"path": TEST})
        assert caught.value.kind == "validation_failed"
        codes = [x["code"] for x in caught.value.data["diagnostics"]]
        assert "unknown_node_type" in codes
        assert d.daemon.runs.active_run() is None
        assert client.call("run.list", {})["runs"] == []
    assert not (rig.root / "runs").exists() or not list((rig.root / "runs").iterdir())


def after_hello_rig(tmp_path: Path) -> tuple[RunRig, Any]:
    gate = barrier(tmp_path / "barriers" / "after_hello")
    rules = [{"point": "runner.after_hello", "role": "runner", "action": gate.action}]
    return RunRig.make(tmp_path, pass_graph(), faults=rules), gate


def break_graph(rig: RunRig) -> None:
    GraphBuilder().entry("n").node("n", "core.no_such_node").write(rig.root, TEST)


def test_file_changed_after_prevalidation_runner_validation_error_recorded(
    tmp_path: Path,
) -> None:
    rig, gate = after_hello_rig(tmp_path)
    with rig.daemon() as d, d.client() as client:
        # 사전 검증은 통과하고 runner가 스냅샷 전 장벽에 섰다: run.start는 이미 성공이다
        started, log = start_and_subscribe(client)
        gate.wait_ready()
        break_graph(rig)
        gate.go()
        log.until_ended()
    ended = log.ended
    assert ended is not None
    assert ended["outcome"] == {"verdict": "error", "exit_code": 4, "finalized_by": "runner"}
    run_dir = Path(started["run_dir"])
    assert run_dir.is_dir()
    view = read_run(run_dir)
    assert view.run_end is not None and view.run_end["code"] == "graph_invalid"
    run_json = read_run_json(run_dir / "run.json")
    assert run_json is not None
    assert any(x["code"] == "unknown_node_type" for x in run_json["diagnostics"])


def test_runner_start_validation_error_visible_in_status(tmp_path: Path) -> None:
    # 구독하지 않은 연결도 run.status·run.list로 runner의 시작 검증 오류를 본다
    rig, gate = after_hello_rig(tmp_path)
    with rig.daemon() as d, d.client() as client:
        started = client.call("run.start", {"path": TEST})
        gate.wait_ready()
        running = client.call("run.status", {"run_id": started["run_id"]})
        assert running["state"] == "running" and running["outcome"] is None
        break_graph(rig)
        gate.go()
        status = wait_ended(client, started["run_id"])
        assert status["outcome"] == {"verdict": "error", "exit_code": 4, "finalized_by": "runner"}
        (listed,) = client.call("run.list", {"limit": 5})["runs"]
        # run.status = 목록 요약 + 스냅샷 호출 관계(calls, M2 T11). M3 목록 요약은 run.json의
        # 결과·배지 필드를 더 싣는다 (M3 계획 2.7)
        assert {k: listed[k] for k in status if k != "calls"} == {
            k: v for k, v in status.items() if k != "calls"
        }
        assert listed["code"] == "graph_invalid"


# ---------------------------------------------------------------- 동시 시작·중복 방지 키


def allow_agent_runs(rig: RunRig, toolset: str = "allow") -> None:
    path = rig.root / ".kookabug" / "local.json"
    path.parent.mkdir(exist_ok=True)
    body = {"format": "kookabug.local/0", "permissions": {"toolsets": {"run": toolset}}}
    path.write_text(json.dumps(body), encoding="utf-8")


def run_folders(rig: RunRig) -> list[Path]:
    runs = rig.root / "runs"
    return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() else []


def test_concurrent_starts_one_run_folder_one_runner(tmp_path: Path) -> None:
    signal = tmp_path / "open"
    rig = RunRig.make(tmp_path, gate_graph(signal))
    with rig.daemon() as d:
        manager = d.daemon.run_manager
        entered: list[str] = []
        both_inside = threading.Event()
        original_start = manager.start
        original_registry = manager._registry  # pyright: ignore[reportPrivateUsage]

        def start(request: Any) -> dict[str, Any]:
            entered.append(threading.current_thread().name)
            if len(entered) == 2:
                both_inside.set()
            return original_start(request)

        def registry() -> Any:
            # 먼저 잠금을 얻은 요청은 사전 검증에서 다른 요청이 시작 순서에 들어올 때까지 선다.
            # 두 번째 요청이 지금 잠금 앞이든 그 직전이든, 잠금이 풀린 뒤에야 ③을 본다
            assert both_inside.wait(30)
            return original_registry()

        manager.start = start  # type: ignore[method-assign]
        manager._registry = registry  # pyright: ignore[reportPrivateUsage]
        with d.client() as a, d.client() as b:
            futures = [
                a.request("run.start", {"path": TEST}),
                b.request("run.start", {"path": TEST}),
            ]
            outcomes: list[Any] = []
            for future in futures:
                try:
                    outcomes.append(future.result(60))
                except DaemonError as exc:
                    outcomes.append(exc)
            started = [o for o in outcomes if isinstance(o, dict)]
            refused = [o for o in outcomes if isinstance(o, DaemonError)]
            assert len(started) == 1 and len(refused) == 1, outcomes
            assert refused[0].kind == "run_busy"
            assert refused[0].data["run_id"] == started[0]["run_id"]
            folders = run_folders(rig)
            assert [f.name.rsplit("_", 1)[-1] for f in folders] == [started[0]["run_id"]]
            # runner는 하나: 그 실행의 run.start 하나뿐이고 다른 실행 폴더가 없다
            starts = [e for e in file_events(folders[0]) if e["event"] == "run.start"]
            assert len(starts) == 1
            signal.touch()
            wait_ended(a, started[0]["run_id"])
            assert run_folders(rig) == folders


def test_idempotency_same_principal_same_args_same_run(tmp_path: Path) -> None:
    signal = tmp_path / "open"
    rig = RunRig.make(tmp_path, gate_graph(signal))
    allow_agent_runs(rig)
    with rig.daemon() as d, d.client(AGENT) as first, d.client(AGENT) as second:
        params = {"path": TEST, "idempotency_key": "k1", "settings": {"a": 1}}
        one = first.call("run.start", params)
        # 같은 주체(다른 연결)·같은 키·같은 인자: 실행 중이어도 run_busy가 아니라 같은 실행
        again = second.call("run.start", dict(params))
        assert again == one
        assert len(run_folders(rig)) == 1
        signal.touch()
        wait_ended(first, one["run_id"])
        # 끝난 뒤에도 기한(10분) 안에서는 같은 실행을 돌려준다
        assert first.call("run.start", dict(params)) == one
        assert len(run_folders(rig)) == 1


def test_idempotency_same_key_different_args_conflict(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, pass_graph())
    with rig.daemon() as d, d.client() as client:
        one = client.call("run.start", {"path": TEST, "idempotency_key": "k1"})
        wait_ended(client, one["run_id"])
        with pytest.raises(DaemonError) as caught:
            client.call("run.start", {"path": TEST, "idempotency_key": "k1", "profile": "x"})
        assert caught.value.kind == "idempotency_conflict"
        assert caught.value.data["run_id"] == one["run_id"]
        assert len(run_folders(rig)) == 1


def test_idempotency_not_shared_across_principals(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, pass_graph())
    allow_agent_runs(rig)
    with rig.daemon() as d, d.client() as ui, d.client(AGENT) as agent:
        one = ui.call("run.start", {"path": TEST, "idempotency_key": "k1"})
        wait_ended(ui, one["run_id"])
        # 다른 주체의 같은 키는 앞 실행을 공유하지 않는다: 새 실행
        two = agent.call("run.start", {"path": TEST, "idempotency_key": "k1"})
        assert two["run_id"] != one["run_id"]
        wait_ended(agent, two["run_id"])
        # UI 연결마다 주체가 다르다 (ui:<연결 번호>)
        with d.client() as other_ui:
            three = other_ui.call("run.start", {"path": TEST, "idempotency_key": "k1"})
            assert three["run_id"] not in (one["run_id"], two["run_id"])
            wait_ended(other_ui, three["run_id"])
        assert len(run_folders(rig)) == 3


def test_idempotency_reuse_rechecks_permission_after_policy_change(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, pass_graph())
    allow_agent_runs(rig)
    with rig.daemon() as d, d.client(AGENT) as agent:
        params = {"path": TEST, "idempotency_key": "k1"}
        one = agent.call("run.start", params)
        wait_ended(agent, one["run_id"])
        allow_agent_runs(rig, "deny")
        with pytest.raises(DaemonError) as caught:
            agent.call("run.start", dict(params))
        assert caught.value.kind == "permission_denied"
        assert caught.value.data["decision"]["final"] == "deny"
        assert len(run_folders(rig)) == 1


# ---------------------------------------------------------------- 실행 중·취소·끊김


def test_run_busy_second_start(tmp_path: Path) -> None:
    signal = tmp_path / "open"
    rig = RunRig.make(tmp_path, gate_graph(signal))
    with rig.daemon() as d, d.client() as client:
        one = client.call("run.start", {"path": TEST})
        with pytest.raises(DaemonError) as caught:
            client.call("run.start", {"path": TEST})
        assert caught.value.kind == "run_busy" and caught.value.data["run_id"] == one["run_id"]
        listed = client.call("run.list", {})["runs"]
        assert [(r["run_id"], r["state"]) for r in listed] == [(one["run_id"], "running")]
        signal.touch()
        wait_ended(client, one["run_id"])
        # 끝나면 다시 시작할 수 있다
        two = client.call("run.start", {"path": TEST})
        assert two["run_id"] != one["run_id"]
        signal.unlink()
        signal.touch()
        wait_ended(client, two["run_id"])


def block_graph() -> GraphBuilder:
    return (
        tk()
        .entry("n_block")
        .node("n_block", "testkit.block", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def blocking(event: Any) -> bool:
    return event.get("event") == "log" and event.get("message") == "blocking"


def test_cancel_reaches_runner_and_ended_cancelled(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, block_graph())
    with rig.daemon() as d, d.client() as client:
        started, log = start_and_subscribe(client)
        log.until_event(blocking)
        assert client.call("run.cancel", {"run_id": started["run_id"]}) == {}
        log.until_ended()
        assert d.daemon.runs.active_run() is None
    view = read_run(started["run_dir"])
    run_end = view.run_end
    assert run_end is not None
    assert (run_end["finalized_by"], run_end["cancel_reason"]) == ("runner", "cancelled")
    (requested,) = [e for e in view.events if e["event"] == "cancel.requested"]
    assert requested["reason"] == "cancelled"
    assert log.ended is not None
    assert log.ended["outcome"] == {"verdict": "error", "exit_code": 2, "finalized_by": "runner"}


def test_ui_disconnect_run_continues(tmp_path: Path) -> None:
    signal = tmp_path / "open"
    rig = RunRig.make(tmp_path, gate_graph(signal))
    with rig.daemon() as d:
        with d.client() as first:
            started, log = start_and_subscribe(first)
            log.until_event(gate_logged)
        # UI가 끊겨도 실행은 그대로다 (끊긴 뒤에도 run.end가 없고 실행 중이다)
        wait_until(lambda: d.daemon.transport.count() == 0)
        assert d.daemon.runs.active_run() == started["run_id"]
        assert read_run(started["run_dir"]).run_end is None
        signal.touch()
        with d.client() as second:
            second.call("run.subscribe", {"run_id": started["run_id"], "after_seq": 0})
            log2 = EventLog(second, started["run_id"]).until_ended()
        assert log2.ended is not None and log2.ended["outcome"]["verdict"] == "pass"
        assert log2.events == file_events(started["run_dir"])


# ---------------------------------------------------------------- 시작 예약과 수명 (검수 T5-1 High)


class Gate:
    """막히는 호출 하나를 장벽에 세운다: `entered`로 도착을 알고 `release`까지 기다린다."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def hold(self) -> None:
        self.entered.set()
        assert self.release.wait(60), "장벽이 풀리지 않았다"


def hold_launch(d: ThreadDaemon) -> Gate:
    """⑤ 시작(`start_decided`)에 장벽: 시작 예약(③)이 끝난 상태에서 선다."""
    gate = Gate()
    service = d.daemon.service
    original = service.start_decided

    def blocked(*args: Any, **kwargs: Any) -> Any:
        gate.hold()
        return original(*args, **kwargs)

    service.start_decided = blocked  # type: ignore[method-assign]
    return gate


def hold_judgment(d: ThreadDaemon) -> Gate:
    """② 권한 판정(`kb_run_start`)에 장벽: 시작 예약 전 시작 잠금 안에서 선다."""
    gate = Gate()
    service = d.daemon.service
    original = service.require

    def blocked(principal: Any, tool: str, arg: str = "", **kwargs: Any) -> Any:
        if tool == "kb_run_start":
            gate.hold()
        return original(principal, tool, arg, **kwargs)

    service.require = blocked  # type: ignore[method-assign]
    return gate


def test_nonforce_shutdown_refused_while_starting(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, pass_graph())
    with rig.daemon() as d, d.client() as first, d.client() as second:
        gate = hold_launch(d)
        pending = first.request("run.start", {"path": TEST})
        assert gate.entered.wait(30)
        try:
            reserved = d.daemon.runs.active_run()
            assert reserved is not None  # 시작 예약이 수명 판단에 보인다
            with pytest.raises(DaemonError) as caught:
                second.call("daemon.shutdown", {})
            assert caught.value.kind == "run_active"
            assert caught.value.data["run_id"] == reserved
            assert d.is_running()
        finally:
            gate.release.set()
        started = pending.result(60)
        assert started["run_id"] == reserved  # 예약한 ID로 시작했다
        wait_ended(first, started["run_id"])
        assert second.call("daemon.shutdown", {}) == {}
        assert d.finished(30) == "daemon.shutdown"


def test_shutdown_decided_refuses_waiting_start(tmp_path: Path) -> None:
    # 시작 요청이 예약 전(②)에 서 있는 동안 일반 종료가 정해진다 → 그 요청은 runner를 만들지 못한다
    rig = RunRig.make(tmp_path, pass_graph())
    with rig.daemon() as d, d.client() as first, d.client() as second:
        gate = hold_judgment(d)
        pending = first.request("run.start", {"path": TEST})
        assert gate.entered.wait(30)
        assert d.daemon.runs.active_run() is None
        assert second.call("daemon.shutdown", {}) == {}
        gate.release.set()
        try:
            pending.result(30)
            raise AssertionError("시작이 성공하면 안 된다")
        except DaemonError as exc:
            assert exc.kind == "shutting_down"
        except Exception:
            pass  # 응답 전에 연결이 닫혔다 (종료 중)
        assert d.finished(30) == "daemon.shutdown"
    assert run_folders(rig) == []


def test_idle_shutdown_waits_for_reserved_start(tmp_path: Path) -> None:
    # 시작 예약 뒤 연결이 끊겨도 유휴가 아니다: 실행이 끝난 뒤에 유휴 종료한다
    rig = RunRig.make(tmp_path, pass_graph())
    with rig.daemon(idle_timeout_s=0.5) as d:
        gate = hold_launch(d)
        client = d.client()
        client.request("run.start", {"path": TEST})
        assert gate.entered.wait(30)
        client.close()
        wait_until(lambda: d.daemon.transport.count() == 0)
        # 유휴 기한(0.5초)의 몇 배를 지나도 끝나지 않는다 (오지 않아야 하는 종료라 기다림의 끝은
        # 시간이다)
        assert not gate.release.wait(2.0)
        assert d.is_running()
        gate.release.set()
        assert d.finished(60) == "유휴 0.5초"
    (folder,) = run_folders(rig)
    view = read_run(folder)
    assert view.run_end is not None and view.run_end["verdict"] == "pass"


def test_idle_shutdown_refuses_waiting_start(tmp_path: Path) -> None:
    # 예약 전(②)에 선 시작 요청의 연결이 끊긴 뒤 유휴 종료가 정해진다 → 그 요청은 runner를 못 만든다
    rig = RunRig.make(tmp_path, pass_graph())
    with rig.daemon(idle_timeout_s=0.5) as d:
        gate = hold_judgment(d)
        client = d.client()
        client.request("run.start", {"path": TEST})
        assert gate.entered.wait(30)
        client.close()
        # 유휴 종료가 정해진 뒤에 판정을 풀어 준다 (daemon은 끝나기 전에 진행 중인 시작을 기다린다)
        wait_until(lambda: d.daemon.run_manager._closing, timeout=30)  # pyright: ignore[reportPrivateUsage]
        gate.release.set()
        assert d.finished(30) == "유휴 0.5초"
    assert run_folders(rig) == []


def test_close_during_start_cancels_started_run(tmp_path: Path) -> None:
    # daemon이 끝날 때 진행 중이던 시작을 빠뜨리지 않는다: 시작이 끝나면 그 실행을 취소한다
    rig = RunRig.make(tmp_path, block_graph())
    with rig.daemon() as d:
        manager = d.daemon.run_manager
        gate = hold_launch(d)
        client = d.client()
        client.request("run.start", {"path": TEST})
        assert gate.entered.wait(30)
        d.daemon.stop("test")
        wait_until(lambda: manager._closing)  # pyright: ignore[reportPrivateUsage]
        gate.release.set()
        assert d.finished(60) == "test"
        client.close()
    (folder,) = run_folders(rig)
    run_end = read_run(folder).run_end
    assert run_end is not None and run_end["cancel_reason"] == "cancelled"
    assert manager.active_run() is None


# ---------------------------------------------------------------- 구독 세대 (검수 T5-1 Mid)


@pytest.mark.parametrize("how", ["unsubscribe", "replace"])
def test_closed_finished_subscription_drops_pending_sends(tmp_path: Path, how: str) -> None:
    # 끝난 실행을 구독하면 따라잡기가 이벤트와 run.ended를 루프에 넘기고 구독 목록에서 빠진다.
    # 그 송신이 루프에서 실행되기 전에 해제(또는 다시 구독)하면 옛 구독의 송신은 버려진다
    rig = RunRig.make(tmp_path, pass_graph())
    with rig.daemon() as d, d.client() as client:
        started = client.call("run.start", {"path": TEST})
        manager = d.daemon.run_manager
        run_id = started["run_id"]
        run = manager._runs[run_id]  # pyright: ignore[reportPrivateUsage]
        assert run.finished.wait(30)
        (connection,) = d.daemon.transport.connections

        def generations_before_delivery() -> None:
            # 루프를 붙잡은 채(넘긴 송신이 실행되지 않음) 구독 → 따라잡기 끝 → 해제·교체
            manager.subscribe(connection.number, run_id, 0)
            wait_until(lambda: not run.subs, timeout=10)
            if how == "unsubscribe":
                manager.unsubscribe(connection.number, run_id)
            manager.subscribe(connection.number, run_id, 0)
            wait_until(lambda: not run.subs, timeout=10)

        d.call_in_loop(generations_before_delivery)
        log = EventLog(client, run_id).until_ended()
        log.quiet(1.0)  # 옛 세대의 이벤트·run.ended가 뒤늦게 오지 않는다
        assert log.seqs == list(range(1, run.last_seq + 1))
        assert log.ended is not None and log.ended["last_seq"] == run.last_seq


def test_lagged_closes_subscription_whose_end_is_pending(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, pass_graph())
    with rig.daemon() as d, d.client() as client:
        started = client.call("run.start", {"path": TEST})
        manager = d.daemon.run_manager
        run_id = started["run_id"]
        run = manager._runs[run_id]  # pyright: ignore[reportPrivateUsage]
        assert run.finished.wait(30)
        (connection,) = d.daemon.transport.connections

        def lag_before_delivery() -> None:
            manager.subscribe(connection.number, run_id, 0)
            wait_until(lambda: not run.subs, timeout=10)
            force_lag(connection, run_id)

        d.call_in_loop(lag_before_delivery)
        log = EventLog(client, run_id)
        log.pump(lambda log: log.lagged == 1)
        log.quiet(1.0)
        assert log.events == [] and log.ended is None  # 넘겼던 송신이 모두 버려졌다
        client.call("run.subscribe", {"run_id": run_id, "after_seq": 0})
        log.until_ended()
        assert log.seqs == list(range(1, run.last_seq + 1))


def test_status_and_subscribe_unknown_run(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, pass_graph())
    with rig.daemon() as d, d.client() as client:
        for method, params in [
            ("run.status", {"run_id": "zzzz0000"}),
            ("run.subscribe", {"run_id": "zzzz0000", "after_seq": 0}),
            ("run.cancel", {"run_id": "zzzz0000"}),
        ]:
            with pytest.raises(DaemonError) as caught:
                client.call(method, params)
            assert caught.value.kind == "run_not_found", method
        assert client.call("run.unsubscribe", {"run_id": "zzzz0000"}) == {}


def test_start_params_reach_runner(tmp_path: Path) -> None:
    # deadline_ms·settings·profile은 실행 조건으로, 플랫폼은 daemon의 가짜 플랫폼으로
    rig = RunRig.make(tmp_path, pass_graph())
    with rig.daemon() as d, d.client() as client:
        params = {"path": TEST, "deadline_ms": 45_000, "settings": {"k": "v"}, "profile": None}
        started = client.call("run.start", params)
        wait_ended(client, started["run_id"])
    run_json = read_run_json(Path(started["run_dir"]) / "run.json")
    assert run_json is not None
    conditions = run_json["conditions"]
    assert (conditions["deadline_ms"], conditions["platform"]) == (45_000, "fake")
    assert conditions["profile"] is None
