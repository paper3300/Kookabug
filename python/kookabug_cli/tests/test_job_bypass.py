"""작업 중 Agent의 CLI 실행은 작업 예산·종료 감독을 우회하지 못한다 (M8 9장 R8, B5 검수 High 6).

`kookabug run`(CLI 실행의 공용 진입점 `WorkspaceService.start_run`)은 다음이면 실행을 만들지 않고
종료 7 `job_active`(판정 `skipped` 3과 겹치지 않는 값):

- 작업 토큰 환경 변수(`KOOKABUG_JOB_TOKEN`)가 있다
- `KOOKABUG_AGENT`가 `job:`로 시작한다
- Agent 주체이고 그 워크스페이스의 `jobs.lock`이 잡혀 있다

작업이 없을 때의 Agent CLI 실행은 그대로다(양성 대조).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers.cli import cli_env, platform_file, run_cli
from helpers.graphs import GraphBuilder, make_workspace, write_json

from kookabug_core.agent_job import jobdir

pytestmark = pytest.mark.process


def _rig(tmp_path: Path) -> tuple[Path, Path]:
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
    platform, _ = platform_file(tmp_path)
    return workspace, platform


def _run(workspace: Path, platform: Path, env: dict[str, str]) -> tuple[int, dict[str, object]]:
    proc = run_cli(
        ["run", "tests/t.graph.json", "--json", "--platform-fake", platform], cwd=workspace, env=env
    )
    return proc.returncode, json.loads(proc.stdout)


def _no_runs(workspace: Path) -> bool:
    runs = workspace / "runs"
    return not runs.exists() or not any(runs.iterdir())


@pytest.mark.parametrize("how", ["token_env", "job_dir_env", "job_agent", "lock_held"])
def test_cli_run_refused_during_job(tmp_path: Path, how: str) -> None:
    workspace, platform = _rig(tmp_path)
    extra: dict[str, str] = {
        "token_env": {"KOOKABUG_AGENT": "panel", "KOOKABUG_JOB_TOKEN": "t" * 43},
        # 다른 작업 변수 이름 (토큰을 지워도 작업 안 프로세스다)
        "job_dir_env": {"KOOKABUG_AGENT": "panel", "KOOKABUG_JOB_DIR": str(tmp_path / "job")},
        "job_agent": {"KOOKABUG_AGENT": "job:j-20261110-010203-abcd"},
        "lock_held": {"KOOKABUG_AGENT": "panel"},
    }[how]
    env = {**cli_env(tmp_path), **extra}
    if how == "lock_held":
        with jobdir.JobLock(workspace):  # agent-job이 이 워크스페이스의 작업을 돌리고 있다
            code, data = _run(workspace, platform, env)
    else:
        code, data = _run(workspace, platform, env)
    assert code == 7, data
    assert str(data["error"]).startswith("job_active") and data["run_id"] is None
    assert _no_runs(workspace)
    # 양성 대조: 작업이 없으면 같은 Agent CLI 실행이 돈다 (토큰 환경·job: 표시도 없을 때)
    plain = cli_env(tmp_path, KOOKABUG_AGENT="panel")
    code, data = _run(workspace, platform, plain)
    assert code == 0 and data["verdict"] == "pass", data
    assert data["principal"]["kind"] == "agent"  # type: ignore[index]


def test_token_env_refused_for_human_principal(tmp_path: Path) -> None:
    """작업 토큰 환경이 있으면 `KOOKABUG_AGENT`를 지운 프로세스(사람 주체로 보임)도 거부한다."""
    workspace, platform = _rig(tmp_path)
    code, data = _run(workspace, platform, cli_env(tmp_path, KOOKABUG_JOB_TOKEN="t" * 43))
    assert code == 7 and str(data["error"]).startswith("job_active") and _no_runs(workspace)
    # 양성 대조: 사람 CLI 실행은 작업이 돌고 있어도 그대로다 (lock은 Agent 주체만 본다)
    with jobdir.JobLock(workspace):
        code, data = _run(workspace, platform, cli_env(tmp_path))
    assert code == 0 and data["principal"]["kind"] == "user", data  # type: ignore[index]
