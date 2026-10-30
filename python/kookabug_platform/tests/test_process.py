"""게임 띄우기·닫기와 실행 Job (구현 계획 M1 2.2, 3장 "프로세스 정리").

runner 역할은 하위 프로세스(`_RUNNER`)가 한다: 이름 있는 Job을 열어 자기를 넣고(실제 runner와 같은
순서) 그 안에서 `launch`한다. 그래서 띄운 게임이 **생성 시점부터** Job 소속인지 본다.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kb_testing.proc import direct_env, python_cmd, wait_until
from kb_testing.sample_game import GAME_DIR, game_command, game_env
from kookabug_core.win import Job, Process
from kookabug_platform.errors import LAUNCH_FAILED, PlatformError
from kookabug_platform.process import (
    _environment_block,  # pyright: ignore[reportPrivateUsage]
    candidate_pids,
    close,
    launch,
    process_windows,
    wait_window,
)
from kookabug_platform.windows import find_window

pytestmark = pytest.mark.process

# runner 흉내: Job에 들어간 뒤 launch, 띄운 PID를 알리고 stdin이 닫힐 때까지 산다
_RUNNER = """
import json, sys
from kookabug_core.win import Job
from kookabug_platform.process import launch
req = json.loads(sys.argv[1])
job = Job.open(req["job"])
job.assign_current()
proc = launch(req["path"], req["args"], cwd=req["cwd"], env=req["env"])
print(json.dumps({"pid": proc.pid, "created": proc.created, "in_job": job.contains(proc.pid)}),
      flush=True)
sys.stdin.read()
"""

# 런처 흉내: 게임을 자식으로 띄우고 바로 끝난다 (창은 자식이 만든다)
_LAUNCHER = """
import json, subprocess, sys
req = json.loads(sys.argv[1])
subprocess.Popen(req["cmd"], cwd=req["cwd"], env=req["env"], creationflags=0x08000000)
"""


def wait_ready(event_log: Path, timeout: float = 20.0) -> dict[str, Any]:
    def ready() -> dict[str, Any] | None:
        if not event_log.exists():
            return None
        for line in event_log.read_text(encoding="utf-8").splitlines():
            if line.strip() and (record := json.loads(line))["event"] == "ready":
                return record
        return None

    found = wait_until(ready, timeout=timeout, message=lambda: f"{event_log} ready 없음")
    assert found is not None
    return found


def game_args(event_log: Path, title: str) -> list[str]:
    return game_command("--event-log", event_log, "--title", title)[1:]


class FakeRunner:
    """Job 안에서 launch하는 runner 흉내 프로세스."""

    def __init__(self, job_name: str, path: str, args: list[str], env: dict[str, str]) -> None:
        req = {"job": job_name, "path": path, "args": args, "cwd": str(GAME_DIR), "env": env}
        self.proc = subprocess.Popen(
            python_cmd("-c", _RUNNER, json.dumps(req)),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=direct_env(),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if not line:
            raise AssertionError(self.proc.communicate(timeout=10)[1].decode(errors="replace"))
        self.launched: dict[str, Any] = json.loads(line)

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.communicate(timeout=10)


@pytest.fixture
def run_job() -> Iterator[Job]:
    job = Job.create(f"Local\\Kookabug.Test.{uuid.uuid4().hex}")
    try:
        yield job
    finally:
        if not job.closed:
            job.terminate()
            job.close()


@pytest.mark.desktop
def test_launch_in_run_job_and_killed_with_job(tmp_path: Path, run_job: Job) -> None:
    assert run_job.name is not None
    event_log = tmp_path / "game.events.jsonl"
    title = f"KBT3 job {uuid.uuid4().hex[:6]}"
    runner = FakeRunner(run_job.name, game_command()[0], game_args(event_log, title), game_env())
    try:
        launched = runner.launched
        ready = wait_ready(event_log)
        assert ready["pid"] == launched["pid"]
        # 띄운 순간부터 실행 Job 소속 (runner가 Job 안이고 BREAKAWAY가 없다)
        assert launched["in_job"] is True and run_job.contains(launched["pid"])
        game = Process.open(launched["pid"])
        try:
            assert game.created == launched["created"]
            # runner가 죽고(그 Job 핸들이 닫힘) 감독자도 Job 핸들을 닫으면 게임도 끝난다
            runner.kill()
            assert game.alive()
            run_job.close()
            assert game.wait(10) is not None
        finally:
            game.close()
    finally:
        runner.kill()


@pytest.mark.desktop
def test_window_found_from_child_of_launcher(tmp_path: Path, run_job: Job) -> None:
    assert run_job.name is not None
    event_log = tmp_path / "game.events.jsonl"
    title = f"KBT3 launcher {uuid.uuid4().hex[:6]}"
    req = {
        "cmd": game_command("--event-log", event_log, "--title", title),
        "cwd": str(GAME_DIR),
        "env": game_env(),
    }
    runner = FakeRunner(
        run_job.name, game_command()[0], ["-c", _LAUNCHER, json.dumps(req)], direct_env()
    )
    try:
        launcher_pid = runner.launched["pid"]
        ready = wait_ready(event_log)
        game_pid = ready["pid"]
        assert game_pid != launcher_pid and run_job.contains(game_pid)
        # 띄운 프로세스(런처)만 보면 창이 없다. 실행 Job 안 전부에서 찾으면 게임 창이 나온다
        assert find_window(title=title, pids=[launcher_pid]) is None
        assert launcher_pid in candidate_pids(launcher_pid, run_job)[:1]
        hwnd = wait_window(lambda: candidate_pids(launcher_pid, run_job), title=title, timeout=10)
        assert hwnd == ready["hwnd"]
        assert wait_window(lambda: [launcher_pid], title=title, timeout=0.2) is None
    finally:
        runner.kill()


@pytest.mark.desktop
def test_close_graceful_then_force(tmp_path: Path) -> None:
    event_log = tmp_path / "game.events.jsonl"
    title = f"KBT3 close {uuid.uuid4().hex[:6]}"
    # 이 검사 프로세스(테스트 세션 Job 안)에서 띄우면 게임도 세션 Job 소속
    game = launch(game_command()[0], game_args(event_log, title), cwd=GAME_DIR, env=game_env())
    try:
        ready = wait_ready(event_log)
        assert process_windows(game.pid) == [ready["hwnd"]]
        assert close(game, 10_000) is True  # WM_CLOSE로 끝남
        assert game.exit_code() == 0
        assert close(game, 10) is True  # 이미 끝난 프로세스
    finally:
        if game.alive():
            game.terminate()
        game.close()
    # 창이 없는 프로세스: WM_CLOSE를 보낼 곳이 없으니 바로 강제 종료
    sleeper = launch(game_command()[0], ["-c", "import time; time.sleep(60)"], env=direct_env())
    try:
        assert close(sleeper, 5_000) is False
        assert sleeper.exit_code() == 1
    finally:
        if sleeper.alive():
            sleeper.terminate()
        sleeper.close()


@pytest.mark.desktop
def test_close_forces_when_window_ignores_wm_close(tmp_path: Path) -> None:
    # 창은 있지만 WM_CLOSE를 무시한다(창 프로시저가 기본 처리하지 않음) → 기한 뒤 강제 종료
    script = (
        "import tkinter as tk, sys; r = tk.Tk(); r.title(sys.argv[1]);"
        "r.protocol('WM_DELETE_WINDOW', lambda: None); r.mainloop()"
    )
    title = f"KBT3 stubborn {uuid.uuid4().hex[:6]}"
    proc = launch(game_command()[0], ["-c", script, title], env=game_env())
    try:
        wait_window(lambda: [proc.pid], title=title, timeout=20)
        assert close(proc, 300) is False
        assert proc.exit_code() == 1
    finally:
        if proc.alive():
            proc.terminate()
        proc.close()


@pytest.mark.parametrize(
    "value",
    ["plain", "한글 값", "\U0001f600 이모지", "a\U00020000b"],
    ids=["ascii", "bmp", "emoji", "cjk-ext-b"],
)
def test_launch_passes_environment_including_non_bmp(value: str) -> None:
    # 비 BMP 글자(UTF-16 대리쌍)가 든 환경 값도 자식에 그대로 간다
    env = {"SYSTEMROOT": os.environ["SYSTEMROOT"], "KB_T3_VALUE": value}
    check = "import os, sys; sys.exit(0 if os.environ['KB_T3_VALUE'] == sys.argv[1] else 7)"
    proc = launch(game_command()[0], ["-c", check, value], env=direct_env(env))
    try:
        assert proc.wait(20) == 0
    finally:
        if proc.alive():
            proc.terminate()
        proc.close()


def test_environment_block_layout() -> None:
    assert "".join(_environment_block({})[:]) == "\0\0"  # 빈 환경도 이중 NUL
    raw = _environment_block({"b": "\U0001f600", "A": "1"})
    block = "".join(raw[:])
    # 버퍼 길이는 UTF-16 단위: "A=1␀b=" 6 + 이모지 2 + NUL 3
    assert ctypes.sizeof(raw) // ctypes.sizeof(ctypes.c_wchar) == 6 + 2 + 3
    # 이름순(대소문자 무시), 항목마다 NUL, 끝은 이중 NUL. 이모지는 UTF-16 두 단위
    assert block.startswith("A=1\0b=") and block.endswith("\0\0")
    assert "\U0001f600" in block


def test_launch_failed_code(tmp_path: Path) -> None:
    for path in (tmp_path / "no-such-game.exe", tmp_path):  # 없는 파일, 폴더
        with pytest.raises(PlatformError) as info:
            launch(path)
        assert info.value.code == LAUNCH_FAILED
        assert str(path) in info.value.message and "Win32 오류" in info.value.message
