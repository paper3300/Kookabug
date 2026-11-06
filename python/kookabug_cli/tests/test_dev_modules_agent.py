"""개발 모듈(`--plugin-module`)은 사람 전용 (M6 계획 3.7·D11, rev1 H3).

`KOOKABUG_AGENT`가 있으면 `kookabug run --plugin-module`·`kookabug daemon --plugin-module`은 실행을
시작하기 전에 종료 5로 거부한다. 계획 검수 재현(`KOOKABUG_AGENT` + runner 프리셋 + 임의 모듈)을
그대로 두고 결과만 뒤집어 확인한다: 모듈 import 표식이 생기지 않는다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from helpers.cli import cli_env, platform_file, run_cli
from helpers.graphs import GraphBuilder, make_workspace, write_json

pytestmark = pytest.mark.process


def _agent_rig(tmp_path: Path) -> tuple[Path, dict[str, str], Path, Path]:
    workspace = tmp_path / "ws"
    make_workspace(workspace)
    write_json(
        workspace,
        "kookabug.json",
        {"format": "kookabug.workspace/0", "permissions": {"preset": "runner"}},
    )
    write_json(
        workspace,
        ".kookabug/local.json",
        {"format": "kookabug.local/0", "permissions": {"preset": "runner"}},
    )
    GraphBuilder().entry("n").node("n", "core.test.pass").write(workspace, "tests/t.graph.json")
    marker = tmp_path / "unapproved-module-imported.txt"
    (tmp_path / "review_unapproved_module.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported', encoding='utf-8')\n",
        encoding="utf-8",
    )
    env = cli_env(tmp_path, KOOKABUG_AGENT="review-agent")
    env["PYTHONPATH"] = str(tmp_path) + os.pathsep + env.get("PYTHONPATH", "")
    platform, _ = platform_file(tmp_path)
    return workspace, env, platform, marker


def test_agent_cli_plugin_module_refused(tmp_path: Path) -> None:
    workspace, env, platform, marker = _agent_rig(tmp_path)
    proc = run_cli(
        [
            "run",
            "tests/t.graph.json",
            "--json",
            "--platform-fake",
            platform,
            "--plugin-module",
            "review_unapproved_module",
        ],
        cwd=workspace,
        env=env,
    )
    assert proc.returncode == 5, proc.stderr
    data = json.loads(proc.stdout)
    assert data["principal"]["kind"] == "agent"
    assert data["run_id"] is None
    assert "dev_modules_agent" in data["error"]
    assert not marker.exists()
    assert not (workspace / "runs").exists() or not any((workspace / "runs").iterdir())


def test_agent_cli_without_plugin_module_still_runs(tmp_path: Path) -> None:
    """회귀: 개발 모듈이 없으면 에이전트 실행은 기존 판정(runner 프리셋 → allow) 그대로."""
    workspace, env, platform, marker = _agent_rig(tmp_path)
    proc = run_cli(
        ["run", "tests/t.graph.json", "--json", "--platform-fake", platform],
        cwd=workspace,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["verdict"] == "pass"
    assert not marker.exists()


def test_agent_daemon_plugin_module_refused(tmp_path: Path) -> None:
    workspace, env, platform, marker = _agent_rig(tmp_path)
    proc = run_cli(
        [
            "daemon",
            "--workspace",
            workspace,
            "--json",
            "--platform-fake",
            platform,
            "--plugin-module",
            "review_unapproved_module",
        ],
        cwd=workspace,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert "dev_modules_agent" in proc.stderr
    assert not marker.exists()
