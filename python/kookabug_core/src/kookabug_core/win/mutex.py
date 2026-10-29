"""이름 있는 뮤텍스 (구현 계획 M0b 2.3·2.4).

Windows 뮤텍스는 **스레드 소유**다: 얻은 스레드만 놓을 수 있고, 소유 스레드나 프로세스가 놓지 않고
끝나면 다음 대기자가 `ABANDONED`로 얻는다. 입력 임대권은 이 성질 위에 전용 스레드로 만든다(T6).
"""

from __future__ import annotations

import ctypes
from enum import StrEnum
from typing import Self

from kookabug_core.win import _kernel32 as k

__all__ = ["NamedMutex", "WaitResult"]


class WaitResult(StrEnum):
    ACQUIRED = "acquired"
    # 앞 소유자가 놓지 않고 끝났다. 얻은 것은 맞다 — 앞 소유자가 남긴 상태를 복구할 책임이 생긴다
    ABANDONED = "abandoned"
    TIMEOUT = "timeout"


class NamedMutex(k.OwnedHandle):
    __slots__ = ("name",)

    def __init__(self, handle: int, name: str) -> None:
        super().__init__(handle)
        self.name = name

    @classmethod
    def open(cls, name: str) -> Self:
        """없으면 만들고 있으면 연다. 만든 쪽도 소유하지 않은 상태로 시작한다."""
        handle = k.CreateMutexW(None, False, name)
        return cls(k.check_handle(handle, f"CreateMutexW({name})"), name)

    def wait(self, timeout: float | None = 0) -> WaitResult:
        """호출한 스레드가 얻으려 한다. 기본은 기다리지 않음(0초), None은 무한."""
        result = k.WaitForSingleObject(self.handle, k.to_ms(timeout))
        if result == k.WAIT_OBJECT_0:
            return WaitResult.ACQUIRED
        if result == k.WAIT_ABANDONED:
            return WaitResult.ABANDONED
        if result == k.WAIT_TIMEOUT:
            return WaitResult.TIMEOUT
        raise k.win_error("WaitForSingleObject")

    def release(self) -> None:
        """소유 스레드에서만 놓을 수 있다. 다른 스레드면 `PermissionError`."""
        if not k.ReleaseMutex(self.handle):
            code = ctypes.get_last_error()
            if code == k.ERROR_NOT_OWNER:
                raise PermissionError(f"이 스레드는 뮤텍스 {self.name}의 소유자가 아니다")
            raise k.win_error("ReleaseMutex", code)
