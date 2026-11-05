"""실행 속도 제한(EcoQoS) 끄기 (M2 사람 확인 S 결함 ②, `kookabug_core.win.power`).

앱·데몬이 띄운 창 없는 runner는 Windows가 몇 초 뒤 실행 속도를 낮춰 OCR이 4~5배 느려졌다. runner는
시작할 때 그 제한에서 빠진다. 이 API로는 다른 프로세스의 값을 읽을 수 없어, 새 프로세스 안에서
스스로 확인하고 runner 진입점이 그것을 가장 먼저 부르는지 본다.
"""

from __future__ import annotations

import io
import subprocess
import sys
from typing import Any

import pytest

from kookabug_core.runner import __main__ as runner_main
from kookabug_core.runner.run import EXIT_START_FAILED

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용")


def test_keep_full_speed_opts_this_process_out() -> None:
    code = (
        "from kookabug_core.win import power; "
        "print(power.full_speed(), power.keep_full_speed(), power.full_speed())"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60
    ).stdout.split()
    assert out[0] != "True"  # 시스템에 맡긴 기본 상태
    assert out[1:] == ["True", "True"]


def test_runner_entry_keeps_full_speed_before_reading_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(runner_main.dpi, "enable_at_startup", lambda: calls.append("dpi"))
    monkeypatch.setattr(runner_main, "utf8_stdio", lambda: None)
    monkeypatch.setattr(runner_main.power, "keep_full_speed", lambda: calls.append("power") or True)
    monkeypatch.setattr(runner_main._faults, "set_role", lambda _role: calls.append("role"))

    class Stdin:
        buffer: Any = io.BytesIO(b"not a spec")

    monkeypatch.setattr(sys, "stdin", Stdin())
    assert runner_main.main() == EXIT_START_FAILED
    assert calls == ["dpi", "power", "role"]
