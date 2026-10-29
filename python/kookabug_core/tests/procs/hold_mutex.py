"""이름 있는 뮤텍스를 얻고, 장벽을 지난 뒤 **놓지 않고** 끝난다 (테스트 보조).

    python hold_mutex.py NAME BARRIER

얻으면 `BARRIER.ready`를 만들고 `BARRIER.go`가 생길 때까지 기다린 뒤 `os._exit(0)`.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from kookabug_core.win import NamedMutex, WaitResult


def main() -> None:
    name, barrier = sys.argv[1], sys.argv[2]
    mutex = NamedMutex.open(name)
    if mutex.wait(10) not in (WaitResult.ACQUIRED, WaitResult.ABANDONED):
        os._exit(2)
    Path(f"{barrier}.ready").touch()
    while not Path(f"{barrier}.go").exists():
        time.sleep(0.01)
    os._exit(0)


if __name__ == "__main__":
    main()
