"""`kookabug screen promote` (M7 계획 3.10, B4): 사람만 (에이전트 종료 5), daemon과 같은
잠금·거래."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from helpers.explored import SESSION, SESSION_REL, make_explored_workspace, read, tree

from kookabug_core.screen_promote import journals


def promote_cli(
    ws: Path, *extra: str, env: dict[str, str] | None = None
) -> tuple[int, dict[str, Any]]:
    """실제 CLI 프로세스 (모킹 없음)."""
    argv = [
        "-X",
        "utf8",
        "-m",
        "kookabug_cli",
        "screen",
        "promote",
        *extra,
        "--workspace",
        str(ws),
        "--json",
    ]
    proc = subprocess.run(
        [sys.executable, *argv],
        env=env or {k: v for k, v in os.environ.items() if k != "KOOKABUG_AGENT"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    return proc.returncode, json.loads(proc.stdout)


def test_cli_promote_human(tmp_path: Path) -> None:
    ws = make_explored_workspace(tmp_path / "ws")
    code, report = promote_cli(
        ws, f"{SESSION}/result", "--id", "upgrade_result", "--folder", "shop"
    )
    assert code == 0, report
    assert report["path"] == "screens/shop/upgrade_result.screen.json"
    assert report["cleanup_pending"] is False
    assert (ws / "screens/shop/upgrade_result.screen.json").is_file()
    assert read(ws, f"{SESSION_REL}/explore.json")["promoted"] == {"result": "upgrade_result"}
    # 합치기
    code, report = promote_cli(ws, f"{SESSION}/bag", "--merge")
    assert code == 0 and report["path"] == "screens/old.screen.json"
    # 거부: 판정 조건 없는 후보, 이미 있는 ID — 아무것도 안 씀
    before = tree(ws)
    code, report = promote_cli(ws, f"{SESSION}/loading")
    assert (code, report["error_code"]) == (1, "validation_failed")
    code, report = promote_cli(ws, f"{SESSION}/upgrade", "--id", "lobby")
    assert (code, report["error_code"]) == (1, "screen_exists")
    assert tree(ws) == before
    assert promote_cli(ws, "형식 없음")[0] == 6
    assert journals(ws) == []


def test_cli_promote_agent_exit5(tmp_path: Path) -> None:
    ws = make_explored_workspace(tmp_path / "ws")
    before = tree(ws)
    env = {**os.environ, "KOOKABUG_AGENT": "agent:1"}
    code, report = promote_cli(ws, f"{SESSION}/upgrade", env=env)
    assert (code, report["error_code"]) == (5, "agent_only")
    assert tree(ws) == before


def screen_cli(
    ws: Path, *argv: str, env: dict[str, str] | None = None
) -> tuple[int, dict[str, Any]]:
    args = ["-X", "utf8", "-m", "kookabug_cli", "screen", *argv, "--workspace", str(ws), "--json"]
    proc = subprocess.run(
        [sys.executable, *args],
        env=env or {k: v for k, v in os.environ.items() if k != "KOOKABUG_AGENT"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    return proc.returncode, json.loads(proc.stdout)


def test_cli_recover_shows_pending_and_blocks_promote(tmp_path: Path) -> None:
    """남은 승격 저널: `screen recover --show`가 남은 파일·원래 바이트 위치를 보이고, 그동안 승격은
    `recovery_pending`. 사람이 파일을 되돌리면 `screen recover`가 끝낸다 (강제 삭제 옵션 없음)."""
    ws = make_explored_workspace(tmp_path / "ws")
    original = (ws / "screens/lobby.screen.json").read_bytes()
    # 커밋 직전에 죽은 CLI 승격 + 사람이 lobby를 고침
    rule = [{"point": "screens.stage", "role": "supervisor", "when": {"event": "before_commit"},
             "action": "exit:9"}]  # fmt: skip
    env = {**{k: v for k, v in os.environ.items() if k != "KOOKABUG_AGENT"}}
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "kookabug_cli", "screen", "promote",
         f"{SESSION}/result", "--id", "upgrade_result", "--workspace", str(ws), "--json"],
        env={**env, "KOOKABUG_FAULTS": json.dumps(rule)},
        capture_output=True,
        timeout=120,
    )  # fmt: skip
    assert proc.returncode == 9
    lobby = ws / "screens/lobby.screen.json"
    lobby.write_bytes(lobby.read_bytes() + b"\n")
    code, report = screen_cli(ws, "recover")
    assert code == 1
    (entry,) = report["journals"]
    assert entry["paths"] == ["screens/lobby.screen.json"]
    backup = entry["backups"]["screens/lobby.screen.json"]
    assert (ws / backup).read_bytes() == original
    code, shown = screen_cli(ws, "recover", "--show")
    assert code == 1 and shown["journals"] == report["journals"]
    code, report = promote_cli(ws, f"{SESSION}/upgrade")
    assert (code, report["error_code"]) == (1, "recovery_pending")
    assert screen_cli(ws, "recover", env={**os.environ, "KOOKABUG_AGENT": "a"})[0] == 5
    lobby.write_bytes((ws / backup).read_bytes())  # 사람이 원래 바이트로 되돌림
    code, report = screen_cli(ws, "recover")
    assert (code, report["journals"]) == (0, [])
    assert journals(ws) == []
    assert promote_cli(ws, f"{SESSION}/upgrade")[0] == 0
