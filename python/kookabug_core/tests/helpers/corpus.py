"""그래프 원문 말뭉치 (`fixtures/graph-corpus/corpus.json`)와 전송 코덱을 Node로 부르는 도우미."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from kb_testing.packaging import REPO_ROOT

CORPUS_DIR = REPO_ROOT / "fixtures" / "graph-corpus"
SAMPLE_WORKSPACE = REPO_ROOT / "fixtures" / "sample-game" / "workspace"
WIRE_TS = REPO_ROOT / "packages" / "schema" / "src" / "wire.ts"
WIRE_NODE = Path(__file__).with_name("wire_node.mjs")


def corpus_files() -> list[Path]:
    data = json.loads((CORPUS_DIR / "corpus.json").read_text(encoding="utf-8"))
    return [REPO_ROOT / rel for rel in data["files"]]


def corpus_id(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix().removeprefix("fixtures/")


def node_executable() -> str:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node 24가 PATH에 없다 (전송 코덱 검사는 실제 JS로 돈다)")
    return node


def through_js(texts: list[str], mode: str = "wire") -> list[dict[str, Any]]:
    """JSON 텍스트마다 Node에서 `JSON.parse` → `wireStringify`(mode "wire") 또는 `JSON.stringify`.

    결과는 `{"ok": 텍스트}` 또는 `{"error": 이름·메시지, "pointer": JSON 포인터}`.
    """
    proc = subprocess.run(
        [node_executable(), str(WIRE_NODE), mode, str(WIRE_TS)],
        input=json.dumps(texts).encode("ascii"),
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return json.loads(proc.stdout.decode("utf-8"))
