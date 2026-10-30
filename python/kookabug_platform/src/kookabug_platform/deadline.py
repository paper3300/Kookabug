"""관측 호출의 유효 기한 (구현 계획 M1 2.6, 계획 검수 11).

관측 호출(캡처·찾기·OCR) 하나의 유효 기한 = `min(설정 기한, 노드 기한 남은 시간, 전체 기한 남은
시간)`. 어느 기한 때문에 끝났는지에 따라 예외가 다르다.

| 끝난 원인 | 예외 |
|---|---|
| 노드 기한 (노드가 넘긴 `deadline`) | `ObservationTimeout` — 노드가 잡아 `timeout` 출구 |
| 설정 기한 (`capture_timeout_ms` 등) | 호출이 정한 `PlatformError` (캡처는 `capture_timeout`) |
| 전체 기한 | `DeadlineExceeded` (M0b 그대로) |

같은 시각에 끝나면 전체 > 노드 > 설정 순으로 본다. 남은 시간이 0이면 관측을 시작하지 않는다.
기다리는 동안은 `SLICE_S`마다 취소(`check`)와 기한을 확인한다.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Final, Literal, NoReturn

from kookabug_core.engine.cancel import DeadlineExceeded
from kookabug_platform.errors import ObservationTimeout

__all__ = ["SLICE_S", "ObservationDeadline"]

SLICE_S: Final = 0.05
"""기다리는 동안 취소·기한을 확인하는 간격."""

type Limit = Literal["run", "node", "config"]


class ObservationDeadline:
    """관측 호출 하나의 기한. 만든 순간부터 잰다.

    `config_ms`는 호출 종류의 설정 기한(양수). `node_ms`·`run_ms`는 그 순간 노드 기한·전체 기한의
    남은 시간(없으면 None). `check`는 취소 확인(취소됐으면 예외를 던진다).
    """

    def __init__(
        self,
        config_ms: int,
        *,
        node_ms: int | None = None,
        run_ms: int | None = None,
        check: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if config_ms <= 0:
            raise ValueError(f"설정 기한은 양수다: {config_ms}")
        self._clock = clock
        self._check = check
        self.config_ms = config_ms
        self.node_ms = node_ms
        self.run_ms = run_ms
        start = clock()
        # 같은 시각이면 앞의 것 (전체 > 노드 > 설정)
        limits: list[tuple[float, Limit]] = []
        if run_ms is not None:
            limits.append((start + max(0, run_ms) / 1000, "run"))
        if node_ms is not None:
            limits.append((start + max(0, node_ms) / 1000, "node"))
        limits.append((start + config_ms / 1000, "config"))
        end, limit = min(limits, key=lambda item: item[0])
        self._end: float = end
        self._limit: Limit = limit

    @property
    def limit(self) -> Limit:
        """가장 이른 기한의 종류."""
        return self._limit

    def remaining_s(self) -> float:
        return max(0.0, self._end - self._clock())

    def expired(self) -> bool:
        return self._clock() >= self._end

    def check(self) -> None:
        """취소 확인. 취소됐으면 그 예외(`Cancelled` 등)."""
        if self._check is not None:
            self._check()

    @property
    def end(self) -> float:
        """기한 시각 (이 기한 시계의 절대값)."""
        return self._end

    def ensure(self, config_error: Callable[[], BaseException]) -> None:
        """취소됐거나 기한이 끝났으면 그 예외. 끊을 수 없는 호출(세션 시작·창 정보) 뒤와 결과를
        확정하기 직전에 부른다 — 기한 뒤에 준비된 결과를 성공으로 내보내지 않는다."""
        self.check()
        if self.expired():
            self.fail(config_error)

    def start(self, config_error: Callable[[], BaseException]) -> None:
        """관측을 시작하기 전: 취소됐거나 남은 시간이 0이면 시작하지 않고 그 예외."""
        self.ensure(config_error)

    def fail(self, config_error: Callable[[], BaseException]) -> NoReturn:
        """기한이 끝났다: 원인별 예외를 던진다. 설정 기한이면 `config_error()`."""
        if self._limit == "run":
            raise DeadlineExceeded(f"테스트 전체 기한을 넘었다 (관측 중, 남은 {self.run_ms}ms)")
        if self._limit == "node":
            raise ObservationTimeout(f"노드 기한 {self.node_ms}ms 안에 관측이 끝나지 않았다")
        raise config_error()

    def wait(
        self,
        cond: threading.Condition,
        ready: Callable[[], bool],
        config_error: Callable[[], BaseException],
        *,
        until_s: float | None = None,
    ) -> bool:
        """`cond`를 잡은 채로 불러, `ready()`가 참이 될 때까지 기다린다. 참이면 True.

        `until_s`(이 기한 시계의 절대 시각)를 주면 그때까지만 기다리고 False(기한 안이면 예외 없음).
        순서는 매번 취소 → 기한 → 준비 → `until_s`: 준비됐어도 취소됐거나 기한이 지났으면 예외다.
        기다리는 동안 `SLICE_S`마다 잠금을 놓고 취소를 확인한다.
        """
        while True:
            cond.release()
            try:
                self.check()
            finally:
                cond.acquire()
            now = self._clock()
            if now >= self._end:
                self.fail(config_error)
            if ready():
                return True
            if until_s is not None and now >= until_s:
                return False
            stop = self._end if until_s is None else min(self._end, until_s)
            cond.wait(min(SLICE_S, max(0.0, stop - now)))

    def now(self) -> float:
        return self._clock()
