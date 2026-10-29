"""`events.jsonl` 작성기 (구현 계획 M0b 2.8)."""

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from kookabug_core.record import Journal, JournalClosed, JournalTruncated, read_journal
from kookabug_sdk import Secret

RUN = "r8k2x7qm"


def lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in path.read_bytes().split(b"\n") if raw]


def test_seq_contiguous_from_one(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with Journal(path, RUN) as journal:
        written = [
            journal.emit({"event": "log", "level": "info", "message": str(i)}) for i in range(5)
        ]
    assert [e["seq"] for e in written] == [1, 2, 3, 4, 5]
    assert [e["seq"] for e in lines(path)] == [1, 2, 3, 4, 5]
    assert {e["run"] for e in lines(path)} == {RUN}


def test_t_is_utc_millis_z(tmp_path: Path) -> None:
    # 다른 시간대의 시각도 UTC로, 마이크로초는 밀리초로 자른다
    kst = timezone(timedelta(hours=9))
    stamp = datetime(2026, 10, 29, 15, 2, 11, 104999, tzinfo=kst)
    with Journal(tmp_path / "e.jsonl", RUN, now=lambda: stamp) as journal:
        event = journal.emit({"event": "debug.resume"})
    assert event["t"] == "2026-10-29T06:02:11.104Z"
    with Journal(tmp_path / "f.jsonl", RUN) as journal:
        real = journal.emit({"event": "debug.resume"})["t"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", real)
    parsed = datetime.fromisoformat(real)
    assert abs(parsed - datetime.now(UTC)) < timedelta(minutes=1)


def test_line_format_sorted_keys_lf_utf8(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    stamp = datetime(2026, 10, 29, 6, 2, 11, 104000, tzinfo=UTC)
    with Journal(path, RUN, now=lambda: stamp) as journal:
        journal.emit(
            {"step": "s1", "message": "한국어 ✓", "level": "info", "event": "log", "node": "n"}
        )
    data = path.read_bytes()
    assert (
        data
        == (
            '{"event": "log", "level": "info", "message": "한국어 ✓", "node": "n", '
            f'"run": "{RUN}", "seq": 1, "step": "s1", "t": "2026-10-29T06:02:11.104Z"}}\n'
        ).encode()
    )
    assert b"\r" not in data


def test_secret_values_never_written(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with Journal(path, RUN) as journal:
        journal.emit(
            {
                "attempt": 1,
                "duration_ms": 0,
                "event": "step.end",
                "exit": "done",
                "outputs": {"pw": Secret("hunter2"), "nested": [{"k": Secret("hunter2")}]},
                "status": "success",
                "step": "s1",
            }
        )
    text = path.read_text(encoding="utf-8")
    assert "hunter2" not in text
    assert lines(path)[0]["outputs"] == {"nested": [{"k": "***"}], "pw": "***"}


def test_non_finite_numbers_written_as_text(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with Journal(path, RUN) as journal:
        journal.emit({"event": "log", "level": "info", "message": "x", "value": float("nan")})
    assert lines(path)[0]["value"] == "nan"


def test_concurrent_emit_two_threads_lines_whole(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    big = "가" * 5000  # 한 번에 쓰기에 충분히 긴 줄
    barrier = threading.Barrier(2)

    with Journal(path, RUN) as journal:

        def worker(name: str) -> None:
            barrier.wait()
            for i in range(200):
                journal.emit({"event": "log", "level": "info", "message": f"{name}{i}{big}"})

        threads = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    view = read_journal(path)
    assert view.warnings == [] and not view.truncated
    assert [e["seq"] for e in view.events] == list(range(1, 401))
    messages = {e["message"][:4].rstrip("가") for e in view.events}
    assert len(messages) == 400


def test_resume_appends_after_last_seq(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with Journal(path, RUN) as journal:
        journal.emit({"event": "debug.pause"})
        journal.emit({"event": "debug.resume"})
    with Journal(path, RUN, writer="supervisor") as again:
        assert again.last_seq == 2
        assert again.emit({"event": "debug.pause"})["seq"] == 3
    assert [e["seq"] for e in lines(path)] == [1, 2, 3]


def test_resume_refuses_truncated_tail(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"event": "debug.pause", "run": "r8k2x7qm", "seq": 1}\n{"event": "lo')
    with pytest.raises(JournalTruncated):
        Journal(path, RUN)
    path.write_bytes(b'{"event": "debug.pause", "run": "r8k2x7qm", "seq": 1}\nnot json\n')
    with pytest.raises(JournalTruncated):
        Journal(path, RUN)


def test_runner_writer_rejects_after_run_end(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    end = {
        "code": "test_pass",
        "duration_ms": 1,
        "event": "run.end",
        "failure_path": None,
        "failure_step": None,
        "finalized_by": "runner",
        "reason": "r",
        "verdict": "pass",
    }
    with Journal(path, RUN) as journal:
        journal.emit({"event": "debug.pause"})
        journal.emit(end)
        with pytest.raises(JournalClosed):
            journal.emit({"event": "cancel.requested", "reason": "cancelled"})
    assert [e["event"] for e in lines(path)] == ["debug.pause", "run.end"]
    # 감독자 작성기는 run.end 뒤에도 input.recovered를 더할 수 있다
    with Journal(path, RUN, writer="supervisor") as sup:
        sup.emit(
            {
                "by": {"kind": "supervisor"},
                "event": "input.recovered",
                "from_run": RUN,
                "inputs": [],
            }
        )
    assert [e["seq"] for e in lines(path)] == [1, 2, 3]

    # 완료된 저널을 다시 열어도 runner 작성기는 쓰지 못한다 (run.end가 끝 줄이 아니어도)
    before = path.read_bytes()
    with Journal(path, RUN) as reopened, pytest.raises(JournalClosed):
        reopened.emit({"event": "cancel.requested", "reason": "cancelled"})
    assert path.read_bytes() == before
    with Journal(path, RUN, writer="supervisor") as sup:
        assert sup.last_seq == 3
        sup.emit(
            {
                "by": {"kind": "supervisor"},
                "event": "input.recovered",
                "from_run": RUN,
                "inputs": [],
            }
        )
    assert [e["seq"] for e in lines(path)] == [1, 2, 3, 4]
    # run.end가 없는 저널은 runner가 이어 쓸 수 있다
    other = tmp_path / "open.jsonl"
    with Journal(other, RUN) as first:
        first.emit({"event": "debug.pause"})
    with Journal(other, RUN) as again:
        assert again.emit({"event": "debug.resume"})["seq"] == 2


def test_closed_journal_and_bad_events_rejected(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "e.jsonl", RUN)
    with pytest.raises(ValueError, match="다른 실행"):
        journal.emit({"event": "debug.pause", "run": "zzzzzzzz"})
    with pytest.raises(ValueError, match="event"):
        journal.emit({"level": "info"})
    journal.close()
    journal.close()
    with pytest.raises(JournalClosed):
        journal.emit({"event": "debug.pause"})


WRITER = """
import sys
from kookabug_sdk import _faults
from kookabug_core.record import Journal

_faults.set_role("runner")
journal = Journal(sys.argv[1], "r8k2x7qm")
journal.emit({"event": "run.start", "graph": "tests/t.graph.json", "protocol": 1,
              "runner": {"created": 1, "pid": 1, "version": "0"}})
journal.emit({"attempt": 1, "event": "step.start", "node": "n_block", "parent": None,
              "path": ["n_block"], "step": "s1"})
journal.emit({"event": "log", "level": "info", "message": "blocking", "node": "n_block",
              "step": "s1"})
journal.emit({"event": "log", "level": "info", "message": "after", "node": "n_block",
              "step": "s1"})
journal.close()
"""


def _wait_for(path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > deadline:
            raise AssertionError(f"{path}이(가) {timeout}초 안에 생기지 않았다")
        time.sleep(0.02)


def test_partial_line_fault_on_selected_event_only(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    barrier = tmp_path / "barrier"
    rule = {
        "action": f"wait:{barrier}",
        "point": "journal.partial_line",
        "role": "runner",
        "when": {"event": "log", "nth": 1},
    }
    env = {**os.environ, "KOOKABUG_FAULTS": json.dumps([rule])}
    proc = subprocess.Popen([sys.executable, "-c", WRITER, str(path)], env=env)
    try:
        _wait_for(Path(f"{barrier}.ready"))
        data = path.read_bytes()
        assert not data.endswith(b"\n")
        *whole, partial = data.split(b"\n")
        assert [json.loads(raw)["event"] for raw in whole] == ["run.start", "step.start"]
        assert partial.startswith(b'{"event": "log"')
        view = read_journal(path)
        assert view.truncated and view.truncated_bytes == len(partial)
        assert [e["event"] for e in view.events] == ["run.start", "step.start"]
        Path(f"{barrier}.go").touch()
        assert proc.wait(timeout=30) == 0
    finally:
        proc.kill()
    # 장벽을 지나면 줄을 마저 쓰고, 두 번째 log에는 걸리지 않는다
    view = read_journal(path)
    assert not view.truncated and view.warnings == []
    assert [e["event"] for e in view.events] == ["run.start", "step.start", "log", "log"]


def test_no_fault_env_single_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 규칙이 없으면 줄을 나누어 쓰지 않는다
    writes: list[bytes] = []
    real = os.write

    def spy(fd: int, data: Any) -> int:
        writes.append(bytes(data))
        return real(fd, data)

    monkeypatch.setattr(os, "write", spy)
    with Journal(tmp_path / "e.jsonl", RUN) as journal:
        journal.emit({"event": "debug.pause"})
    assert len(writes) == 1 and writes[0].endswith(b"\n")


def test_write_failure_rejects_later_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 줄 앞부분만 쓰고 실패한 저널에 이어 쓰면 읽기가 그 줄과 다음 줄을 함께 버린다
    path = tmp_path / "e.jsonl"
    real = os.write

    def half_then_fail(fd: int, data: Any) -> int:
        real(fd, bytes(data)[:5])
        raise OSError("디스크 오류")

    with Journal(path, RUN) as journal:
        journal.emit({"event": "debug.pause"})
        monkeypatch.setattr(os, "write", half_then_fail)
        with pytest.raises(OSError, match="디스크"):
            journal.emit({"event": "debug.resume"})
        monkeypatch.setattr(os, "write", real)
        with pytest.raises(JournalClosed, match="쓰기가 실패한"):
            journal.emit({"event": "debug.resume"})
    view = read_journal(path)
    assert view.truncated
    assert [e["event"] for e in view.events] == ["debug.pause"]
