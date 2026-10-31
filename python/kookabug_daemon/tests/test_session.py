"""잠금·`session.json`·경쟁 (M2 계획 2.3, 검수 M2)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import DaemonProcess, ThreadDaemon, daemon_env, make_workspace
from kb_testing.proc import Spawned, barrier, faults_env, wait_until
from kookabug_core.schema import check_shape
from kookabug_core.win import ProcessId, identify
from kookabug_core.win import _kernel32 as k
from kookabug_daemon import session as sess
from kookabug_daemon.client import DaemonClient, attach, probe_session, spawn_daemon
from kookabug_daemon.session import DaemonLock, LockBusy, SessionInfo

pytestmark = pytest.mark.process


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return make_workspace(tmp_path / "ws")


def info_for(root: Path, *, pid: int, created: int, start_id: str = "a" * 32) -> SessionInfo:
    return SessionInfo(
        pid=pid,
        process_created=str(created),
        start_id=start_id,
        protocol=1,
        daemon_version="0.0.0",
        port=1,
        token="0" * 64,
        workspace=str(root),
        started_at="2026-10-31T00:00:00.000Z",
    )


def dead_ident(tmp_path: Path) -> ProcessId:
    """끝난 프로세스의 식별 (그 PID는 지금 없거나 다른 프로세스다)."""
    proc = subprocess.Popen(["cmd", "/c", "exit 0"], creationflags=subprocess.CREATE_NO_WINDOW)
    ident = identify(proc.pid)
    proc.wait(10)
    assert ident is not None or proc.returncode == 0
    return ident or ProcessId(proc.pid, 1)


def stop_via_client(root: Path) -> None:
    info = sess.read_session(root)
    assert info is not None
    with DaemonClient.from_session(info) as client:
        client.call("daemon.shutdown", {})


def session_files(root: Path) -> list[str]:
    return sorted(p.name for p in (root / ".kookabug").iterdir())


def test_session_json_fields_and_atomic(
    root: Path, tmp_path: Path, spawned: Spawned, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc = DaemonProcess.start(spawned, root, tmp_path / "d", env=daemon_env(tmp_path))
    line = proc.first_line()
    assert line["status"] == "started", proc.output()
    data = json.loads((root / ".kookabug" / "session.json").read_text("utf-8"))
    assert check_shape(data, "session") == []
    ident = identify(proc.pid)
    assert ident is not None
    assert (data["pid"], data["process_created"]) == (proc.pid, str(ident.created))
    assert data["protocol"] == 1 and data["workspace"] == str(root)
    assert data["port"] == line["session"]["port"]
    assert len(data["token"]) == 64 and len(data["start_id"]) == 32
    # --json 출력에는 토큰이 없다
    assert "token" not in line["session"] and data["token"] not in proc.stdout()
    assert {k: v for k, v in data.items() if k != "token"} == line["session"]
    # 임시 파일이 남지 않는다
    assert not [n for n in session_files(root) if n.endswith(".tmp")]
    stop_via_client(root)
    assert proc.wait() == 0
    assert not (root / ".kookabug" / "session.json").exists()

    # 원자적 쓰기: replace가 실패하면 기존 파일이 그대로이고 임시 파일도 남지 않는다
    old = info_for(root, pid=os.getpid(), created=1, start_id="b" * 32)
    sess.write_session(root, old)
    before = (root / ".kookabug" / "session.json").read_bytes()

    def broken(src: Any, dst: Any) -> None:
        raise PermissionError("주입한 실패")

    monkeypatch.setattr(sess.os, "replace", broken)
    monkeypatch.setattr(sess, "_REPLACE_TRIES", 2)
    with pytest.raises(PermissionError):
        sess.write_session(root, info_for(root, pid=os.getpid(), created=2, start_id="c" * 32))
    assert (root / ".kookabug" / "session.json").read_bytes() == before
    assert not [n for n in session_files(root) if n.endswith(".tmp")]


def test_two_daemons_race_one_wins_other_exits_0_with_session(
    root: Path, tmp_path: Path, spawned: Spawned
) -> None:
    env = daemon_env(tmp_path)
    procs = [DaemonProcess.start(spawned, root, tmp_path / f"d{i}", env=env) for i in range(2)]
    lines = [p.first_line() for p in procs]
    statuses = sorted(line["status"] for line in lines)
    assert statuses == ["already_running", "started"], [p.output() for p in procs]
    winner = next(p for p, line in zip(procs, lines, strict=True) if line["status"] == "started")
    loser = next(p for p in procs if p is not winner)
    assert loser.wait() == 0
    assert winner.alive()
    on_disk = sess.read_session(root)
    assert on_disk is not None and on_disk.pid == winner.pid
    assert {line["session"]["start_id"] for line in lines} == {on_disk.start_id}
    stop_via_client(root)
    assert winner.wait() == 0


def test_stale_session_json_replaced(root: Path, tmp_path: Path, spawned: Spawned) -> None:
    dead = dead_ident(tmp_path)
    stale = info_for(root, pid=dead.pid, created=dead.created)
    sess.write_session(root, stale)
    # 살아 있는 PID지만 생성 시각이 다르면 다른 프로세스다
    other = info_for(root, pid=os.getpid(), created=12345, start_id="d" * 32)
    assert not sess.session_alive(stale) and not sess.session_alive(other)

    proc = DaemonProcess.start(spawned, root, tmp_path / "d", env=daemon_env(tmp_path))
    line = proc.first_line()
    assert line["status"] == "started", proc.output()
    now = sess.read_session(root)
    assert now is not None and now.start_id != stale.start_id and now.pid == proc.pid
    assert sess.session_alive(now)
    stop_via_client(root)
    assert proc.wait() == 0


def _valid_fields(root: Path) -> dict[str, Any]:
    return info_for(root, pid=os.getpid(), created=1).to_json()


def _corrupt_values(root: Path) -> dict[str, bytes]:
    """스키마는 통과하거나 형식 검사에서 예외를 낼 수 있는 손상 (검수 T3_1)."""
    out: dict[str, bytes] = {"nested": b"[" * 2000 + b"]" * 2000}
    for name, change in {
        "float_pid": {"pid": float(os.getpid())},
        "float_port": {"port": 1.0},
        "long_created": {"process_created": "9" * 5000},
        "created_over_filetime": {"process_created": str(2**64)},
        "pid_over_dword": {"pid": 2**40},
        "unsafe_int": {"pid": 2**60},
    }.items():
        out[name] = json.dumps({**_valid_fields(root), **change}).encode("utf-8")
    return out


CORRUPT_VALUE_IDS = [
    "nested",
    "float_pid",
    "float_port",
    "long_created",
    "created_over_filetime",
    "pid_over_dword",
    "unsafe_int",
]


@pytest.mark.parametrize("which", CORRUPT_VALUE_IDS)
def test_corrupt_session_values_read_as_none(root: Path, which: str) -> None:
    path = sess.session_path(root)
    path.parent.mkdir()
    path.write_bytes(_corrupt_values(root)[which])
    assert sess.read_session(root) is None
    assert sess.wait_for_valid_session(root, lambda _: True, timeout=0) is None
    # 붙기 순서는 예외 없이 "daemon 띄우기"로 넘어간다
    spawned_roots: list[Path] = []
    assert attach(root, spawn=spawned_roots.append, probe=lambda _: True, timeout=0) is None
    assert spawned_roots == [root]
    # 값 변환이 실패하는 세션도 살아 있지 않은 것으로 본다
    weird = SessionInfo(**{**_valid_fields(root), "pid": 2**40})
    assert sess.session_alive(weird) is False


@pytest.mark.parametrize(
    "content",
    [b"{not json", b'{"format": "kookabug.session/0"}', b"\xff\xfe", b"[]", "nested", "long"],
    ids=["not_json", "missing_fields", "not_utf8", "not_object", "nested", "long_created"],
)
def test_corrupt_session_json_treated_stale(
    root: Path, tmp_path: Path, spawned: Spawned, content: bytes | str
) -> None:
    path = root / ".kookabug" / "session.json"
    path.parent.mkdir(parents=True)
    named = {"nested": "nested", "long": "long_created"}
    path.write_bytes(_corrupt_values(root)[named[content]] if isinstance(content, str) else content)
    assert sess.read_session(root) is None
    proc = DaemonProcess.start(spawned, root, tmp_path / "d", env=daemon_env(tmp_path))
    line = proc.first_line()
    assert line["status"] == "started", proc.output()
    now = sess.read_session(root)
    assert now is not None and now.start_id == line["session"]["start_id"]
    stop_via_client(root)
    assert proc.wait() == 0


def test_session_removed_only_by_owner(root: Path, tmp_path: Path, spawned: Spawned) -> None:
    mine = info_for(root, pid=os.getpid(), created=1, start_id="e" * 32)
    sess.write_session(root, mine)
    assert sess.remove_session(root, "f" * 32) is False
    assert sess.read_session(root) == mine
    assert sess.remove_session(root, mine.start_id) is True
    assert sess.read_session(root) is None

    # daemon이 끝날 때 session.json이 다른 start_id면 지우지 않는다
    proc = DaemonProcess.start(spawned, root, tmp_path / "d", env=daemon_env(tmp_path))
    line = proc.first_line()
    assert line["status"] == "started", proc.output()
    real = sess.read_session(root)
    assert real is not None
    with DaemonClient.from_session(real) as client:
        foreign = info_for(root, pid=os.getpid(), created=1, start_id="9" * 32)
        sess.write_session(root, foreign)
        client.call("daemon.shutdown", {})
    assert proc.wait() == 0
    assert sess.read_session(root) == foreign


def test_lock_released_when_killed(root: Path, tmp_path: Path, spawned: Spawned) -> None:
    env = daemon_env(tmp_path)
    first = DaemonProcess.start(spawned, root, tmp_path / "d1", env=env)
    assert first.first_line()["status"] == "started", first.output()
    with pytest.raises(LockBusy):
        DaemonLock.acquire(root)
    first.proc.kill()  # TerminateProcess: 정리 코드가 돌지 않는다
    first.wait()
    left = sess.read_session(root)
    assert left is not None and not sess.session_alive(left)  # 오래된 파일이 남는다

    second = DaemonProcess.start(spawned, root, tmp_path / "d2", env=env)
    line = second.first_line()
    assert line["status"] == "started", second.output()
    assert line["session"]["start_id"] != left.start_id
    stop_via_client(root)
    assert second.wait() == 0


def test_lock_handle_not_inherited(root: Path) -> None:
    # runner 등 자식이 잠금 핸들을 물려받아 daemon이 죽은 뒤에도 쥐지 않게
    with DaemonLock.acquire(root) as lock:
        assert not k.is_inheritable(lock.handle)


def test_loser_waits_for_valid_session_barrier(
    root: Path, tmp_path: Path, spawned: Spawned
) -> None:
    after_lock = barrier(tmp_path / "barriers" / "after_lock")
    before_publish = barrier(tmp_path / "barriers" / "before_publish")
    rules = [
        {"point": "daemon.after_lock", "role": "supervisor", "action": after_lock.action},
        {
            "point": "daemon.before_session_publish",
            "role": "supervisor",
            "action": before_publish.action,
        },
    ]
    # 옛 파일(죽은 daemon)이 남아 있는 상태에서 시작한다
    dead = dead_ident(tmp_path)
    old = info_for(root, pid=dead.pid, created=dead.created, start_id="1" * 32)
    sess.write_session(root, old)

    winner = DaemonProcess.start(
        spawned, root, tmp_path / "winner", env=faults_env(rules, daemon_env(tmp_path))
    )
    after_lock.wait_ready()
    loser = DaemonProcess.start(spawned, root, tmp_path / "loser", env=daemon_env(tmp_path))

    # 1. 이긴 쪽이 잠금만 쥐고 멈춤: 옛 파일만 있다. 진 쪽은 끝나지 않고 기다린다
    time.sleep(1.0)  # 기다리는 쪽이 옛 파일을 여러 번 읽을 시간 (0.1초 간격)
    assert loser.alive(), loser.output()
    assert loser.stdout() == ""

    # 2. 포트는 열렸지만 session.json을 공개하기 직전: 진 쪽은 계속 기다린다
    (root / ".kookabug" / "session.json").unlink()
    after_lock.go()
    before_publish.wait_ready()
    time.sleep(1.0)
    assert loser.alive(), loser.output()
    assert loser.stdout() == ""

    # 3. 공개하면 진 쪽은 유효한 세션(같은 start_id)을 확인하고 0으로 끝난다
    before_publish.go()
    win_line = winner.first_line()
    assert win_line["status"] == "started", winner.output()
    lose_line = loser.first_line()
    assert lose_line["status"] == "already_running", loser.output()
    assert lose_line["session"]["start_id"] == win_line["session"]["start_id"]
    assert loser.wait() == 0
    stop_via_client(root)
    assert winner.wait() == 0


def test_loser_timeout_exit_6(root: Path, tmp_path: Path, spawned: Spawned) -> None:
    after_lock = barrier(tmp_path / "barriers" / "after_lock")
    rules = [{"point": "daemon.after_lock", "role": "supervisor", "action": after_lock.action}]
    winner = DaemonProcess.start(
        spawned, root, tmp_path / "winner", env=faults_env(rules, daemon_env(tmp_path))
    )
    after_lock.wait_ready()
    started = time.monotonic()
    loser = DaemonProcess.start(
        spawned, root, tmp_path / "loser", "--session-wait-s", "1.5", env=daemon_env(tmp_path)
    )
    assert loser.wait() == 6, loser.output()
    assert time.monotonic() - started >= 1.5
    line = loser.first_line()
    assert line["status"] == "error" and "유효한 세션" in line["error"]
    after_lock.go()
    win_line = winner.first_line()
    assert win_line["status"] == "started", winner.output()
    stop_via_client(root)
    assert winner.wait() == 0


def test_lock_access_denied_is_error_not_race(root: Path, tmp_path: Path, spawned: Spawned) -> None:
    lock_file = root / ".kookabug" / "daemon.lock"
    lock_file.parent.mkdir(parents=True)
    lock_file.write_bytes(b"")
    user = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True
    ).stdout.strip()
    sid = user.split(",")[-1].strip('"')
    # 데이터 읽기·쓰기만 거부한다 (ACL 읽기·쓰기는 남겨 정리할 수 있게)
    subprocess.run(
        ["icacls", str(lock_file), "/deny", f"*{sid}:(RD,WD)"], check=True, capture_output=True
    )
    try:
        with pytest.raises(PermissionError):
            DaemonLock.acquire(root)
        started = time.monotonic()
        proc = DaemonProcess.start(spawned, root, tmp_path / "d", env=daemon_env(tmp_path))
        assert proc.wait() == 6, proc.output()
        # 경쟁으로 보고 15초를 기다리지 않는다
        assert time.monotonic() - started < 10
        line = proc.first_line()
        assert line["status"] == "error" and "잠금 파일" in line["error"]
        assert "daemon.lock" in line["error"]
    finally:
        subprocess.run(
            ["icacls", str(lock_file), "/remove:d", f"*{sid}"], check=True, capture_output=True
        )


def test_existing_daemon_transient_connect_failure_same_start_id_ok(
    root: Path, tmp_path: Path, spawned: Spawned
) -> None:
    env = daemon_env(tmp_path)
    proc = DaemonProcess.start(spawned, root, tmp_path / "d", env=env)
    line = proc.first_line()
    assert line["status"] == "started", proc.output()

    calls: list[str] = []

    def flaky(info: SessionInfo) -> bool:
        # 첫 연결은 일시적으로 실패한다 (같은 daemon은 살아 있다)
        calls.append(info.start_id)
        return len(calls) > 1 and probe_session(info)

    launched: list[subprocess.Popen[bytes]] = []

    def spawn(where: Path) -> None:
        child = spawn_daemon(
            where, command=[sys.executable, "-m", "kookabug_cli", "daemon", "--json"]
        )
        launched.append(spawned.track(child))

    found = attach(root, spawn=spawn, probe=flaky)
    assert found is not None and found.start_id == line["session"]["start_id"]
    assert calls[0] == found.start_id and len(calls) >= 2
    # 띄운 daemon은 경쟁에서 지고 "이미 실행 중"으로 끝난다
    assert len(launched) == 1 and launched[0].wait(30) == 0
    logs = list((root / ".kookabug" / "logs").glob("daemon-*-launch.log"))
    assert any("already_running" in p.read_text("utf-8") for p in logs)
    # 같은 start_id에 다시 붙는다
    with DaemonClient.from_session(found) as client:
        assert client.hello_result is not None
        assert client.hello_result["start_id"] == found.start_id
        client.call("daemon.shutdown", {})
    assert proc.wait() == 0


def test_thread_daemon_publishes_and_cleans(root: Path) -> None:
    with ThreadDaemon(root) as d:
        found = sess.read_session(root)
        assert found is not None and found == d.session
        assert probe_session(found)
    wait_until(lambda: sess.read_session(root) is None, timeout=10)
