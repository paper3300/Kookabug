"""`kookabug mcp` (M5 계획 3.1).

    kookabug mcp [--workspace <루트>] [--agent-id <id>] [--unattended] [--client <이름>]
                 [--job-token-env <환경 변수 이름>]

- 워크스페이스: 인자 → 현재 폴더에서 위로 `kookabug.json` 찾기. 없으면 종료 코드 6
- `--agent-id` 기본 `mcp:<PID>`. 기본은 attended(사람이 에이전트를 몰고 있음), `--unattended`면
  사람 없음(확인이 필요한 도구는 거부). 둘 다 자기 신고라 보안 경계가 아니다
  (`KOOKABUG_AGENT`와 같음)
- `--job-token-env`(M8 R7): 그 환경 변수의 작업 토큰으로 붙는다 — 주체가 그 작업에 묶인다(자기
  신고가 아님). 토큰이 틀리거나 만료됐으면 daemon이 연결을 거부한다(종료 코드 6)
- 작업 안(`KOOKABUG_JOB_TOKEN`이 있거나 `--agent-id`·`KOOKABUG_AGENT`가 `job:`)인데
  `--job-token-env`가 없으면 붙지 않고 종료 코드 3 (`job_active` — 작업 예산·종료 감독 우회 금지)
- daemon에 붙지 못하거나 판이 다르면 종료 코드 6. stdin이 끝나면 0
- stdout은 프로토콜 전용, 로그는 stderr
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, BinaryIO, Final

__all__ = ["EXIT_OK", "EXIT_USAGE", "add_parser", "run"]

EXIT_OK: Final = 0
EXIT_JOB_ACTIVE: Final = 3
"""작업 안에서 토큰 없이 붙으려 했다 (`job_active`, M8 R8)."""
EXIT_USAGE: Final = 6


def add_parser(commands: Any) -> None:
    """`commands`는 `add_subparsers()`가 돌려준 값."""
    mcp: argparse.ArgumentParser = commands.add_parser(
        "mcp",
        help="MCP 서버 (stdio): 에이전트 CLI가 워크스페이스 daemon을 쓰게 한다",
        description="MCP 서버를 stdio로 띄운다. 에이전트 CLI의 MCP 서버 설정에 등록한다 "
        "(0 정상 종료, 6 워크스페이스 없음·daemon에 붙지 못함)",
    )
    mcp.add_argument("--workspace", help="워크스페이스 루트 (기본: 현재 폴더에서 위로 찾기)")
    mcp.add_argument("--agent-id", help="에이전트 주체 ID (기본 mcp:<PID>)")
    mcp.add_argument(
        "--unattended",
        action="store_true",
        help="사람이 지켜보지 않는 연결 (확인이 필요한 도구는 거부)",
    )
    mcp.add_argument("--client", default="mcp", help="연결 이름 (에이전트 목록 표시용)")
    mcp.add_argument(
        "--job-token-env",
        metavar="NAME",
        help="작업 토큰을 읽을 환경 변수 이름 (agent-job이 정한다. 값은 인자로 받지 않는다)",
    )
    mcp.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])


def _inside_job(agent_id: str | None) -> bool:
    """작업 안에서 띄운 프로세스다: 작업 변수(토큰·작업 ID·작업 폴더·MCP 설정)가 있거나 주체 ID·
    `KOOKABUG_AGENT`가 `job:`."""
    from kookabug_core.service import JOB_ENV_NAMES

    if any(os.environ.get(name) for name in JOB_ENV_NAMES):
        return True
    ids = (agent_id or "", os.environ.get("KOOKABUG_AGENT") or "")
    return any(i.strip().lower().startswith("job:") for i in ids)


def _workspace(given: str | None) -> Path:
    from kookabug_core.workspace import Workspace

    ws = Workspace.open(Path(given)) if given else Workspace.find(Path.cwd())
    return ws.root


def run(
    args: argparse.Namespace,
    *,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
) -> int:
    from kookabug_mcp.stdio import StdioChannel, protect_stdout

    # 프로토콜 stdout을 가장 먼저 떼어 낸다 (그 뒤의 어떤 출력도 stderr로 간다)
    proto = stdout if stdout is not None else protect_stdout()
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, str(args.log_level).upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from kookabug_core.workspace import WorkspaceError
    from kookabug_mcp.daemon_link import DaemonLink, LinkError
    from kookabug_mcp.server import McpServer

    try:
        root = _workspace(args.workspace)
    except WorkspaceError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return EXIT_USAGE
    job_token: str | None = None
    env_name = getattr(args, "job_token_env", None)
    if not env_name and _inside_job(args.agent_id):
        # 작업 안에서 토큰 없이 붙으면 작업 예산·종료 감독을 피하는 Agent 연결이 된다 (M8 R8)
        print(
            "오류: job_active — 작업 안 Agent는 작업 토큰 연결(--job-token-env)로만 붙는다",
            file=sys.stderr,
        )
        return EXIT_JOB_ACTIVE
    if env_name:
        # 토큰은 환경 변수로만 받는다 (argv·로그에 남지 않게, M8 R9). 없으면 붙지 않는다
        job_token = os.environ.get(str(env_name)) or None
        if job_token is None:
            print(f"오류: 환경 변수 {env_name}에 작업 토큰이 없다", file=sys.stderr)
            return EXIT_USAGE
    link = DaemonLink(
        root,
        agent_id=args.agent_id or f"mcp:{os.getpid()}",
        attended=not args.unattended,
        name=str(args.client),
        job_token=job_token,
    )
    try:
        link.connect()
    except LinkError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return EXIT_USAGE
    channel = StdioChannel(stdin if stdin is not None else sys.stdin.buffer, proto)
    return McpServer(channel, link).serve()
