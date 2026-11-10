"""외부 Agent CLI 프로필 (M8 계획 3.9·3.15, 9장 R9).

- `claude`(`claude -p`, `--mcp-config`·`--strict-mcp-config`, Kookabug MCP 도구만 허용·셸·파일 도구
  끄기), `codex`(`codex exec -`, MCP 설정 `-c`, 읽기 전용 샌드박스), `custom`(`--agent-command`,
  CI의 가짜 CLI). 프롬프트는 stdin으로 준다. 프로필의 안전 플래그는 **권장**이며 보장 범위 밖이다
  (3.15 보안 경계 — CLI 판마다 바뀐다)
- 작업 토큰은 **자식 환경 변수 `KOOKABUG_JOB_TOKEN`으로만** 넘긴다. argv·`mcp.json`·`job.json`·
  예약 XML에 넣지 않는다(R9). `mcp.json`에는 환경 변수 **이름**만 있다
- 자식 환경은 허용 목록만 넘긴다(R9): 시스템·파이썬 실행에 필요한 이름 + 프로필 인증 변수 + 작업
  변수 + 사람이 `--pass-env`로 고른 이름. `KOOKABUG_SECRET_*`(게임 계정 비밀값)는 넘기지 않는다
- 자식에게 넘기는 환경 중 `BASE_ENV` 밖의 값(프로필 인증·`--pass-env`·작업 변수, 6자 이상)은
  `agent.log` 가림 대상이다 (`passed_values`)
"""

from __future__ import annotations

import ctypes
import json
import shutil
import sys
from collections.abc import Callable, Iterable, Mapping
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from kookabug_core.agents.detect import detect

__all__ = [
    "AUTH_ENV",
    "BASE_ENV",
    "JOB_DIR_ENV",
    "JOB_ENV",
    "MCP_CONFIG_ENV",
    "PROFILES",
    "REDACT_MIN",
    "TOKEN_ENV",
    "Command",
    "ProfileError",
    "auth_values",
    "build_prompt",
    "child_env",
    "cli_executable",
    "command_line",
    "mcp_config",
    "mcp_server",
    "passed_values",
    "split_command",
]

PROFILES: Final = ("claude", "codex", "custom")
TOKEN_ENV: Final = "KOOKABUG_JOB_TOKEN"
JOB_ENV: Final = "KOOKABUG_JOB_ID"
JOB_DIR_ENV: Final = "KOOKABUG_JOB_DIR"
MCP_CONFIG_ENV: Final = "KOOKABUG_JOB_MCP_CONFIG"
SERVER_NAME: Final = "kookabug"

BASE_ENV: Final = frozenset(
    {
        # Windows·프로세스 실행에 필요한 것
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "PATH",
        "PATHEXT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "USERNAME",
        "USERDOMAIN",
        "HOMEDRIVE",
        "HOMEPATH",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "COMMONPROGRAMFILES",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "PROCESSOR_IDENTIFIER",
        "OS",
        "LANG",
        # 파이썬 (`kookabug mcp`·가짜 CLI)
        "PYTHONUTF8",
        "PYTHONIOENCODING",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "__PYVENV_LAUNCHER__",
        # Kookabug 설정 위치 (비밀값 아님 — daemon 찾기·사용자 설정·검사 임대권 이름)
        "KOOKABUG_USER_CONFIG_DIR",
        "KOOKABUG_STATE_DIR",
        "KOOKABUG_INPUT_LEASE_NAME",
        "KOOKABUG_TEST_DISPLAY",
    }
)
"""자식 환경 허용 목록 (대문자 이름). 여기 없는 이름은 넘기지 않는다."""

AUTH_ENV: Final[Mapping[str, tuple[str, ...]]] = {
    "claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"),
    "codex": ("OPENAI_API_KEY", "CODEX_API_KEY"),
    "custom": (),
}
"""프로필 인증 변수: 넘기되 값은 `agent.log`에서 가린다."""

_CONFIG_ENV: Final[Mapping[str, tuple[str, ...]]] = {
    "claude": ("CLAUDE_CONFIG_DIR",),
    "codex": ("CODEX_HOME",),
    "custom": (),
}


class ProfileError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Command:
    argv: list[str]
    """실행할 명령 (토큰 없음)."""
    name: str
    """`job.json`에 남길 실행 파일 이름 (경로·인자 없음)."""


# ---------------------------------------------------------------- 명령줄


def split_command(text: str) -> list[str]:
    """Windows 명령줄 → argv (`CommandLineToArgvW` — CreateProcess와 같은 규칙)."""
    if not text.strip():
        raise ProfileError("agent_command_empty", "--agent-command가 비었다")
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int(0)
    argv = shell32.CommandLineToArgvW(text, ctypes.byref(count))
    if not argv:
        raise ProfileError("agent_command_invalid", "--agent-command를 나누지 못했다")
    try:
        return [argv[i] for i in range(count.value)]
    finally:
        kernel32.LocalFree(ctypes.cast(argv, wintypes.HLOCAL))


def mcp_server(root: Path, job_id: str) -> tuple[str, list[str]]:
    """설치본 `kookabug mcp` 명령 (실행 파일, 인자). 토큰은 환경 변수 이름으로만 가리킨다."""
    return sys.executable, [
        "-m",
        "kookabug_cli",
        "mcp",
        "--workspace",
        str(root),
        "--unattended",
        "--agent-id",
        f"job:{job_id}",
        "--client",
        "agent-job",
        "--job-token-env",
        TOKEN_ENV,
    ]


def mcp_config(root: Path, job_id: str) -> dict[str, Any]:
    """`mcp.json` (claude `--mcp-config` 형식, 가짜 CLI도 읽는다). 값에 토큰이 없다."""
    command, args = mcp_server(root, job_id)
    return {"mcpServers": {SERVER_NAME: {"command": command, "args": args, "env": {}}}}


def _toml(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def cli_executable(profile: str, which: Callable[[str], str | None] = shutil.which) -> str | None:
    """무인 작업이 띄울 본체 CLI(`claude`·`codex`) 경로.

    에이전트 감지 표(`agents.detect`)의 `cli_path`를 먼저 쓴다 — 패널이 ACP로 붙는 어댑터
    (`claude-agent-acp`·`npx …`)가 아니라 본체 CLI다. 표에 그 CLI 줄이 없거나 못 찾았으면
    지금처럼 `which(profile)`.
    """
    for row in detect(which):
        if row["cli"] == profile and row["cli_path"] is not None:
            return str(row["cli_path"])
    return which(profile)


def command_line(
    profile: str,
    *,
    root: Path,
    job_id: str,
    mcp_path: Path,
    agent_command: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> Command:
    """프로필의 명령줄. 프롬프트는 stdin, 토큰은 환경 변수(이 argv에는 없다)."""
    if profile == "custom":
        if not agent_command:
            raise ProfileError(
                "agent_command_required", "custom 프로필은 --agent-command가 있어야 한다"
            )
        argv = split_command(agent_command)
        return Command(argv, Path(argv[0]).name)
    if profile not in PROFILES:
        raise ProfileError("profile_unknown", f"모르는 Agent 프로필이다: {profile!r}")
    exe = cli_executable(profile, which)
    if exe is None:
        raise ProfileError("cli_not_found", f"{profile} CLI를 PATH에서 찾지 못했다")
    if profile == "claude":
        argv = [
            exe,
            "-p",
            "--output-format",
            "text",
            "--mcp-config",
            str(mcp_path),
            "--strict-mcp-config",
            # 권장: Kookabug MCP 도구만 쓰고 셸·파일 쓰기·웹 도구는 끈다 (보장 범위 밖, 3.15)
            "--allowedTools",
            f"mcp__{SERVER_NAME}",
            "--disallowedTools",
            "Bash,Edit,Write,MultiEdit,NotebookEdit,WebFetch,WebSearch",
        ]
    else:
        command, args = mcp_server(root, job_id)
        argv = [
            exe,
            "exec",
            # 권장: 읽기 전용 샌드박스 (보장 범위 밖, 3.15)
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--cd",
            str(root),
            "-c",
            f"mcp_servers.{SERVER_NAME}.command={_toml(command)}",
            "-c",
            f"mcp_servers.{SERVER_NAME}.args={_toml(args)}",
            "-c",
            f"mcp_servers.{SERVER_NAME}.env_vars={_toml([TOKEN_ENV])}",
            "-",  # 프롬프트는 stdin
        ]
    return Command(argv, Path(exe).name)


# ---------------------------------------------------------------- 환경


def child_env(
    profile: str,
    parent: Mapping[str, str],
    *,
    token: str,
    job_id: str,
    job_dir: Path,
    mcp_path: Path,
    pass_env: Iterable[str] = (),
) -> dict[str, str]:
    """자식 환경: 허용 목록에 든 이름만 + 작업 변수. 허용 목록 밖은 하나도 넘기지 않는다."""
    allowed = set(BASE_ENV)
    allowed |= set(AUTH_ENV.get(profile, ())) | set(_CONFIG_ENV.get(profile, ()))
    allowed |= {name.upper() for name in pass_env if not name.upper().startswith("KOOKABUG_SECRET")}
    env = {name: value for name, value in parent.items() if name.upper() in allowed}
    env[TOKEN_ENV] = token
    env[JOB_ENV] = job_id
    env[JOB_DIR_ENV] = str(job_dir)
    env[MCP_CONFIG_ENV] = str(mcp_path)
    return env


def auth_values(profile: str, parent: Mapping[str, str]) -> list[str]:
    """그 프로필 인증 변수의 값들."""
    upper = {k.upper(): v for k, v in parent.items()}
    return [upper[name] for name in AUTH_ENV.get(profile, ()) if upper.get(name)]


REDACT_MIN: Final = 6
"""이보다 짧은 환경 값은 가리지 않는다 (`1`·`true` 같은 값이 로그 전체를 가리지 않게)."""


def passed_values(child: Mapping[str, str]) -> list[str]:
    """`agent.log` 가림 목록: 자식에게 실제로 넘기는 환경 중 시스템 기본(`BASE_ENV`) **밖**의 값
    전부 — 프로필 인증·`--pass-env`·작업 변수(R9). 이름을 바꿔 넘긴 인증 값도 걸린다. 6자 미만은
    뺀다."""
    return [
        value
        for name, value in child.items()
        if name.upper() not in BASE_ENV and len(value) >= REDACT_MIN
    ]


# ---------------------------------------------------------------- 프롬프트


def build_prompt(
    body: str,
    *,
    playbook: str,
    version: int,
    job_id: str,
    basis: str,
    budget: Mapping[str, int],
    trigger: str,
    workspace: str,
) -> str:
    """플레이북 본문 + 작업 머리말. 위키·지식 내용은 넣지 않는다(3.3 경로 차단)."""
    head = [
        "<!-- kookabug:job -->",
        f"작업 ID: {job_id}",
        f"플레이북: {playbook} (판 {version})",
        f"기준: {basis}",
        f"예산: {budget.get('minutes')}분 · 실행 {budget.get('runs')}회",
        f"트리거: {trigger}",
        f"워크스페이스: {workspace}",
        "<!-- /kookabug:job -->",
        "",
    ]
    return "\n".join(head) + body
