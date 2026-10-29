"""입력 임대권 (구현 계획 M0b 2.4 "입력 임대권")."""

from __future__ import annotations

import contextlib
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from helpers.lease import LeaseEnv, spawn_holder

from kb_testing.proc import PROCS_DIR, Spawned, barrier, direct_env, python_cmd
from kookabug_core.inputs import (
    FakeBackend,
    InputActor,
    InputLease,
    InputLeaseBusy,
    LeaseOwner,
    lease_file,
    lease_name,
    read_lease_file,
    recover_run,
    state_dir,
)
from kookabug_core.inputs.lease import DEFAULT_LEASE_NAME
from kookabug_core.record import InputKey, Journal, read_run
from kookabug_core.record.runfolder import EVENTS_FILE, INPUT_RECOVERY_FILE
from kookabug_core.win import NamedMutex, ProcessId, WaitResult, current

pytestmark = pytest.mark.process

CTRL = InputKey("keyboard", "ctrl")


def dead_run(
    env: LeaseEnv,
    label: str,
    *events: dict[str, Any],
    clean: bool = False,
    write_lease: bool = True,
) -> Path:
    """입력 기록을 남기고 죽은 앞 소유자: 실행 폴더·저널과 옆 파일(기본 `clean: false`)."""
    run_dir = env.run_dir(label)
    run_dir.mkdir(parents=True)
    run_id = (label + "00000000")[:8]
    with Journal(run_dir / EVENTS_FILE, run_id) as journal:
        for event in events:
            journal.emit(event)
    if not write_lease:
        return run_dir
    owner = LeaseOwner("runner", ProcessId(4, 1), run_id=run_id, run_dir=str(run_dir)).to_json()
    data = (
        {"owner": None, "clean": True, "last_owner": owner}
        if clean
        else {"owner": owner, "clean": False}
    )
    env.state_dir.mkdir(parents=True, exist_ok=True)
    lease_file(env.state_dir).write_text(json.dumps(data), encoding="utf-8")
    return run_dir


def down(key: str) -> dict[str, Any]:
    return {"event": "input.down", "device": "keyboard", "key": key}


def mutex_busy(name: str) -> bool:
    """다른 스레드에서 뮤텍스를 얻어 본다 (얻었으면 바로 놓는다)."""
    seen: list[WaitResult] = []

    def probe() -> None:
        with NamedMutex.open(name) as mutex:
            result = mutex.wait(0)
            seen.append(result)
            if result is not WaitResult.TIMEOUT:
                mutex.release()

    thread = threading.Thread(target=probe)
    thread.start()
    thread.join(10)
    return seen == [WaitResult.TIMEOUT]


def test_second_acquire_denied_with_owner_info(env: LeaseEnv, spawned: Spawned) -> None:
    wall = barrier(env.root / "wall")
    a = spawn_holder(
        spawned,
        env,
        "a",
        script=[{"op": "wait", "barrier": str(wall.path)}, {"op": "finish"}],
    )
    a.wait_status("acquired.json")
    b = env.lease("b")
    with pytest.raises(InputLeaseBusy) as caught:
        b.lease.acquire(0)
    owner = caught.value.owner
    assert owner is not None
    assert owner["kind"] == "runner"
    assert owner["run_id"] == a.run_id
    assert owner["run_dir"] == str(a.run_dir)
    assert owner["pid"] == a.proc.pid
    assert caught.value.code == "input_lease_busy"
    assert a.run_id in str(caught.value)
    wall.go()
    assert a.wait_status("released.json")["clean"] is True
    assert a.proc.wait(30) == 0
    acquired = b.lease.acquire(0)
    assert not acquired.abandoned
    assert acquired.recovered == ()
    assert b.lease.release(None)


def test_owner_killed_acquired_as_abandoned(env: LeaseEnv, spawned: Spawned) -> None:
    a = spawn_holder(spawned, env, "a", script=[{"op": "hang"}])
    a.wait_status("acquired.json")
    # 이름 있는 뮤텍스는 마지막 핸들이 닫히면 없어진다: 소유자가 죽을 때 다른 핸들이 열려 있어야
    # ABANDONED가 보인다. 그래서 복구 여부는 ABANDONED가 아니라 옆 파일(clean)로 정한다
    with NamedMutex.open(env.name):
        a.proc.kill()
        a.proc.wait(30)
        b = env.lease("b")
        acquired = b.lease.acquire(0)
    assert acquired.abandoned
    assert acquired.previous is not None
    assert acquired.previous["owner"]["run_id"] == a.run_id
    assert b.lease.release(None)


def test_clean_release_no_recovery(env: LeaseEnv) -> None:
    a = env.lease("a")
    assert a.lease.acquire(0).recovered == ()
    actor = a.actor()
    actor.key("ctrl")
    assert actor.stop(10)
    assert a.lease.release(actor)
    data = read_lease_file(env.state_dir)
    assert data is not None
    assert data["owner"] is None
    assert data["clean"] is True
    assert data["last_owner"]["run_id"] == a.run_id

    b = env.lease("b")
    acquired = b.lease.acquire(0)
    assert not acquired.abandoned
    assert acquired.recovered == ()
    assert not (a.run_dir / INPUT_RECOVERY_FILE).exists()
    assert b.lease.release(None)
    assert [line["by"] for line in env.log_lines()] == ["a", "a"]


def test_acquire_after_dirty_owner_recovers_keys_first(env: LeaseEnv, spawned: Spawned) -> None:
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

    b = env.lease("b")
    acquired = b.lease.acquire(0)
    [recovery] = acquired.recovered
    assert recovery.from_run == a.run_id
    assert recovery.inputs == (CTRL,)
    # 얻은 쪽이 입력하기 전에 먼저 뗐다
    actor = b.actor()
    actor.key("x")
    assert actor.stop(10)
    assert b.lease.release(actor)
    ops = [(line["by"], line["op"], line["key"]) for line in env.log_lines()]
    assert ops == [
        ("a", "down", "ctrl"),
        ("b", "up", "ctrl"),
        ("b", "down", "x"),
        ("b", "up", "x"),
    ]
    marker = json.loads((a.run_dir / INPUT_RECOVERY_FILE).read_text(encoding="utf-8"))
    assert marker["recovered_by"] == {"kind": "runner", "run_id": b.run_id}
    assert marker["keys"] == [{"device": "keyboard", "key": "ctrl"}]
    b.journal.close()
    recovered = [e for e in read_run(b.run_dir).events if e["event"] == "input.recovered"]
    assert recovered == [
        {
            "event": "input.recovered",
            "from_run": a.run_id,
            "inputs": [{"device": "keyboard", "key": "ctrl"}],
            "by": {"kind": "runner", "run": b.run_id},
            "run": b.run_id,
            "seq": 1,
            "t": recovered[0]["t"],
        }
    ]


def test_recovery_marker_prevents_double_release(env: LeaseEnv) -> None:
    a_dir = dead_run(env, "a", down("ctrl"))
    (a_dir / INPUT_RECOVERY_FILE).write_text("{}", encoding="utf-8")
    b = env.lease("b")
    acquired = b.lease.acquire(0)
    assert acquired.recovered == ()
    assert b.lease.release(None)
    assert env.log_lines() == []


def test_recover_run_skips_when_marker_exists(env: LeaseEnv) -> None:
    a_dir = dead_run(env, "a", down("ctrl"))
    (a_dir / INPUT_RECOVERY_FILE).write_text("{}", encoding="utf-8")
    backend = FakeBackend(env.log, by="supervisor")
    outcome = recover_run(a_dir, backend=backend, name=env.name, directory=env.state_dir)
    assert outcome.status == "already_recovered"
    assert env.log_lines() == []


def test_recover_run_skips_when_owner_clean(env: LeaseEnv, spawned: Spawned) -> None:
    a_dir = dead_run(env, "a", down("ctrl"), clean=True)
    # 뮤텍스는 옆 파일을 쓰지 않는 다른 프로세스가 쥐고 있다: 옆 파일만으로 끝나고 기다리지 않는다
    wall = barrier(env.root / "held")
    holder = spawned.popen(
        python_cmd(PROCS_DIR / "hold_mutex.py", env.name, wall.path), env=direct_env(env.env)
    )
    wall.wait_ready()
    backend = FakeBackend(env.log, by="supervisor")
    outcome = recover_run(a_dir, backend=backend, name=env.name, directory=env.state_dir, timeout=0)
    wall.go()
    assert holder.wait(30) == 0
    assert outcome.status == "not_needed"
    assert env.log_lines() == []


def test_recover_run_acquires_and_releases(env: LeaseEnv) -> None:
    a_dir = dead_run(
        env, "a", down("ctrl"), {"event": "input.down", "device": "mouse", "button": "left"}
    )
    backend = FakeBackend(env.log, by="supervisor")
    outcome = recover_run(a_dir, backend=backend, name=env.name, directory=env.state_dir)
    assert outcome.status == "recovered"
    assert set(outcome.inputs) == {CTRL, InputKey("mouse", "left")}
    assert {
        (line["by"], line["op"], line.get("key") or line.get("button")) for line in env.log_lines()
    } == {
        ("supervisor", "up", "ctrl"),
        ("supervisor", "up", "left"),
    }
    marker = json.loads((a_dir / INPUT_RECOVERY_FILE).read_text(encoding="utf-8"))
    assert marker["recovered_by"]["kind"] == "supervisor"
    # 입력을 하지 않았으므로 곧바로 깨끗하게 놓았다
    data = read_lease_file(env.state_dir)
    assert data is not None and data["clean"] is True and data["owner"] is None
    assert not mutex_busy(env.name)
    # 두 번 불러도 같은 키를 다시 떼지 않는다
    again = recover_run(a_dir, backend=backend, name=env.name, directory=env.state_dir)
    assert again.status == "already_recovered"
    assert len(env.log_lines()) == 2


def test_recover_run_lease_busy(env: LeaseEnv) -> None:
    a_dir = dead_run(env, "a", down("ctrl"), write_lease=False)
    other = env.lease("other")
    try:
        # 다른 주체가 쥐고 있고, 그 주체는 a를 복구하지 않았다(표시 파일 없음)
        other.lease.acquire(0)
        backend = FakeBackend(env.log, by="supervisor")
        outcome = recover_run(
            a_dir, backend=backend, name=env.name, directory=env.state_dir, timeout=0.2
        )
    finally:
        other.lease.release(None)
    assert outcome.status == "lease_busy"


def test_release_refused_for_unstarted_actor_and_no_restart_after_release(env: LeaseEnv) -> None:
    old = env.lease("old")
    old.lease.acquire(0)
    actor = InputActor(old.backend, emit=old.journal.emit, gate=old.gate)
    # 시작하지 않은 액터는 아직 시작할 수 있으므로 quiesced가 아니다
    assert old.lease.release(actor) is False
    assert mutex_busy(env.name)
    assert actor.stop(10)
    assert old.lease.release(actor) is True

    new = env.lease("new")
    new.lease.acquire(0)
    try:
        with pytest.raises(RuntimeError):
            actor.start()
    finally:
        assert new.lease.release(None)
    assert env.log_lines() == []


def test_release_refused_unless_quiesced(env: LeaseEnv) -> None:
    a = env.lease("a")
    a.lease.acquire(0)
    actor = a.actor()
    # 액터가 아직 살아 있다
    assert a.lease.release(actor) is False
    data = read_lease_file(env.state_dir)
    assert data is not None and data["clean"] is False
    assert data["owner"]["run_id"] == a.run_id
    assert mutex_busy(env.name)
    # 액터가 멈추면 놓을 수 있다
    assert actor.stop(10)
    assert a.lease.release(actor) is True
    assert not mutex_busy(env.name)

    # 액터는 끝났지만 떼지 못한 키가 남았다
    def refuse_up() -> None:
        raise OSError("떼기 거부")

    c = env.lease("c", hooks={"before_up": {"ctrl": refuse_up}, "after_down": {"ctrl": "block"}})
    c.lease.acquire(0)
    actor = c.actor()
    pressed = threading.Thread(target=lambda: _swallow(lambda: actor.key("ctrl")), daemon=True)
    pressed.start()
    env.wait_log(by="c", op="down", key="ctrl")
    assert actor.stop(10) is False
    assert actor.held == [CTRL]
    assert c.lease.release(actor) is False
    data = read_lease_file(env.state_dir)
    assert data is not None and data["clean"] is False
    assert mutex_busy(env.name)
    c.lease.abandon()  # 프로세스가 놓지 않고 끝난 것과 같다


def _swallow(fn: Any) -> None:
    with contextlib.suppress(BaseException):  # Cancelled
        fn()


def test_process_exit_without_clean_release_forces_next_recovery(
    env: LeaseEnv, spawned: Spawned
) -> None:
    # a는 키를 누르고 떼기까지 했지만 임대권을 깨끗하게 놓지 않고 끝났다
    a = spawn_holder(
        spawned, env, "a", script=[{"op": "key", "key": "ctrl"}, {"op": "exit", "code": 0}]
    )
    assert a.proc.wait(30) == 0
    b = env.lease("b")
    acquired = b.lease.acquire(0)
    # 뮤텍스는 a와 함께 없어져 ABANDONED가 아닐 수 있다. 그래도 옆 파일이 clean: false이므로
    # 복구는 반드시 돈다 (뗄 키는 없었다)
    assert acquired.previous is not None and acquired.previous["clean"] is False
    [recovery] = acquired.recovered
    assert recovery.from_run == a.run_id
    assert recovery.inputs == ()
    assert (a.run_dir / INPUT_RECOVERY_FILE).exists()
    assert b.lease.release(None)
    assert [(line["by"], line["op"]) for line in env.log_lines()] == [("a", "down"), ("a", "up")]


def test_name_env_override(env: LeaseEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KOOKABUG_INPUT_LEASE_NAME", raising=False)
    monkeypatch.delenv("KOOKABUG_STATE_DIR", raising=False)
    assert lease_name() == DEFAULT_LEASE_NAME
    assert state_dir().name == "Kookabug"
    monkeypatch.setenv("KOOKABUG_INPUT_LEASE_NAME", env.name)
    monkeypatch.setenv("KOOKABUG_STATE_DIR", str(env.state_dir))
    assert lease_name() == env.name
    assert lease_file() == env.state_dir / "input-lease.json"
    lease = InputLease(LeaseOwner.current("runner"), FakeBackend(env.log))
    lease.acquire(0)
    assert mutex_busy(env.name)
    assert lease.file.exists()
    assert lease.release(None)


def test_stale_owner_file_reported_as_unknown(env: LeaseEnv, spawned: Spawned) -> None:
    # 뮤텍스는 옆 파일을 쓰지 않는 다른 프로세스가 쥐고, 옆 파일에는 이미 끝난 소유자가 있다
    me = current()
    stale = LeaseOwner("runner", ProcessId(me.pid, me.created + 1), run_id="gone0001").to_json()
    env.state_dir.mkdir(parents=True)
    lease_file(env.state_dir).write_text(
        json.dumps({"owner": stale, "clean": False}), encoding="utf-8"
    )
    wall = barrier(env.root / "held")
    holder = spawned.popen(
        python_cmd(PROCS_DIR / "hold_mutex.py", env.name, wall.path), env=direct_env(env.env)
    )
    wall.wait_ready()
    b = env.lease("b")
    with pytest.raises(InputLeaseBusy) as caught:
        b.lease.acquire(0)
    assert caught.value.owner is None
    assert caught.value.stale_owner == stale
    assert "알 수 없는" in str(caught.value)
    wall.go()
    assert holder.wait(30) == 0
