"""`kookabug secret set|delete` (UX5): 테스트 계정 비밀값을 사람이 직접 등록한다.

    kookabug secret set <키> [--replace] [--workspace DIR] [--json]   # 값은 표준 입력 한 줄
    kookabug secret delete <키> [--workspace DIR] [--json]

데스크톱 앱 계정 화면이 부른다 (주 프로세스가 값을 표준 입력으로만 넘긴다 — 명령줄·daemon RPC·
로그·파일에 값이 없다). 값은 Windows 자격 증명 관리자 `kookabug:<워크스페이스 ID>:<키>`에만 쓴다.
워크스페이스 ID가 없으면 처음 만들 때 `kookabug.json`에 넣는다 (`secrets.create`와 같음).
`KOOKABUG_AGENT`가 있으면 아무것도 하지 않고 종료 5. 종료 코드 0 성공, 1 거부(키 형식·이미 있음·
빈 값·자격 증명 관리자 오류), 5 에이전트.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO

__all__ = ["EXIT_DENIED", "EXIT_REFUSED", "VALUE_LIMIT", "add_parser", "run"]

AGENT_ENV = "KOOKABUG_AGENT"
EXIT_REFUSED = 1
EXIT_DENIED = 5
VALUE_LIMIT = 1024
"""값 글자 수 상한 (계정 이름·비밀번호)."""


def add_parser(commands: Any) -> None:
    secret: argparse.ArgumentParser = commands.add_parser(
        "secret", help="테스트 계정 비밀값 등록·삭제 (사람만)"
    )
    actions = secret.add_subparsers(dest="action", required=True, metavar="동작")
    put = actions.add_parser(
        "set",
        help="표준 입력 한 줄을 그 키의 비밀값으로 자격 증명 관리자에 쓴다",
        description="값은 표준 입력으로만 받는다 (0 성공, 1 거부, 5 에이전트)",
    )
    put.add_argument("key", help="비밀값 키 (예: login.password)")
    put.add_argument("--replace", action="store_true", help="이미 있으면 바꾼다")
    remove = actions.add_parser("delete", help="그 키의 비밀값을 지운다")
    remove.add_argument("key", help="비밀값 키")
    for sub in (put, remove):
        sub.add_argument(
            "--workspace", metavar="DIR", help="워크스페이스 루트 (기본: 현재 폴더에서 위로 찾는다)"
        )
        sub.add_argument("--json", action="store_true", help="결과 JSON 한 개만 출력한다")


def _read_value(stdin: TextIO) -> str | None:
    """표준 입력 한 줄 (끝 줄바꿈만 뗀다). 비었거나 길거나 제어 문자가 있으면 None."""
    raw = stdin.read(VALUE_LIMIT + 2)
    value = raw[:-1] if raw.endswith("\n") else raw
    value = value[:-1] if value.endswith("\r") else value
    if not value or len(value) > VALUE_LIMIT or any(ord(c) < 32 for c in value):
        return None
    return value


def run(args: argparse.Namespace, out: TextIO, err: TextIO, stdin: TextIO | None = None) -> int:
    report: dict[str, Any] = {"command": f"secret {args.action}", "key": args.key}

    def finish(code: int, text: str, **extra: Any) -> int:
        report.update(exit_code=code, message=text, **extra)
        if args.json:
            print(json.dumps(report, ensure_ascii=False), file=out)
        else:
            print(text, file=out if code == 0 else err)
        return code

    if AGENT_ENV in os.environ:
        return finish(
            EXIT_DENIED, "비밀값 등록은 사람만 한다 (KOOKABUG_AGENT)", error_code="agent_only"
        )
    from kookabug_core.recorder.secrets import SECRET_KEY
    from kookabug_core.workspace import Workspace, WorkspaceError, ensure_workspace_id

    if not SECRET_KEY.fullmatch(args.key) or len(args.key) > 128:
        return finish(EXIT_REFUSED, "비밀값 키 형식이 틀렸다", error_code="key_invalid")
    if sys.platform != "win32":
        return finish(
            EXIT_REFUSED,
            "자격 증명 관리자는 Windows에서만 쓸 수 있다",
            error_code="platform_unavailable",
        )
    from kookabug_core.win.credentials import CredentialError, CredentialStore

    try:
        root = (
            Workspace.open(Path(args.workspace)).root
            if args.workspace
            else Workspace.find(Path.cwd()).root
        )
    except WorkspaceError as exc:
        return finish(EXIT_REFUSED, f"오류: {exc}", error_code="workspace_invalid")
    store = CredentialStore()
    try:
        if args.action == "delete":
            wid = ensure_workspace_id(root)
            gone = store.delete(wid, args.key)
            return finish(0, "지웠다" if gone else "없는 키다", deleted=gone)
        value = _read_value(stdin if stdin is not None else sys.stdin)
        if value is None:
            return finish(
                EXIT_REFUSED,
                f"값이 비었거나 {VALUE_LIMIT}자를 넘거나 줄바꿈·제어 문자가 있다",
                error_code="value_invalid",
            )
        wid = ensure_workspace_id(root)
        if not args.replace and store.read(wid, args.key) is not None:
            return finish(EXIT_REFUSED, "이미 있는 키다", error_code="exists")
        store.write(wid, args.key, value)
    except (CredentialError, WorkspaceError) as exc:
        return finish(EXIT_REFUSED, f"오류: {exc}", error_code="io_error")
    return finish(0, "등록했다 (값은 자격 증명 관리자에만 있다)")
