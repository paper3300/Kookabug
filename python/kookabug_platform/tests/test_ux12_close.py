"""UX12 검수 1 High 5 — `core.app.close`가 process 없이 지금 창의 프로세스를 닫을 때, 창의 PID와
생성 시각을 함께 확인한다: 같은 PID를 다시 쓴 다른 프로세스(생성 시각이 다름)는 닫지 않는다.

검사가 직접 띄운 숨김 Python 자식만 대상으로 한다 (옛 창 참조는 그 PID에 다른 생성 시각을 붙여
"PID 재사용 뒤" 상태를 만든다). 실제 Windows 프로세스 API를 쓴다.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from kookabug_core.engine.errors import EngineError
from kookabug_core.win import identify
from kookabug_nodes.app import close
from kookabug_platform.platform import WindowsPlatform
from kookabug_sdk.types import WindowRef


@pytest.fixture
def child() -> Iterator[subprocess.Popen[bytes]]:
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c", "import time; time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


def _ctx(platform: WindowsPlatform, window: WindowRef) -> SimpleNamespace:
    return SimpleNamespace(
        window=window, process=SimpleNamespace(close=platform.close_process), config={}
    )


def test_stale_window_does_not_kill_reused_pid(child: subprocess.Popen[bytes]) -> None:
    platform = WindowsPlatform()
    stale = WindowRef(0xDEAD, "옛 창", pid=child.pid, process_created="1", binding="gone")
    try:
        with pytest.raises(EngineError) as caught:
            close(_ctx(platform, stale), force_after_ms=0)  # pyright: ignore[reportArgumentType]
        assert caught.value.code == "process_gone"
        assert child.poll() is None  # 그 PID의 (다른) 프로세스는 살아 있다
    finally:
        platform.close()


def test_matching_window_closes_its_process(child: subprocess.Popen[bytes]) -> None:
    ident = identify(child.pid)
    assert ident is not None
    platform = WindowsPlatform()
    window = WindowRef(0xBEEF, "게임", pid=child.pid, process_created=str(ident.created))
    try:
        close(_ctx(platform, window), force_after_ms=0)  # pyright: ignore[reportArgumentType]
        child.wait(timeout=10)
        assert child.poll() is not None
    finally:
        platform.close()
