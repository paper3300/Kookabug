"""외부 Agent CLI 프로필 (M8 계획 3.9, R9) — 명령줄 생성만 검사한다 (claude·codex를 띄우지 않음)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kookabug_core.agent_job import profiles

JOB = "j-20261110-000000-abcd"
TOKEN = "tok-" + "x" * 40


def fake_which(name: str) -> str | None:
    return {"claude": r"C:\Tools\claude.cmd", "codex": r"C:\Tools\codex.exe"}.get(name)


def test_claude_codex_command_lines(tmp_path: Path) -> None:
    mcp = tmp_path / "mcp.json"
    claude = profiles.command_line(
        "claude", root=tmp_path, job_id=JOB, mcp_path=mcp, which=fake_which
    )
    assert claude.name == "claude.cmd"
    argv = claude.argv
    assert argv[:2] == [r"C:\Tools\claude.cmd", "-p"]
    assert argv[argv.index("--mcp-config") + 1] == str(mcp)
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--allowedTools") + 1] == "mcp__kookabug"
    assert "Bash" in argv[argv.index("--disallowedTools") + 1]

    codex = profiles.command_line(
        "codex", root=tmp_path, job_id=JOB, mcp_path=mcp, which=fake_which
    )
    argv = codex.argv
    assert argv[:2] == [r"C:\Tools\codex.exe", "exec"]
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[-1] == "-"  # 프롬프트는 stdin
    configs = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert any(c.startswith("mcp_servers.kookabug.command=") for c in configs)
    args = next(c for c in configs if c.startswith("mcp_servers.kookabug.args="))
    server_args = json.loads(args.split("=", 1)[1])
    assert server_args[server_args.index("--job-token-env") + 1] == profiles.TOKEN_ENV
    assert "--unattended" in server_args and f"job:{JOB}" in server_args
    assert any(c == 'mcp_servers.kookabug.env_vars=["KOOKABUG_JOB_TOKEN"]' for c in configs)

    custom = profiles.command_line(
        "custom",
        root=tmp_path,
        job_id=JOB,
        mcp_path=mcp,
        agent_command=r'"C:\Program Files\py\python.exe" -m fake --script "a b"',
    )
    assert custom.argv == [r"C:\Program Files\py\python.exe", "-m", "fake", "--script", "a b"]
    assert custom.name == "python.exe"

    # mcp.json: 토큰 값이 없고 환경 변수 이름만
    config = profiles.mcp_config(tmp_path, JOB)
    server = config["mcpServers"]["kookabug"]
    assert server["env"] == {}
    assert server["args"][server["args"].index("--job-token-env") + 1] == "KOOKABUG_JOB_TOKEN"
    for command in (claude, codex, custom):
        assert not any(TOKEN in a for a in command.argv)

    with pytest.raises(profiles.ProfileError) as caught:
        profiles.command_line(
            "claude", root=tmp_path, job_id=JOB, mcp_path=mcp, which=lambda _: None
        )
    assert caught.value.code == "cli_not_found"
    with pytest.raises(profiles.ProfileError) as caught:
        profiles.command_line("custom", root=tmp_path, job_id=JOB, mcp_path=mcp)
    assert caught.value.code == "agent_command_required"
    with pytest.raises(profiles.ProfileError) as caught:
        profiles.command_line("gpt", root=tmp_path, job_id=JOB, mcp_path=mcp, which=fake_which)
    assert caught.value.code == "profile_unknown"


def test_child_env_allowlist(tmp_path: Path) -> None:
    parent = {
        "PATH": r"C:\Windows",
        "SystemRoot": r"C:\Windows",
        "KOOKABUG_SECRET_ACCOUNTS_QA": "s3cret-value",
        "ANTHROPIC_API_KEY": "sk-ant-abc",
        "OPENAI_API_KEY": "sk-openai",
        "AWS_SECRET_ACCESS_KEY": "aws",
        "MY_TOOL_HOME": "x",
        "KOOKABUG_USER_CONFIG_DIR": "cfg",
    }
    env = profiles.child_env(
        "claude",
        parent,
        token=TOKEN,
        job_id=JOB,
        job_dir=tmp_path,
        mcp_path=tmp_path / "mcp.json",
        pass_env=["MY_TOOL_HOME", "KOOKABUG_SECRET_ACCOUNTS_QA"],
    )
    # 양성 대조: 허용 목록·프로필 인증·사람이 고른 이름·작업 변수는 넘어간다
    assert env["PATH"] == r"C:\Windows" and env["SystemRoot"] == r"C:\Windows"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-abc"
    assert env["MY_TOOL_HOME"] == "x" and env["KOOKABUG_USER_CONFIG_DIR"] == "cfg"
    assert env[profiles.TOKEN_ENV] == TOKEN and env[profiles.JOB_ENV] == JOB
    # 허용 목록 밖·다른 프로필 인증·게임 비밀값(--pass-env로도)은 넘어가지 않는다
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert "KOOKABUG_SECRET_ACCOUNTS_QA" not in env
    assert profiles.auth_values("claude", parent) == ["sk-ant-abc"]
    assert profiles.auth_values("custom", parent) == []


def test_prompt_has_header_and_playbook_only(tmp_path: Path) -> None:
    prompt = profiles.build_prompt(
        "본문\n",
        playbook="repair",
        version=1,
        job_id=JOB,
        basis="working",
        budget={"minutes": 60, "runs": 30},
        trigger="manual",
        workspace="예제",
    )
    assert prompt.startswith("<!-- kookabug:job -->\n작업 ID: " + JOB)
    assert "예산: 60분 · 실행 30회" in prompt and prompt.endswith("본문\n")
