"""프로세스 테스트 기반: 헬퍼·세션 Job·정리 픽스처 (구현 계획 M0b 2.3·2.12)."""

import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from kb_testing.proc import (
    Spawned,
    assert_no_live,
    barrier,
    faults_env,
    inner_pytest,
    isolated_env,
    read_fake_input_log,
    wait_until,
)
from kb_testing.pytest_plugin import session_job
from kookabug_core.win import Job, ProcessId


def test_wait_until_returns_value() -> None:
    calls = iter([0, None, "ok"])
    assert wait_until(lambda: next(calls), interval=0) == "ok"


def test_wait_until_times_out_with_message() -> None:
    with pytest.raises(AssertionError, match=r"0\.05초 안에 조건이 맞지 않았다: 장벽 X"):
        wait_until(lambda: False, timeout=0.05, message="장벽 X")
    with pytest.raises(AssertionError, match="늦게 만든 설명"):
        wait_until(lambda: False, timeout=0, message=lambda: "늦게 만든 설명")


@pytest.mark.process
def test_barrier_ready_and_go(tmp_path: Path, spawned: Spawned) -> None:
    gate = barrier(tmp_path / "b/one")
    rule = {"point": "runner.after_hello", "role": "runner", "action": gate.action}
    code = (
        "from kookabug_sdk import _faults\n"
        "_faults.set_role('runner')\n"
        "_faults.fault_point('runner.after_hello')\n"
    )
    proc = spawned.popen([sys.executable, "-c", code], env=faults_env([rule]))
    gate.wait_ready()
    assert proc.poll() is None  # go 전에는 지나가지 않는다
    gate.go()
    assert proc.wait(timeout=30) == 0


@pytest.mark.process
def test_session_job_contains_pytest(spawned: Spawned) -> None:
    job = session_job()
    assert job.contains()
    assert os.getpid() in job.process_ids()
    assert not job.inheritable
    # 테스트가 띄우는 프로세스는 생성 시점부터 세션 Job 소속이다
    child = spawned.popen([sys.executable, "-c", "import time; time.sleep(600)"])
    assert job.contains(child.pid)
    # 세션 Job 핸들은 Python이 닫지 않는다 (닫으면 pytest가 끝난다)
    with pytest.raises(ValueError, match="keep_until_exit"):
        job.close()
    assert not job.closed


def test_keep_until_exit_handle_not_closed_by_finalizer() -> None:
    job = Job.create(kill_on_close=False).keep_until_exit()
    handle = job.handle
    del job  # 소멸자가 닫지 않는다
    assert Job(handle, None).process_ids() == []  # 핸들이 아직 유효하다


@pytest.mark.process
def test_cleanup_fixture_kills_leftovers(tmp_path: Path) -> None:
    # 같은 pytest 프로세스 안에서 앞 테스트가 남긴 프로세스가 다음 테스트 전에 끝났는지 본다.
    # 세션 Job은 pytest가 끝날 때만 정리하므로, 여기서 끝났다면 정리 픽스처가 끝낸 것이다
    test_file = tmp_path / "test_inner_cleanup.py"
    test_file.write_text(
        textwrap.dedent(
            """
            from kb_testing.proc import python_cmd
            from kookabug_core.win import ProcessId, identify, is_alive

            LEFT: list[ProcessId] = []

            def test_leave_processes(spawned):
                for _ in range(2):
                    child = spawned.popen(python_cmd("-c", "import time; time.sleep(600)"))
                    LEFT.append(identify(child.pid))
                assert all(is_alive(i) for i in LEFT)

            def test_previous_processes_gone():
                assert len(LEFT) == 2
                assert not any(is_alive(i) for i in LEFT)
            """
        ),
        encoding="utf-8",
    )
    result = inner_pytest(test_file)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout


# 세션 Job은 pytest 자신이 든 KILL_ON_JOB_CLOSE Job이다. 인터프리터 종료 중에 Python이 그 핸들을
# 닫으면 pytest가 그 순간 강제 종료돼 종료 코드가 0으로 바뀐다 (검수 T5 1차 High)
EXIT_CASES = {
    "passed": ("def test_ok():\n    assert session_job().contains()\n", (), 0, "1 passed"),
    "failed": ("def test_fail():\n    assert False, 'deliberate'\n", (), 1, "1 failed"),
    "collection_error": ("import no_such_module_kb_test\n", (), 2, "1 error"),
    "usage_error": ("def test_ok():\n    pass\n", ("--no-such-option-kb",), 4, ""),
}


@pytest.mark.process
@pytest.mark.parametrize("case", list(EXIT_CASES))
def test_inner_pytest_exit_code_preserved(case: str, tmp_path: Path) -> None:
    body, args, expected, summary = EXIT_CASES[case]
    test_file = tmp_path / "test_inner_exit.py"
    test_file.write_text(
        "from kb_testing.pytest_plugin import session_job\n\n" + body, encoding="utf-8"
    )
    result = inner_pytest(test_file, *args)
    detail = result.stdout + result.stderr
    assert result.returncode == expected, detail
    assert summary in result.stdout, detail


@pytest.mark.process
def test_failed_run_keeps_exit_code_and_cleans_descendants(tmp_path: Path) -> None:
    # 실패로 정상 종료할 때도 종료 코드는 1이고, 남은 자손은 OS가 세션 Job을 닫으며 끝낸다
    ident_file = tmp_path / "child.json"
    test_file = tmp_path / "inner" / "test_inner_fail.py"
    test_file.parent.mkdir()
    test_file.write_text(
        textwrap.dedent(
            f"""
            import json, subprocess
            from pathlib import Path
            from kb_testing.proc import python_cmd
            from kookabug_core.win import identify

            def test_fail_leaving_child():
                child = subprocess.Popen(python_cmd("-c", "import time; time.sleep(600)"))
                Path({str(ident_file)!r}).write_text(json.dumps(identify(child.pid).to_json()))
                assert False, "deliberate"
            """
        ),
        encoding="utf-8",
    )
    result = inner_pytest(test_file)
    assert result.returncode == 1, result.stdout + result.stderr
    child = ProcessId.from_json(json.loads(ident_file.read_text(encoding="utf-8")))
    assert_no_live([child])


def test_isolated_env_strips_outer_settings(tmp_path: Path) -> None:
    outer = {"PATH": "x", "KOOKABUG_AGENT": "a", "kookabug_faults": "[]", "OTHER": "1"}
    env = isolated_env(tmp_path, outer, KOOKABUG_SECRET_X="s")
    assert env["PATH"] == "x" and env["OTHER"] == "1"
    assert "KOOKABUG_AGENT" not in env and "kookabug_faults" not in env
    assert env["KOOKABUG_STATE_DIR"] == str(tmp_path / "state")
    assert env["KOOKABUG_USER_CONFIG_DIR"] == str(tmp_path / "user-config")
    assert env["KOOKABUG_SECRET_X"] == "s"
    other = isolated_env(tmp_path, outer)
    assert env["KOOKABUG_INPUT_LEASE_NAME"].startswith("Local\\Kookabug.InputLease.test-")
    assert env["KOOKABUG_INPUT_LEASE_NAME"] != other["KOOKABUG_INPUT_LEASE_NAME"]


def test_read_fake_input_log_drops_partial_tail(tmp_path: Path) -> None:
    path = tmp_path / "input.jsonl"
    assert read_fake_input_log(path) == []
    path.write_bytes(b'{"op": "down", "key": "a"}\n{"op": "up", "key": "a"}\n{"op": "do')
    assert [e["op"] for e in read_fake_input_log(path)] == ["down", "up"]
