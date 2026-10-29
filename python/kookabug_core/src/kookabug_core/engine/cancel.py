"""취소와 테스트 전체 기한.

취소에는 사유가 있다 (구현 계획 M0b 2.6): `cancelled`(외부 취소), `deadline_exceeded`(테스트 전체
기한 — runner 제어 스레드의 기한 감시), `supervisor_lost`(감독자 사망). 먼저 정한 사유가 남는다.
기한 초과는 `DeadlineExceeded`(판정 `error`/`deadline_exceeded`), 나머지는 `Cancelled`(`cancelled`).
"""

from __future__ import annotations

import threading
from typing import Final, Literal

from kookabug_sdk.context import Cancelled

__all__ = ["CANCEL_REASONS", "CancelReason", "CancelToken", "Cancelled", "DeadlineExceeded"]

type CancelReason = Literal["cancelled", "deadline_exceeded", "supervisor_lost"]
CANCEL_REASONS: Final[tuple[CancelReason, ...]] = (
    "cancelled",
    "deadline_exceeded",
    "supervisor_lost",
)

_MESSAGES: Final[dict[CancelReason, str]] = {
    "cancelled": "실행이 취소됐다",
    "deadline_exceeded": "테스트 전체 기한을 넘었다",
    "supervisor_lost": "감독자가 사라져 실행을 취소했다",
}


class DeadlineExceeded(Cancelled):
    """테스트 전체 기한을 넘었다. 판정은 `error`(`deadline_exceeded`, G11).

    노드 코드의 `except Exception`에 잡히지 않도록 `Cancelled`(BaseException)를 잇는다.
    """


class CancelToken:
    """실행 취소 신호. 노드는 `ctx.check_cancel()`·`ctx.sleep()`에서 이것을 확인한다."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason: CancelReason | None = None
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> CancelReason | None:
        """취소 사유 (취소되지 않았으면 None)."""
        return self._reason

    def cancel(self, reason: CancelReason = "cancelled") -> None:
        """취소한다. 사유는 처음 것이 남는다."""
        if reason not in CANCEL_REASONS:
            raise ValueError(f"모르는 취소 사유 {reason!r}")
        with self._lock:
            if self._reason is not None:
                return
            self._reason = reason
        self._event.set()

    def wait(self, timeout: float | None = None) -> bool:
        """취소될 때까지(최대 `timeout`초) 기다린다. 취소됐으면 True."""
        return self._event.wait(timeout)

    def check(self) -> None:
        if not self._event.is_set():
            return
        reason = self._reason or "cancelled"
        if reason == "deadline_exceeded":
            raise DeadlineExceeded(_MESSAGES[reason])
        raise Cancelled(_MESSAGES[reason])
