"""`kb_testing.sample_game` 헬퍼 (구현 계획 M1 2.13)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kb_testing.proc import wait_until
from kb_testing.pytest_plugin import session_job
from kb_testing.sample_game import is_window, launch_sample_game, window_pid
from kookabug_core.win import Job

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


def test_wait_event_fails_fast_when_game_exits(tmp_path: Path) -> None:
    game = launch_sample_game(
        ("--font", "kookabug-missing-font"), workdir=tmp_path, wait_ready=False
    )
    with game, pytest.raises(AssertionError, match="끝났다"):
        game.wait_ready(timeout=30)
