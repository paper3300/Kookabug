"""취소와 테스트 전체 기한."""

from __future__ import annotations

import threading

from kookabug_sdk.context import Cancelled

__all__ = ["CancelToken", "Cancelled", "DeadlineExceeded"]


class DeadlineExceeded(Cancelled):
    """테스트 전체 기한을 넘었다. 판정은 `error`(`deadline_exceeded`, G11).

    노드 코드의 `except Exception`에 잡히지 않도록 `Cancelled`(BaseException)를 잇는다.
    """


class CancelToken:
    """실행 취소 신호. 노드는 `ctx.check_cancel()`·`ctx.sleep()`에서 이것을 확인한다."""

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled("실행이 취소됐다")
