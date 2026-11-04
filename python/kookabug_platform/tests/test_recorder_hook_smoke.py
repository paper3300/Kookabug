"""실제 훅 프로세스가 뜨고 생존 보고를 보내고 정상으로 끝나는가 (M4 계획 2.1, T3).

`desktop`: 전역 저수준 훅은 대화형 세션에서만 걸린다. 입력을 보내지 않고, 그 사이 사람이 친 키가
훅에 잡혀도 이 검사는 내용을 보지도 출력하지도 않는다(개수·생존만 본다).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from kb_testing.proc import wait_until
from kookabug_core.recorder.contract import HOOK_PROTOCOL
from kookabug_daemon.recorder_hook import HookClient, HookStop

pytestmark = [pytest.mark.desktop, pytest.mark.timeout(60)]


def test_hookproc_starts_reports_health_and_stops(tmp_path: Path) -> None:
    stops: list[HookStop] = []
    client = HookClient(
        mono_base_ns=time.monotonic_ns(),
        on_update=lambda update: None,
        on_stop=stops.append,
        env={k: v for k, v in os.environ.items() if k != "KOOKABUG_TESTING"},
        logs_dir=tmp_path,
    )
    hello = client.start(timeout=30)
    try:
        assert hello["protocol"] == HOOK_PROTOCOL
        assert hello["hooks"] == {"mouse": True, "keyboard": True}
        assert hello["dpi_awareness"] == "per_monitor_v2"
        assert hello["pid"] == client.pid
        # 생존 보고 500 ms마다 — 1.2초면 둘 이상
        wait_until(lambda: client.stream.health_count >= 2, timeout=5)
        assert stops == []
    finally:
        client.stop()
    process = client._process
    assert process is not None and not process.alive()
    assert process.exit_code() == 0, (tmp_path / "hook.stderr.log").read_text(encoding="utf-8")
    assert stops == []
