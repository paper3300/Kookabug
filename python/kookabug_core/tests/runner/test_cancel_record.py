"""취소 기록과 마무리의 순서 (구현 계획 M0b 2.6 "취소 순서" 6, 검수 fixci-1 지적 1).

제어 스레드는 사유를 정한 뒤 잠금 밖에서 `cancel.requested`를 쓴다. 그 사이 주 스레드 마무리가
`run.end`를 먼저 쓰면 늦은 기록은 작성기가 거부해 사라진다. 주 스레드는 `record_cancel()`로 기록을
확정한 뒤 `run.end`를 쓴다 — 제어 스레드가 아직 기록에 닿지 않았으면 대신 쓰고, 쓰는 중이면
끝나기를 기다린다. 같은 프로세스에서 실제 `Controller`·`Runner._finish`·`Journal`로 확인한다.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from helpers.worker import Background, ObservedLock

from kookabug_core.record import Journal
from kookabug_core.runner import EXIT_OK, Controller, Runner, RunSpec, Watchdog
from kookabug_core.runner.run import _End
from kookabug_core.runner.spec import ControlSpec
from kookabug_core.win import current


def make_runner(tmp_path: Path) -> tuple[Runner, Controller]:
    """시작 순서를 건너뛰고 저널·제어기만 붙인 runner (제어 채널·감독자 없음)."""
    spec = RunSpec(
        run_id="r1",
        run_dir=tmp_path,
        workspace_root=tmp_path,
        graph="tests/t.graph.json",
        control=ControlSpec("unused", b"x" * 32),
        job_name="unused",
        supervisor=current(),
        deadline_ms=60_000,
    )
    runner = Runner(spec)
    # 시작하지 않는다: 자기 종료하지 않는 감시자
    runner.watchdog = Watchdog(
        spec.supervisor,
        shutdown_grace_ms=spec.shutdown_grace_ms,
        self_kill_margin_ms=spec.self_kill_margin_ms,
    )
    runner.journal = Journal(runner.folder.events, spec.run_id)
    runner.journal.emit({"event": "run.start"})
    runner.controller = Controller(
        cancel=runner.token,
        watchdog=runner.watchdog,
        pause=runner.pause,
        deadline_at=runner.deadline_at,
        peer=None,
    )
    return runner, runner.controller


def records(runner: Runner) -> list[dict[str, Any]]:
    text = runner.folder.events.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_finish_records_cancel_when_control_thread_stalls_before_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 제어 스레드가 사유만 정하고 기록 잠금에 닿기 전에 멈췄다 → 주 스레드가 대신 쓰고 run.end
    runner, controller = make_runner(tmp_path)
    stalled, release = threading.Event(), threading.Event()
    released: list[bool] = []
    attempts: list[str] = []
    control = threading.Thread(target=lambda: controller.cancel("deadline_exceeded"))
    real_notify = controller.notify_stopping

    def notify(reason: Any) -> None:  # 취소 순서 5 (기록 바로 앞)
        if threading.current_thread() is control:
            stalled.set()
            released.append(release.wait(10))
        real_notify(reason)

    def emit(event: Mapping[str, Any]) -> None:
        attempts.append(event["event"])
        runner._emit_quiet(event)

    monkeypatch.setattr(controller, "notify_stopping", notify)
    controller.journal_ready(emit)
    control.start()
    try:
        assert stalled.wait(10)
        assert controller.cancel_reason == "deadline_exceeded"
        code = runner._finish(_End.error("deadline_exceeded", "기한"))
    finally:
        release.set()
        control.join(10)
    assert not control.is_alive() and released == [True]
    assert code == EXIT_OK
    events = records(runner)
    assert [e["event"] for e in events] == ["run.start", "cancel.requested", "run.end"]
    assert events[1]["reason"] == "deadline_exceeded"
    assert events[2]["cancel_reason"] == "deadline_exceeded"
    assert attempts.count("cancel.requested") == 1  # 늦게 깨어난 제어 스레드는 다시 쓰지 않는다


def test_finish_waits_for_cancel_record_in_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 제어 스레드가 기록을 차지하고 쓰는 중에 멈췄다 → 주 스레드는 그 쓰기가 끝난 뒤 run.end
    runner, controller = make_runner(tmp_path)
    claimed, release = threading.Event(), threading.Event()
    released: list[bool] = []
    control = threading.Thread(target=lambda: controller.cancel("cancelled"))

    def emit(event: Mapping[str, Any]) -> None:
        if event["event"] == "cancel.requested" and threading.current_thread() is control:
            claimed.set()
            released.append(release.wait(10))
        runner._emit_quiet(event)

    controller.journal_ready(emit)
    lock = ObservedLock(controller._record_lock)  # journal_ready 뒤: 처음 잡는 것은 제어 스레드
    monkeypatch.setattr(controller, "_record_lock", lock)
    control.start()
    try:
        assert claimed.wait(10)
        finishing = Background(lambda: runner._finish(_End.error("cancelled", "취소")))
        assert lock.attempted.wait(10)  # 마무리가 기록 잠금 앞에 닿았다
        assert lock.locked()  # 제어 스레드가 기록을 붙잡은 채 잠금을 쥐고 있다
        assert not lock.acquired.is_set()
        release.set()
        code = finishing.join()
    finally:
        release.set()
        control.join(10)
    assert not control.is_alive() and released == [True] and lock.acquired.is_set()
    assert code == EXIT_OK
    events = records(runner)
    assert [e["event"] for e in events] == ["run.start", "cancel.requested", "run.end"]
    assert events[2]["cancel_reason"] == "cancelled"
