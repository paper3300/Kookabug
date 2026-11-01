"""daemon이 감독자인 수명 (M2 계획 2.3·2.8, T5): daemon이 죽으면 runner가 스스로 취소하고 기록을
마무리한다(M0b 규칙 회귀). `run.list`는 CLI 실행도 보여 준다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers.cli import run_cli
from helpers.daemon_runs import TEST, EventLog, RunRig
from helpers.graphs import GraphBuilder
from helpers.run import tk

from kb_testing.daemon import DaemonProcess
from kb_testing.proc import Spawned, wait_until
from kookabug_core.record import read_run, read_run_json
from kookabug_core.runner.run import unix_micros
from kookabug_core.win import ProcessId, identify, is_alive
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.session import read_session

pytestmark = [pytest.mark.process, pytest.mark.timeout(180)]


def runner_of(run_dir: Path) -> ProcessId:
    start = read_run(run_dir).run_start
    assert start is not None
    runner = start["runner"]
    ident = identify(runner["pid"])
    assert ident is not None and unix_micros(ident) == runner["created"]
    return ident


def test_daemon_killed_runner_self_cancels_and_record_finalized(
    tmp_path: Path, spawned: Spawned
) -> None:
    graph = tk().entry("n_block").node("n_block", "testkit.block")
    rig = RunRig.make(tmp_path, graph)
    proc = DaemonProcess.start(spawned, rig.root, tmp_path / "d", *rig.daemon_args(), env=rig.env)
    assert proc.first_line()["status"] == "started", proc.output()
    info = read_session(rig.root)
    assert info is not None
    with DaemonClient.from_session(info) as client:
        started = client.call("run.start", {"path": TEST})
        client.call("run.subscribe", {"run_id": started["run_id"], "after_seq": 0})
        EventLog(client, started["run_id"]).until_event(
            lambda e: e["event"] == "log" and e.get("message") == "blocking"
        )
        run_dir = Path(started["run_dir"])
        runner = runner_of(run_dir)
        proc.proc.kill()  # TerminateProcess: 감독자(daemon)의 Job 핸들도 OS가 닫는다
        proc.wait(30)
    # runner는 감독자 사망을 알고 스스로 취소한 뒤 기록을 마무리한다
    wait_until(lambda: not is_alive(runner), timeout=60)
    view = read_run(run_dir)
    (requested,) = [e for e in view.events if e["event"] == "cancel.requested"]
    assert requested["reason"] == "supervisor_lost"
    run_end = view.run_end
    assert run_end is not None
    assert (run_end["finalized_by"], run_end["cancel_reason"]) == ("runner", "supervisor_lost")
    run_json = read_run_json(run_dir / "run.json")
    assert run_json is not None and run_json["status"] == "finished"
    # 새 daemon이 잠금을 얻고 그 실행을 끝난 실행으로 본다
    with rig.daemon() as d, d.client() as client:
        status = client.call("run.status", {"run_id": started["run_id"]})
        assert status["state"] == "ended"
        assert status["outcome"] == {"verdict": "error", "exit_code": 2, "finalized_by": "runner"}
        assert d.daemon.runs.active_run() is None


def test_run_list_includes_cli_runs(tmp_path: Path) -> None:
    graph = GraphBuilder().entry("n").node("n", "core.test.pass")
    rig = RunRig.make(tmp_path, graph)
    done = run_cli(["run", TEST, "--json"], cwd=rig.root, env=rig.env)
    assert done.returncode == 0, done.stdout + done.stderr
    cli_run = json.loads(done.stdout)
    with rig.daemon() as d, d.client() as client:
        started = client.call("run.start", {"path": TEST})
        wait_until(
            lambda: client.call("run.status", {"run_id": started["run_id"]})["state"] == "ended",
            interval=0.1,
        )
        runs = client.call("run.list", {"limit": 10})["runs"]
        # 최근 실행부터: daemon 실행 → CLI 실행
        assert [r["run_id"] for r in runs] == [started["run_id"], cli_run["run_id"]]
        listed = runs[1]
        # run.status = 목록 요약 + 스냅샷 호출 관계(calls, M2 T11). M3 목록 요약은 run.json의
        # 결과·배지 필드를 더 싣는다 (M3 계획 2.7)
        status = client.call("run.status", {"run_id": cli_run["run_id"]})
        assert {k: listed[k] for k in status if k != "calls"} == {
            k: v for k, v in status.items() if k != "calls"
        }
        assert listed["code"] == "test_pass" and listed["debug_intervened"] is False
        assert (listed["graph"], listed["state"], listed["run_dir"]) == (
            TEST,
            "ended",
            cli_run["run_dir"],
        )
        assert listed["outcome"] == {"verdict": "pass", "exit_code": 0, "finalized_by": "runner"}
        assert listed["last_seq"] == read_run(cli_run["run_dir"]).last_seq
        assert client.call("run.list", {"limit": 1})["runs"] == runs[:1]
        # 이 daemon이 띄우지 않은 실행도 구독(기록 다시 보기)할 수 있다. 취소는 할 수 없다
        client.call("run.subscribe", {"run_id": cli_run["run_id"], "after_seq": 0})
        log = EventLog(client, cli_run["run_id"]).until_ended()
        assert log.events == read_run(cli_run["run_dir"]).events
        assert log.ended is not None and log.ended["outcome"] == listed["outcome"]
        with pytest.raises(DaemonError) as caught:
            client.call("run.cancel", {"run_id": cli_run["run_id"]})
        assert caught.value.kind == "run_not_found"
