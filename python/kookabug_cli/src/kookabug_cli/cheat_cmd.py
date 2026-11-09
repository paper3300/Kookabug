"""`kookabug cheat list|adopt|unadopt` (M8 계획 3.2·3.14). 치트 채택은 사람만 한다.

    kookabug cheat list [--workspace DIR] [--json]
    kookabug cheat adopt <ID> --rev N --category 분류 [--workspace DIR] [--json]
    kookabug cheat unadopt <ID> --rev N [--workspace DIR] [--json]

daemon 없이 워크스페이스에 직접 쓴다 — 쓰기는 지식 연산(`ops.apply` → `filetx`) 한 경로뿐이다.
`KOOKABUG_AGENT`가 있으면 목록 보기까지 아무것도 하지 않고 종료 5. 종료 코드 0 성공, 1 거부(없는
치트·분류, rev 다름, 구현에 미해결·동적 의존성), 5 에이전트.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, TextIO

__all__ = ["EXIT_DENIED", "EXIT_REFUSED", "add_parser", "run"]

AGENT_ENV = "KOOKABUG_AGENT"
EXIT_REFUSED = 1
EXIT_DENIED = 5


def add_parser(commands: Any) -> None:
    cheat: argparse.ArgumentParser = commands.add_parser("cheat", help="치트 목록·채택 (사람만)")
    actions = cheat.add_subparsers(dest="action", required=True, metavar="동작")
    listing = actions.add_parser("list", help="치트 정의와 채택 상태")
    adopt = actions.add_parser(
        "adopt",
        help="치트를 분류와 함께 채택한다",
        description="그 rev 정의·구현을 채택한다 (0 채택, 1 거부, 5 에이전트)",
    )
    adopt.add_argument("id", help="치트 ID")
    adopt.add_argument("--rev", type=int, required=True, help="채택할 정의 rev")
    adopt.add_argument(
        "--category", required=True, help="kookabug.json cheats.categories의 분류 ID"
    )
    unadopt = actions.add_parser("unadopt", help="치트 채택을 푼다")
    unadopt.add_argument("id", help="치트 ID")
    unadopt.add_argument("--rev", type=int, required=True, help="지금 정의 rev")
    for sub in (listing, adopt, unadopt):
        sub.add_argument(
            "--workspace", metavar="DIR", help="워크스페이스 루트 (기본: 현재 폴더에서 위로 찾는다)"
        )
        sub.add_argument("--json", action="store_true", help="결과 JSON 한 개만 출력한다")


def run(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    report: dict[str, Any] = {"command": f"cheat {args.action}"}

    def finish(code: int, text: str, **extra: Any) -> int:
        report.update(exit_code=code, message=text, **extra)
        if args.json:
            print(json.dumps(report, ensure_ascii=False), file=out)
        else:
            print(text, file=out if code == 0 else err)
        return code

    if AGENT_ENV in os.environ:
        return finish(
            EXIT_DENIED, "치트 목록·채택은 사람만 한다 (KOOKABUG_AGENT)", error_code="agent_only"
        )
    from kookabug_core.knowledge import cheats
    from kookabug_core.knowledge.formats import KnowledgeError
    from kookabug_core.workspace import Workspace, WorkspaceError

    try:
        root = (
            Workspace.open(Path(args.workspace)).root
            if args.workspace
            else Workspace.find(Path.cwd()).root
        )
    except WorkspaceError as exc:
        return finish(EXIT_REFUSED, f"오류: {exc}", error_code="workspace_invalid")
    by = f"cli:{os.environ.get('USERNAME', 'user')}"
    try:
        if args.action == "list":
            listed = cheats.list_cheats(root)
            lines = [
                f"{c['id']} rev {c['rev']} — {c['title']} "
                f"[{'채택: ' + str(c['category']) if c['adopted'] else '채택 안 됨'}]"
                + (f" ({c['problem']})" if c["problem"] else "")
                for c in listed["cheats"]
            ]
            text = "\n".join(lines) if lines else "치트가 없다"
            return finish(0, text, **listed)
        if args.action == "adopt":
            done = cheats.adopt(root, args.id, args.rev, args.category, by=by)
            return finish(0, f"채택했다: {args.id} rev {args.rev} ({args.category})", **done)
        done = cheats.unadopt(root, args.id, args.rev, by=by)
        return finish(0, f"채택을 풀었다: {args.id}", **done)
    except KnowledgeError as exc:
        return finish(EXIT_REFUSED, f"오류: {exc.message}", error_code=exc.code)
    except WorkspaceError as exc:
        return finish(EXIT_REFUSED, f"오류: {exc}", error_code="workspace_invalid")
