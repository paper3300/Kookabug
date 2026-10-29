"""복구 경로 (구현 계획 M0b 2.7). **감독자만** 부른다 — 한 실행에 감독자는 하나이므로 복구 작성자도
하나다.

runner가 어떻게 끝났든(정상·하드 종료·kill·크래시·마무리 중 사망) 항상 부르고, 두 번 불러도 결과가
같다 (이벤트 중복 없음).

1. runner 프로세스 종료를 **식별(PID + 생성 시각)로 확인**한다. 확인 전에는 아무것도 쓰지 않는다
   (고장 지점 `recovery.runner_exit_observed`)
2. `finalize_run()`: 잘린 끝 줄 자르기 → 임대권 안의 키 복구(`recover_run`, 복구 표시 파일 확인,
   고장 지점 `recovery.before_input_recovery`) → `run.end`가 없으면 `runner_died` →
   `run.json` 재구성
   (고장 지점 `recovery.before_finalize`는 그 직전)
3. Job 정리: `TerminateJobObject` → 핸들 닫기 (`run.end` 유무와 무관). 키 복구가 Job 정리보다 먼저다

열린 스텝에는 `step.end`를 쓰지 않는다 (읽기가 "중단"으로 표시한다).
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from kookabug_core.inputs import InputBackend, create_backend, recover_run
from kookabug_core.record import FinalizeResult, InputKey, InputRecoveryOutcome, finalize_run
from kookabug_core.win import Job, Process, ProcessId
from kookabug_sdk import _faults

__all__ = ["RecoverResult", "RunnerStillAlive", "recover", "supervisor_backend"]

JOB_EXIT_WAIT_S: Final = 5.0
"""Job을 끝낸 뒤 안의 프로세스가 실제로 끝나기를 기다리는 시간."""


class RunnerStillAlive(Exception):
    """runner가 아직 끝나지 않았다. 복구 경로는 아무것도 쓰지 않았다."""


@dataclass(frozen=True, slots=True)
class RecoverResult:
    finalize: FinalizeResult
    runner_exit_code: int | None
    """runner 종료 코드 (식별로 열 수 없어 모르면 None)."""
    job_terminated: bool


def supervisor_backend(platform: Mapping[str, Any], run_id: str | None) -> InputBackend | None:
    """감독자가 키를 뗄 백엔드: 실행 사양의 `platform`과 같은 장치(가짜면 같은 기록 파일)."""
    if platform.get("kind") != "fake" or not platform.get("input_log"):
        return None
    return create_backend("fake", input_log=platform["input_log"], run=run_id, by="supervisor")


def recover(
    run_dir: str | os.PathLike[str],
    runner: ProcessId | Process,
    job: Job | None,
    *,
    backend: InputBackend | None,
    exit_timeout: float | None = 0,
    seed: Mapping[str, Any] | None = None,
    lease_name: str | None = None,
    lease_dir: str | os.PathLike[str] | None = None,
) -> RecoverResult:
    """runner가 끝난 실행을 마무리한다. `exit_timeout` 안에 runner가 끝나지 않으면
    `RunnerStillAlive`(아무것도 쓰지 않고 Job도 건드리지 않음). runner 종료를 확인했으면 `job`은
    기록 복구의 성패와 무관하게 끝내고 닫는다(이미 닫혔으면 None을 준다). 기록 복구 오류는 Job
    정리 뒤 그대로 던진다.

    `backend`가 None이면 키 복구 수단이 없다(`input_recovery: unavailable`). `lease_name`·
    `lease_dir`는 입력 임대권 이름·상태 폴더 (기본: 환경 변수 → 기본값, runner와 같아야 한다).
    """
    exit_code = _wait_exit(runner, exit_timeout)
    _faults.fault_point("recovery.runner_exit_observed")

    def recover_inputs(folder: Path, held: Sequence[InputKey]) -> InputRecoveryOutcome:
        _faults.fault_point("recovery.before_input_recovery")
        assert backend is not None
        return recover_run(folder, backend=backend, held=held, name=lease_name, directory=lease_dir)

    # runner 종료를 확인한 뒤에는 기록 복구가 실패해도(파일 I/O 등) Job 정리는 항상 한다.
    # 키 복구는 finalize_run 안에서 Job 정리보다 먼저 시도되고, 기록 오류는 그대로 호출자에게 간다
    try:
        _faults.fault_point("recovery.before_finalize")
        result = finalize_run(
            run_dir,
            runner_exit_code=exit_code,
            recover_inputs=None if backend is None else recover_inputs,
            seed=seed,
        )
    finally:
        terminated = _clean_job(job)
    return RecoverResult(result, exit_code, terminated)


def _clean_job(job: Job | None) -> bool:
    """`TerminateJobObject` → 안의 프로세스가 실제로 끝나기를 기다림(`JOB_EXIT_WAIT_S`까지) → 핸들
    닫기. 끝냈으면 True. `TerminateJobObject`는 끝내기를 요청만 하고 바로 돌아오므로 기다린다."""
    if job is None or job.closed:
        return False
    terminated = False
    try:
        members: list[Process] = []
        with contextlib.suppress(OSError):
            for pid in job.process_ids():
                with contextlib.suppress(ProcessLookupError):
                    members.append(Process.open(pid))
        try:
            with contextlib.suppress(OSError):
                job.terminate(1)
                terminated = True
            deadline = time.monotonic() + JOB_EXIT_WAIT_S
            for proc in members:
                with contextlib.suppress(OSError):
                    proc.wait(max(0.0, deadline - time.monotonic()))
        finally:
            for proc in members:
                proc.close()
    finally:
        job.close()
    return terminated


def _wait_exit(runner: ProcessId | Process, timeout: float | None) -> int | None:
    """runner 종료를 식별로 확인한다. 이미 없거나 PID가 다른 프로세스면 끝난 것(코드 모름)."""
    if isinstance(runner, Process):
        code = runner.wait(timeout)
        if code is None:
            raise RunnerStillAlive(f"runner(PID {runner.pid})가 아직 끝나지 않았다")
        return code
    try:
        proc = Process.open(runner)
    except ProcessLookupError:
        return None
    with proc:
        code = proc.wait(timeout)
    if code is None:
        raise RunnerStillAlive(f"runner(PID {runner.pid})가 아직 끝나지 않았다")
    return code
