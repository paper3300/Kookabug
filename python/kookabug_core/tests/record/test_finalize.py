"""멱등 마무리 `finalize_run` (구현 계획 M0b 2.7)."""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from kookabug_core.record import (
    InputKey,
    InputRecoveryOutcome,
    Journal,
    finalize_run,
    read_run,
    read_run_json,
    write_run_json,
)
from kookabug_core.record.runfolder import finished_run_json
from kookabug_core.schema import check_shape

RUN = "r8k2x7qm"
STARTED = "2026-10-29T06:02:11.000Z"
NOW = datetime(2026, 10, 29, 6, 2, 21, tzinfo=UTC)


def running_json() -> dict[str, Any]:
    return {
        "format": "kookabug.run/0",
        "graph": "tests/t.graph.json",
        "run_id": RUN,
        "started_at": STARTED,
        "status": "running",
    }


def run_start() -> dict[str, Any]:
    return {
        "event": "run.start",
        "graph": "tests/t.graph.json",
        "protocol": 1,
        "runner": {"created": 1, "pid": 1, "version": "0"},
    }


def step_start(step: str, node: str) -> dict[str, Any]:
    return {
        "attempt": 1,
        "event": "step.start",
        "node": node,
        "parent": None,
        "path": [node],
        "step": step,
    }


def step_end(step: str) -> dict[str, Any]:
    return {
        "attempt": 1,
        "duration_ms": 1,
        "event": "step.end",
        "exit": "done",
        "outputs": {},
        "status": "success",
        "step": step,
    }


def runner_end() -> dict[str, Any]:
    return {
        "code": "test_pass",
        "duration_ms": 5,
        "event": "run.end",
        "failure_path": None,
        "failure_step": None,
        "finalized_by": "runner",
        "reason": "core.test.pass에 도달했다",
        "verdict": "pass",
    }


def make_run(tmp_path: Path, *events: dict[str, Any], run_json: bool = True) -> Path:
    """runner가 `events`까지 쓰고 죽은 실행 폴더."""
    folder = tmp_path / f"2026-10-29T06-02-11_t_{RUN}"
    folder.mkdir()
    if run_json:
        write_run_json(folder / "run.json", running_json())
    stamp = datetime(2026, 10, 29, 6, 2, 11, tzinfo=UTC)
    with Journal(folder / "events.jsonl", RUN, now=lambda: stamp) as journal:
        for event in events:
            journal.emit(event)
    return folder


def events_of(folder: Path) -> list[dict[str, Any]]:
    return read_run(folder).events


def assert_valid(folder: Path) -> None:
    view = read_run(folder)
    assert not view.truncated and view.warnings == []
    for event in view.events:
        assert check_shape(event, "events") == [], event
    data = read_run_json(folder / "run.json")
    assert data is not None and check_shape(data) == [], data


def test_no_run_end_appends_runner_died(tmp_path: Path) -> None:
    folder = make_run(
        tmp_path,
        run_start(),
        step_start("s1", "n_entry"),
        step_end("s1"),
        step_start("s2", "n_block"),
    )
    result = finalize_run(folder, runner_exit_code=1, now=lambda: NOW)
    end = events_of(folder)[-1]
    assert end["event"] == "run.end" and end["seq"] == 5
    assert end["verdict"] == "error" and end["code"] == "runner_died"
    assert end["finalized_by"] == "supervisor"
    assert end["runner_exit_code"] == 1
    assert end["failure_step"] == "s2" and end["failure_path"] == ["n_block"]
    assert end["duration_ms"] == 10_000
    assert end["input_recovery"] == "not_needed"
    assert "cancel_reason" not in end and "truncated_bytes" not in end
    assert result.appended == ["run.end"] and result.run_end == end
    # 열린 스텝에는 step.end를 쓰지 않는다
    view = read_run(folder)
    assert view.steps["s2"].status == "interrupted"
    data = read_run_json(folder / "run.json")
    assert data is not None
    assert data["status"] == "finished" and data["code"] == "runner_died"
    assert data["finalized_by"] == "supervisor" and data["runner_exit_code"] == 1
    assert data["run_json_repaired"] is True and data["ended_at"] == end["t"]
    assert_valid(folder)


def test_existing_run_end_not_overwritten(tmp_path: Path) -> None:
    folder = make_run(tmp_path, run_start(), runner_end())
    write_run_json(folder / "run.json", finished_run_json(running_json(), events_of(folder)[-1]))
    before = (folder / "events.jsonl").read_bytes()
    run_json_before = (folder / "run.json").read_bytes()
    result = finalize_run(folder, runner_exit_code=0)
    assert (folder / "events.jsonl").read_bytes() == before
    assert (folder / "run.json").read_bytes() == run_json_before  # 확인만
    assert result.appended == [] and not result.run_json_repaired
    assert result.run_end["finalized_by"] == "runner"


def test_run_json_rebuilt_from_run_end(tmp_path: Path) -> None:
    # runner가 run.end를 쓰고 run.json을 완료로 바꾸기 전에 죽었다
    folder = make_run(tmp_path, run_start(), runner_end())
    result = finalize_run(folder, runner_exit_code=1)
    end = events_of(folder)[-1]
    assert end["finalized_by"] == "runner" and end["verdict"] == "pass"  # 덮어쓰지 않는다
    data = read_run_json(folder / "run.json")
    assert data is not None
    assert data["status"] == "finished" and data["verdict"] == "pass"
    assert data["code"] == "test_pass" and data["finalized_by"] == "runner"
    assert data["run_json_repaired"] is True and result.run_json_repaired
    assert "runner_exit_code" not in data  # run.end에 없던 값은 만들어 넣지 않는다
    assert_valid(folder)
    # run.end와 다른 완료 run.json도 다시 만든다
    write_run_json(folder / "run.json", {**data, "verdict": "fail"})
    assert finalize_run(folder).run_json_repaired
    assert read_run_json(folder / "run.json")["verdict"] == "pass"  # type: ignore[index]


def supervisor_end(exit_code: int | None = 4) -> dict[str, Any]:
    end = {**runner_end(), "code": "runner_died", "finalized_by": "supervisor", "verdict": "error"}
    if exit_code is not None:
        end["runner_exit_code"] = exit_code
    return end


@pytest.mark.parametrize(
    ("journal_code", "json_code"),
    [
        pytest.param(4, None, id="missing-in-json"),
        pytest.param(4, 99, id="different"),
        pytest.param(None, 99, id="only-in-json"),
    ],
)
def test_run_json_exit_code_repaired(
    tmp_path: Path, journal_code: int | None, json_code: int | None
) -> None:
    # 완료 run.json으로 옮기는 결과 필드는 빠짐·다름·run.end에 없는데 남음을 모두 고친다
    folder = make_run(tmp_path, run_start(), supervisor_end(journal_code))
    data = finished_run_json(running_json(), events_of(folder)[-1])
    data.pop("runner_exit_code", None)
    if json_code is not None:
        data["runner_exit_code"] = json_code
    assert check_shape(data) == []  # 형식은 맞지만 run.end와 다르다
    write_run_json(folder / "run.json", data)
    result = finalize_run(folder)
    actual = read_run_json(folder / "run.json")
    assert actual is not None and result.run_json_repaired
    assert actual.get("runner_exit_code") == journal_code
    assert ("runner_exit_code" in actual) == (journal_code is not None)
    assert not finalize_run(folder).run_json_repaired  # 고친 뒤에는 그대로


@pytest.mark.parametrize("field", ["verdict", "code", "reason", "failure_step", "ended_at"])
def test_run_json_missing_result_field_repaired(tmp_path: Path, field: str) -> None:
    folder = make_run(tmp_path, run_start(), runner_end())
    data = finished_run_json(running_json(), events_of(folder)[-1])
    del data[field]
    write_run_json(folder / "run.json", data)
    assert finalize_run(folder).run_json_repaired
    actual = read_run_json(folder / "run.json")
    assert actual is not None and field in actual


def test_truncated_tail_cut_before_append(tmp_path: Path) -> None:
    folder = make_run(tmp_path, run_start(), step_start("s1", "n_block"))
    path = folder / "events.jsonl"
    whole = path.read_bytes()
    partial = b'{"event": "log", "level": "info", "mess'
    path.write_bytes(whole + partial)
    result = finalize_run(folder, runner_exit_code=1)
    assert result.truncated_bytes == len(partial)
    data = path.read_bytes()
    assert data.startswith(whole) and partial not in data
    events = events_of(folder)
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert events[-1]["truncated_bytes"] == len(partial)
    assert read_run(folder).steps["s1"].status == "interrupted"
    assert_valid(folder)


def test_finalize_twice_no_duplicate_events(tmp_path: Path) -> None:
    folder = make_run(
        tmp_path,
        run_start(),
        step_start("s1", "n_hold"),
        {"device": "keyboard", "event": "input.down", "key": "ctrl", "step": "s1"},
    )
    calls: list[Sequence[InputKey]] = []

    def recover(run_dir: Path, held: Sequence[InputKey]) -> InputRecoveryOutcome:
        calls.append(held)
        return InputRecoveryOutcome("recovered", held)

    first = finalize_run(folder, runner_exit_code=1, recover_inputs=recover)
    after_first = (folder / "events.jsonl").read_bytes()
    run_json_first = (folder / "run.json").read_bytes()
    second = finalize_run(folder, runner_exit_code=1, recover_inputs=recover)
    assert first.appended == ["input.recovered", "run.end"]
    assert second.appended == [] and not second.run_json_repaired
    assert (folder / "events.jsonl").read_bytes() == after_first
    assert (folder / "run.json").read_bytes() == run_json_first
    assert len(calls) == 1
    assert second.run_end == first.run_end
    assert_valid(folder)


def test_recover_callback_called_only_when_held_and_no_marker(tmp_path: Path) -> None:
    calls: list[tuple[Path, list[InputKey]]] = []

    def recover(run_dir: Path, held: Sequence[InputKey]) -> InputRecoveryOutcome:
        calls.append((run_dir, list(held)))
        return InputRecoveryOutcome("recovered")

    down = {"device": "keyboard", "event": "input.down", "key": "ctrl"}
    click = {"button": "left", "device": "mouse", "event": "input.down"}
    up = {"device": "keyboard", "event": "input.up", "key": "ctrl"}

    # 눌린 키 없음 → 부르지 않는다
    (a := tmp_path / "a").mkdir()
    none_held = make_run(a, run_start(), down, up)
    assert finalize_run(none_held, recover_inputs=recover).input_recovery == "not_needed"
    assert calls == []

    # 복구 표시 파일이 있음(다음 임대권 소유자가 이미 뗌) → 부르지 않는다
    (b := tmp_path / "b").mkdir()
    marked = make_run(b, run_start(), down)
    (marked / "input-recovery.json").write_text("{}", encoding="utf-8")
    result = finalize_run(marked, recover_inputs=recover)
    assert calls == [] and result.input_recovery == "already_recovered"
    assert [e["event"] for e in events_of(marked)][-1] == "run.end"
    assert events_of(marked)[-1]["input_recovery"] == "already_recovered"

    # 눌린 키가 있고 표시 파일이 없음 → 부르고, 뗀 키를 기록한다
    (c := tmp_path / "c").mkdir()
    held = make_run(c, run_start(), down, click)
    result = finalize_run(held, recover_inputs=recover)
    assert calls == [(held, [InputKey("keyboard", "ctrl"), InputKey("mouse", "left")])]
    recovered = [e for e in events_of(held) if e["event"] == "input.recovered"]
    assert recovered == [
        {
            **recovered[0],
            "by": {"kind": "supervisor"},
            "from_run": RUN,
            "inputs": [
                {"device": "keyboard", "key": "ctrl"},
                {"button": "left", "device": "mouse"},
            ],
        }
    ]
    assert result.input_recovery == "recovered"
    assert_valid(held)

    # 복구 수단이 없거나 임대권을 못 얻으면 이벤트 없이 결과만 남긴다
    (d := tmp_path / "d").mkdir()
    busy = make_run(d, run_start(), down)
    result = finalize_run(busy, recover_inputs=lambda *_: InputRecoveryOutcome("lease_busy"))
    assert result.input_recovery == "lease_busy"
    assert [e["event"] for e in events_of(busy)] == ["run.start", "input.down", "run.end"]
    (e := tmp_path / "e").mkdir()
    assert finalize_run(make_run(e, run_start(), down)).input_recovery == "unavailable"


def test_recovery_after_existing_run_end(tmp_path: Path) -> None:
    # run.end는 있으나 키가 눌린 채 죽었다 (액터가 멈춤) → run.end 뒤에 input.recovered만 더한다
    folder = make_run(
        tmp_path,
        run_start(),
        {"device": "keyboard", "event": "input.down", "key": "a"},
        runner_end(),
    )
    result = finalize_run(
        folder, recover_inputs=lambda _d, held: InputRecoveryOutcome("recovered", held)
    )
    assert [e["event"] for e in events_of(folder)] == [
        "run.start",
        "input.down",
        "run.end",
        "input.recovered",
    ]
    assert result.appended == ["input.recovered"]
    assert_valid(folder)


def test_cancel_reason_copied_into_runner_died(tmp_path: Path) -> None:
    folder = make_run(
        tmp_path,
        run_start(),
        step_start("s1", "n_block"),
        {"event": "cancel.requested", "reason": "deadline_exceeded"},
    )
    finalize_run(folder, runner_exit_code=4)
    end = events_of(folder)[-1]
    assert end["cancel_reason"] == "deadline_exceeded"
    assert end["code"] == "runner_died" and end["runner_exit_code"] == 4
    assert_valid(folder)


def test_three_outcomes_distinguished(tmp_path: Path) -> None:
    (a := tmp_path / "a").mkdir()
    by_runner = make_run(a, run_start(), step_start("s1", "n_pass"), step_end("s1"), runner_end())
    finalize_run(by_runner)
    (b := tmp_path / "b").mkdir()
    by_supervisor = make_run(b, run_start(), step_start("s1", "n_block"))
    finalize_run(by_supervisor, runner_exit_code=1)
    (c := tmp_path / "c").mkdir()
    nobody = make_run(c, run_start(), step_start("s1", "n_block"))

    runner_view, supervisor_view, nobody_view = (
        read_run(f) for f in (by_runner, by_supervisor, nobody)
    )
    assert runner_view.outcome == "finalized_by_runner"
    assert runner_view.interrupted_steps == []
    assert supervisor_view.outcome == "finalized_by_supervisor"
    assert supervisor_view.run_end is not None
    assert supervisor_view.run_end["code"] == "runner_died"
    assert [s.step for s in supervisor_view.interrupted_steps] == ["s1"]
    assert nobody_view.outcome == "interrupted" and nobody_view.status == "interrupted"
    assert [s.step for s in nobody_view.interrupted_steps] == ["s1"]


def test_seed_used_when_nothing_written(tmp_path: Path) -> None:
    # runner가 run.json도 저널도 쓰기 전에 죽었다
    folder = tmp_path / f"2026-10-29T06-02-11_t_{RUN}"
    folder.mkdir()
    with pytest.raises(ValueError, match="seed"):
        finalize_run(folder)
    assert not (folder / "events.jsonl").exists()  # 실패하면 아무것도 쓰지 않는다
    seed = {"graph": "tests/t.graph.json", "run_id": RUN, "started_at": STARTED}
    result = finalize_run(folder, runner_exit_code=3, seed=seed)
    assert result.run_end["seq"] == 1 and result.run_end["duration_ms"] is None
    data = read_run_json(folder / "run.json")
    assert data is not None and data["graph"] == "tests/t.graph.json"
    assert_valid(folder)


def test_run_json_start_fields_kept(tmp_path: Path) -> None:
    folder = make_run(tmp_path, run_start(), step_start("s1", "n_block"))
    start = {
        **running_json(),
        "conditions": {"deadline_ms": 1000, "platform": "fake", "profile": None, "settings": {}},
        "plugins": [{"id": "testkit", "version": "0"}],
    }
    write_run_json(folder / "run.json", start)
    finalize_run(folder, runner_exit_code=1)
    data = read_run_json(folder / "run.json")
    assert data is not None
    assert data["conditions"] == start["conditions"] and data["plugins"] == start["plugins"]
    assert data["started_at"] == STARTED
    assert_valid(folder)
