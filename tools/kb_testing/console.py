"""영문 Windows 콘솔(cp1252)을 흉내 내 진입점을 띄운다.

로컬 한국어 Windows(cp949)에서는 한국어 출력이 그냥 되므로, 콘솔 인코딩에 기대는 버그가
드러나지 않는다. 하위 프로세스의 표준 입출력 인코딩을 cp1252로 강제해 재현한다.
출력은 UTF-8로 읽고, UTF-8이 아닌 바이트가 섞였으면 실패로 본다
(진입점은 콘솔 인코딩과 무관하게 UTF-8로 쓴다).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

LEGACY_CONSOLE = {"PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}


def legacy_console_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.update(LEGACY_CONSOLE)
    return env


def run_legacy_console(
    cmd: Sequence[str | Path], cwd: Path, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [str(c) for c in cmd],
        cwd=cwd,
        env=legacy_console_env(env),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    for name, text in (("stdout", proc.stdout), ("stderr", proc.stderr)):
        if "�" in text:
            raise AssertionError(f"{name}가 UTF-8이 아니다: {cmd}\n{text}")
    return proc
