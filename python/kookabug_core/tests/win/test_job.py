"""Job Object (구현 계획 M0b 2.3 "실행 Job 수명")."""

import subprocess
import uuid
from pathlib import Path

import pytest

from kb_testing.proc import (
    PROCS_DIR,
    Spawned,
    assert_no_live,
    direct_env,
    python_cmd,
    read_tree,
    wait_until,
)
from kookabug_core.win import Job, Process, ProcessId, run_job_name

pytestmark = pytest.mark.process

TREE = PROCS_DIR / "tree.py"


def job_name() -> str:
    return run_job_name(f"test-{uuid.uuid4().hex}")


def start_tree(
    spawned: Spawned, out: Path, depth: int, job: str | None = None
) -> dict[int, ProcessId]:
    """사슬을 런처 없이 띄우고 단계마다 식별을 모은다. 모두 정리 대상에 넣는다."""
    out.mkdir(parents=True, exist_ok=True)
    cmd = python_cmd(TREE, "--out", out, "--depth", str(depth))
    if job:
        cmd += ["--job", job]
    spawned.popen(cmd, env=direct_env())
    wait_until(
        lambda: len(read_tree(out)) == depth,
        message=lambda: f"사슬이 다 뜨지 않았다: {read_tree(out)}",
    )
    tree = read_tree(out)
    idents = {level: ProcessId(r["pid"], r["created"]) for level, r in tree.items()}
    for ident in idents.values():
        spawned.track(ident)
    return idents


def sleeper(spawned: Spawned) -> subprocess.Popen[bytes]:
    return spawned.popen(python_cmd("-c", "import time; time.sleep(600)"))


def test_child_dies_when_all_handles_closed(spawned: Spawned) -> None:
    job = Job.create(job_name())
    child = sleeper(spawned)
    job.assign(child.pid)
    assert job.contains(child.pid)
    job.close()
    assert child.wait(timeout=30) is not None


def runner_dies_after_supervisor_closed(
    tmp_path: Path, spawned: Spawned, *, kill_on_close: bool, worker_wait: float
) -> int | None:
    """감독자(이 테스트)가 Job을 만들고 runner(사슬 맨 위)가 이름으로 열어 자기를 넣은 뒤 워커를
    띄운다 — 핸들은 이 둘뿐이다(워커는 소속만 확인하고 닫는다). 감독자가 먼저 닫고 runner를 죽인
    뒤 워커가 끝나기를 `worker_wait`초 기다린 결과(종료 코드, 살아 있으면 None)."""
    name = job_name()
    job = Job.create(name, kill_on_close=kill_on_close)
    tree = start_tree(spawned, tmp_path / "tree", depth=2, job=name)
    assert set(job.process_ids()) == {tree[0].pid, tree[1].pid}  # 런처 없음
    job.close()
    with (
        Process.open(tree[0], terminate=True) as runner,
        Process.open(tree[1]) as worker,
    ):
        # runner의 핸들이 남아 있으므로 Job이 끝내지 않는다 (끝냈다면 1초 안에 드러난다)
        assert runner.wait(1.0) is None
        assert worker.alive()
        runner.terminate()
        assert runner.wait(30) is not None
        return worker.wait(worker_wait)


def test_job_survives_while_second_handle_open(tmp_path: Path, spawned: Spawned) -> None:
    # runner의 핸들이 마지막으로 닫히면 OS가 남은 워커를 끝낸다
    exit_code = runner_dies_after_supervisor_closed(
        tmp_path, spawned, kill_on_close=True, worker_wait=30
    )
    assert exit_code is not None


def test_without_kill_on_close_worker_outlives_last_handle(
    tmp_path: Path, spawned: Spawned
) -> None:
    # 음성 대조: KILL_ON_JOB_CLOSE가 없으면 같은 구성에서 워커가 살아남는다. 위 검사의 통과가
    # 런처의 자손 정리 같은 다른 경로가 아니라 Job 설정에서 온다는 증거
    exit_code = runner_dies_after_supervisor_closed(
        tmp_path, spawned, kill_on_close=False, worker_wait=1.0
    )
    assert exit_code is None


def test_terminate_job_kills_grandchildren(tmp_path: Path, spawned: Spawned) -> None:
    name = job_name()
    with Job.create(name) as job:
        tree = start_tree(spawned, tmp_path / "tree", depth=3, job=name)
        assert set(job.process_ids()) == {i.pid for i in tree.values()}
        job.terminate(9)
        assert_no_live(tree.values())
        assert job.process_ids() == []


def test_process_opens_named_job_and_assigns_itself_before_children(
    tmp_path: Path, spawned: Spawned
) -> None:
    name = job_name()
    with Job.create(name) as job:
        start_tree(spawned, tmp_path / "tree", depth=3, job=name)
        records = read_tree(tmp_path / "tree")
        # 자식·손자는 시작하자마자 이미 Job 안이다 (넣는 사이의 경쟁이 없다)
        assert [records[level]["in_job"] for level in range(3)] == [True, True, True]
        assert set(job.process_ids()) == {records[level]["pid"] for level in range(3)}


def test_job_handle_not_inherited(spawned: Spawned) -> None:
    with Job.create(job_name()) as job:
        assert not job.inheritable
        # 핸들 상속을 켠 자식에서도 그 값은 Job 핸들이 아니다
        code = (
            "import ctypes, sys\n"
            "k = ctypes.WinDLL('kernel32')\n"
            "k.QueryInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int,"
            " ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]\n"
            "buf = ctypes.create_string_buffer(64)\n"
            "ok = k.QueryInformationJobObject(int(sys.argv[1]), 1, buf, 64, None)\n"
            "sys.exit(10 if ok else 0)\n"
        )
        child = spawned.popen(python_cmd("-c", code, str(job.handle)), close_fds=False)
        assert child.wait(timeout=30) == 0


def test_create_refuses_existing_name_and_open_missing() -> None:
    # 같은 이름을 먼저 만든 Job에 붙지 않는다 (가로채기 방지)
    name = job_name()
    with Job.create(name), pytest.raises(FileExistsError):
        Job.create(name)
    with pytest.raises(FileNotFoundError):
        Job.open(job_name())
