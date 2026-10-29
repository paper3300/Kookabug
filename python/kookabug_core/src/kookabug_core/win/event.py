"""Win32 이벤트·여러 핸들 대기·자기 종료 (runner 자기 종료 감시자용, 구현 계획 M0b 2.6).

감시자는 Python 잠금을 쓰지 않는다: 다른 스레드는 Win32 이벤트를 세우는 것(`SetEvent`)으로만
깨우고, 감시자는 OS 대기(`WaitForMultipleObjects`)에서만 기다린다.
"""

from __future__ import annotations

import ctypes
import os
from collections.abc import Sequence
from typing import NoReturn, Self

from kookabug_core.win import _kernel32 as k

__all__ = ["WinEvent", "terminate_current", "wait_any"]


class WinEvent(k.OwnedHandle):
    """이름 없는 Win32 이벤트 (기본은 수동 재설정: 한 번 세우면 계속 신호 상태)."""

    __slots__ = ()

    @classmethod
    def create(cls, *, manual_reset: bool = True) -> Self:
        handle = k.CreateEventW(None, manual_reset, False, None)
        return cls(k.check_handle(handle, "CreateEventW"))

    def set(self) -> None:
        k.check(k.SetEvent(self.handle), "SetEvent")


def wait_any(handles: Sequence[int], timeout: float | None) -> int | None:
    """핸들 중 하나가 신호 상태가 될 때까지 기다린다. 그 순번, 기한을 넘기면 None."""
    if not 0 < len(handles) <= k.MAXIMUM_WAIT_OBJECTS:
        raise ValueError(f"핸들은 1~{k.MAXIMUM_WAIT_OBJECTS}개다: {len(handles)}")
    array = (k.HANDLE * len(handles))(*handles)
    result = k.WaitForMultipleObjects(len(handles), array, False, k.to_ms(timeout))
    if result == k.WAIT_TIMEOUT:
        return None
    if k.WAIT_OBJECT_0 <= result < k.WAIT_OBJECT_0 + len(handles):
        return result - k.WAIT_OBJECT_0
    if k.WAIT_ABANDONED <= result < k.WAIT_ABANDONED + len(handles):
        return result - k.WAIT_ABANDONED
    raise k.win_error("WaitForMultipleObjects")


def terminate_current(exit_code: int) -> NoReturn:
    """이 프로세스를 곧바로 끝낸다 (`TerminateProcess(GetCurrentProcess())`). 정리·flush 없음."""
    k.TerminateProcess(k.GetCurrentProcess(), exit_code)
    # 실패할 일이 없지만, 돌아오면 같은 효과의 다른 길로 끝낸다
    ctypes.set_last_error(0)
    os._exit(exit_code)
