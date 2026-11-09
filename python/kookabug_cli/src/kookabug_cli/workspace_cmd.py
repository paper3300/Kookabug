"""`kookabug workspace new` (M8 계획 3.1·C15). 새 워크스페이스를 만든다 (daemon 없이 동작).

    kookabug workspace new <폴더> --name 이름 [--git] [--json]

사람만: `KOOKABUG_AGENT`가 있으면 아무것도 만들지 않고 종료 5. 종료 코드 0 만듦, 1 거부(비어 있지
않은 폴더·이름), 5 에이전트.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, TextIO

__all__ = ["EXIT_DENIED", "EXIT_REFUSED", "add_parser", "run"]

AGENT_ENV = "KOOKABUG_AGENT"
EXIT_REFUSED = 1
EXIT_DENIED = 5


def add_parser(commands: Any) -> None:
    """`commands`는 `add_subparsers()`가 돌려준 값."""
    workspace: argparse.ArgumentParser = commands.add_parser(
        "workspace", help="워크스페이스 만들기 (사람만)"
    )
    actions = workspace.add_subparsers(dest="action", required=True, metavar="동작")
    new = actions.add_parser(
        "new",
        help="새 워크스페이스를 만든다",
        description="새 워크스페이스(kookabug.json·AGENTS.md·.gitignore·knowledge/·wiki/)를 만든다 "
        "(0 만듦, 1 거부, 5 에이전트)",
    )
    new.add_argument("folder", help="만들 폴더 (없거나 비어 있어야 한다)")
    new.add_argument("--name", required=True, help="프로젝트 이름")
    new.add_argument("--git", action="store_true", help="git init도 한다")
    new.add_argument("--json", action="store_true", help="결과 JSON 한 개만 출력한다")


def run(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    from kookabug_core.workspace_new import CreateError, create_workspace

    report: dict[str, Any] = {"command": "workspace new", "folder": args.folder}

    def finish(code: int, text: str, **extra: Any) -> int:
        report.update(exit_code=code, message=text, **extra)
        if args.json:
            print(json.dumps(report, ensure_ascii=False), file=out)
        else:
            print(text, file=out if code == 0 else err)
        return code

    if AGENT_ENV in os.environ:
        return finish(
            EXIT_DENIED,
            "워크스페이스 만들기는 사람만 한다 (KOOKABUG_AGENT)",
            error_code="agent_only",
        )
    try:
        created = create_workspace(args.folder, args.name, git=args.git)
    except CreateError as exc:
        return finish(EXIT_REFUSED, f"오류: {exc.message}", error_code=exc.code)
    text = f"워크스페이스를 만들었다: {created.root}"
    for warning in created.warnings:
        text += f"\n경고: {warning}"
    return finish(0, text, **created.to_dict())
