"""`kookabug daemon` (M2 계획 2.3). 워크스페이스 daemon을 띄운다.

    kookabug daemon [--workspace DIR] [--idle-timeout-s 600] [--json] [--log-level info]

이미 그 워크스페이스의 daemon이 돌고 있으면 그 세션을 확인하고 종료 코드 0으로 끝난다.
인자와 수명은 `kookabug_daemon`이 정한다. 여기는 CLI 하위 명령으로 잇기만 한다.
"""

from __future__ import annotations

import argparse
from typing import Any, TextIO

from kookabug_daemon import options

__all__ = ["add_parser", "run"]


def add_parser(commands: Any) -> None:
    """`commands`는 `add_subparsers()`가 돌려준 값."""
    daemon: argparse.ArgumentParser = commands.add_parser(
        "daemon",
        help="워크스페이스 daemon을 띄운다 (데스크톱 앱·에이전트가 붙는다)",
        description="워크스페이스 daemon을 띄운다. 이미 돌고 있으면 그 세션을 확인하고 끝난다 "
        "(0 정상 종료·이미 실행 중, 6 사용법·환경 오류)",
    )
    options.add_arguments(daemon)


def run(args: argparse.Namespace, out: TextIO, err: TextIO, *, dpi_error: str | None) -> int:
    # daemon(websockets·asyncio)은 쓸 때만 불러온다 (`kookabug run` 시작을 가볍게)
    from kookabug_daemon import app

    try:
        config = app.config_from_args(args)
    except app.UsageError as exc:
        print(f"오류: {exc}", file=err)
        return app.EXIT_USAGE
    return app.run(config, as_json=args.json, dpi_error=dpi_error, out=out, err=err)
