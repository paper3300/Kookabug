"""E2E 도우미: 앱이 저장한 그래프 파일을 Python 코어 규칙으로 본다 (M2 계획 T9 edit.spec.ts).

    python graph_check.py equal <그래프 파일> <기대 값 JSON 파일>
        파일 값과 기대 값이 `canonical.json_equal`로 같은가 → {"equal": bool}
    python graph_check.py types <그래프 파일> <JSON 포인터>...
        포인터 자리 값의 Python 타입 이름 → {"types": {포인터: "float" | "int" | ...}}

결과는 표준 출력 한 줄 JSON이다. 파일은 바이트로 읽어 `loads_strict`로 푼다 (로더와 같은 규칙).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from kookabug_core.canonical import json_equal, loads_strict


def _read(path: str) -> Any:
    return loads_strict(Path(path).read_bytes().decode("utf-8"))


def _at(value: Any, pointer: str) -> Any:
    for part in pointer.split("/")[1:]:
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def main(argv: list[str]) -> int:
    mode, path, *rest = argv
    if mode == "equal":
        expected = json.loads(Path(rest[0]).read_text("utf-8"))
        print(json.dumps({"equal": json_equal(_read(path), expected)}))
    elif mode == "types":
        value = _read(path)
        print(json.dumps({"types": {p: type(_at(value, p)).__name__ for p in rest}}))
    else:
        raise SystemExit(f"모르는 모드: {mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
