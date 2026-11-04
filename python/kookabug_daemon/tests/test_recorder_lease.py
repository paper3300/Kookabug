"""녹화 세션의 입력 임대권 (`RecorderLease`, M4 계획 2.3): runner와 같은 임대권을 다투고,
`lease.changed`로 소유자 `kind: "recorder"`가 UI에 간다."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from helpers.daemon_runs import TEST, RunRig
from helpers.run import tk

from kb_testing.proc import direct_env
from kookabug_core.inputs.lease import (
    DEFAULT_LEASE_NAME,
    LEASE_NAME_ENV,
    STATE_DIR_ENV,
    lease_name,
    read_lease_file,
)
from kookabug_core.schema.shape import validator
from kookabug_daemon.client import DaemonClient
from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.recorder_lease import RecorderLease

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


CHILD = (
    "import json; from kookabug_core.inputs.lease import lease_name, state_dir; "
    "print(json.dumps([lease_name(), str(state_dir())]))"
)


@pytest.mark.parametrize("mode", ["missing", "empty", "explicit"])
def test_name_and_state_dir_follow_given_environment_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    # 검수 T2-1: 부모(daemon) 환경에 다른 이름이 있어도, 넘긴 runner 환경에서 이름이 없거나 빈
    # 값이면 그 환경으로 띄운 runner와 같은 기본 이름을 써야 한다 (부모 값으로 되돌아가지 않는다)
    monkeypatch.setenv(LEASE_NAME_ENV, f"Local\\Kookabug.InputLease.parent-{uuid.uuid4().hex}")
    env = direct_env(dict(os.environ))
    env.pop(LEASE_NAME_ENV, None)
    env[STATE_DIR_ENV] = str(tmp_path / "state")
    if mode == "empty":
        env[LEASE_NAME_ENV] = ""
    elif mode == "explicit":
        env[LEASE_NAME_ENV] = f"Local\\Kookabug.InputLease.child-{uuid.uuid4().hex}"
    lease = RecorderLease(tmp_path, environ=env)
    child = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", CHILD],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    runner_name, runner_dir = json.loads(child.stdout)
    assert lease.name == runner_name
    assert lease.directory == Path(runner_dir)
    expected = env[LEASE_NAME_ENV] if mode == "explicit" else DEFAULT_LEASE_NAME
    assert lease.name == expected
    assert lease_name(env) == expected
    assert lease.name != os.environ[LEASE_NAME_ENV]


def lease_changed_errors(params: dict[str, Any]) -> list[str]:
    schema = validator("daemon-rpc", "#/$defs/LeaseChangedParams")
    return [e.message for e in schema.iter_errors(params)]


def test_lease_changed_reports_recorder_owner(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path)
    with rig.daemon() as d, d.client() as client:
        assert next_lease(client) is None
        lease = RecorderLease(rig.root, environ=rig.env)
        acquired = lease.acquire()
        assert acquired.recovered == () and lease.held
        owner = next_lease(client)
        assert owner is not None
        assert (owner["kind"], owner["run_id"], owner["run_dir"]) == ("recorder", None, None)
        assert owner["device"] == {"kind": "none"}
        assert owner["workspace"] == str(rig.root)
        assert isinstance(owner["created"], str)  # 값 규칙 밖 정수는 문자열로
        assert lease_changed_errors({"owner": owner}) == []
        # 새로 붙은 연결도 hello 직후 지금 소유자(녹화)를 받는다
        with d.client() as late:
            assert next_lease(late) == owner
        lease.release()
        assert next_lease(client) is None
        data = read_lease_file(lease.directory)
        assert data is not None and data["clean"] is True
        assert data["last_owner"]["kind"] == "recorder"
        lease.release()  # 쥐고 있지 않으면 아무것도 하지 않는다


def test_recorder_lease_busy_while_run_holds_and_run_busy_while_recording(tmp_path: Path) -> None:
    signal = tmp_path / "open"
    graph = (
        tk()
        .entry("n_key")
        .node("n_key", "testkit.input.hold", inputs={"key": "a"}, next={"done": "n_gate"})
        .node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    rig = RunRig.make(tmp_path, graph)
    with rig.daemon() as d, d.client() as client:
        assert next_lease(client) is None
        started = client.call("run.start", {"path": TEST})
        runner = next_lease(client)
        assert runner is not None and runner["kind"] == "runner"
        lease = RecorderLease(rig.root, environ=rig.env)
        with pytest.raises(RequestFailed) as caught:
            lease.acquire()
        assert caught.value.code == "input_lease_busy"
        busy_owner = caught.value.fields["owner"]
        assert (busy_owner["kind"], busy_owner["run_id"]) == ("runner", started["run_id"])
        assert isinstance(busy_owner["created"], str)
        assert not lease.held
        signal.touch()
        assert next_lease(client) is None
        lease.acquire()
        assert next_lease(client)["kind"] == "recorder"  # type: ignore[index]
        lease.release()
