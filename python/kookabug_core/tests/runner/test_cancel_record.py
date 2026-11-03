"""취소 기록과 마무리의 순서 (구현 계획 M0b 2.6 "취소 순서" 6, 검수 fixci-1 지적 1).

제어 스레드는 사유를 정한 뒤 잠금 밖에서 `cancel.requested`를 쓴다. 그 사이 주 스레드 마무리가
`run.end`를 먼저 쓰면 늦은 기록은 작성기가 거부해 사라진다. 주 스레드는 `record_cancel()`로 기록을
확정한 뒤 `run.end`를 쓴다 — 제어 스레드가 아직 기록에 닿지 않았으면 대신 쓰고, 쓰는 중이면
끝나기를 기다린다. 같은 프로세스에서 실제 `Controller`·`Runner._finish`·`Journal`로 확인한다.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from helpers.worker import Background, ObservedLock

from kb_testing.proc import wait_until
from kookabug_core.record import Journal
from kookabug_core.runner import EXIT_OK, Controller, Runner, RunSpec, Watchdog
from kookabug_core.runner.control import cancel_hard_stop_at
from kookabug_core.runner.run import _End, video_wait_s
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
        deadline_at_ms=runner.deadline_at_ms,
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


# ---------------------------------------------------------------- 판정 확정 뒤 기한 (CI 수정 5)


def test_finishing_ends_only_deadline_watch(tmp_path: Path) -> None:
    # 마무리를 시작하면 기한 초과는 취소를 시작하지 않는다. 외부 취소는 그대로 받는다
    runner, controller = make_runner(tmp_path)
    controller.finishing()
    assert controller.cancel("deadline_exceeded") is False
    assert controller.cancel_reason is None and not runner.token.cancelled
    assert controller.cancel("cancelled") is True
    assert controller.cancel_reason == "cancelled"


def test_control_thread_skips_passed_deadline_while_finishing_but_sees_supervisor_loss(
    tmp_path: Path,
) -> None:
    runner, controller = make_runner(tmp_path)
    controller.deadline_at_ms = 0  # 기한은 이미 지났다
    controller.finishing()
    controller.start()
    try:
        time.sleep(0.3)  # 제어 스레드가 20ms마다 여러 번 본다
        assert controller.cancel_reason is None
        # 감독자 사망 감시는 마무리 중에도 돈다
        assert runner.watchdog is not None
        runner.watchdog.supervisor_lost_at = time.monotonic()
        wait_until(lambda: controller.cancel_reason == "supervisor_lost", timeout=5)
    finally:
        controller.stop()


def test_control_thread_still_cancels_on_deadline_before_finishing(tmp_path: Path) -> None:
    # 대조: 마무리 전에는 지난 기한이 바로 deadline_exceeded 취소다
    _, controller = make_runner(tmp_path)
    controller.deadline_at_ms = 0
    controller.start()
    try:
        wait_until(lambda: controller.cancel_reason == "deadline_exceeded", timeout=5)
    finally:
        controller.stop()


def test_finish_after_deadline_passed_has_no_cancel_reason(tmp_path: Path) -> None:
    # 판정(pass)이 정해진 뒤 마무리 중에 기한이 지나도 run.end에 취소 사유·cancel.requested가 없다
    runner, controller = make_runner(tmp_path)
    controller.journal_ready(runner._emit_quiet)
    controller.deadline_at_ms = 0
    real_finishing = controller.finishing

    def finishing() -> None:
        real_finishing()
        controller.start()  # 확정 직후 제어 스레드가 지난 기한을 본다
        time.sleep(0.2)

    controller.finishing = finishing  # type: ignore[method-assign]
    code = runner._finish(_End(verdict="pass", code="test_pass", reason="통과"))
    assert code == EXIT_OK
    events = records(runner)
    assert [e["event"] for e in events] == ["run.start", "run.end"]
    assert events[1]["verdict"] == "pass" and "cancel_reason" not in events[1]


def test_finish_by_is_earliest_known_stop(tmp_path: Path) -> None:
    # 마무리 예산의 끝: 감독자가 알린 하드 종료·감독자 사망 + 유예·runner.stopping + 유예 중
    # 가장 이른 것
    runner, controller = make_runner(tmp_path)
    watchdog = runner.watchdog
    assert watchdog is not None
    assert controller.finish_by(3_000) is None
    controller.notify_stopping("cancelled")
    stopping_at = controller.stopping_at
    assert stopping_at is not None
    assert controller.finish_by(3_000) == pytest.approx(stopping_at + 3.0)
    controller._note_hard_stop(stopping_at + 1.5)  # run.cancel의 hard_stop_in_ms
    assert controller.finish_by(3_000) == pytest.approx(stopping_at + 1.5)
    watchdog.supervisor_lost_at = stopping_at - 5.0  # 사망 + 감시자 유예
    assert controller.finish_by(3_000) == pytest.approx(
        stopping_at - 5.0 + watchdog.shutdown_grace_s
    )


class _StuckActor:
    """`RELEASE_ALL`·`STOP`을 처리하다 백엔드에서 멈춘 입력 액터 흉내: 스레드가 끝나지 않는다."""

    quiesced = False

    def stop(self, timeout: float | None = None) -> bool:
        return False

    def join(self, timeout: float) -> bool:
        time.sleep(max(0.0, timeout))
        return False


def test_finish_actor_wait_shrinks_when_earlier_deadline_arrives(tmp_path: Path) -> None:
    # 정상 판정 뒤 멈춘 액터를 기다리는 중(유예 5초의 절반 = 2.5초)에 더 이른 종료 기한(외부 취소)이
    # 알려지면 기다림이 그 기한에서 기록 여유(1초)를 뺀 때까지로 바로 줄어 pass를 기록한다.
    # 실제 runner로는 pass 뒤 액터가 멈춘 상태를 만들 수 없다: 노드의 키·마우스 입력은 노드가
    # 끝나기 전에 떼므로, 마무리의 RELEASE_ALL은 백엔드를 부르지 않아 훅이 걸리지 않는다
    runner, controller = make_runner(tmp_path)
    controller.journal_ready(runner._emit_quiet)
    runner.actor = cast(Any, _StuckActor())
    finishing = Background(lambda: runner._finish(_End("pass", "test_pass", "통과")))
    time.sleep(0.3)  # 마무리가 액터를 기다리는 중
    arrived = time.monotonic()
    controller._note_hard_stop(arrived + 1.2)  # 기다림의 끝 = 0.2초 뒤
    code = finishing.join()
    waited = time.monotonic() - arrived
    assert code == EXIT_OK
    assert waited < 1.0, waited  # 고정 기다림이면 약 2.2초 더 기다린다
    events = records(runner)
    assert events[-1]["event"] == "run.end" and events[-1]["verdict"] == "pass"


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        # 절대 기한이 정확: 전달이 1.3초 늦어 상대값(꺼낸 때 + 3초)이 늦어도 절대 기한
        ({"hard_stop_at_mono": 101.7, "hard_stop_in_ms": 3_000}, 101.7),
        # 상대값이 더 이르면 그쪽 (어느 쪽도 늦게 잡지 않는다)
        ({"hard_stop_at_mono": 102.5, "hard_stop_in_ms": 2_000}, 102.0),
        # 이미 지났거나 유예(3초)보다 멀다 = 시계 원점이 다르다고 봄 → 지금(녹화를 기다리지 않음)
        ({"hard_stop_at_mono": 99.0, "hard_stop_in_ms": 3_000}, 100.0),
        ({"hard_stop_at_mono": 100.0, "hard_stop_in_ms": 3_000}, 100.0),
        ({"hard_stop_at_mono": 60_103.0, "hard_stop_in_ms": 3_000}, 100.0),
        ({"hard_stop_at_mono": 103.5, "hard_stop_in_ms": 3_000}, 100.0),
        # 절대 시각 없이 상대값만 (전달 지연만큼 늦을 수 있는 옛 방식)
        ({"hard_stop_in_ms": 2_500}, 102.5),
        ({}, None),
    ],
)
def test_cancel_hard_stop_at_trusts_neither_side_late(
    params: dict[str, Any], expected: float | None
) -> None:
    got = cancel_hard_stop_at(params, received=100.0, shutdown_grace_s=3.0)
    assert got == (None if expected is None else pytest.approx(expected))


@pytest.mark.parametrize(
    ("grace_ms", "wait_s"),
    [(5_000, 3.0), (4_000, 3.0), (3_000, 2.0), (2_000, 1.0), (1_500, 0.75), (0, 0.0)],
)
def test_video_wait_leaves_record_reserve_inside_shutdown_grace(
    grace_ms: int, wait_s: float
) -> None:
    # 녹화 기다림 상한: 3초, 단 마무리 유예에서 기록 여유(1초, 유예가 2초 미만이면 절반)를 뺀 시간
    assert video_wait_s(grace_ms) == pytest.approx(wait_s)
    assert video_wait_s(grace_ms) < grace_ms / 1000 or grace_ms == 0
