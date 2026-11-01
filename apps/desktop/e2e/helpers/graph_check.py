"""E2E 도우미: 앱이 저장한 파일을 Python 코어 규칙으로 본다 (M2 계획 T9 edit.spec.ts, T14 인수).

    python graph_check.py equal <그래프 파일> <기대 값 JSON 파일>
        파일 값과 기대 값이 `canonical.json_equal`로 같은가 → {"equal": bool}
    python graph_check.py types <그래프 파일> <JSON 포인터>...
        포인터 자리 값의 Python 타입 이름 → {"types": {포인터: "float" | "int" | ...}}
    python graph_check.py diagnostics <워크스페이스 루트> <그래프 상대 경로>
        디스크 파일의 실행 전 검증 진단 (`validate.check_graph`)
        → {"diagnostics": [[severity, code, node, pointer], ...]}
    python graph_check.py find <target 파일> <PNG 파일>
        저장한 target 파일을 다시 읽어 그 PNG에서 찾은 상자 (runner와 같은 매칭)
        → {"rect": [x, y, w, h] | null}

결과는 표준 출력 한 줄 JSON이다. 그래프는 바이트로 읽어 `loads_strict`로 푼다 (로더와 같은 규칙).
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


def _diagnostics(root: str, rel: str) -> list[list[str | None]]:
    from kookabug_core.validate import check_graph
    from kookabug_core.workspace import Workspace

    _, found = check_graph(Workspace.open(root), rel)
    return [[d.severity, d.code, d.node, d.pointer] for d in found]


def _find(target: str, png: str) -> list[int] | None:
    from kookabug_platform.frames import decode_image
    from kookabug_platform.vision import FrameMeta, Vision, load_target_file

    spec = load_target_file(Path(target))
    pixels = decode_image(Path(png).read_bytes())
    match = Vision().find(pixels, FrameMeta.of_image(pixels), spec).match
    return None if match is None else list(match.rect)


def main(argv: list[str]) -> int:
    mode, path, *rest = argv
    if mode == "equal":
        expected = json.loads(Path(rest[0]).read_text("utf-8"))
        print(json.dumps({"equal": json_equal(_read(path), expected)}))
    elif mode == "types":
        value = _read(path)
        print(json.dumps({"types": {p: type(_at(value, p)).__name__ for p in rest}}))
    elif mode == "diagnostics":
        print(json.dumps({"diagnostics": _diagnostics(path, rest[0])}, ensure_ascii=False))
    elif mode == "find":
        print(json.dumps({"rect": _find(path, rest[0])}))
    else:
        raise SystemExit(f"모르는 모드: {mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
