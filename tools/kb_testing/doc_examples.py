"""설계 문서의 ```json 예시 블록을 꺼낸다 (```jsonl 등 다른 언어 블록은 제외)."""

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
