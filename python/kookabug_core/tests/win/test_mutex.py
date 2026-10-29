"""이름 있는 뮤텍스 (구현 계획 M0b 2.3·2.4)."""

import sys
import threading
import uuid
from pathlib import Path

import pytest

from kb_testing.proc import PROCS_DIR, Spawned, barrier
from kookabug_core.win import NamedMutex, WaitResult

pytestmark = pytest.mark.process


def mutex_name() -> str:
    return f"Local\\Kookabug.Test.{uuid.uuid4().hex}"


def test_abandoned_wait_result(tmp_path: Path, spawned: Spawned) -> None:
    name = mutex_name()
    gate = barrier(tmp_path / "held")
    holder = spawned.popen([sys.executable, PROCS_DIR / "hold_mutex.py", name, gate.path])
    with NamedMutex.open(name) as mutex:
        gate.wait_ready()
        assert mutex.wait(0) is WaitResult.TIMEOUT
        gate.go()
        assert holder.wait(timeout=30) == 0
        # 놓지 않고 끝난 프로세스의 뮤텍스: 얻었지만 앞 소유자가 버렸다
        assert mutex.wait(0) is WaitResult.ABANDONED
        mutex.release()
        assert mutex.wait(0) is WaitResult.ACQUIRED
        mutex.release()


def test_release_from_owner_thread_only() -> None:
    with NamedMutex.open(mutex_name()) as mutex:
        assert mutex.wait(0) is WaitResult.ACQUIRED
        errors: list[BaseException] = []
        seen: list[WaitResult] = []

        def other() -> None:
            seen.append(mutex.wait(0))
            try:
                mutex.release()
            except PermissionError as exc:
                errors.append(exc)

        thread = threading.Thread(target=other)
        thread.start()
        thread.join(timeout=30)
        # 다른 스레드는 얻지도 놓지도 못한다
        assert seen == [WaitResult.TIMEOUT]
        assert len(errors) == 1
        mutex.release()
        with pytest.raises(PermissionError):
            mutex.release()
