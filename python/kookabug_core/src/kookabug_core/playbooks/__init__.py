"""플레이북 (M8 계획 3.10) — 설치본에 함께 배포하는 `agent-job` 지시문.

- 파일: 이 패키지의 `<이름>.md`. 머리말(`---` 사이)은 `format: kookabug.playbook/0`, `name`,
  `version`(제품과 함께 바뀌는 판, 정수), `tools`(필요한 툴셋, 작업 허용 범위가 된다)
- 워크스페이스로 복사하지 않고 위키·지식에서 만들지 않는다(KB문서 3장 7 "지식은 지시가 아니다").
  이름은 허용 목록(`NAMES`)만 읽는다 — 경로 조각으로 다른 파일을 읽을 수 없다
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from typing import Final

__all__ = ["FORMAT", "NAMES", "Playbook", "PlaybookError", "load", "versions"]

FORMAT: Final = "kookabug.playbook/0"
NAMES: Final = ("init", "followup", "triage", "repair", "explore", "author", "lint", "probe")
"""배포하는 플레이북 이름 (허용 목록)."""
_TOOLSETS: Final = frozenset(
    {"core", "graph_edit", "run", "observe", "control", "screens", "knowledge", "cases"}
)
_HEAD: Final = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


class PlaybookError(Exception):
    """없는 이름이거나 배포 파일 형식이 틀렸다."""


@dataclass(frozen=True, slots=True)
class Playbook:
    name: str
    version: int
    tools: tuple[str, ...]
    body: str


def _parse(name: str, text: str) -> Playbook:
    match = _HEAD.match(text)
    if match is None:
        raise PlaybookError(f"플레이북 {name}에 머리말이 없다")
    head: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            raise PlaybookError(f"플레이북 {name} 머리말 줄이 틀렸다: {line!r}")
        head[key.strip()] = value.strip()
    if head.get("format") != FORMAT or head.get("name") != name:
        raise PlaybookError(f"플레이북 {name}의 format·name이 틀렸다")
    try:
        version = int(head["version"])
    except KeyError, ValueError:
        raise PlaybookError(f"플레이북 {name}의 version이 정수가 아니다") from None
    tools = tuple(t.strip() for t in head.get("tools", "").strip("[]").split(",") if t.strip())
    if "core" not in tools or not set(tools) <= _TOOLSETS:
        raise PlaybookError(f"플레이북 {name}의 tools가 틀렸다: {tools}")
    return Playbook(name, version, tools, text[match.end() :].strip() + "\n")


def load(name: str) -> Playbook:
    """배포된 플레이북 하나. 허용 목록 밖 이름이면 `PlaybookError`."""
    if name not in NAMES:
        raise PlaybookError(f"모르는 플레이북이다: {name!r} (있는 것: {', '.join(NAMES)})")
    text = resources.files(__name__).joinpath(f"{name}.md").read_text(encoding="utf-8")
    return _parse(name, text)


def versions() -> dict[str, int]:
    """`{이름: 판}` (`kb_project_info`·`agent-job playbooks`)."""
    return {name: load(name).version for name in NAMES}
