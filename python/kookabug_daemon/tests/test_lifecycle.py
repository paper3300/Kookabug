"""daemon 수명: 유휴 종료·shutdown·DPI (M2 계획 2.3)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from kb_testing.daemon import DaemonProcess, FakeRuns, ThreadDaemon, daemon_env, make_workspace
from kb_testing.proc import Spawned
from kookabug_daemon import session as sess
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = pytest.mark.process


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return make_workspace(tmp_path / "ws")


def test_idle_timeout_exits_without_clients_and_runs(
    root: Path, tmp_path: Path, spawned: Spawned
) -> None:
    started = time.monotonic()
    proc = DaemonProcess.start(
        spawned, root, tmp_path / "d", "--idle-timeout-s", "1", env=daemon_env(tmp_path)
    )
    assert proc.first_line()["status"] == "started", proc.output()
    assert proc.wait(30) == 0, proc.output()
    assert time.monotonic() - started >= 1.0
    assert sess.read_session(root) is None  # 자기 session.json을 지웠다
    logs = list((root / ".kookabug" / "logs").glob("daemon-*.log"))
    assert any("유휴 1초" in p.read_text("utf-8") for p in logs)


def test_idle_timer_reset_by_connection(root: Path) -> None:
    runs = FakeRuns()
    with ThreadDaemon(root, runs=runs, idle_timeout_s=0.6) as d:
        client = d.client()
        time.sleep(1.5)  # 연결이 있는 동안은 유휴가 아니다
        assert d.is_running()
        client.close()
        assert d.finished(10) == "유휴 0.6초"

    # 진행 중인 실행이 있어도 유휴가 아니다
    runs = FakeRuns(active="abcd1234")
    with ThreadDaemon(root, runs=runs, idle_timeout_s=0.4) as d:
        time.sleep(1.2)
        assert d.is_running()
        runs.active = None
        assert d.finished(10) == "유휴 0.4초"
        assert not runs.cancelled.is_set()


def test_shutdown_refused_with_active_run_unless_force(root: Path) -> None:
    runs = FakeRuns(active="abcd1234")
    with ThreadDaemon(root, runs=runs) as d:
        with d.client() as client:
            with pytest.raises(DaemonError) as caught:
                client.call("daemon.shutdown", {})
            assert caught.value.kind == "run_active"
            assert caught.value.data["run_id"] == "abcd1234"
            assert d.is_running() and not runs.cancelled.is_set()
            # force: 실행을 취소하고 마무리를 기다린 뒤 끝낸다. 응답은 받는다
            assert client.call("daemon.shutdown", {"force": True}) == {}
            assert d.finished(10) == "daemon.shutdown"
            assert runs.cancelled.is_set()
            client.wait_closed(10)
        assert sess.read_session(root) is None


def test_shutdown_without_runs_and_new_connections_refused(root: Path) -> None:
    with ThreadDaemon(root) as d:
        info = d.session
        with d.client() as client:
            assert client.call("daemon.shutdown", {}) == {}
            assert client.wait_closed(10) == 1001
        assert d.finished(10) == "daemon.shutdown"
    with pytest.raises(OSError):
        DaemonClient.connect(info.port, info.token, timeout=2)


def test_dpi_set_at_startup(root: Path, tmp_path: Path, spawned: Spawned) -> None:
    proc = DaemonProcess.start(
        spawned, root, tmp_path / "d", "--idle-timeout-s", "1", env=daemon_env(tmp_path)
    )
    line = proc.first_line()
    assert line["status"] == "started", proc.output()
    assert (line["dpi_awareness"], line["dpi_error"]) == ("per_monitor_v2", None)
    assert proc.wait(30) == 0
    assert "DPI 인식: per_monitor_v2" in Path(line["log"]).read_text("utf-8")
