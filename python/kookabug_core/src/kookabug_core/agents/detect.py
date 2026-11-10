"""에이전트 감지 표 (M5 계획 3.12): 에이전트 패널·첫 설정 대화 상자의 "감지한 에이전트" 목록.

앱은 ACP로 말하는 명령만 띄운다. Claude Code·Codex 본체 CLI(`claude`·`codex`)는 ACP로 말하지 않아
어댑터가 따로 있어야 한다. 그래서 제품마다 세 가지를 본다.

1. 어댑터 명령이 `PATH`에 있으면 그것 (`via: "path"`)
2. 없고 본체 CLI와 `npx`가 있으면 고정 판 어댑터를 npx로 받아 띄운다 (`via: "npx"`).
   판을 고정해 어댑터 새 판이 몰래 들어오지 않게 하고, 판 올리기는 이 표를 고쳐서 한다
3. 둘 다 아니면 연결할 수 없다 (`installed: false`). 본체가 있는데 npx가 없으면 `cli_path`만 채운다

여기서는 찾기만 하고 설치하지 않는다(npx도 연결할 때 앱이 띄운다).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

__all__ = ["DETECT_TABLE", "Candidate", "detect"]


@dataclass(frozen=True, slots=True)
class Candidate:
    """감지 표의 줄 하나."""

    id: str
    name: str
    cli: str
    """본체 CLI 실행 파일 이름 (설치·로그인 여부 안내용)."""
    commands: tuple[tuple[str, tuple[str, ...]], ...]
    """`PATH`에 있으면 바로 쓰는 ACP 명령 후보 (실행 파일 이름, 인자). 앞에서부터 본다."""
    package: str | None = None
    """본체만 있을 때 npx로 받을 ACP 어댑터 (`이름@고정 판`)."""


DETECT_TABLE: Final = (
    Candidate(
        "claude-code",
        "Claude Code",
        "claude",
        (("claude-agent-acp", ()), ("claude-code-acp", ())),
        "@agentclientprotocol/claude-agent-acp@0.96.0",
    ),
    Candidate(
        "codex",
        "Codex CLI",
        "codex",
        (("codex-acp", ()),),
        "@agentclientprotocol/codex-acp@2.3.0",
    ),
    Candidate("gemini", "Gemini CLI", "gemini", (("gemini", ("--experimental-acp",)),)),
)


def detect(which: Callable[[str], str | None] | None = None) -> list[dict[str, Any]]:
    """표의 제품마다 한 줄: 연결에 쓸 명령·찾은 방법·본체 CLI 위치."""
    which = which or shutil.which
    npx: str | None = None
    npx_checked = False
    out: list[dict[str, Any]] = []
    for item in DETECT_TABLE:
        cli_path = which(item.cli)
        command, args = item.commands[0]
        path: str | None = None
        via: str | None = None
        for cmd, cmd_args in item.commands:
            found = which(cmd)
            if found is not None:
                command, args, path, via = cmd, cmd_args, found, "path"
                break
        if via is None and cli_path is not None and item.package is not None:
            if not npx_checked:
                npx, npx_checked = which("npx"), True
            if npx is not None:
                command, args, path, via = "npx", ("-y", item.package), npx, "npx"
        out.append(
            {
                "id": item.id,
                "name": item.name,
                "command": command,
                "args": list(args),
                "installed": via is not None,
                "path": path,
                "via": via,
                "cli": item.cli,
                "cli_path": cli_path,
                "package": item.package,
            }
        )
    return out
