"""외부 PR 게이트 (2026-11-03 사용자 결정: 허용한 사람만 PR).

`.github/workflows/pr-gate.yml`이 `pull_request_target`에서 PR 코드가 아니라 기준 브랜치의 이 파일을
부른다. 작성자가 허용 목록(`.github/APPROVED_CONTRIBUTORS`)에 있거나 레포 주인·봇이면 통과, 아니면
워크플로가 안내 댓글(`.github/pr-gate-comment.md`)을 달고 PR을 닫는다.

    PR_AUTHOR=<login> PR_AUTHOR_TYPE=User REPO_OWNER=<login> python3 tools/pr_gate.py
    # stdout: allowed=true|false (GITHUB_OUTPUT 형식)

러너 기본 Python(3.12 이상)으로 돌아야 하므로 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPROVED_FILE = ROOT / ".github" / "APPROVED_CONTRIBUTORS"


def parse_approved(text: str) -> set[str]:
    """한 줄에 GitHub 계정 하나. `#` 뒤는 주석, 빈 줄·앞의 `@`는 무시, 대소문자는 가리지 않는다."""
    logins: set[str] = set()
    for line in text.removeprefix("﻿").splitlines():
        login = line.split("#", 1)[0].strip().removeprefix("@")
        if login:
            logins.add(login.casefold())
    return logins


def is_allowed(author: str, author_type: str, owner: str, approved: set[str]) -> bool:
    """레포 주인·봇·허용 목록의 사람만 PR을 열어 둔다."""
    login = author.strip().casefold()
    if not login:
        return False
    if author_type == "Bot":
        return True
    return login == owner.strip().casefold() or login in approved


def main() -> int:
    author = os.environ.get("PR_AUTHOR", "")
    author_type = os.environ.get("PR_AUTHOR_TYPE", "")
    owner = os.environ.get("REPO_OWNER", "")
    try:
        approved = parse_approved(APPROVED_FILE.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        approved = set()
    allowed = is_allowed(author, author_type, owner, approved)
    print(f"allowed={'true' if allowed else 'false'}")
    print(
        f"PR 작성자 {author!r} ({author_type}): {'허용' if allowed else '허용 목록 밖'}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
