"""죽은 runner의 복구 경로가 늦으면 다음 소유자가 먼저 복구하고, 늦은 복구 경로는 다음 소유자의
입력을 건드리지 않는다 (구현 계획 M0b 2.4 "복구 경로의 키 복구도 임대권 안에서만")."""

from __future__ import annotations

import pytest
from helpers.lease import LeaseEnv, spawn_holder

from kb_testing.proc import Spawned, barrier
from kookabug_core.record.runfolder import INPUT_RECOVERY_FILE

pytestmark = pytest.mark.process


def test_dead_runner_recovery_delayed_next_owner_recovers_then_inputs(
    env: LeaseEnv, spawned: Spawned
) -> None:
    a = spawn_holder(
        spawned,
        env,
        "a",
        script=[{"op": "key", "key": "ctrl"}],
        hooks={"after_down": {"ctrl": "hang"}},
    )
    env.wait_log(by="a", op="down", key="ctrl")
    a.proc.kill()
    a.proc.wait(30)

    # a의 복구 경로(감독자 역할)는 키 복구 직전에 붙잡혀 있다
    wall = barrier(env.root / "before_input_recovery")
    recovery = spawn_holder(
        spawned,
        env,
        "supervisor",
        mode="recover",
        target=a.run_dir,
        faults=[
            {
                "point": "recovery.before_input_recovery",
                "role": "supervisor",
                "action": wall.action,
            }
        ],
    )
    wall.wait_ready()

    # b가 임대권을 얻어 a의 ctrl을 먼저 떼고, 자기 ctrl을 누른 채 있다
    b = spawn_holder(
        spawned,
        env,
        "b",
        script=[{"op": "key", "key": "ctrl"}, {"op": "finish"}],
        hooks={"after_down": {"ctrl": "block"}},
    )
    assert b.wait_status("acquired.json")["recovered"] == [
        {"from_run": a.run_id, "inputs": [{"device": "keyboard", "key": "ctrl"}]}
    ]
    env.wait_log(by="b", op="down", key="ctrl")

    wall.go()
    assert recovery.wait_status("recovered.json")["status"] == "already_recovered"
    assert recovery.proc.wait(30) == 0
    # 늦은 복구 경로는 아무것도 떼지 않았다: b의 ctrl은 아직 눌린 채다
    ops = [(line["by"], line["op"], line["key"]) for line in env.log_lines()]
    assert ops == [("a", "down", "ctrl"), ("b", "up", "ctrl"), ("b", "down", "ctrl")]

    b.cancel()
    assert b.wait_status("released.json")["clean"] is True
    assert b.proc.wait(30) == 0
    ops = [(line["by"], line["op"], line["key"]) for line in env.log_lines()]
    assert ops == [
        ("a", "down", "ctrl"),
        ("b", "up", "ctrl"),
        ("b", "down", "ctrl"),
        ("b", "up", "ctrl"),  # b가 뗄 때까지 눌린 상태였다
    ]
    assert all(line["by"] != "supervisor" for line in env.log_lines())
    assert (a.run_dir / INPUT_RECOVERY_FILE).exists()
