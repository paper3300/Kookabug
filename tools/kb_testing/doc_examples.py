"""설계 문서의 ```json 예시 블록(`json_blocks`)과 ```jsonl 예시 줄(`jsonl_lines`)을 꺼낸다."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from kb_testing.packaging import REPO_ROOT

DOCS = {
    "schema": REPO_ROOT / "Docs" / "Design" / "그래프 JSON 스키마 v0.md",
    "workspace": REPO_ROOT / "Docs" / "Design" / "워크스페이스 구조.md",
}

_BLOCK = re.compile(r"^```json\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
_JSONL_BLOCK = re.compile(r"^```jsonl\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)


@dataclass(frozen=True)
class DocBlock:
    doc: str
    index: int
    line: int
    text: str

    @property
    def id(self) -> str:
        return f"{self.doc}#{self.index}"

    @property
    def data(self) -> Any:
        return json.loads(self.text)


def json_blocks() -> list[DocBlock]:
    blocks = []
    for doc, path in DOCS.items():
        content = path.read_text(encoding="utf-8")
        for index, m in enumerate(_BLOCK.finditer(content)):
            line = content.count("\n", 0, m.start(1)) + 1
            blocks.append(DocBlock(doc, index, line, m.group(1)))
    return blocks


def jsonl_lines() -> list[DocBlock]:
    """```jsonl 블록의 줄마다 하나 (`index`는 블록 번호, `line`은 문서 안 줄 번호)."""
    lines = []
    for doc, path in DOCS.items():
        content = path.read_text(encoding="utf-8")
        for index, m in enumerate(_JSONL_BLOCK.finditer(content)):
            first = content.count("\n", 0, m.start(1)) + 1
            for offset, text in enumerate(m.group(1).splitlines()):
                lines.append(DocBlock(doc, index, first + offset, text))
    return lines
