"""화면 지도 잠금 `.kookabug/screens.lock` (M7 계획 3.7·10장 R4).

daemon(저장·승격·버리기·복구)과 CLI(승격·복구)가 프로세스를 넘어 한 번에 하나만 `screens/`를 바꾸게
한다. 바이트 하나를 `msvcrt.locking`으로 쥔다 — 프로세스가 죽으면 OS가 핸들과 함께 푼다. 같은
프로세스의 다른 핸들도 막힌다. 잠금 순서는 `screens.lock` → 세션 잠금이다.
"""

from __future__ import annotations

import contextlib
import msvcrt
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

__all__ = ["LOCK_FILE", "WAIT_S", "ScreensBusy", "screens_lock"]

LOCK_FILE: Final = ".kookabug/screens.lock"
WAIT_S: Final = 5.0
"""잠금을 기다리는 시간. 넘으면 `screens_busy`."""


class ScreensBusy(Exception):
    """다른 프로세스·작업이 화면 지도 잠금을 쥐고 있다 (`screens_busy`)."""

    code = "screens_busy"


@contextlib.contextmanager
def screens_lock(root: Path, *, wait_s: float = WAIT_S) -> Iterator[None]:
    path = root.joinpath(*LOCK_FILE.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + wait_s
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ScreensBusy(
                        "다른 작업이 화면 지도를 바꾸는 중이다 (.kookabug/screens.lock)"
                    ) from None
                time.sleep(0.02)
        try:
            yield
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            with contextlib.suppress(OSError):
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)
