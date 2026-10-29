"""실행 기록 읽기: 잘린 끝 줄, "중단", 따라 읽기, 눌렸을 수 있는 키 (구현 계획 M0b 2.4·2.8)."""

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from kookabug_core.record import InputKey, Journal, follow, held_inputs, read_journal, read_run

RUN = "r8k2x7qm"


def start(step: str, node: str) -> dict[str, Any]:
    return {
        "attempt": 1,
        "event": "step.start",
        "node": node,
        "parent": None,
        "path": [node],
        "step": step,
    }


def end(step: str, status: str = "success") -> dict[str, Any]:
    return {
        "attempt": 1,
        "duration_ms": 1,
        "event": "step.end",
        "exit": "done",
        "outputs": {},
        "status": status,
        "step": step,
    }


RUN_START = {
    "event": "run.start",
    "graph": "tests/t.graph.json",
    "protocol": 1,
    "runner": {"created": 1, "pid": 1, "version": "0"},
}
RUN_END = {
    "code": "test_pass",
    "duration_ms": 3,
    "event": "run.end",
    "failure_path": None,
    "failure_step": None,
    "finalized_by": "runner",
    "reason": "r",
    "verdict": "pass",
}


def write(folder: Path, *events: dict[str, Any]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    with Journal(folder / "events.jsonl", RUN) as journal:
        for event in events:
            journal.emit(event)
    return folder / "events.jsonl"


def test_truncated_last_line_ignored_and_flagged(tmp_path: Path) -> None:
    path = write(tmp_path, RUN_START, start("s1", "n_a"), end("s1"))
    whole = path.read_bytes()
    lines = whole.split(b"\n")
    # 마지막 완전한 줄의 앞 절반만 남긴다 (실제 쓰기 중 사망의 모양)
    cut = whole[: len(whole) - 1 - len(lines[-2]) // 2]
    path.write_bytes(cut)
    view = read_run(tmp_path)
    assert view.truncated
    assert [e["event"] for e in view.events] == ["run.start", "step.start"]
    assert view.valid_size == len(b"\n".join(lines[:2])) + 1
    assert view.truncated_bytes == len(cut) - view.valid_size
    assert view.steps["s1"].status == "interrupted"
    assert path.read_bytes() == cut  # 읽기는 파일을 고치지 않는다
    # \n으로 끝나도 JSON이 아닌 끝 줄도 잘린 줄로 본다
    path.write_bytes(b"\n".join(lines[:2]) + b'\n{"event": \n')
    again = read_run(tmp_path)
    assert again.truncated and [e["seq"] for e in again.events] == [1, 2]
    assert not read_run(tmp_path / "missing").truncated


def test_cut_inside_multibyte_character(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        RUN_START,
        {"event": "log", "level": "info", "message": "가나다라", "node": None, "step": None},
    )
    data = path.read_bytes()
    index = data.rindex("나".encode()) + 1  # UTF-8 문자 중간
    path.write_bytes(data[:index])
    view = read_run(tmp_path)
    assert view.truncated and [e["event"] for e in view.events] == ["run.start"]


def test_step_without_end_is_interrupted(tmp_path: Path) -> None:
    write(tmp_path, RUN_START, start("s1", "n_a"), end("s1"), start("s2", "n_b"), RUN_END)
    view = read_run(tmp_path)
    assert view.steps["s1"].status == "success"
    assert view.steps["s2"].status == "interrupted"
    assert [s.step for s in view.interrupted_steps] == ["s2"]
    assert view.status == "finished"


def test_run_without_run_end_is_interrupted(tmp_path: Path) -> None:
    write(tmp_path, RUN_START, start("s1", "n_a"), end("s1"))
    view = read_run(tmp_path)
    assert view.status == "interrupted" and view.outcome == "interrupted"
    assert view.run_end is None
    empty = read_run(tmp_path / "nothing")
    assert empty.status == "interrupted" and empty.events == [] and empty.warnings


def test_corrupt_middle_line_warned_and_skipped(tmp_path: Path) -> None:
    path = write(tmp_path, RUN_START, start("s1", "n_a"), end("s1"))
    first, *rest = path.read_bytes().split(b"\n")
    path.write_bytes(b"\n".join([first, b"{broken", b"[1, 2]", *rest]))
    view = read_run(tmp_path)
    assert not view.truncated
    assert [e["seq"] for e in view.events] == [1, 2, 3]
    assert len(view.warnings) == 2 and "2번째 줄" in view.warnings[0]


def test_seq_gap_warned(tmp_path: Path) -> None:
    path = write(tmp_path, RUN_START, start("s1", "n_a"), end("s1"))
    first, _, third, tail = path.read_bytes().split(b"\n")
    path.write_bytes(b"\n".join([first, third, tail]))
    view = read_run(tmp_path)
    assert view.warnings == ["seq 빈틈: 2 자리에 3"]
    assert view.last_seq == 3


def test_follow_yields_after_seq_and_new_lines(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    journal = Journal(tmp_path / "events.jsonl", RUN)
    journal.emit(RUN_START)
    journal.emit(start("s1", "n_a"))
    got: list[dict[str, Any]] = []
    first_seen = threading.Event()

    def reader() -> None:
        for event in follow(tmp_path, after_seq=1, timeout=30, until_run_end=True):
            got.append(event)
            first_seen.set()

    thread = threading.Thread(target=reader)
    thread.start()
    assert first_seen.wait(30)
    journal.emit(end("s1"))
    journal.emit(RUN_END)  # until_run_end: run.end를 주면 끝난다
    thread.join(30)
    journal.close()
    assert not thread.is_alive()
    assert [e["seq"] for e in got] == [2, 3, 4]


RECOVERED = {
    "by": {"kind": "supervisor"},
    "event": "input.recovered",
    "from_run": RUN,
    "inputs": [{"device": "keyboard", "key": "ctrl"}],
}


def test_follow_default_continues_after_run_end_until_stop(tmp_path: Path) -> None:
    # run.end 뒤에도 감독자가 input.recovered를 더할 수 있다. 기본은 stop·timeout까지 따라간다
    path = write(tmp_path, RUN_START, RUN_END)
    stop = threading.Event()
    stream = follow(tmp_path, stop=stop.is_set, interval=0.001)
    assert [next(stream)["event"], next(stream)["event"]] == ["run.start", "run.end"]
    with Journal(path, RUN, writer="supervisor") as journal:
        journal.emit(RECOVERED)
    stop.set()  # 감독자 마무리가 끝난 것을 아는 호출자가 멈춘다
    assert [e["event"] for e in stream] == ["input.recovered"]


def test_follow_stop_drains_all_complete_lines(tmp_path: Path) -> None:
    # 이미 쓰인 완전한 줄은 run.end 뒤의 것까지 버리지 않는다
    path = write(tmp_path, RUN_START, RUN_END)
    with Journal(path, RUN, writer="supervisor") as journal:
        journal.emit(RECOVERED)
    assert [e["seq"] for e in follow(tmp_path, stop=lambda: True)] == [1, 2, 3]
    # until_run_end도 run.end를 본 읽기에서 함께 읽힌 줄은 다 준다
    got = list(follow(tmp_path, until_run_end=True, timeout=30))
    assert [e["event"] for e in got] == ["run.start", "run.end", "input.recovered"]


@pytest.mark.parametrize("partial_size", [30, 2000], ids=["file-grows", "file-shrinks"])
def test_follow_survives_supervisor_tail_replacement(tmp_path: Path, partial_size: int) -> None:
    # 따라 읽는 쪽이 잘린 끝 줄을 읽은 뒤 감독자가 그 줄을 잘라 내고 run.end를 같은 자리에 쓴다
    from kookabug_core.record import finalize_run, write_run_json

    path = write(tmp_path, RUN_START)
    write_run_json(
        tmp_path / "run.json",
        {
            "format": "kookabug.run/0",
            "graph": "tests/t.graph.json",
            "run_id": RUN,
            "started_at": "2026-10-29T06:02:11.000Z",
            "status": "running",
        },
    )
    with path.open("ab") as f:
        f.write(b'{"event": "log", "message": "' + b"x" * partial_size)
    stream = follow(tmp_path, timeout=0.3, interval=0.001)
    assert next(stream)["event"] == "run.start"
    next_read = path.stat().st_size
    finalize_run(tmp_path, runner_exit_code=4)
    assert (path.stat().st_size > next_read) == (partial_size == 30)
    assert [e["event"] for e in stream] == ["run.end"]


def test_follow_resyncs_when_file_shrinks_below_position(tmp_path: Path) -> None:
    path = write(tmp_path, RUN_START, start("s1", "n_a"), end("s1"))
    stream = follow(tmp_path, timeout=0.3, interval=0.001)
    assert [next(stream)["seq"] for _ in range(3)] == [1, 2, 3]
    first = path.read_bytes().split(b"\n")[0] + b"\n"
    path.write_bytes(first)  # 읽은 위치보다 짧아진다
    with Journal(path, RUN, writer="supervisor") as journal:
        for event in (start("s1", "n_a"), end("s1"), RUN_END):
            journal.emit(event)
    # 처음부터 다시 읽되 이미 준 seq는 건너뛴다
    assert [e["seq"] for e in stream] == [4]


def test_follow_does_not_yield_partial_line(tmp_path: Path) -> None:
    path = write(tmp_path, RUN_START)
    with path.open("ab") as f:
        f.write(json.dumps({**start("s1", "n_a"), "run": RUN, "seq": 2}).encode()[:20])
    stop = threading.Event()
    got = list(follow(tmp_path, stop=stop.is_set, timeout=0.2))
    assert [e["seq"] for e in got] == [1]
    # 줄이 마저 쓰이면 준다
    rest = json.dumps({**start("s1", "n_a"), "run": RUN, "seq": 2}).encode()[20:] + b"\n"
    with path.open("ab") as f:
        f.write(rest)
    assert [e["seq"] for e in follow(tmp_path, after_seq=1, timeout=0.2)] == [2]
    stop.set()
    assert list(follow(tmp_path / "missing", stop=stop.is_set)) == []


def key(name: str, kind: str = "input.down", **extra: Any) -> dict[str, Any]:
    return {"device": "keyboard", "event": kind, "key": name, **extra}


def button(name: str, kind: str = "input.down") -> dict[str, Any]:
    return {"button": name, "device": "mouse", "event": kind}


@pytest.mark.parametrize(
    ("events", "held"),
    [
        pytest.param([key("ctrl")], [InputKey("keyboard", "ctrl")], id="last-down"),
        pytest.param([key("ctrl"), key("ctrl", "input.up")], [], id="down-then-up"),
        pytest.param(
            [button("left"), key("a"), key("a", "input.up")],
            [InputKey("mouse", "left")],
            id="mouse-button",
        ),
        pytest.param(
            [key("ctrl"), key("shift"), button("right"), key("shift", "input.up"), key("a")],
            [InputKey("keyboard", "a"), InputKey("keyboard", "ctrl"), InputKey("mouse", "right")],
            id="several",
        ),
        pytest.param(
            [key("ctrl"), key("ctrl", "input.up"), key("ctrl")],
            [InputKey("keyboard", "ctrl")],
            id="down-again",
        ),
        pytest.param(
            [
                key("ctrl"),
                button("left"),
                {
                    "by": {"kind": "supervisor"},
                    "event": "input.recovered",
                    "from_run": RUN,
                    "inputs": [{"device": "keyboard", "key": "ctrl"}],
                },
            ],
            [InputKey("mouse", "left")],
            id="own-recovery-clears",
        ),
        pytest.param(
            [
                key("ctrl"),
                {
                    "by": {"kind": "runner"},
                    "event": "input.recovered",
                    "from_run": "zzzzzzzz",
                    "inputs": [{"device": "keyboard", "key": "ctrl"}],
                },
            ],
            [InputKey("keyboard", "ctrl")],
            id="other-run-recovery-ignored",
        ),
    ],
)
def test_held_inputs_rules(
    tmp_path: Path, events: list[dict[str, Any]], held: list[InputKey]
) -> None:
    write(tmp_path, RUN_START, *events)
    assert held_inputs(read_run(tmp_path)) == held


def test_held_inputs_truncated_down_line_dropped(tmp_path: Path) -> None:
    # 잘린 끝 줄이 input.down이면 그 줄을 버린 뒤 판단한다 (down은 백엔드 호출 전에 쓰므로 그 키는
    # 아직 눌리지 않았다)
    path = write(tmp_path, RUN_START, key("ctrl"), key("ctrl", "input.up"), key("a"))
    data = path.read_bytes()
    path.write_bytes(data[: len(data) - 10])
    view = read_run(tmp_path)
    assert view.truncated
    assert held_inputs(view) == []
    assert InputKey("mouse", "left").to_event() == {"button": "left", "device": "mouse"}


def test_outcome_and_cancel_reason(tmp_path: Path) -> None:
    write(
        tmp_path, RUN_START, {"event": "cancel.requested", "reason": "deadline_exceeded"}, RUN_END
    )
    view = read_journal(tmp_path / "events.jsonl")
    assert view.outcome == "finalized_by_runner"
    assert view.cancel_reason == "deadline_exceeded"
    assert view.run_id == RUN
