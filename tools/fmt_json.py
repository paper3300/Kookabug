"""레포가 관리하는 JSON을 canonical 형식으로 맞춘다.

대상: `packages/schema/*.schema.json`,
설계 문서(`kb_testing.doc_examples.DOCS`)의 ```json 예시 블록.

    uv run python tools/fmt_json.py          # 고친다
    uv run python tools/fmt_json.py --check  # 다르면 실패 (값은 바꾸지 않는다)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from kb_testing.doc_examples import DOCS
from kookabug_core.canonical import canonical_dumps
from kookabug_sdk.console import utf8_stdio

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "packages" / "schema"
_BLOCK = re.compile(r"(^```json\n)(.*?)(^```[ \t]*$)", re.MULTILINE | re.DOTALL)


def formatted(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return canonical_dumps(json.loads(text))
    return _BLOCK.sub(lambda m: m[1] + canonical_dumps(json.loads(m[2])) + m[3], text)


def targets() -> list[Path]:
    return sorted(SCHEMA_DIR.glob("*.schema.json")) + list(DOCS.values())


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    parser = argparse.ArgumentParser(description="JSON을 canonical 형식으로")
    parser.add_argument("--check", action="store_true", help="쓰지 않고 차이만 확인")
    args = parser.parse_args(argv)
    stale = [p for p in targets() if formatted(p) != p.read_text(encoding="utf-8")]
    for path in stale:
        if args.check:
            print(f"canonical 형식이 아니다: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        else:
            path.write_bytes(formatted(path).encode("utf-8"))
    return 1 if args.check and stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
