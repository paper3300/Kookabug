"""에이전트 감지 표 (M5 계획 3.12): 에이전트 패널 빈 화면의 "감지한 에이전트" 목록.

일반 제품명과 ACP로 붙는 명령 후보를 한 곳에 둔다. 경로(`PATH`)에서 찾기만 하고 설치하지 않는다.
실제 명령 이름·인자는 제품마다 바뀔 수 있어 사람 확인(m5-manual)에서 고친다.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

__all__ = ["DETECT_TABLE", "Candidate", "detect"]


@dataclass(frozen=True, slots=True)
class Candidate:
    """감지 표의 줄 하나: 같은 제품의 명령 후보를 앞에서부터 본다."""

    id: str
    name: str
    commands: tuple[tuple[str, tuple[str, ...]], ...]
    """(실행 파일 이름, 인자) 후보."""


DETECT_TABLE: Final = (
    Candidate("claude-code", "Claude Code", (("claude-code-acp", ()),)),
    Candidate("codex", "Codex CLI", (("codex-acp", ()),)),
    Candidate("gemini", "Gemini CLI", (("gemini", ("--experimental-acp",)),)),
)


def detect(which: Callable[[str], str | None] | None = None) -> list[dict[str, Any]]:
    """표의 제품마다 찾은 첫 명령(없으면 첫 후보·`installed: false`)."""
    which = which or shutil.which
    out: list[dict[str, Any]] = []
    for item in DETECT_TABLE:
        found: tuple[str, tuple[str, ...], str] | None = None
        for command, args in item.commands:
            path = which(command)
            if path is not None:
                found = (command, args, path)
                break
        command, args = item.commands[0] if found is None else found[:2]
        out.append(
            {
                "id": item.id,
                "name": item.name,
                "command": command,
                "args": list(args),
                "installed": found is not None,
                "path": None if found is None else found[2],
            }
        )
    return out
