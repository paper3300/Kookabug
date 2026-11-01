"""runner 활성 시계 (구현 계획 M3 2.2).

기한 전용 시계다: `now_ms()` = 단조 시간에서 지금까지 멈춘 시간을 뺀 값. 멈춘 동안에는 멈춘
순간 값에 머문다. 노드 기한(`ctx.deadline`)·전체 기한(실행기 `runtime.deadline`, 제어 스레드의
기한 감시)이 모두 이 시계를 보므로 멈춘 시간만큼 저절로 늘어난다. 경과(`duration_ms`)는 이
시계가 아니라 실제 단조 시계로 잰다.

멈춤 확정·재개는 주 스레드가 하고(`PauseGate`), 읽기는 아무 스레드에서나 한다(잠금 하나).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from kookabug_core.engine.cancel import CancelToken

__all__ = ["ActiveClock"]


class ActiveClock:
    """멈춘 시간을 뺀 단조 시계 (ms).

    `sleep`은 실제 시간으로 기다린다(멈춤 요청을 보지 않는 기다림 — 누르고 있기 등). `cancel`을
    주면 취소되는 즉시 깬다. 멈출 수 있는 기다림은 실행기 런타임의 `wait_pausable`이다.
    """

    def __init__(
        self,
        cancel: CancelToken | None = None,
        *,
        now_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.cancel = cancel
        self._now_ns = now_ns
        self._lock = threading.Lock()
        self._paused_ns = 0
        self._since: int | None = None
        self._pauses = 0

    def now_ms(self) -> int:
        with self._lock:
            at = self._since if self._since is not None else self._now_ns()
            return (at - self._paused_ns) // 1_000_000

    def sleep(self, ms: int) -> None:
        if self.cancel is None:
            time.sleep(ms / 1000)
        else:
            self.cancel.wait(ms / 1000)

    @property
    def pauses(self) -> int:
        """지금까지 멈춘 횟수 (멈출 때마다 오른다 — 어떤 구간에 멈춤이 있었는지 가린다)."""
        with self._lock:
            return self._pauses

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._since is not None

    @property
    def paused_ms(self) -> int:
        """멈춰 있던 시간 합 (지금 멈춰 있으면 지금까지)."""
        with self._lock:
            total = self._paused_ns
            if self._since is not None:
                total += self._now_ns() - self._since
            return total // 1_000_000

    def pause(self) -> None:
        """멈춤 확정: 이 순간부터 시계가 머문다. 이미 멈춰 있으면 그대로."""
        with self._lock:
            if self._since is None:
                self._since = self._now_ns()
                self._pauses += 1

    def resume(self) -> int:
        """재개: 시계가 다시 간다. 이번 멈춤의 길이(ms)를 준다 (멈춰 있지 않았으면 0)."""
        with self._lock:
            if self._since is None:
                return 0
            span = self._now_ns() - self._since
            self._paused_ns += span
            self._since = None
            return span // 1_000_000
