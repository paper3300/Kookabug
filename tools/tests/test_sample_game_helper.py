"""`kb_testing.sample_game` 헬퍼 (구현 계획 M1 2.13)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from kb_testing.proc import TOOLS_DIR, assert_no_live, direct_env, python_cmd, wait_until
from kb_testing.pytest_plugin import session_job
from kb_testing.sample_game import is_window, launch_job, launch_sample_game, window_pid
from kookabug_core.win import Job, identify, is_alive

pytestmark = pytest.mark.desktop


def test_launch_in_session_job_waits_window_and_closes(tmp_path: Path) -> None:
    game = launch_sample_game((), workdir=tmp_path)
    with game:
        # 테스트 하네스의 세션 Job 안 (runner 실행 Job과는 따로)
        assert session_job().contains(game.pid)
        assert game.ready["pid"] == game.pid
        assert is_window(game.hwnd) and window_pid(game.hwnd) == game.pid
        assert game.wait_screen("title")["seq"] > game.ready["seq"]
        hwnd = game.hwnd
        assert game.close() == 0
    assert game.proc.poll() == 0
    assert game.events()[-1]["event"] == "exit"
    wait_until(lambda: not is_window(hwnd), timeout=5, message="창이 남아 있다")


def test_launch_into_given_job(tmp_path: Path) -> None:
    job = Job.create(kill_on_close=True)
    try:
        game = launch_sample_game((), workdir=tmp_path, job=job)
        with game:
            assert job.contains(game.pid) and session_job().contains(game.pid)
        assert game.proc.poll() is not None
        # 이미 끝난 게임을 다시 닫아도 된다
        assert game.close() == game.proc.returncode
    finally:
        job.close()


_CHILD_LAUNCH = """
import os, time
from pathlib import Path
from kb_testing.sample_game import launch_sample_game

def launch_and_hang():
    out = Path(os.environ["KB_CHILD_OUT"])
    game = launch_sample_game(("--title", "KB orphan check"), workdir=out)
    (out / "game.pid").write_text(str(game.pid), encoding="utf-8")
    time.sleep(120)  # 부모가 이 프로세스를 강제로 끝낸다 (정리 코드가 돌지 않음)
"""


@pytest.mark.parametrize("child", ["pytest", "script"])
def test_game_dies_when_launching_process_is_killed(tmp_path: Path, child: str) -> None:
    # 게임을 띄운 프로세스(하위 pytest·pytest 밖 스크립트)가 네이티브 크래시처럼 정리 없이 죽어도
    # 게임이 남지 않는다 — 세션 Job / launch_job의 KILL_ON_JOB_CLOSE (T4-4 추가 지시)
    out = tmp_path / "child"
    out.mkdir()
    if child == "pytest":
        source = tmp_path / "test_child_game.py"
        source.write_text(
            _CHILD_LAUNCH + "\ndef test_hang():\n    launch_and_hang()\n", encoding="utf-8"
        )
        cmd = python_cmd(
            "-m",
            "pytest",
            source,
            "-p",
            "no:cacheprovider",
            "-p",
            "kb_testing.pytest_plugin",
            "--rootdir",
            tmp_path,
            "-q",
            "-p",
            "no:timeout",
        )
    else:
        source = tmp_path / "child_game.py"
        source.write_text(_CHILD_LAUNCH + "\nlaunch_and_hang()\n", encoding="utf-8")
        cmd = python_cmd(source)
    env = direct_env({**os.environ, "PYTHONPATH": str(TOOLS_DIR), "KB_CHILD_OUT": str(out)})
    proc = subprocess.Popen(
        cmd, cwd=tmp_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    try:
        pid_file = out / "game.pid"
        wait_until(
            lambda: pid_file.exists() or proc.poll() is not None,
            timeout=30,
            message="하위 프로세스가 게임을 띄우지 못했다",
        )
        assert proc.poll() is None, proc.stderr.read() if proc.stderr else b""
        game = identify(int(pid_file.read_text(encoding="utf-8")))
        assert game is not None and is_alive(game)
        proc.kill()  # TerminateProcess: 하위 프로세스의 정리 코드·fixture가 돌지 않는다
        proc.wait(10)
        assert_no_live([game], timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(10)


def test_launch_job_in_pytest_is_session_job() -> None:
    # pytest 안에서는 세션 Job을 그대로 쓴다 (밖은 위 "script" 경우가 본다)
    assert launch_job() is session_job()


def test_wait_event_fails_fast_when_game_exits(tmp_path: Path) -> None:
    game = launch_sample_game(
        ("--font", "kookabug-missing-font"), workdir=tmp_path, wait_ready=False
    )
    with game, pytest.raises(AssertionError, match="끝났다"):
        game.wait_ready(timeout=30)
