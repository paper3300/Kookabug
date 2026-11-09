"""`kookabug cheat list|adopt|unadopt` (M8 계획 3.2·3.14) — 실제 CLI 프로세스. 채택은 사람만."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from kb_testing.sample_game import copy_example_workspace


def cli(ws: Path, *args: str, agent: bool = False) -> tuple[int, dict[str, Any]]:
    env = {k: v for k, v in os.environ.items() if k != "KOOKABUG_AGENT"}
    if agent:
        env["KOOKABUG_AGENT"] = "agent:1"
    proc = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "kookabug_cli",
            "cheat",
            *args,
            "--workspace",
            str(ws),
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    return proc.returncode, json.loads(proc.stdout)


def test_cheat_adopt_agent_exit5(tmp_path: Path) -> None:
    ws = copy_example_workspace(tmp_path)
    cheats_file = ws / "knowledge" / "cheats.json"
    before = hashlib.sha256(cheats_file.read_bytes()).hexdigest()
    for args in (
        ("list",),
        ("adopt", "give_gold", "--rev", "1", "--category", "dev_safe"),
        ("unadopt", "give_gold", "--rev", "1"),
    ):
        code, out = cli(ws, *args, agent=True)
        assert code == 5 and out["error_code"] == "agent_only", args
    assert hashlib.sha256(cheats_file.read_bytes()).hexdigest() == before
    # 사람은 채택·풀기, 잘못된 분류·rev는 1. 패턴 밖 글자는 감사 이력에 가기 전에 거부
    log = ws / "knowledge" / "log.jsonl"
    code, out = cli(ws, "adopt", "give gold;x", "--rev", "1", "--category", "dev_safe")
    assert code == 1 and out["error_code"] == "format"
    assert not log.exists() or "give gold" not in log.read_text(encoding="utf-8")
    code, out = cli(ws, "adopt", "give_gold", "--rev", "1", "--category", "nope")
    assert code == 1 and out["error_code"] == "category_unknown"
    code, out = cli(ws, "adopt", "give_gold", "--rev", "1", "--category", "dev_safe")
    assert code == 0 and out["adoption"]["category"] == "dev_safe"
    code, out = cli(ws, "list")
    assert code == 0 and out["cheats"][0]["adopted"] is True
    code, out = cli(ws, "unadopt", "give_gold", "--rev", "1")
    assert code == 0 and out["adoption"] is None
