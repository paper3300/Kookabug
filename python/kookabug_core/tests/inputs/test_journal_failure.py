"""입력 기록 쓰기가 실패하면 액터가 입력을 막는다 (구현 계획 M0b 2.4 액터 계약 6, 검수 T6-1 High).

반쯤 쓴 `input.up` 줄 뒤에 다음 요청의 `input.down`이 붙으면 읽기가 합쳐진 줄을 버려, 실제로
누른 키가 복구 대상에서 빠진다. 액터는 실패 뒤 대기 요청을 취소하고 새 입력을 하지 않는다.
"""

from __future__ import annotations

import pytest
from helpers.lease import LeaseEnv, spawn_holder

from kb_testing.proc import Spawned, barrier
from kookabug_core.record import InputKey, held_inputs, read_run

pytestmark = pytest.mark.process


def test_partial_up_line_blocks_queued_request_and_next_owner_recovers(
    env: LeaseEnv, spawned: Spawned
) -> None:
    at_up = barrier(env.root / "at_up")
    queue_b = barrier(env.root / "queue_b")
    a = spawn_holder(
        spawned,
        env,
        "a",
        hooks={"before_up": {"a": at_up.action}},
        faults=[
            {
                "point": "journal.partial_line",
                "role": "runner",
                "when": {"event": "input.up"},
                "action": "raise",
            }
        ],
        script=[
            {"op": "key_async", "key": "a"},
            {"op": "wait", "barrier": str(queue_b.path)},
            # a가 up 직전에 멈춘 동안 b를 큐에 넣고, a를 놓아 준다
            {"op": "key_async", "key": "b"},
            {"op": "wait_queued", "count": 1},
            {"op": "go", "barrier": str(at_up.path)},
            {"op": "hang"},
        ],
    )
    at_up.wait_ready()
    queue_b.go()
    assert a.wait_status("key_a.json")["error"] == "RuntimeError"  # 기록 실패 (고장 주입)
    assert a.wait_status("key_b.json")["error"] == "Cancelled"
    # b는 백엔드에 닿지 않았다
    assert [(line["op"], line["key"]) for line in env.log_lines()] == [("down", "a"), ("up", "a")]

    a.proc.kill()
    a.proc.wait(30)
    view = read_run(a.run_dir)
    assert view.truncated
    assert held_inputs(view) == [InputKey("keyboard", "a")]

    b = env.lease("b")
    [recovery] = b.lease.acquire(0).recovered
    assert recovery.inputs == (InputKey("keyboard", "a"),)
    assert b.lease.release(None)
    physical: dict[str, bool] = {}
    for line in env.log_lines():
        physical[line["key"]] = line["op"] == "down"
    assert not any(physical.values()), physical
