"""감독자(하네스) 하드 종료 경로 (구현 계획 M0b 2.6·2.7 "종료 보장").

결과는 모두: runner 종료(코드 4) → 복구 경로가 키 복구(임대권 안, 마지막 물리 동작 up) →
`run.end`(`runner_died`, `cancel_reason`) → `run.json` → Job 안 프로세스 없음. 그리고 복구 경로의
`run.end` 뒤에 runner가 쓴 줄이 없다.

하드 종료 타이머는 감독자의 `cancel()` 또는 runner의 `runner.stopping` 알림(기한 초과·정상 마무리
시작)을 처음 받은 때부터 돈다 (계획 검수 4차 M2: 외부 취소 없이도 같은 규칙).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder
from helpers.run import tk
from helpers.runner import Done, RunnerHarness

from kb_testing.proc import Spawned, assert_no_live, barrier, wait_until
from kookabug_core.inputs import FakeBackend, InputLease, LeaseOwner
from kookabug_core.inputs.lease import LEASE_NAME_ENV, STATE_DIR_ENV
from kookabug_core.record import Journal
from kookabug_core.win import ProcessId, identify
from kookabug_sdk import _faults

pytestmark = pytest.mark.process

FINALIZE_POINTS = (
    "runner.after_run_end",
    "runner.before_run_json_final",
    "runner.before_worker_shutdown",
    "runner.before_lease_release",
)


def key_graph(key: str = "ctrl") -> GraphBuilder:
    return (
        tk()
        .entry("n_key")
        .node("n_key", "testkit.input.hold", inputs={"key": key}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def hung_actor(tmp_path: Path, spawned: Spawned, **kw: Any) -> RunnerHarness:
    """노드가 `ctrl`을 누른 채 액터가 백엔드에서 멈췄다 (after_down: hang, 끊을 수 없음)."""
    h = RunnerHarness.make(tmp_path, key_graph(), hooks={"after_down": {"ctrl": "hang"}}, **kw)
    h.start(spawned)
    wait_until(lambda: any(line["op"] == "down" for line in h.fake_inputs()))
    return h


def job_idents(h: RunnerHarness) -> list[ProcessId]:
    return [i for i in (identify(pid) for pid in h.job_pids()) if i is not None]


def assert_supervisor_finalized(done: Done, h: RunnerHarness, cancel_reason: str | None) -> None:
    assert done.exit_code == 4 and h.hard_stopped, h.stderr()
    run_end = done.run_end
    assert run_end is not None
    assert run_end["code"] == "runner_died" and run_end["finalized_by"] == "supervisor"
    assert run_end["runner_exit_code"] == 4
    assert run_end.get("cancel_reason") == cancel_reason
    # 복구 경로의 run.end가 마지막 줄이다 (runner가 그 뒤에 쓴 것이 없다)
    assert done.view.events[-1] == run_end
    assert done.run_json is not None and done.run_json["status"] == "finished"


def assert_key_recovered(done: Done, h: RunnerHarness) -> None:
    (recovered,) = done.of("input.recovered")
    assert recovered["inputs"] == [{"device": "keyboard", "key": "ctrl"}]
    assert done.run_end is not None and done.run_end["input_recovery"] == "recovered"
    ctrl = [line for line in h.fake_inputs() if line.get("key") == "ctrl"]
    assert ctrl[-1]["op"] == "up" and ctrl[-1]["by"] == "supervisor"
    assert (h.run_dir / "input-recovery.json").exists()


def test_cancel_with_hung_actor(tmp_path: Path, spawned: Spawned) -> None:
    h = hung_actor(tmp_path, spawned)
    idents = job_idents(h)
    # 제어 스레드의 취소 응답은 바로 온다 (액터·주 스레드가 멈춰 있어도)
    assert h.cancel() == "cancelling"
    done = h.finish()
    assert_supervisor_finalized(done, h, "cancelled")
    assert_key_recovered(done, h)
    assert_no_live(idents)


def test_deadline_with_hung_actor(tmp_path: Path, spawned: Spawned) -> None:
    # 외부 취소 없이 기한 초과 → runner가 runner.stopping으로 알림 → 하네스 하드 종료 타이머
    h = hung_actor(tmp_path, spawned, deadline_ms=4_000)
    idents = job_idents(h)
    done = h.finish()
    assert h.stopping[:1] == ["deadline_exceeded"]
    assert_supervisor_finalized(done, h, "deadline_exceeded")
    assert_key_recovered(done, h)
    assert_no_live(idents)


@pytest.mark.parametrize("point", FINALIZE_POINTS)
def test_hang_in_finalize_hard_stopped_by_supervisor(
    tmp_path: Path, spawned: Spawned, point: str
) -> None:
    faults = [{"point": point, "role": "runner", "action": "hang"}]
    h = RunnerHarness.make(tmp_path, key_graph(), faults=faults).start(spawned)
    h.wait_event("step.start", node="n_pass")
    idents = job_idents(h)
    done = h.finish()
    assert done.exit_code == 4 and h.hard_stopped, h.stderr()
    assert h.stopping[:1] == ["finish"]
    run_end = done.run_end
    assert run_end is not None
    if point == "runner.before_worker_shutdown":
        # run.end 전: 감독자가 마무리한다
        assert run_end["code"] == "runner_died" and run_end["finalized_by"] == "supervisor"
        assert done.run_json is not None and done.run_json["run_json_repaired"] is True
    else:
        # runner가 쓴 run.end는 그대로. run.json만 필요하면 다시 만든다
        assert run_end["verdict"] == "pass" and run_end["finalized_by"] == "runner"
        repaired = point != "runner.before_lease_release"
        assert done.run_json is not None
        assert done.run_json.get("run_json_repaired", False) is repaired
    assert done.view.events[-1] == run_end
    # 키는 노드가 이미 뗐다: 복구할 키 없음. 임대권은 깨끗하게 놓이지 않았다(dirty로 버려짐)
    assert done.of("input.recovered") == []
    lease = h.lease_file()
    assert lease is not None and lease["clean"] is False
    assert_no_live(idents)


def test_channel_lost_supervisor_hard_stops_and_recovers(tmp_path: Path, spawned: Spawned) -> None:
    graph = tk().entry("n_block").node("n_block", "testkit.block")
    h = RunnerHarness.make(tmp_path, graph).start(spawned)
    h.wait_log("blocking")
    idents = job_idents(h)
    assert h.peer is not None
    h.peer.close()  # 감독자 쪽에서 채널을 잃었다 → 곧바로 하드 종료
    done = h.finish()
    assert_supervisor_finalized(done, h, None)
    assert_no_live(idents)


def test_hard_stop_lease_left_dirty_next_owner_recovers(
    tmp_path: Path, spawned: Spawned, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = hung_actor(tmp_path, spawned)
    h.cancel()
    assert h.wait() == 4
    # 이 프로세스가 감독자 역할: 복구 경로를 키 복구 직전 장벽에 붙잡아 둔다
    hold = barrier(tmp_path / "barriers" / "before_input_recovery")
    monkeypatch.setenv(
        _faults.ENV,
        json.dumps(
            [
                {
                    "point": "recovery.before_input_recovery",
                    "role": "supervisor",
                    "action": hold.action,
                }
            ]
        ),
    )
    _faults.set_role("supervisor")
    try:
        result: list[Any] = []
        recovering = threading.Thread(target=lambda: result.append(h.recover()), daemon=True)
        recovering.start()
        hold.wait_ready()
        # 다음 소유자 B가 임대권을 얻는다: 입력 전에 A의 키를 떼고, 자기 ctrl을 누른다
        b_dir = tmp_path / "b"
        b_dir.mkdir()
        backend = FakeBackend(h.input_log, run="bbbbbbbb", by="b")
        lease = InputLease(
            LeaseOwner.current("runner", run_id="bbbbbbbb", run_dir=b_dir),
            backend,
            name=h.lease_env[LEASE_NAME_ENV],
            directory=h.lease_env[STATE_DIR_ENV],
            emit=Journal(b_dir / "events.jsonl", "bbbbbbbb").emit,
        )
        (recovery,) = lease.acquire(0).recovered
        assert recovery.run_dir == h.run_dir
        assert [k.name for k in recovery.inputs] == ["ctrl"]
        backend.down("ctrl")
        hold.go()
        recovering.join(30)
        assert result, "복구 경로가 끝나지 않았다"
    finally:
        _faults.reset()
    lines = h.fake_inputs()
    b_down = max(i for i, line in enumerate(lines) if line["by"] == "b" and line["op"] == "down")
    # B의 ctrl down 뒤에 A 복구 경로(감독자)의 up이 없다
    assert not [line for line in lines[b_down:] if line["by"] == "supervisor"]
    done_view = h.view()
    assert done_view.run_end is not None
    assert done_view.run_end["input_recovery"] == "already_recovered"
    lease.release(None)
