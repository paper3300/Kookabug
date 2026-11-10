"""`kookabug workspace new` (M8 계획 3.1·C15) — 실제 CLI 프로세스."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 정션")
def test_review_workspace_new_refuses_junction_target(tmp_path: Path) -> None:
    """B7 검수 H1: 만들 폴더(또는 그 조각)가 정션이면 앱을 거치지 않고 CLI를 바로 불러도
    거부한다."""
    import _winapi

    selected = tmp_path / "selected"
    outside = tmp_path / "outside"
    selected.mkdir()
    outside.mkdir()
    _winapi.CreateJunction(str(outside), str(selected / "game"))
    code, out = cli(str(selected / "game"), "--name", "game")
    assert code == 1 and out["error_code"] == "path_link"
    assert list(outside.iterdir()) == []  # 외부 폴더에 아무것도 생기지 않는다
    # 조각(상위 폴더)이 정션인 경우도: link → outside, link/new
    _winapi.CreateJunction(str(outside), str(tmp_path / "link"))
    code, out = cli(str(tmp_path / "link" / "new"), "--name", "new")
    assert code == 1 and out["error_code"] == "path_link"
    assert list(outside.iterdir()) == []
    # 양성 대조: 같은 부모의 일반 하위 폴더는 만든다
    code, out = cli(str(selected / "plain"), "--name", "plain")
    assert code == 0 and (selected / "plain" / "kookabug.json").is_file()
