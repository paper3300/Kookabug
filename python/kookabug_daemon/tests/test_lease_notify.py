"""알림 `lease.changed` (M2 계획 2.4·2.8, T5): 입력 임대권 옆 파일 폴링."""

from __future__ import annotations

import queue
import time
from pathlib import Path
from typing import Any

import pytest
from helpers.daemon_runs import TEST, RunRig
from helpers.run import tk

from kookabug_daemon.client import DaemonClient
from kookabug_daemon.lease_watch import lease_dir, wire_safe

pytestmark = [pytest.mark.process, pytest.mark.timeout(120)]


def next_lease(client: DaemonClient, timeout: float = 30) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while (left := deadline - time.monotonic()) > 0:
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            break
        if message["method"] == "lease.changed":
            return message["params"]["owner"]
    raise AssertionError(f"{timeout}초 안에 lease.changed가 오지 않았다")


def test_lease_changed_on_run_start_and_end(tmp_path: Path) -> None:
    signal = tmp_path / "open"
    graph = (
        tk()
        .entry("n_key")
        .node("n_key", "testkit.input.hold", inputs={"key": "a"}, next={"done": "n_gate"})
        .node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    rig = RunRig.make(tmp_path, graph)
    assert lease_dir(rig.env) == tmp_path / "state"
    with rig.daemon() as d, d.client() as client:
        started = client.call("run.start", {"path": TEST})
        # 실행이 입력을 쓰는 동안: 소유자 = 그 실행의 runner
        owner = next_lease(client)
        assert owner is not None
        assert (owner["kind"], owner["run_id"]) == ("runner", started["run_id"])
        # 프로세스 생성 시각(FILETIME)은 값 규칙 밖이라 문자열로 온다
        assert isinstance(owner["created"], str) and int(owner["created"]) > 2**53
        assert isinstance(owner["pid"], int)
        signal.touch()
        # 깨끗하게 놓았다: 소유자 없음
        assert next_lease(client) is None


def test_wire_safe_converts_only_unsafe_integers() -> None:
    value = {"a": [1, 2**53 - 1, -(2**53), True], "b": {"c": 2**60, "d": 1.5e300, "e": "x"}}
    assert wire_safe(value) == {
        "a": [1, 2**53 - 1, str(-(2**53)), True],
        "b": {"c": str(2**60), "d": 1.5e300, "e": "x"},
    }
