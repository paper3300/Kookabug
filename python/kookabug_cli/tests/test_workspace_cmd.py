"""`kookabug workspace new` (M8 계획 3.1·C15) — 실제 CLI 프로세스."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def cli(*args: str, env: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "kookabug_cli", "workspace", "new", *args, "--json"],
        env=env or {k: v for k, v in os.environ.items() if k != "KOOKABUG_AGENT"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    return proc.returncode, json.loads(proc.stdout)


def test_workspace_new_human(tmp_path: Path) -> None:
    code, out = cli(str(tmp_path / "p"), "--name", "상점")
    assert code == 0 and out["exit_code"] == 0
    assert (tmp_path / "p" / "kookabug.json").is_file() and out["id"]
    code, out = cli(str(tmp_path / "p"), "--name", "다시")
    assert code == 1 and out["error_code"] == "not_empty"


def test_workspace_new_agent_exit5(tmp_path: Path) -> None:
    code, out = cli(
        str(tmp_path / "p"), "--name", "x", env={**os.environ, "KOOKABUG_AGENT": "agent:1"}
    )
    assert code == 5 and out["error_code"] == "agent_only"
    assert not (tmp_path / "p").exists()
