"""입력 임대권의 녹화 주체 (M4 계획 2.3 C1): `kind: "recorder"`·장치 `none`·액터 없는 깨끗한 놓기,
녹화와 실행이 서로 `input_lease_busy`, 놓지 않고 죽은 녹화 소유자 다음 획득자는 떼지 않는다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from helpers.lease import LeaseEnv, spawn_holder
from helpers.run import tk
from helpers.runner import RunnerHarness, events_of

from kb_testing.proc import Spawned, barrier, direct_env, python_cmd, wait_until
from kookabug_core.inputs import InputLease, InputLeaseBusy, LeaseOwner, NoneBackend
from kookabug_core.inputs.lease import read_lease_file
from kookabug_core.schema.shape import validator

pytestmark = pytest.mark.process


def recorder_lease(env: LeaseEnv, workspace: str = "D:/ws") -> InputLease:
    owner = LeaseOwner.current("recorder", workspace=workspace)
    return InputLease(owner, NoneBackend(), name=env.name, directory=env.state_dir)


def lease_file_errors(data: Any) -> list[str]:
    return [e.message for e in validator("daemon-rpc", "#/$defs/LeaseFile").iter_errors(data)]


def input_graph() -> Any:
    return (
        tk()
        .entry("n_key")
        .node("n_key", "testkit.input.hold", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def test_recorder_owner_acquire_release_clean(env: LeaseEnv) -> None:
    lease = recorder_lease(env)
    acquired = lease.acquire(0)
    assert acquired.recovered == () and acquired.idle_previous is None
    data = read_lease_file(env.state_dir)
    assert data is not None and data["clean"] is False
    owner = data["owner"]
    assert (owner["kind"], owner["run_id"], owner["run_dir"]) == ("recorder", None, None)
    assert owner["workspace"] == "D:/ws" and owner["device"] == {"kind": "none"}
    assert lease_file_errors(data) == []
    # 입력 장치가 없으니 액터 없이 깨끗하게 놓는다
    lease.release_idle()
    assert not lease.held
    data = read_lease_file(env.state_dir)
    assert data is not None
    assert (data["owner"], data["clean"]) == (None, True)
    assert data["last_owner"]["kind"] == "recorder"
    assert lease_file_errors(data) == []
    # 장치가 있는 소유자는 release_idle로 놓을 수 없다 (액터가 멈췄는지 봐야 한다)
    runner = env.lease("r")
    runner.lease.acquire(0)
    with pytest.raises(RuntimeError):
        runner.lease.release_idle()
    assert runner.lease.release(None)


def test_recorder_busy_when_runner_holds(env: LeaseEnv, spawned: Spawned) -> None:
    wall = barrier(env.root / "wall")
    a = spawn_holder(
        spawned, env, "a", script=[{"op": "wait", "barrier": str(wall.path)}, {"op": "finish"}]
    )
    a.wait_status("acquired.json")
    lease = recorder_lease(env)
    with pytest.raises(InputLeaseBusy) as caught:
        lease.acquire(0)
    assert caught.value.owner is not None
    assert (caught.value.owner["kind"], caught.value.owner["run_id"]) == ("runner", a.run_id)
    assert not lease.held
    wall.go()
    assert a.proc.wait(30) == 0
    # 실행이 깨끗하게 놓은 뒤에는 녹화가 얻는다 (앞 소유자 복구 없음)
    acquired = lease.acquire(0)
    assert acquired.recovered == ()
    lease.release_idle()


def test_runner_busy_when_recorder_holds(tmp_path: Path, spawned: Spawned) -> None:
    env = LeaseEnv.make(tmp_path / "lease")
    lease = recorder_lease(env)
    lease.acquire(0)
    try:
        h = RunnerHarness.make(
            tmp_path,
            input_graph(),
            lease_name=env.name,
            state_dir=env.state_dir,
        ).start(spawned)
        done = h.finish()
    finally:
        lease.release_idle()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None
    assert done.run_end["verdict"] == "error"
    assert done.run_end["code"] == "input_lease_busy"
    # 실행 기록에 누가 쥐었는지 (녹화 소유자) 남는다
    assert "recorder" in done.run_end["reason"]
    assert done.of("step.start") == []
    assert h.fake_inputs() == []


RECORDER_DAEMON = """
import json, os, sys, time
from pathlib import Path
from kookabug_core.inputs import InputLease, LeaseOwner, NoneBackend
out = Path(sys.argv[1])
owner = LeaseOwner.current("recorder", workspace="D:/ws")
lease = InputLease(owner, NoneBackend())
lease.acquire(0)
(out / "acquired.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
time.sleep(600)
"""


def test_dirty_recorder_owner_recovery_is_noop_and_marks_clean(
    tmp_path: Path, spawned: Spawned
) -> None:
    # daemon이 녹화 중 강제 종료됨: 뮤텍스는 OS가 풀고 옆 파일은 녹화 소유자 clean: false로 남는다
    env = LeaseEnv.make(tmp_path / "lease")
    out = tmp_path / "daemon"
    out.mkdir()
    script = tmp_path / "recorder_daemon.py"
    script.write_text(RECORDER_DAEMON, encoding="utf-8")
    proc = spawned.popen(python_cmd(script, out), env=direct_env(env.env))
    wait_until(lambda: (out / "acquired.json").exists() or proc.poll() is not None, timeout=30)
    assert (out / "acquired.json").exists(), proc.poll()
    proc.kill()
    proc.wait(30)
    dirty = read_lease_file(env.state_dir)
    assert dirty is not None and dirty["clean"] is False and dirty["owner"]["kind"] == "recorder"

    # 다음 획득자(이 프로세스 안의 실행 역할): 녹화는 입력하지 않았으니 떼지 않고, 그 앞 소유자를
    # 옆 파일의 last_owner로 남긴다
    nxt = env.lease("b")
    acquired = nxt.lease.acquire(0)
    assert acquired.recovered == ()
    assert acquired.idle_previous is not None and acquired.idle_previous["kind"] == "recorder"
    held = read_lease_file(env.state_dir)
    assert held is not None and held["clean"] is False
    assert held["owner"]["run_id"] == nxt.run_id
    assert held["last_owner"]["kind"] == "recorder"
    assert lease_file_errors(held) == []
    assert env.log_lines() == []  # 아무것도 떼지 않았다
    assert nxt.lease.release(None)
    released = read_lease_file(env.state_dir)
    assert released is not None and released["clean"] is True
    assert released["last_owner"]["run_id"] == nxt.run_id

    # 실제 runner도 같다: 다시 녹화 소유자를 더럽게 남기고 실행하면 떼기·복구 기록 없이 통과
    (out / "again").mkdir()
    proc = spawned.popen(python_cmd(script, out / "again"), env=direct_env(env.env))
    wait_until(lambda: (out / "again" / "acquired.json").exists() or proc.poll() is not None)
    proc.kill()
    proc.wait(30)
    h = RunnerHarness.make(
        tmp_path / "run", input_graph(), lease_name=env.name, state_dir=env.state_dir
    ).start(spawned)
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "pass"
    assert events_of(done.view.events, "input.recovered") == []
    assert all(line.get("by") == "runner" for line in h.fake_inputs())
    final = read_lease_file(env.state_dir)
    assert final is not None and final["clean"] is True
    assert final["last_owner"]["kind"] == "runner"
