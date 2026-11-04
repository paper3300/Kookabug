"""녹화 중 실행 거부와 녹화 시작 예약 (M4 계획 2.3 검수 M9·C30).

녹화 시작 예약(`RunManager.reserve_recording`)과 `run.start`가 같은 시작 잠금 안에서 판정한다.
녹화가 `starting`·`recording`·`paused`인 동안 `run.start`는 runner를 띄우기 전에(실행 폴더 없이)
`recording_active`로 거부되고, 진행 중인 실행이 있으면 녹화 예약이 `run_active`로 거부된다.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from helpers.daemon_runs import TEST, RunRig
from helpers.graphs import GraphBuilder
from helpers.run import tk

from kb_testing.proc import wait_until
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.runs import RecordingReservation, RunManager

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]


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
        .entry("n_gate")
        .node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def run_folders(rig: RunRig) -> list[Path]:
    runs = rig.root / "runs"
    return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() else []


def wait_ended(client: DaemonClient, run_id: str, timeout: float = 60) -> dict[str, Any]:
    return wait_until(
        lambda: (s := client.call("run.status", {"run_id": run_id}))["state"] == "ended" and s,
        timeout=timeout,
        interval=0.05,
    )


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params)
    return caught.value


def test_run_start_rejected_before_spawn_while_recording(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, pass_graph())
    with rig.daemon() as d, d.client() as client:
        manager: RunManager = d.daemon.run_manager
        reservation = manager.reserve_recording()
        for state in ("recording", "paused"):
            reservation.set_state(state)
            error = refused(client, "run.start", {"path": TEST})
            assert (error.kind, error.data["state"]) == ("recording_active", state)
        # runner를 띄우기 전에 거부했다: 실행 폴더·목록에 아무것도 없다
        assert run_folders(rig) == []
        assert client.call("run.list", {})["runs"] == []
        assert manager.active_run() is None
        # 정지(stopped) = 예약을 푼 뒤에는 실행할 수 있다
        reservation.release()
        reservation.release()  # 여러 번 불러도 된다
        assert manager.recording_state() is None and reservation.state is None
        with pytest.raises(RuntimeError):
            reservation.set_state("recording")
        started = client.call("run.start", {"path": TEST})
        assert wait_ended(client, started["run_id"])["outcome"]["verdict"] == "pass"


def test_run_start_rejected_while_starting(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, pass_graph())
    with rig.daemon() as d, d.client() as client:
        manager: RunManager = d.daemon.run_manager
        # UI 실행 하나를 끝내 두고(다시 시작 대상)
        first = client.call("run.start", {"path": TEST})
        wait_ended(client, first["run_id"])
        reservation = manager.reserve_recording()
        assert reservation.state == "starting" and reservation.active
        error = refused(client, "run.start", {"path": TEST})
        assert (error.kind, error.data["state"]) == ("recording_active", "starting")
        # 다시 시작도 같은 자리에서 거부된다
        error = refused(client, "run.restart", {"run_id": first["run_id"]})
        assert (error.kind, error.data["state"]) == ("recording_active", "starting")
        assert len(run_folders(rig)) == 1
        # 녹화 예약은 하나뿐이다
        with pytest.raises(RequestFailed) as caught:
            manager.reserve_recording()
        assert caught.value.code == "recording_active"
        assert caught.value.fields == {"state": "starting"}
        reservation.release()


def test_reserve_rejected_while_run_active(tmp_path: Path) -> None:
    signal = tmp_path / "open"
    rig = RunRig.make(tmp_path, gate_graph(signal))
    with rig.daemon() as d, d.client() as client:
        manager: RunManager = d.daemon.run_manager
        started = client.call("run.start", {"path": TEST})
        with pytest.raises(RequestFailed) as caught:
            manager.reserve_recording()
        assert caught.value.code == "run_active"
        assert caught.value.fields == {"run_id": started["run_id"]}
        assert manager.recording_state() is None
        signal.touch()
        wait_ended(client, started["run_id"])
        reservation = manager.reserve_recording()
        assert manager.recording_state() == "starting"
        reservation.release()


def invalid_graph() -> GraphBuilder:
    """사전 검증(시작 잠금 안 ④)에서 걸리는 그래프 — runner 없이 시작 순서를 끝까지 돈다."""
    return GraphBuilder().entry("n_bad").node("n_bad", "core.no_such.node")


def race(
    manager: RunManager,
    client: DaemonClient,
    *,
    mode: str = "free",
    inside_start: threading.Event | None = None,
) -> tuple[RecordingReservation | RequestFailed, dict[str, Any] | DaemonError]:
    """녹화 예약과 `run.start`를 함께 보낸다. `mode`: free(동시에 출발, 순서는 스케줄러 몫),
    run_first(실행이 시작 순서 ④에 들어간 순간 녹화 예약을 보냄 — 잠금 앞에서 기다려야 한다),
    recording_first(녹화 예약을 잡은 뒤 실행을 보냄)."""
    go = threading.Barrier(2)
    reserved: list[RecordingReservation | RequestFailed] = []

    def reserve() -> None:
        go.wait()
        if mode == "run_first":
            assert inside_start is not None and inside_start.wait(30)
        try:
            reserved.append(manager.reserve_recording())
        except RequestFailed as exc:
            reserved.append(exc)

    thread = threading.Thread(target=reserve)
    thread.start()
    go.wait()
    if mode == "recording_first":
        thread.join(60)
    future = client.request("run.start", {"path": TEST})
    outcome: dict[str, Any] | DaemonError
    try:
        outcome = future.result(60)
    except DaemonError as exc:
        outcome = exc
    thread.join(60)
    return reserved[0], outcome


def test_reserve_vs_run_start_race_one_wins(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, invalid_graph())
    with rig.daemon() as d, d.client() as client:
        manager: RunManager = d.daemon.run_manager
        original = manager._registry  # pyright: ignore[reportPrivateUsage]
        inside_start = threading.Event()
        overlaps: list[str] = []

        def registry() -> Any:
            # ④ 사전 검증 = 실행 시작 예약을 쥔 구간: 이때 녹화 예약이 있으면 둘이 함께 진행된 것
            inside_start.set()
            if manager.recording_state() is not None:
                overlaps.append("녹화 예약 중에 실행 시작 순서가 ④까지 왔다")
            time.sleep(0.002)
            return original()

        manager._registry = registry  # pyright: ignore[reportPrivateUsage]
        seen: dict[str, int] = {"recording_won": 0, "sequential": 0}
        modes = ("free", "run_first", "free", "recording_first")
        for i in range(100):
            mode = modes[i % len(modes)]
            inside_start.clear()
            reserved, outcome = race(manager, client, mode=mode, inside_start=inside_start)
            assert isinstance(outcome, DaemonError)
            # 검증 실패 실행은 진행 중으로 남지 않으므로 녹화 예약은 결국 잡힌다 (run_active 없음)
            assert isinstance(reserved, RecordingReservation), (mode, reserved)
            if outcome.kind == "recording_active":
                # 녹화가 먼저 잡았다: 실행은 ③에서 거부(④에 들어가지 않음)
                assert outcome.data["state"] == "starting"
                assert not inside_start.is_set()
                assert mode != "run_first"
                seen["recording_won"] += 1
            else:
                # 실행이 먼저 시작 잠금을 잡았다: 녹화 예약은 그 시작 순서가 끝날 때까지(검증
                # 실패로 실행 예약을 푼 뒤) 잠금 앞에서 기다렸다가 잡는다 — 차례대로
                assert outcome.kind == "validation_failed" and inside_start.is_set()
                assert mode != "recording_first"
                seen["sequential"] += 1
            reserved.release()
            assert manager.recording_state() is None and manager.active_run() is None
        # 함께 진행된 적이 없다 (실행 시작 순서 ④에서 녹화 예약을 본 적 없음)
        assert overlaps == []
        # 순서를 정한 반복이 양쪽 차례를 다 지났다
        assert seen["recording_won"] >= 25 and seen["sequential"] >= 25, seen
        assert run_folders(rig) == []


def test_reserve_vs_real_run_start_never_together(tmp_path: Path) -> None:
    # 실제 runner까지 가는 실행으로 몇 번: 이긴 쪽만 진행하고, 실행이 끝날 때까지 녹화는 못 잡는다
    rig = RunRig.make(tmp_path, pass_graph())
    with rig.daemon() as d, d.client() as client:
        manager: RunManager = d.daemon.run_manager
        original = manager._registry  # pyright: ignore[reportPrivateUsage]
        inside_start = threading.Event()

        def registry() -> Any:
            inside_start.set()
            return original()

        manager._registry = registry  # pyright: ignore[reportPrivateUsage]
        modes = ("free", "recording_first", "run_first", "free")
        outcomes: set[str] = set()
        for i in range(8):
            mode = modes[i % len(modes)]
            inside_start.clear()
            reserved, outcome = race(manager, client, mode=mode, inside_start=inside_start)
            if isinstance(reserved, RecordingReservation):
                # 녹화가 이겼다: 실행은 runner 없이 거부
                assert isinstance(outcome, DaemonError) and outcome.kind == "recording_active"
                assert mode != "run_first"
                reserved.release()
                outcomes.add("recording")
            else:
                # 실행이 이겼다: 녹화 예약은 진행 중 실행 때문에 거부되고 실행은 끝까지 간다
                assert isinstance(outcome, dict), outcome
                assert reserved.code == "run_active" and mode != "recording_first"
                assert manager.recording_state() is None
                assert wait_ended(client, outcome["run_id"])["outcome"]["verdict"] == "pass"
                outcomes.add("run")
        assert outcomes == {"recording", "run"}
        # 실행이 이긴 경우에만 실행 폴더가 생겼다
        assert len(run_folders(rig)) >= 2
