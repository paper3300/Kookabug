"""실행기 시계. 테스트는 `FakeClock`(SDK와 같은 것)만 쓴다."""

from __future__ import annotations

import time

from kookabug_core.engine.cancel import CancelToken
from kookabug_sdk.context import Clock
from kookabug_sdk.testing import FakeClock

__all__ = ["Clock", "FakeClock", "SystemClock"]


class SystemClock:
    """실제 시계 (단조 시간, ms).

    `cancel`을 주면 `sleep`은 취소되는 즉시 깬다 (`time.sleep`은 취소로 깨지 않는다). 깬 뒤의
    판단(`Cancelled`)은 부른 쪽이 `check()`로 한다.
    """

    def __init__(self, cancel: CancelToken | None = None) -> None:
        self.cancel = cancel

    def now_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000

    def sleep(self, ms: int) -> None:
        if self.cancel is None:
            time.sleep(ms / 1000)
        else:
            self.cancel.wait(ms / 1000)
