"""복구 경로 `kookabug_core.recovery.recover` (구현 계획 M0b 2.7). 감독자 역할은 테스트 하네스."""

from __future__ import annotations

import contextlib
import ctypes
from collections.abc import Iterator
from pathlib import Path

import pytest
from helpers.graphs import GraphBuilder
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of

from kb_testing.proc import Spawned, barrier, direct_env, python_cmd
from kookabug_core.record import create_run_folder, read_run
from kookabug_core.recovery import RunnerStillAlive, recover
from kookabug_core.win import Job, Process, run_job_name

pytestmark = pytest.mark.process


def block_graph() -> GraphBuilder:
    return (
        tk()
        .entry("n_block")
        .node("n_block", "testkit.block", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def test_recover_waits_for_runner_identity_exit(tmp_path: Path, spawned: Spawned) -> None:
    h = RunnerHarness.make(tmp_path, block_graph()).start(spawned)
    h.wait_log("blocking")
    before = (h.run_dir / "events.jsonl").read_bytes()
    with pytest.raises(RunnerStillAlive):
        h.recover()
    # 확인 전에는 아무것도 쓰지 않았고 Job도 건드리지 않았다
    assert (h.run_dir / "events.jsonl").read_bytes() == before
    assert h.run_json() is not None and h.run_json()["status"] == "running"  # type: ignore[index]
    assert h.job is not None and not h.job.closed
    h.kill_runner()
    done = h.finish()
    assert done.exit_code == 1
    assert done.run_end is not None
    assert done.run_end["code"] == "runner_died" and done.run_end["finalized_by"] == "supervisor"
    assert done.run_end["runner_exit_code"] == 1
    _, end = step_of(done.view.events, "n_block")
    assert end is None  # 열린 스텝에는 step.end를 쓰지 않는다 (읽기가 "중단")
    assert done.view.steps[step_of(done.view.events, "n_block")[0]["step"]].status == "interrupted"
    assert done.run_json is not None and done.run_json["run_json_repaired"] is True


def test_recover_idempotent(tmp_path: Path, spawned: Spawned) -> None:
    h = RunnerHarness.make(tmp_path, block_graph()).start(spawned)
    h.wait_log("blocking")
    h.kill_runner()
    first = h.finish()
    size = (h.run_dir / "events.jsonl").stat().st_size
    again = h.recover()
    assert again.finalize.appended == []
    assert again.finalize.run_end == first.run_end
    assert (h.run_dir / "events.jsonl").stat().st_size == size
    assert [e["event"] for e in read_run(h.run_dir).events].count("run.end") == 1


def test_recover_noop_after_normal_runner_finish(tmp_path: Path, spawned: Spawned) -> None:
    graph = tk().entry("n_pass").node("n_pass", "core.test.pass")
    h = RunnerHarness.make(tmp_path, graph, plugin_modules=()).start(spawned)
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.recovered is not None
    assert done.recovered.finalize.appended == []
    assert done.recovered.finalize.input_recovery == "not_needed"
    assert done.recovered.finalize.run_json_repaired is False
    assert done.recovered.finalize.truncated_bytes == 0


def test_recover_keeps_existing_run_end(tmp_path: Path, spawned: Spawned) -> None:
    stall = barrier(tmp_path / "barriers" / "after_run_end")
    faults = [{"point": "runner.after_run_end", "role": "runner", "action": stall.action}]
    graph = tk().entry("n_pass").node("n_pass", "core.test.pass")
    h = RunnerHarness.make(tmp_path, graph, plugin_modules=(), faults=faults, hard_stop=False)
    h.start(spawned)
    stall.wait_ready()
    h.kill_runner()
    done = h.finish()
    assert done.run_end is not None
    # runner가 쓴 run.end를 runner_died로 덮지 않는다. run.json만 run.end에서 다시 만든다
    assert done.run_end["verdict"] == "pass" and done.run_end["finalized_by"] == "runner"
    assert done.of("run.end") == [done.run_end]
    assert done.run_json is not None
    assert done.run_json["verdict"] == "pass" and done.run_json["run_json_repaired"] is True
    assert done.recovered is not None and done.recovered.finalize.appended == []


def test_record_failure_still_cleans_job(tmp_path: Path, spawned: Spawned) -> None:
    # runner 종료를 확인한 뒤 기록 복구가 실패해도(다른 프로그램이 run.json을 공유 없이 엶) Job은
    # 끝내고 닫으며, 기록 오류는 호출자에게 그대로 간다 (검수 T9-1 R1)
    folder = create_run_folder(tmp_path / "runs", "tests/t.graph.json")
    job = Job.create(run_job_name(folder.run_id))
    sleep = python_cmd("-c", "import time; time.sleep(600)")
    runner_proc = spawned.popen(sleep, env=direct_env())
    member_proc = spawned.popen(sleep, env=direct_env())
    with (
        Process.open(runner_proc.pid, terminate=True) as runner,
        Process.open(member_proc.pid) as member,
    ):
        job.assign(member.pid)
        runner.terminate(1)
        assert runner.wait(10) == 1
        folder.run_json.write_text("{}", encoding="utf-8")
        with open_exclusive(folder.run_json):
            with pytest.raises(PermissionError):
                recover(
                    folder.path,
                    runner,
                    job,
                    backend=None,
                    seed={"run_id": folder.run_id, "graph": "tests/t.graph.json"},
                )
            assert job.closed
            assert not member.alive()


@contextlib.contextmanager
def open_exclusive(path: Path) -> Iterator[None]:
    """공유 모드 0으로 연다 (그동안 다른 쪽의 교체·쓰기는 공유 위반)."""
    handle = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    handle.restype = ctypes.c_void_p
    handle.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    raw = handle(str(path), 0x80000000, 0, None, 3, 0x80, None)  # GENERIC_READ, OPEN_EXISTING
    assert raw not in (None, ctypes.c_void_p(-1).value)
    close = ctypes.WinDLL("kernel32").CloseHandle
    close.argtypes = (ctypes.c_void_p,)
    try:
        yield
    finally:
        close(raw)
