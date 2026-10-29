"""실행기 시계. 테스트는 `FakeClock`(SDK와 같은 것)만 쓴다."""

from __future__ import annotations

import time

from kookabug_sdk.context import Clock
from kookabug_sdk.testing import FakeClock

__all__ = ["Clock", "FakeClock", "SystemClock"]


class SystemClock:
    """실제 시계 (단조 시간, ms)."""

    def now_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000

    def sleep(self, ms: int) -> None:
        time.sleep(ms / 1000)
