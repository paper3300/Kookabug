"""멱등 마무리 (구현 계획 M0b 2.7 `finalize_run`).

runner가 어떻게 끝났든 runner 종료를 확인한 쪽(감독자 복구 경로)이 부른다. 두 번 불러도 결과가
같다 (이벤트 중복 없음).

1. 저널 끝이 잘린 줄이면 마지막 완전한 줄까지 자른다 (`truncated_bytes`)
2. 키 복구: 기록상 눌렸을 수 있는 키가 있고 복구 표시 파일(`input-recovery.json`)이 없으면
   `recover_inputs`를 부른다 (임대권 안의 복구는 부르는 쪽 몫). 복구했으면 `input.recovered`
3. `run.end`가 없으면 `run.end`(`error`/`runner_died`, `finalized_by: supervisor`)를 덧붙인다.
   **있으면 덮어쓰지 않는다** (`run.end` 뒤에는 `input.recovered`만 더해질 수 있다)
4. `run.json`이 `finished`가 아니거나 `run.end`와 다르면 `run.end`에서 다시 만든다
   (`run_json_repaired: true`)

열린 스텝에는 `step.end`를 쓰지 않는다 (읽기가 "중단"으로 표시한다).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from kookabug_core.record.journal import Journal
from kookabug_core.record.reader import InputKey, RunView, held_inputs, read_run
from kookabug_core.record.runfolder import (
    EVENTS_FILE,
    INPUT_RECOVERY_FILE,
    RUN_FORMAT,
    RUN_JSON_FILE,
    finished_run_json,
    read_run_json,
    run_id_of_folder,
    run_json_matches,
    write_run_json,
)

__all__ = ["FinalizeResult", "InputRecoveryOutcome", "RecoverInputs", "finalize_run"]

type InputRecovery = Literal[
    "already_recovered", "lease_busy", "not_needed", "recovered", "unavailable"
]


@dataclass(frozen=True, slots=True)
class InputRecoveryOutcome:
    """키 복구 결과. `recovered`면 `inputs`를 뗐다."""

    status: InputRecovery
    inputs: Sequence[InputKey] = ()


# (실행 폴더, 눌렸을 수 있는 키) → 결과. 임대권 안의 복구는 T6 `recover_run`이 맡는다
type RecoverInputs = Callable[[Path, Sequence[InputKey]], InputRecoveryOutcome]


@dataclass(slots=True)
class FinalizeResult:
    run_end: dict[str, Any]
    truncated_bytes: int = 0
    input_recovery: InputRecovery = "not_needed"
    appended: list[str] = field(default_factory=list[str])
    """이번 호출이 저널에 더한 이벤트 종류 (두 번째 호출이면 빈 목록)."""
    run_json_repaired: bool = False


def finalize_run(
    run_dir: str | os.PathLike[str],
    *,
    runner_exit_code: int | None = None,
    recover_inputs: RecoverInputs | None = None,
    seed: Mapping[str, Any] | None = None,
    now: Callable[[], datetime] | None = None,
) -> FinalizeResult:
    """runner가 끝난 실행 폴더를 마무리한다. runner 종료 확인 뒤에만 부른다 (작성자는 하나).

    `seed`는 `run.json`도 `run.start`도 없을 때(runner가 기록을 시작하기 전에 죽음) 쓸 시작
    정보(`run_id`·`graph`·`started_at` 등)다.
    """
    folder = Path(run_dir)
    clock = now or (lambda: datetime.now(UTC))
    events_path = folder / EVENTS_FILE

    # 1. 잘린 끝 줄
    view = read_run(folder)
    truncated = view.truncated_bytes
    if truncated:
        os.truncate(events_path, view.valid_size)
        view = read_run(folder)

    start_json = read_run_json(folder / RUN_JSON_FILE)
    run_id = _run_id(folder, view, start_json, seed)
    # 시작 정보를 모르면 아무것도 쓰기 전에 실패한다
    base = _start_fields(start_json, view, run_id, seed)
    appended: list[str] = []

    with Journal(events_path, run_id, writer="supervisor", now=clock) as journal:
        # 2. 키 복구
        recovery = _recover_inputs(folder, view, run_id, recover_inputs, journal, appended)

        # 3. run.end
        run_end = view.run_end
        if run_end is None:
            run_end = journal.emit(
                _runner_died(view, runner_exit_code, recovery, truncated, clock())
            )
            appended.append("run.end")

    # 4. run.json
    repaired = False
    if not run_json_matches(start_json, run_end):
        data = finished_run_json(base, run_end)
        data["run_json_repaired"] = True
        write_run_json(folder / RUN_JSON_FILE, data)
        repaired = True

    return FinalizeResult(
        run_end=run_end,
        truncated_bytes=truncated,
        input_recovery=recovery,
        appended=appended,
        run_json_repaired=repaired,
    )


def _recover_inputs(
    folder: Path,
    view: RunView,
    run_id: str,
    recover_inputs: RecoverInputs | None,
    journal: Journal,
    appended: list[str],
) -> InputRecovery:
    held = held_inputs(view)
    if not held:
        return "not_needed"
    if (folder / INPUT_RECOVERY_FILE).exists():
        # 다음 임대권 소유자가 이미 뗐다
        return "already_recovered"
    if recover_inputs is None:
        return "unavailable"
    outcome = recover_inputs(folder, held)
    if outcome.status == "recovered":
        journal.emit(
            {
                "by": {"kind": "supervisor"},
                "event": "input.recovered",
                "from_run": run_id,
                "inputs": [k.to_event() for k in (outcome.inputs or held)],
            }
        )
        appended.append("input.recovered")
    return outcome.status


def _runner_died(
    view: RunView,
    exit_code: int | None,
    recovery: InputRecovery,
    truncated: int,
    now: datetime,
) -> dict[str, Any]:
    code_text = f" (종료 코드 {exit_code})" if exit_code is not None else ""
    open_steps = view.interrupted_steps
    last = open_steps[-1] if open_steps else None
    event: dict[str, Any] = {
        "code": "runner_died",
        "duration_ms": _duration_ms(view, now),
        "event": "run.end",
        "failure_path": last.path if last is not None and last.path else None,
        "failure_step": last.step if last is not None else None,
        "finalized_by": "supervisor",
        "input_recovery": recovery,
        "reason": f"runner가 실행을 마무리하지 못하고 끝났다{code_text}",
        "verdict": "error",
    }
    if exit_code is not None:
        event["runner_exit_code"] = exit_code
    if view.cancel_reason is not None:
        event["cancel_reason"] = view.cancel_reason
    if truncated:
        event["truncated_bytes"] = truncated
    return event


def _duration_ms(view: RunView, now: datetime) -> int | None:
    start = view.run_start
    if start is None:
        return None
    try:
        began = datetime.fromisoformat(start["t"])
    except KeyError, TypeError, ValueError:
        return None
    return max(0, int((now - began).total_seconds() * 1000))


def _run_id(
    folder: Path,
    view: RunView,
    start_json: Mapping[str, Any] | None,
    seed: Mapping[str, Any] | None,
) -> str:
    for candidate in (
        view.run_id,
        (start_json or {}).get("run_id"),
        (seed or {}).get("run_id"),
        run_id_of_folder(folder),
    ):
        if isinstance(candidate, str) and candidate:
            return candidate
    raise ValueError(f"run_id를 알 수 없다: {folder}")


def _start_fields(
    start_json: Mapping[str, Any] | None,
    view: RunView,
    run_id: str,
    seed: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """완료 `run.json`의 바탕: 기존 `run.json` → `seed` → `run.start`에서 아는 것."""
    base: dict[str, Any] = {}
    run_start = view.run_start
    if run_start is not None:
        base["graph"] = run_start.get("graph")
        base["started_at"] = run_start.get("t")
    base.update(seed or {})
    base.update(start_json or {})
    base.update(format=RUN_FORMAT, run_id=run_id)
    if not isinstance(base.get("graph"), str) or not isinstance(base.get("started_at"), str):
        raise ValueError(
            "run.json도 run.start도 없어 시작 정보를 알 수 없다. seed에 graph·started_at을 준다"
        )
    return base
