"""이중 고장: 감독자와 runner가 둘 다 죽으면 다음 임대권 획득자가 입력 전에 키를 뗀다
(구현 계획 M0b 2.4 "이중 고장", 4차 결정 3)."""

from __future__ import annotations

import pytest
from helpers.lease import LeaseEnv, spawn_holder, spawn_sleeper

from kb_testing.proc import Spawned, barrier
from kookabug_core.record import InputKey, read_run
from kookabug_core.record.runfolder import INPUT_RECOVERY_FILE

pytestmark = pytest.mark.process

CTRL = {"device": "keyboard", "key": "ctrl"}


def test_next_owner_releases_keys_of_dead_runner_without_supervisor(
    env: LeaseEnv, spawned: Spawned
) -> None:
    supervisor = spawn_sleeper(spawned, env)
    a = spawn_holder(
        spawned,
        env,
        "a",
        script=[{"op": "key", "key": "ctrl"}],
        hooks={"after_down": {"ctrl": "hang"}},  # 키를 누른 채 멈춘 runner
    )
    env.wait_log(by="a", op="down", key="ctrl")
    for proc in (a.proc, supervisor):
        proc.kill()
        proc.wait(30)
    # 아무도 a를 마무리하지 않았다: 기록은 읽기만으로 "중단"
    assert read_run(a.run_dir).status == "interrupted"

    b = spawn_holder(spawned, env, "b", script=[{"op": "key", "key": "x"}, {"op": "finish"}])
    acquired = b.wait_status("acquired.json")
    assert acquired["recovered"] == [{"from_run": a.run_id, "inputs": [CTRL]}]
    assert b.wait_status("released.json")["clean"] is True
    assert b.proc.wait(30) == 0

    # b는 자기 입력 전에 a의 ctrl을 뗐다
    assert [(line["by"], line["op"], line["key"]) for line in env.log_lines()] == [
        ("a", "down", "ctrl"),
        ("b", "up", "ctrl"),
        ("b", "down", "x"),
        ("b", "up", "x"),
    ]
    assert (a.run_dir / INPUT_RECOVERY_FILE).exists()
    recovered = [e for e in read_run(b.run_dir).events if e["event"] == "input.recovered"]
    assert [(e["from_run"], e["inputs"]) for e in recovered] == [(a.run_id, [CTRL])]


def test_truncated_journal_tail_down_line_ignored_then_recovered(
    env: LeaseEnv, spawned: Spawned
) -> None:
    wall = barrier(env.root / "half_line")
    supervisor = spawn_sleeper(spawned, env)
    # ctrl+a: ctrl down은 다 쓰고, a의 input.down 줄을 반쯤 쓴 채 멈춤 (a는 아직 누르지 않음)
    a = spawn_holder(
        spawned,
        env,
        "a",
        script=[{"op": "key", "key": "ctrl+a"}],
        faults=[
            {
                "point": "journal.partial_line",
                "role": "runner",
                "when": {"event": "input.down", "nth": 2},
                "action": wall.action,
            }
        ],
    )
    wall.wait_ready()
    for proc in (a.proc, supervisor):
        proc.kill()
        proc.wait(30)

    view = read_run(a.run_dir)
    assert view.truncated
    assert [(e["event"], e["key"]) for e in view.events] == [("input.down", "ctrl")]
    # 가짜 기록: a는 before_down 전이라 백엔드로 누르지 않았다
    assert [(line["op"], line["key"]) for line in env.log_lines()] == [("down", "ctrl")]

    b = env.lease("b")
    acquired = b.lease.acquire(0)
    [recovery] = acquired.recovered
    assert recovery.inputs == (InputKey("keyboard", "ctrl"),)
    assert b.lease.release(None)
    assert [(line["by"], line["op"], line["key"]) for line in env.log_lines()] == [
        ("a", "down", "ctrl"),
        ("b", "up", "ctrl"),
    ]
