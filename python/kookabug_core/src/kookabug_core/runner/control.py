"""runner 제어: 제어 스레드, 취소 순서, 경계 멈춤 (구현 계획 M0b 2.6).

**제어 스레드**는 감독자의 제어 요청(`run.cancel`·`run.pause`·`run.resume {mode}`·
`run.breakpoints`)을 받는 즉시 답하고,
감독자 사망(자기 종료 감시자가 세운 값)과 테스트 전체 기한을 20ms마다 본다. 전체 기한은 실행기
런타임과 같은 활성 시계(멈춘 시간을 뺀 시계, M3 2.2)로 보고, 주 스레드가 판정을 확정해 마무리를
시작하면(`finishing`) 더 보지 않는다 — 마무리는 판정을 바꾸지 않고 실제 시간 유예가 따로 있다.
노드를 실행하지 않고, `run.end`·`run.json`·임대권 놓기·입력 백엔드 호출을 하지 않는다. 저널에는
`cancel.requested`·`control.lost`만 쓴다(`run.end` 뒤에는 작성기가 거부하므로 버려진다).

**취소 순서** (`Controller.cancel`, 사유 `cancelled`·`deadline_exceeded`·`supervisor_lost`)

1. 자기 종료 감시자에 종료 단계 진입 시각을 알린다 (저널 쓰기보다 먼저)
2. 취소 토큰을 세운다 — 주 스레드가 다음 확인 지점에서 `Cancelled`(기한이면 `DeadlineExceeded`)로
   풀려 나온다. 액터 게이트보다 먼저 세워, 게이트가 돌려보낸 입력 요청의 `Cancelled`도 같은 사유로
   기록되게 한다. 멈춤(경계·폴링)에서 기다리던 주 스레드도 깨운다. 취소 뒤의 유예(워커 취소
   유예·마무리 유예·자기 종료 감시자)는 실제 시간이다
3. 입력 액터 게이트를 닫는다 — 새 입력 거부, 대기 요청 취소, 큐 맨 앞 `RELEASE_ALL`. 제어 스레드는
   백엔드를 부르지 않는다
4. 워커에 `cancel`(송신 큐) + 유예 타이머 (만료 시 워커 종료, 송신 성공과 무관)
5. 감독자에 `runner.stopping{reason}` 알림 (감독자 하드 종료 타이머의 시작점)
6. `cancel.requested{reason}` 기록 (저널 잠금이 필요한 일은 마지막에). 주 스레드는 `run.end` 전에
   `record_cancel()`을 부른다: 기록이 끝났으면 바로, 쓰는 중이면 끝난 뒤 돌아가고, 제어 스레드가
   사유만 정하고 아직 기록에 닿지 못했으면 주 스레드가 대신 쓴다(한 번만). 실행기가 먼저 기한을
   본 경우도 주 스레드가 같은 `cancel("deadline_exceeded")`로 모은다

`cancel.requested`·액터의 `input.up`·`worker.exit`·`step.end`는 서로 다른 스레드·프로세스가 쓰므로
그 사이 순서는 정해지지 않는다. 정해진 것: 게이트가 닫힌 뒤 새 입력 요청은 처리되지 않는다
(진행 중이던 원시 동작 하나는 끝난다), 그 동작이 누른 키는 액터가 뗀다, `run.end`는 주 스레드가
마지막에 쓴다.

**제어 채널 EOF**는 감독자 사망의 증거가 아니다: `control.lost`만 남기고 하던 일을 계속한다.
"""

from __future__ import annotations

import contextlib
import queue
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final, Literal

from kookabug_core.engine.cancel import CancelReason, CancelToken
from kookabug_core.engine.debug import RESUME_MODES, Breakpoint, ResumeMode, StepPoint, step_limit
from kookabug_core.engine.provenance import Epochs
from kookabug_core.inputs import InputActor
from kookabug_core.runner.clock import ActiveClock
from kookabug_core.runner.watchdog import Watchdog
from kookabug_core.schema import check_shape
from kookabug_core.workerhost import WorkerProcess
from kookabug_sdk import _faults
from kookabug_sdk.rpc import INVALID_PARAMS, METHOD_NOT_FOUND, Incoming, PeerLost, RpcPeer

__all__ = [
    "CONTROL_THREAD_NAME",
    "NOT_PAUSED",
    "ControlState",
    "Controller",
    "NotPaused",
    "PauseGate",
    "PauseReason",
    "PauseWhere",
    "PollPoint",
    "StopReason",
    "cancel_hard_stop_at",
]

CONTROL_THREAD_NAME: Final = "kookabug-runner-control"
_POLL_S: Final = 0.02

type ControlState = Literal["running", "pausing", "paused", "cancelling"]
type StopReason = Literal["finish"] | CancelReason
type Emit = Callable[[Mapping[str, Any]], object]


type PauseWhere = Literal["boundary", "poll"]
type PauseReason = Literal["breakpoint", "step", "request"]

NOT_PAUSED: Final = "not_paused"
"""`run.resume`(Step)을 멈추지 않은 runner가 거절할 때 오류 `data.reason` (code invalid_params)."""


_CLOCK_SLACK_S: Final = 0.005
"""감독자가 보낸 절대 기한을 "유예보다 멀다"고 판정할 때 봐주는 부동소수 오차."""


def cancel_hard_stop_at(
    params: Mapping[str, Any], received: float, shutdown_grace_s: float
) -> float | None:
    """`run.cancel` params(형식 확인 뒤)에서 하드 종료 기한(이 프로세스의 단조 시각)을 정한다.

    - `hard_stop_at_mono`(절대): 같은 PC에서 `time.monotonic`은 시스템 전역 QPC라 감독자와 원점이
      같다는 계약으로, 전달·처리 지연과 상관없이 정확하다. 그래도 그대로 믿지 않는다. 꺼낸 시각
      + `hard_stop_in_ms`와 비교해 이른 쪽을 쓰고, 이미 지났거나 꺼낸 시각 + 마무리 유예보다 멀면
      (감독자는 꺼낸 시각 전에 타이머를 걸었으므로 그럴 수 없다 — 시계 원점이 다르다고 본다)
      꺼낸 시각을 기한으로 해 녹화를 기다리지 않고 바로 기록하게 한다
    - `hard_stop_in_ms`만(절대 시각 없음): 꺼낸 시각 + 남은 시간. 전달 지연만큼 늦게 잡힐 수 있다
    - 둘 다 없으면 None (`runner.stopping` 시각 + 유예로 본다)
    """
    left = params.get("hard_stop_in_ms")
    relative = received + left / 1000 if isinstance(left, int) else None
    absolute = params.get("hard_stop_at_mono")
    if not isinstance(absolute, (int, float)) or isinstance(absolute, bool):
        return relative
    if absolute <= received or absolute > received + shutdown_grace_s + _CLOCK_SLACK_S:
        return received  # 말이 안 되는 기한: 보수적으로 지금
    return float(absolute) if relative is None else min(float(absolute), relative)


class NotPaused(Exception):
    """멈추지 않은 실행에 Step(`step_*`)으로 재개하려 했다. 아무것도 바꾸지 않았다."""

    def __init__(self, state: ControlState) -> None:
        super().__init__(f"멈춰 있지 않다 ({state})")
        self.state: ControlState = state


class PauseGate:
    """멈춤 게이트 (M0b 경계 멈춤 + M3 2.2 폴링 멈춤·활성 시계 + 2.3 브레이크포인트·Step).

    주 스레드가 확인 지점에서 멈춘다: 스텝 시작 직전(`at_boundary` — 브레이크포인트·Step 목표·
    일시정지 요청), 또는 코어 노드의 멈출 수 있는 기다림 안(`at_poll` — 일시정지 요청만). 멈춤을
    확정하면 활성 시계를 세우고(`debug.pause`), 재개하면 다시 돌린다(`debug.resume`의 `paused_ms`).
    그래서 멈춘 시간은 노드 기한·전체 기한에서 빠진다.

    재개 방식(`resume(mode)`)이 Step이면 멈춘 자리의 호출 깊이로 다음에 멈출 경계를 정한다
    (`engine.debug.step_limit`). 멈추면(어떤 이유로든) 목표·요청은 사라진다.

    멈춘 동안 취소는 바로 먹힌다(취소가 재개를 이긴다). 멈춘 동안 입력 임대권은 그대로 쥔다.
    """

    def __init__(
        self,
        cancel: CancelToken,
        clock: ActiveClock,
        breakpoints: Iterable[Breakpoint] = (),
        epochs: Epochs | None = None,
    ) -> None:
        self._cancel = cancel
        self.clock = clock
        self.epochs = epochs if epochs is not None else Epochs()
        """관측 세대: 재개할 때마다(Step 포함) 1 올린다 (M3 2.4, 사용자 결정 U4)."""
        self._cond = threading.Condition()
        self._requested = False
        self._paused = False
        self._where: PauseWhere | None = None
        self._point: StepPoint | None = None
        """멈춘 자리 (멈춰 있을 때만)."""
        self._breakpoints: frozenset[Breakpoint] = frozenset(breakpoints)
        self._limit: int | None = None
        """Step 목표: 이 깊이 이하인 다음 경계에서 멈춘다 (None이면 목표 없음)."""
        self._mode: ResumeMode = "continue"
        """마지막 재개 방식 (`debug.resume.mode`)."""
        self.count = 0
        """`debug.pause`를 남긴 횟수 (`run.json`의 `pause_count`)."""
        self.on_pause: Callable[[bool, str], None] | None = None
        """멈춤 확정(True)·재개(False) 알림 (주 스레드 — 녹화 게이트, M3 2.5)."""

    def request(self) -> ControlState:
        with self._cond:
            if self._cancel.cancelled:
                return "cancelling"
            if self._paused:
                return "paused"
            self._requested = True
            self._cond.notify_all()  # 폴링 확인 지점의 기다림을 깨운다
            return "pausing"

    def resume(self, mode: ResumeMode = "continue") -> ControlState:
        """재개한다. `continue`는 멈추지 않았어도 받는다(일시정지 요청을 거둔다, M0b). Step은
        멈춰 있을 때만 받고, 아니면 `NotPaused`."""
        with self._cond:
            if mode != "continue" and not self._paused:
                raise NotPaused(self._state())
            point = self._point
            self._limit = None if point is None else step_limit(mode, point.depth)
            self._mode = mode
            self._requested = False
            self._paused = False
            self._cond.notify_all()
            return "cancelling" if self._cancel.cancelled else "running"

    def set_breakpoints(self, breakpoints: Iterable[Breakpoint]) -> ControlState:
        """브레이크포인트 목록 전체를 바꾼다 (다음 경계부터)."""
        with self._cond:
            self._breakpoints = frozenset(breakpoints)
            return self._state()

    @property
    def breakpoints(self) -> frozenset[Breakpoint]:
        with self._cond:
            return self._breakpoints

    def wake(self) -> None:
        with self._cond:
            self._cond.notify_all()

    @property
    def state(self) -> ControlState:
        with self._cond:
            return self._state()

    def _state(self) -> ControlState:
        if self._cancel.cancelled:
            return "cancelling"
        if self._paused:
            return "paused"
        return "pausing" if self._requested else "running"

    @property
    def paused_where(self) -> PauseWhere | None:
        """멈춰 있으면 그 자리(`boundary`·`poll`), 아니면 None."""
        with self._cond:
            return self._where if self._paused else None

    @property
    def intervened(self) -> bool:
        """한 번이라도 멈췄다 (`debug_intervened`)."""
        return self.count > 0

    def wait_request(self, timeout_s: float) -> bool:
        """주 스레드(폴링 확인 지점): 멈춤 요청·취소까지 최대 `timeout_s`초 기다린다. 요청이 있으면
        True (소비하지 않는다 — `at_poll`이 확정한다)."""
        with self._cond:
            if not self._requested and not self._cancel.cancelled and timeout_s > 0:
                self._cond.wait(timeout_s)
            return self._requested and not self._cancel.cancelled

    def at_boundary(self, point: StepPoint, emit: Emit) -> None:
        """주 스레드: 스텝 시작 직전. 브레이크포인트·Step 목표·일시정지 요청 중 하나라도 맞으면
        `debug.pause` 뒤 재개·취소를 기다린다. 이유는 브레이크포인트 > Step > 요청 순으로 하나."""
        self._cancel.check()
        with self._cond:
            reason: PauseReason | None
            if point.key in self._breakpoints:
                reason = "breakpoint"
            elif self._limit is not None and point.depth <= self._limit and not point.entry:
                reason = "step"
            elif self._requested:
                reason = "request"
            else:
                reason = None
            if reason is not None:
                self._enter(point, "boundary")
        if reason is not None:
            self._hold(point, "boundary", reason, emit)

    def at_poll(self, point: StepPoint, emit: Emit) -> None:
        """주 스레드: 코어 노드의 멈출 수 있는 기다림 안. 일시정지 요청만 본다(브레이크포인트·Step
        목표는 경계에서만). 요청이 있으면 그 자리에서 멈춘다."""
        self._cancel.check()
        with self._cond:
            if not self._requested:
                return
            self._enter(point, "poll")
        self._hold(point, "poll", "request", emit)

    def _enter(self, point: StepPoint, where: PauseWhere) -> None:
        """멈춤 확정 (잠금 안): 요청·Step 목표는 이 멈춤으로 끝난다."""
        self._requested = False
        self._limit = None
        self._paused = True
        self._where = where
        self._point = point
        self._mode = "continue"

    def _hold(self, point: StepPoint, where: PauseWhere, reason: PauseReason, emit: Emit) -> None:
        # 멈춤 확정: 이 순간부터 활성 시계가 머문다 (기록보다 먼저 — 쓰는 시간도 멈춘 시간이다)
        self.clock.pause()
        self.count += 1
        if self.on_pause is not None:
            self.on_pause(True, point.step)  # 멈춘 동안 영상을 쓰지 않는다 (사용자 결정 U7)
        try:
            emit(
                {
                    "event": "debug.pause",
                    **point.to_event(),
                    "reason": reason,
                    "where": where,
                }
            )
            with self._cond:
                while self._paused and not self._cancel.cancelled:
                    self._cond.wait()
        finally:
            with self._cond:
                self._paused = False
                self._where = None
                self._point = None
                mode = self._mode
            paused_ms = self.clock.resume()
            if self.on_pause is not None:
                self.on_pause(False, point.step)
        self._cancel.check()
        # 재개: 멈춘 동안 화면이 바뀌었을 수 있으니 이전 세대 관측값을 쓰지 않게 세대를 올린다
        epoch = self.epochs.advance()
        emit(
            {
                "event": "debug.resume",
                "step": point.step,
                "mode": mode,
                "epoch": epoch,
                "paused_ms": paused_ms,
            }
        )


class PollPoint:
    """실행기의 폴링 확인 지점(`engine.debug.PausePoint`) → 멈춤 게이트 + 저널 쓰기."""

    def __init__(self, gate: PauseGate, emit: Emit) -> None:
        self._gate = gate
        self._emit = emit

    def wait_request(self, timeout_s: float) -> bool:
        return self._gate.wait_request(timeout_s)

    def at_poll(self, point: StepPoint) -> None:
        self._gate.at_poll(point, self._emit)


class Controller:
    """제어 스레드와 취소 순서. 주 스레드가 액터·워커를 만들면 `attach_*`로 알린다 — 이미 취소된
    뒤면 그 자리에서 게이트를 닫거나 워커 취소를 시작한다."""

    def __init__(
        self,
        *,
        cancel: CancelToken,
        watchdog: Watchdog,
        pause: PauseGate,
        deadline_at_ms: int,
        peer: RpcPeer | None,
    ) -> None:
        self.token = cancel
        self.watchdog = watchdog
        self.pause = pause
        self.clock = pause.clock
        self.deadline_at_ms = deadline_at_ms
        """전체 기한 시각 (활성 시계 ms — 실행기 런타임의 전체 기한과 같은 시계, M3 2.2)."""
        self.peer = peer
        self._lock = threading.Lock()
        self._reason: CancelReason | None = None
        self._actor: InputActor | None = None
        self._workers: list[WorkerProcess] = []
        self._emit: Emit | None = None
        self._cancel_logged = False
        self._record_lock = threading.Lock()  # `cancel.requested` 차지·기록을 한 번에
        self._stopping_sent = False
        self.stopping_at: float | None = None
        """`runner.stopping`을 처음 보낸 실제 단조 시각 (감독자 하드 종료 타이머의 시작점)."""
        self._finishing = False
        self._hard_stop_at: float | None = None
        """감독자가 `run.cancel`로 알린 하드 종료 기한 (실제 단조 시각)."""
        self._finish_extended: float | None = None
        """감독자가 영상 마무리 단계를 허락하며 다시 건 하드 종료 기한 (실제 단조 시각)."""
        self._lost_seen = False
        self._external_stop = False
        self._deadline_listeners: list[threading.Event] = []
        """종료 기한(`finish_by`)이 바뀔 수 있을 때 세우는 Event (마무리의 기다림이 깨어 다시
        잰다)."""
        self._channel_lost = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name=CONTROL_THREAD_NAME, daemon=True)

    @property
    def cancel_reason(self) -> CancelReason | None:
        return self._reason

    @property
    def external_stop(self) -> bool:
        """감독자가 `run.cancel`을 보냈거나 감독자가 죽었다 (먼저 정해진 취소 사유와 상관없이 —
        판정 확정 뒤에 와도). 영상 마무리 단계는 이때 기다리지 않고 바로 끝낸다."""
        return self._external_stop

    # ------------------------------------------------------------ 수명

    def start(self) -> Controller:
        self._thread.start()
        return self

    def stop(self) -> None:
        """주 스레드 마무리 끝: 제어 스레드를 멈춘다 (이 뒤 들어온 요청에는 답하지 않는다)."""
        self._stop.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(1.0)

    def finishing(self) -> None:
        """판정이 확정돼 주 스레드가 마무리를 시작한다: 이 뒤로는 전체 기한 감시를 끝낸다.

        마무리(녹화 정리·`run.end`·`run.json`)는 판정을 바꾸지 않으므로 기한이 지나도 취소 사유를
        붙이지 않는다. 마무리의 실제 시간 유예(감독자 하드 종료·자기 종료 감시자)와 감독자 사망
        감시·외부 취소는 그대로다. 이미 시작된 취소는 그대로 남는다."""
        with self._lock:
            self._finishing = True

    def _note_hard_stop(self, at: float) -> None:
        with self._lock:
            if self._hard_stop_at is None or at < self._hard_stop_at:
                self._hard_stop_at = at
        self._deadline_changed()

    def add_deadline_listener(self, event: threading.Event) -> None:
        """종료 기한이 바뀔 수 있으면(감독자가 알린 하드 종료·취소 시작·`runner.stopping`) `event`를
        세운다. 마무리가 녹화·워커·액터를 기다리는 동안 더 이른 기한이 알려지면 바로 깨어 기다림을
        줄인다. 받은 쪽은 깨면 `finish_by`를 다시 읽는다 (신호에 값은 없다)."""
        with self._lock:
            self._deadline_listeners.append(event)

    def remove_deadline_listener(self, event: threading.Event) -> None:
        with self._lock, contextlib.suppress(ValueError):
            self._deadline_listeners.remove(event)

    def _deadline_changed(self) -> None:
        with self._lock:
            listeners = list(self._deadline_listeners)
        for event in listeners:
            event.set()

    def extend_finish(self, at: float) -> None:
        """감독자가 run.end 뒤 영상 마무리 단계를 허락해 하드 종료 타이머를 `at`(실제 단조 시각)으로
        다시 걸었다: `runner.stopping` + 유예 대신 이 기한을 쓴다. 외부 취소(`run.cancel` 기한)·
        감독자 사망 + 유예는 그대로 더 이르면 이긴다."""
        with self._lock:
            self._finish_extended = at
        self._deadline_changed()

    def finish_by(self, shutdown_grace_ms: int) -> float | None:
        """runner가 끝나야 하는 가장 이른 실제 단조 시각 (모르면 None). 알려진 종료 기한 중 가장
        이른 것이다: 감독자가 `run.cancel`로 알린 하드 종료 기한, 감시자가 알아챈 감독자 사망 +
        유예(자기 종료), 처음 보낸 `runner.stopping` + 유예(감독자가 받은 뒤 거는 타이머라 실제
        기한은 이보다 늦다 — 영상 마무리 단계를 허락받았으면 감독자가 다시 건 기한). 마무리는 이
        시각에서 기록 여유를 뺀 때까지만 녹화를 기다린다."""
        grace_s = shutdown_grace_ms / 1000
        with self._lock:
            times = [t for t in (self._hard_stop_at,) if t is not None]
            if self.stopping_at is not None:
                stopping_by = self.stopping_at + grace_s
                if self._finish_extended is not None:
                    stopping_by = max(stopping_by, self._finish_extended)
                times.append(stopping_by)
        lost_at = self.watchdog.supervisor_lost_at
        if lost_at is not None:
            times.append(lost_at + self.watchdog.shutdown_grace_s)
        return min(times) if times else None

    def journal_ready(self, emit: Emit) -> None:
        """저널이 열렸다. 그 전에 취소됐으면 `cancel.requested`를 지금 남긴다."""
        with self._lock:
            self._emit = emit
        self.record_cancel()

    def record_cancel(self) -> None:
        """시작된 취소의 `cancel.requested`를 한 번만 쓴다. 제어 스레드든 주 스레드든 먼저 온
        쪽이 쓰고, 늦게 온 쪽은 그 쓰기(시도)가 끝난 뒤에 돌아간다.

        주 스레드 마무리는 `run.end` 전에 이것을 부른다: 제어 스레드가 사유만 정하고 아직 기록에
        닿지 못했으면 주 스레드가 대신 쓴다(`run.end` 뒤에는 작성기가 거부하므로 기다림만으로는
        늦은 기록이 버려질 수 있다)."""
        with self._record_lock:
            with self._lock:
                reason = self._reason
                if reason is None or self._emit is None or self._cancel_logged:
                    return
                self._cancel_logged = True
            self._safe_emit({"event": "cancel.requested", "reason": reason})

    def attach_actor(self, actor: InputActor) -> None:
        with self._lock:
            self._actor = actor
            cancelled = self._reason is not None
        if cancelled:
            actor.close_gate()

    def attach_worker(self, worker: WorkerProcess) -> None:
        """워커를 취소 대상에 더한다 (환경마다 하나 — 취소는 모두에게)."""
        with self._lock:
            self._workers.append(worker)
            cancelled = self._reason is not None
        if cancelled:
            worker.cancel()

    # ------------------------------------------------------------ 감독자에게

    def notify_stopping(self, reason: StopReason) -> None:
        """`runner.stopping` (처음 한 번). 송신 큐에 넣기만 한다."""
        with self._lock:
            if self._stopping_sent:
                return
            self._stopping_sent = True
            self.stopping_at = time.monotonic()
        self._deadline_changed()
        peer = self.peer
        if peer is not None:
            with contextlib.suppress(PeerLost):
                peer.notify("runner.stopping", {"reason": reason})

    # ------------------------------------------------------------ 취소 순서

    def cancel(self, reason: CancelReason) -> bool:
        """취소 순서를 시작한다 (처음 한 번만, 사유는 처음 것). 어느 스레드에서 불러도 된다.
        마무리를 시작한 뒤(`finishing`)의 기한 초과는 무시한다 — 제어 스레드가 기한을 본 직후
        주 스레드가 판정을 확정해도 확정 뒤에는 취소가 시작되지 않는다."""
        if self._reason is None:
            _faults.fault_point("runner.before_cancel", event=reason)
        with self._lock:
            if self._reason is not None:
                return False
            if reason == "deadline_exceeded" and self._finishing:
                return False
            self._reason = reason
            actor = self._actor
            workers = list(self._workers)
        self.watchdog.arm()
        self.token.cancel(reason)
        self.pause.wake()
        if actor is not None:
            actor.close_gate()
        for worker in workers:
            worker.cancel()
        self.notify_stopping(reason)
        # 감독자 사망 취소면 사망 + 유예가 새 종료 기한이다 (stopping을 이미 보냈어도 알린다)
        self._deadline_changed()
        self.record_cancel()
        return True

    def _safe_emit(self, event: Mapping[str, Any]) -> None:
        emit = self._emit
        if emit is None:
            return
        # run.end 뒤(JournalClosed)·쓰기 실패한 저널: 제어 스레드의 기록은 버려도 된다
        with contextlib.suppress(Exception):
            emit(event)

    # ------------------------------------------------------------ 제어 스레드

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.watchdog.supervisor_lost and not self._lost_seen:
                self._lost_seen = True
                self._external_stop = True
                # 이미 다른 사유로 취소했어도 사망 + 유예가 새 종료 기한이다 (영상 마무리 단계의
                # 긴 기다림도 깨운다)
                if not self.cancel("supervisor_lost"):
                    self._deadline_changed()
            if (
                self._reason is None
                and not self._finishing
                and self.clock.now_ms() >= self.deadline_at_ms
            ):
                self.cancel("deadline_exceeded")
            peer = self.peer
            if peer is None or self._channel_lost:
                self._stop.wait(_POLL_S)
                continue
            try:
                item = peer.incoming.get(timeout=_POLL_S)
            except queue.Empty:
                continue
            if self._stop.is_set():
                return
            if isinstance(item, PeerLost):
                self._channel_lost = True
                self._safe_emit({"event": "control.lost", "error": str(item)})
            else:
                self._handle(peer, item)

    def _handle(self, peer: RpcPeer, request: Incoming) -> None:
        method = request.method
        # 받은 제어 요청을 처리하기 직전 (이벤트 = 메서드: 늦은 수신 처리 흉내)
        _faults.fault_point("runner.before_control", event=method)
        if method == "run.cancel":
            received = time.monotonic()
            params = request.params
            # 감독자가 이미 건 하드 종료 기한 (형식이 틀려도 취소는 받는다)
            if not check_shape(params, "rpc", ref="#/$defs/RunCancelParams"):
                at = cancel_hard_stop_at(params, received, self.watchdog.shutdown_grace_s)
                if at is not None:
                    self._note_hard_stop(at)
            self._respond(peer, request, "cancelling")
            self._external_stop = True
            if not self.cancel("cancelled"):
                self._deadline_changed()  # 이미 다른 사유로 취소했어도 마무리 기다림을 깨운다
        elif method == "run.pause":
            self._respond(peer, request, self.pause.request())
        elif method == "run.resume":
            mode = request.params.get("mode", "continue")
            if mode not in RESUME_MODES:
                self._reject(peer, request, f"모르는 재개 방식 {mode!r}")
                return
            try:
                state = self.pause.resume(mode)
            except NotPaused as exc:
                self._reject(peer, request, str(exc), {"reason": NOT_PAUSED, "state": exc.state})
                return
            self._respond(peer, request, state)
        elif method == "run.breakpoints":
            params = request.params
            if check_shape(params, "rpc", ref="#/$defs/RunBreakpointsParams"):
                self._reject(peer, request, "run.breakpoints params 형식이 틀렸다")
                return
            state = self.pause.set_breakpoints(Breakpoint.many(params["breakpoints"]))
            self._respond(peer, request, state)
        elif not request.is_notification:
            with contextlib.suppress(PeerLost):
                peer.respond_error(request, METHOD_NOT_FOUND, f"모르는 제어 메서드 {method}")

    @staticmethod
    def _respond(peer: RpcPeer, request: Incoming, state: ControlState) -> None:
        if request.is_notification:
            return
        with contextlib.suppress(PeerLost):
            peer.respond(request, {"state": state})

    @staticmethod
    def _reject(
        peer: RpcPeer, request: Incoming, message: str, data: Mapping[str, Any] | None = None
    ) -> None:
        if request.is_notification:
            return
        with contextlib.suppress(PeerLost):
            peer.respond_error(
                request, INVALID_PARAMS, message, None if data is None else dict(data)
            )
