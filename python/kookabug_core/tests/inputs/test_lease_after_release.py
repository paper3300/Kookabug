"""깨끗한 놓기 뒤에는 앞 소유자의 입력이 없다 (구현 계획 M0b 2.4, 3차 검수 S1)."""

from __future__ import annotations

import pytest
from helpers.lease import LeaseEnv, spawn_holder

from kb_testing.proc import Spawned, barrier
from kookabug_core.inputs import InputLeaseBusy
from kookabug_core.record import InputKey
from kookabug_core.record.runfolder import INPUT_RECOVERY_FILE

pytestmark = pytest.mark.process

CTRL = InputKey("keyboard", "ctrl")


def actor_stalled_before_up(spawned: Spawned, env: LeaseEnv, join_timeout: float):
    """a: ctrl을 누른 채(게이트가 닫힐 때까지) → 취소 → 액터가 up 직전 장벽에서 멈춤."""
    wall = barrier(env.root / "before_up")
    a = spawn_holder(
        spawned,
        env,
        "a",
        script=[{"op": "key", "key": "ctrl"}, {"op": "finish", "join_timeout": join_timeout}],
        hooks={"after_down": {"ctrl": "block"}},
        faults=[
            {
                "point": "actor.before_backend",
                "role": "runner",
                "when": {"event": "up"},
                "action": wall.action,
            }
        ],
    )
    a.wait_status("acquired.json")
    env.wait_log(by="a", op="down", key="ctrl")
    a.cancel()
    wall.wait_ready()
    return a, wall


def test_no_input_from_previous_owner_after_clean_release(env: LeaseEnv, spawned: Spawned) -> None:
    a, wall = actor_stalled_before_up(spawned, env, join_timeout=30)
    b = env.lease("b")
    # a의 주 스레드는 액터 join을 기다리며 임대권을 놓지 않는다
    with pytest.raises(InputLeaseBusy) as caught:
        b.lease.acquire(0)
    assert caught.value.owner is not None and caught.value.owner["run_id"] == a.run_id
    assert a.status("released.json") is None

    wall.go()
    released = a.wait_status("released.json")
    assert released["clean"] is True
    assert a.proc.wait(30) == 0

    acquired = b.lease.acquire(0)
    assert acquired.recovered == ()  # 깨끗하게 놓았으므로 복구할 것이 없다
    actor = b.actor()
    actor.key("ctrl")
    assert actor.stop(10)
    assert b.lease.release(actor)

    lines = env.log_lines()
    # a가 깨끗하게 놓은 뒤 a 프로세스의 동작은 하나도 없다
    cut = released["log_lines"]
    assert all(line["pid"] == a.proc.pid for line in lines[:cut])
    assert all(line["pid"] != a.proc.pid for line in lines[cut:])
    assert [(line["by"], line["op"], line["key"]) for line in lines] == [
        ("a", "down", "ctrl"),
        ("a", "up", "ctrl"),
        ("b", "down", "ctrl"),
        ("b", "up", "ctrl"),
    ]
    assert not (a.run_dir / INPUT_RECOVERY_FILE).exists()


def test_actor_join_timeout_leaves_lease_dirty(env: LeaseEnv, spawned: Spawned) -> None:
    a, _ = actor_stalled_before_up(spawned, env, join_timeout=0.5)
    # 장벽을 풀지 않는다: join 기한 초과 → 놓지 않고 끝남 (하드 종료와 같다)
    released = a.wait_status("released.json")
    assert released["clean"] is False
    assert a.proc.wait(30) == 4

    b = env.lease("b")
    acquired = b.lease.acquire(0)
    assert acquired.previous is not None and acquired.previous["clean"] is False
    [recovery] = acquired.recovered
    assert recovery.from_run == a.run_id
    assert recovery.inputs == (CTRL,)
    assert b.lease.release(None)
    assert [(line["by"], line["op"], line["key"]) for line in env.log_lines()] == [
        ("a", "down", "ctrl"),
        ("b", "up", "ctrl"),
    ]
    assert (a.run_dir / INPUT_RECOVERY_FILE).exists()
