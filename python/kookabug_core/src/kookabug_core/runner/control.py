"""runner 제어: 제어 스레드, 취소 순서, 경계 멈춤 (구현 계획 M0b 2.6).

**제어 스레드**는 감독자의 제어 요청(`run.cancel`·`run.pause`·`run.resume`)을 받는 즉시 답하고,
감독자 사망(자기 종료 감시자가 세운 값)과 테스트 전체 기한을 20ms마다 본다. 노드를 실행하지 않고,
`run.end`·`run.json`·임대권 놓기·입력 백엔드 호출을 하지 않는다. 저널에는 `cancel.requested`·
`control.lost`만 쓴다(`run.end` 뒤에는 작성기가 거부하므로 버려진다).

**취소 순서** (`Controller.cancel`, 사유 `cancelled`·`deadline_exceeded`·`supervisor_lost`)

1. 자기 종료 감시자에 종료 단계 진입 시각을 알린다 (저널 쓰기보다 먼저)
2. 취소 토큰을 세운다 — 주 스레드가 다음 확인 지점에서 `Cancelled`(기한이면 `DeadlineExceeded`)로
   풀려 나온다. 액터 게이트보다 먼저 세워, 게이트가 돌려보낸 입력 요청의 `Cancelled`도 같은 사유로
   기록되게 한다. 경계 멈춤에서 기다리던 주 스레드도 깨운다
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
from collections.abc import Callable, Mapping
from typing import Any, Final, Literal

from kookabug_core.engine.cancel import CancelReason, CancelToken
from kookabug_core.inputs import InputActor
from kookabug_core.runner.watchdog import Watchdog
from kookabug_core.workerhost import WorkerProcess
from kookabug_sdk.rpc import METHOD_NOT_FOUND, Incoming, PeerLost, RpcPeer

__all__ = ["CONTROL_THREAD_NAME", "ControlState", "Controller", "PauseGate", "StopReason"]

CONTROL_THREAD_NAME: Final = "kookabug-runner-control"
_POLL_S: Final = 0.02

type ControlState = Literal["running", "pausing", "paused", "cancelling"]
type StopReason = Literal["finish"] | CancelReason
type Emit = Callable[[Mapping[str, Any]], object]


class PauseGate:
    """경계 멈춤 (M0b 최소, P8). `run.pause`를 받으면 다음 스텝 시작 확인 지점에서 멈춘다.

    멈춘 동안 취소는 바로 먹힌다(취소가 재개를 이긴다). 멈춘 시간은 기한에서 빼지 않는다(M3부터).
    """

    def __init__(self, cancel: CancelToken) -> None:
        self._cancel = cancel
        self._cond = threading.Condition()
        self._requested = False
        self._paused = False
        self.count = 0
        """`debug.pause`를 남긴 횟수 (`run.json`의 `pause_count`)."""

    def request(self) -> ControlState:
        with self._cond:
            if self._cancel.cancelled:
                return "cancelling"
            if self._paused:
                return "paused"
            self._requested = True
            return "pausing"

    def resume(self) -> ControlState:
        with self._cond:
            self._requested = False
            self._paused = False
            self._cond.notify_all()
            return "cancelling" if self._cancel.cancelled else "running"

    def wake(self) -> None:
        with self._cond:
            self._cond.notify_all()

    @property
    def state(self) -> ControlState:
        with self._cond:
            if self._cancel.cancelled:
                return "cancelling"
            if self._paused:
                return "paused"
            return "pausing" if self._requested else "running"

    def at_boundary(self, step: str, emit: Emit) -> None:
        """주 스레드: 스텝 시작 직전. 멈춤 요청이 있으면 `debug.pause` 뒤 재개·취소를 기다린다."""
        self._cancel.check()
        with self._cond:
            if not self._requested:
                return
            self._requested = False
            self._paused = True
        self.count += 1
        emit({"event": "debug.pause", "step": step})
        with self._cond:
            while self._paused and not self._cancel.cancelled:
                self._cond.wait()
            self._paused = False
        self._cancel.check()
        emit({"event": "debug.resume", "step": step})


class Controller:
    """제어 스레드와 취소 순서. 주 스레드가 액터·워커를 만들면 `attach_*`로 알린다 — 이미 취소된
    뒤면 그 자리에서 게이트를 닫거나 워커 취소를 시작한다."""

    def __init__(
        self,
        *,
        cancel: CancelToken,
        watchdog: Watchdog,
        pause: PauseGate,
        deadline_at: float,
        peer: RpcPeer | None,
    ) -> None:
        self.token = cancel
        self.watchdog = watchdog
        self.pause = pause
        self.deadline_at = deadline_at
        self.peer = peer
        self._lock = threading.Lock()
        self._reason: CancelReason | None = None
        self._actor: InputActor | None = None
        self._worker: WorkerProcess | None = None
        self._emit: Emit | None = None
        self._cancel_logged = False
        self._record_lock = threading.Lock()  # `cancel.requested` 차지·기록을 한 번에
        self._stopping_sent = False
        self._channel_lost = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name=CONTROL_THREAD_NAME, daemon=True)

    @property
    def cancel_reason(self) -> CancelReason | None:
        return self._reason

    # ------------------------------------------------------------ 수명

    def start(self) -> Controller:
        self._thread.start()
        return self

    def stop(self) -> None:
        """주 스레드 마무리 끝: 제어 스레드를 멈춘다 (이 뒤 들어온 요청에는 답하지 않는다)."""
        self._stop.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(1.0)

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
        with self._lock:
            self._worker = worker
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
        peer = self.peer
        if peer is not None:
            with contextlib.suppress(PeerLost):
                peer.notify("runner.stopping", {"reason": reason})

    # ------------------------------------------------------------ 취소 순서

    def cancel(self, reason: CancelReason) -> bool:
        """취소 순서를 시작한다 (처음 한 번만, 사유는 처음 것). 어느 스레드에서 불러도 된다."""
        with self._lock:
            if self._reason is not None:
                return False
            self._reason = reason
            actor = self._actor
            worker = self._worker
        self.watchdog.arm()
        self.token.cancel(reason)
        self.pause.wake()
        if actor is not None:
            actor.close_gate()
        if worker is not None:
            worker.cancel()
        self.notify_stopping(reason)
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
            if self._reason is None:
                if self.watchdog.supervisor_lost:
                    self.cancel("supervisor_lost")
                elif time.monotonic() >= self.deadline_at:
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
        if method == "run.cancel":
            self._respond(peer, request, "cancelling")
            self.cancel("cancelled")
        elif method == "run.pause":
            self._respond(peer, request, self.pause.request())
        elif method == "run.resume":
            self._respond(peer, request, self.pause.resume())
        elif not request.is_notification:
            with contextlib.suppress(PeerLost):
                peer.respond_error(request, METHOD_NOT_FOUND, f"모르는 제어 메서드 {method}")

    @staticmethod
    def _respond(peer: RpcPeer, request: Incoming, state: ControlState) -> None:
        if request.is_notification:
            return
        with contextlib.suppress(PeerLost):
            peer.respond(request, {"state": state})
