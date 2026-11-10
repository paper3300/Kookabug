"""감독자 입력 복구 확인의 임대권 정리 (M8 R8): 복구는 끝났는데 깨끗한 놓기(옆 파일 쓰기)가 실패해도
얻은 임대권을 쥔 채 두지 않는다."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from helpers.lease import Holder, LeaseEnv, spawn_holder

from kb_testing.proc import Spawned
from kookabug_core.agent_job.settle import input_settled
from kookabug_core.inputs import FakeBackend, InputLease, LeaseOwner, recover_run
from kookabug_core.inputs import lease as lease_mod
from kookabug_core.inputs.backends import NoneBackend
from kookabug_core.inputs.lease import read_lease_file
from kookabug_core.record.runfolder import INPUT_RECOVERY_FILE

pytestmark = pytest.mark.process


def _dead_holder_with_ctrl(spawned: Spawned, env: LeaseEnv) -> Holder:
    """Ctrl을 누른 채 멈춘 runner를 죽인다 (깨끗하게 놓지 않은 죽은 소유자)."""
    holder = spawn_holder(
        spawned,
        env,
        "a",
        script=[{"op": "key", "key": "ctrl"}],
        hooks={"after_down": {"ctrl": "hang"}},
    )
    env.wait_log(by="a", op="down", key="ctrl")
    holder.proc.kill()
    holder.proc.wait(30)
    return holder


def _fail_clean_write_once(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """옆 파일의 `clean: true` 쓰기만 한 번 `PermissionError`. 나머지는 원래 구현."""
    original = lease_mod._write_json  # pyright: ignore[reportPrivateUsage]
    failed: list[int] = []

    def flaky(path: Path, data: Mapping[str, Any]) -> None:
        if data.get("clean") is True and not failed:
            failed.append(1)
            raise PermissionError("주입: 옆 파일 쓰기 실패")
        original(path, data)

    monkeypatch.setattr(lease_mod, "_write_json", flaky)
    return failed


def _ops(env: LeaseEnv) -> list[tuple[str, str]]:
    return [(line["op"], line["key"]) for line in env.log_lines()]


def _other_subject(env: LeaseEnv, tmp_path: Path) -> InputLease:
    """다른 워크스페이스의 사람 녹화 주체 (입력 장치 없음)."""
    owner = LeaseOwner.current("recorder", workspace=tmp_path / "other")
    return InputLease(owner, NoneBackend(), name=env.name, directory=env.state_dir)


def test_settle_release_io_error_does_not_leak_lease(
    spawned: Spawned, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = LeaseEnv.make(tmp_path)
    root = tmp_path / "ws"
    root.mkdir()
    holder = _dead_holder_with_ctrl(spawned, env)
    failed = _fail_clean_write_once(monkeypatch)

    # 키는 뗐지만 깨끗한 놓기를 기록하지 못했다 → 확인 못 함, 임대권은 놓는다
    assert input_settled(root, env.env, timeout=1) is False
    assert failed == [1]
    assert _ops(env) == [("down", "ctrl"), ("up", "ctrl")]
    assert (holder.run_dir / INPUT_RECOVERY_FILE).exists()
    side = read_lease_file(env.state_dir)
    assert side is not None and side["clean"] is False
    assert side["owner"]["kind"] == "supervisor"

    # 양성 대조: 다음 시도가 다시 얻어(쥔 채 남았으면 이 프로세스의 다른 스레드라 못 얻는다)
    # 깨끗하게 놓는다. 이미 뗀 키는 다시 떼지 않는다
    assert input_settled(root, env.env, timeout=1) is True
    assert _ops(env) == [("down", "ctrl"), ("up", "ctrl")]
    side = read_lease_file(env.state_dir)
    assert side is not None and side["clean"] is True
    assert side["last_owner"]["kind"] == "supervisor"

    # 다른 주체가 바로 얻는다
    other = _other_subject(env, tmp_path)
    acquired = other.acquire(0)
    try:
        assert acquired.recovered == ()
    finally:
        other.release_idle()
    assert _ops(env) == [("down", "ctrl"), ("up", "ctrl")]


def test_recover_run_release_io_error_does_not_leak_lease(
    spawned: Spawned, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """감독자 강제 복구(`force_settle` → `RunHandle.recover` → `recover_run`)도 같다."""
    env = LeaseEnv.make(tmp_path)
    holder = _dead_holder_with_ctrl(spawned, env)
    failed = _fail_clean_write_once(monkeypatch)
    backend = FakeBackend(env.log, run=None, by="supervisor")

    with pytest.raises(PermissionError):
        recover_run(
            holder.run_dir, backend=backend, timeout=1, name=env.name, directory=env.state_dir
        )
    assert failed == [1]
    assert _ops(env) == [("down", "ctrl"), ("up", "ctrl")]

    # 쥔 채 남지 않았다: 다른 주체가 바로 얻고, 뗄 것이 없다
    other = _other_subject(env, tmp_path)
    assert other.acquire(0).recovered == ()
    other.release_idle()

    # 다시 부르면(감독 재시도) 이미 복구됨으로 확인된다
    again = recover_run(
        holder.run_dir, backend=backend, timeout=1, name=env.name, directory=env.state_dir
    )
    assert again.status == "already_recovered"
    assert _ops(env) == [("down", "ctrl"), ("up", "ctrl")]
