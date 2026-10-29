"""취소 사유·취소로 깨는 sleep·이벤트 보관 옵션·경계 훅 (구현 계획 M0b 2.6, T9 엔진 변경)."""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import make_workspace
from helpers.run import TEST, tk
from testkit import registry_with_testkit

from kookabug_core.engine import (
    Cancelled,
    CancelToken,
    DeadlineExceeded,
    ExecOptions,
    Executor,
    MemoryEventSink,
    SystemClock,
)
from kookabug_core.engine.cancel import CancelReason
from kookabug_core.loader import load_program


def delay_program(tmp_path: Path) -> Any:
    ws = make_workspace(tmp_path)
    (
        tk()
        .entry("n_delay")
        .node("n_delay", "core.flow.delay", inputs={"ms": 10_000}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
        .write(ws, TEST)
    )
    return load_program(ws, TEST)


class CancelOnStart:
    """`n_delay`가 시작하면 그 사유로 취소한다."""

    def __init__(self, token: CancelToken, reason: CancelReason) -> None:
        self.token = token
        self.reason: CancelReason = reason
        self.events: list[dict[str, Any]] = []

    def emit(self, event: Mapping[str, Any]) -> None:
        self.events.append(dict(event))
        if event["event"] == "step.start" and event["node"] == "n_delay":
            self.token.cancel(self.reason)


@pytest.mark.parametrize(
    ("reason", "status", "code"),
    [
        ("cancelled", "cancelled", "cancelled"),
        ("deadline_exceeded", "error", "deadline_exceeded"),
        ("supervisor_lost", "cancelled", "cancelled"),
    ],
)
def test_cancel_reason_maps_to_code(
    tmp_path: Path, reason: CancelReason, status: str, code: str
) -> None:
    token = CancelToken()
    sink = CancelOnStart(token, reason)
    result = Executor(cancel=token, sink=sink).run(delay_program(tmp_path))
    (end,) = [e for e in sink.events if e["event"] == "step.end" and e["step"] != "s1"]
    assert end["status"] == status and end["error"]["code"] == code
    assert result.verdict == "error" and result.code == code
    assert token.reason == reason


def test_cancel_reason_first_wins() -> None:
    token = CancelToken()
    token.cancel("deadline_exceeded")
    token.cancel("cancelled")
    assert token.reason == "deadline_exceeded"
    with pytest.raises(DeadlineExceeded):
        token.check()


def test_unknown_cancel_reason_rejected() -> None:
    with pytest.raises(ValueError, match="취소 사유"):
        CancelToken().cancel("bored")  # type: ignore[arg-type]


def test_system_clock_sleep_wakes_on_cancel() -> None:
    token = CancelToken()
    clock = SystemClock(token)
    threading.Timer(0.05, token.cancel).start()
    began = time.monotonic()
    clock.sleep(10_000)
    assert time.monotonic() - began < 1.0
    with pytest.raises(Cancelled):
        token.check()


def test_executor_default_clock_wakes_on_cancel(tmp_path: Path) -> None:
    # 시계를 주지 않으면 실행기의 SystemClock은 그 실행의 취소 토큰으로 깬다
    token = CancelToken()
    executor = Executor(cancel=token)
    assert isinstance(executor.clock, SystemClock) and executor.clock.cancel is token
    program = delay_program(tmp_path)
    threading.Timer(0.1, token.cancel).start()
    began = time.monotonic()
    result = executor.run(program)
    assert time.monotonic() - began < 2.0
    assert result.code == "cancelled"


def test_collect_events_false_keeps_result_events_empty(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    tk().entry("n_pass").node("n_pass", "core.test.pass").write(ws, TEST)
    sink = MemoryEventSink()
    result = Executor(sink=sink).run(load_program(ws, TEST), ExecOptions(collect_events=False))
    assert result.verdict == "pass"
    assert result.events == []
    assert [e["event"] for e in sink.events] == ["step.start", "step.end", "step.start", "step.end"]
    collected = Executor().run(load_program(ws, TEST))
    assert len(collected.events) == 4  # 기본은 그대로 모은다 (M0a 호환)


def test_before_step_called_before_step_start(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    tk().entry("n_pass").node("n_pass", "core.test.pass").write(ws, TEST)
    sink = MemoryEventSink()
    seen: list[tuple[str, int]] = []
    Executor(sink=sink, before_step=lambda step: seen.append((step, len(sink.events)))).run(
        load_program(ws, TEST)
    )
    # 스텝마다 step.start를 쓰기 전에 불린다
    assert seen == [("s1", 0), ("s2", 2)]


def test_before_step_cancel_ends_run_without_starting_step(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    tk().entry("n_pass").node("n_pass", "core.test.pass").write(ws, TEST)
    sink = MemoryEventSink()
    token = CancelToken()

    def boundary(step: str) -> None:
        if step == "s2":
            token.cancel("deadline_exceeded")
            token.check()

    result = Executor(sink=sink, cancel=token, before_step=boundary).run(load_program(ws, TEST))
    assert result.verdict == "error" and result.code == "deadline_exceeded"
    assert result.failure_step is None
    assert [e["event"] for e in sink.events] == ["step.start", "step.end"]


class _GateInput:
    """입력 액터 게이트 흉내: 기한 초과로 취소된 뒤 일반 `Cancelled`로 요청을 돌려보낸다."""

    def __init__(self, token: CancelToken) -> None:
        self.token = token

    def click(self, at: Any, *, button: str = "left") -> None:
        self.token.cancel("deadline_exceeded")
        raise Cancelled("입력이 막혔다")

    def key(self, key: str) -> None:
        raise AssertionError

    def type_text(self, text: Any) -> None:
        raise AssertionError


class _GatePlatform:
    def __init__(self, token: CancelToken) -> None:
        self.input = _GateInput(token)

    def capture(self, window: Any, region: Any) -> Any:
        raise AssertionError


def test_gate_cancelled_is_recorded_with_token_reason(tmp_path: Path) -> None:
    # 다른 곳(입력 액터 게이트)이 던진 일반 Cancelled도 기한 초과 취소면 deadline_exceeded
    ws = make_workspace(tmp_path)
    (
        tk()
        .entry("n_tap")
        .node("n_tap", "testkit.input.tap", inputs={"x": 1, "y": 2}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
        .write(ws, TEST)
    )
    token = CancelToken()
    sink = MemoryEventSink()
    result = Executor(
        registry_with_testkit(), platform=_GatePlatform(token), cancel=token, sink=sink
    ).run(load_program(ws, TEST))
    assert result.code == "deadline_exceeded"
    (end,) = [e for e in sink.events if e["event"] == "step.end" and e["step"] == "s2"]
    assert end["status"] == "error" and end["error"]["code"] == "deadline_exceeded"
