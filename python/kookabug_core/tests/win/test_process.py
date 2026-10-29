"""프로세스 식별·살아 있음·종료 코드·자식 띄우기 (구현 계획 M0b 2.3)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from kb_testing.proc import Spawned
from kookabug_core.win import CHILD_FLAGS, Process, ProcessId, current, identify, is_alive, spawn


def test_identity_detects_pid_reuse() -> None:
    me = current()
    assert me.pid == os.getpid()
    assert identify(me.pid) == me
    assert is_alive(me)
    # 같은 PID라도 생성 시각이 다르면 다른 프로세스다 (PID 재사용)
    reused = ProcessId(me.pid, me.created + 1)
    assert not is_alive(reused)
    with pytest.raises(ProcessLookupError):
        Process.open(reused)
    assert ProcessId.from_json(me.to_json()) == me


@pytest.mark.process
def test_alive_and_exit_code(spawned: Spawned) -> None:
    child = spawned.popen(
        [sys.executable, "-c", "import sys; sys.stdin.read(); sys.exit(7)"], stdin=subprocess.PIPE
    )
    ident = identify(child.pid)
    assert ident is not None
    with Process.open(ident) as proc:
        assert proc.alive() and is_alive(ident)
        assert proc.exit_code() is None
        assert proc.wait(0) is None
        assert child.stdin is not None
        child.stdin.close()
        assert proc.wait(30) == 7
        assert not proc.alive()
        assert proc.exit_code() == 7
    child.wait(30)
    assert not is_alive(ident)


@pytest.mark.process
def test_terminate_sets_exit_code(spawned: Spawned) -> None:
    child = spawned.popen([sys.executable, "-c", "import time; time.sleep(600)"])
    with Process.open(child.pid, terminate=True) as proc:
        proc.terminate(4)
        assert proc.wait(30) == 4
        proc.terminate(5)  # 이미 끝났으면 아무것도 하지 않는다
        assert proc.exit_code() == 4


@pytest.mark.process
def test_spawn_redirects_to_files(tmp_path: Path, spawned: Spawned) -> None:
    out, err = tmp_path / "logs/child.stdout.log", tmp_path / "logs/child.stderr.log"
    code = (
        "import sys\n"
        "sys.stdout.buffer.write('출력\\n'.encode())\n"
        "sys.stderr.buffer.write('오류\\n'.encode())\n"
    )
    proc = spawned.track(spawn([sys.executable, "-c", code], stdout=out, stderr=err))
    assert proc.wait(timeout=30) == 0
    assert out.read_text(encoding="utf-8") == "출력\n"
    assert err.read_text(encoding="utf-8") == "오류\n"
    assert CHILD_FLAGS & subprocess.CREATE_NEW_PROCESS_GROUP
    assert CHILD_FLAGS & subprocess.CREATE_NO_WINDOW
