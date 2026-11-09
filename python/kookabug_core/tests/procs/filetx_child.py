"""`filetx` 검사용 거래(또는 복구)를 자식 프로세스에서 한 번 한다 (M8 B1 실패 주입 — kill).

    python -X utf8 filetx_child.py <워크스페이스> [recover]

`KOOKABUG_FAULTS`(지점 `filetx.stage`, 역할 supervisor)가 있으면 그 단계에서 죽는다. 끝까지 가면
결과 JSON 한 줄을 찍고 0. `recover`면 거래 대신 잠금 + 복구만 한다(복구 중 종료 검사).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers.filetx_case import run_tx

from kookabug_core import filetx
from kookabug_sdk import _faults


def main() -> int:
    _faults.set_role("supervisor")
    root = Path(sys.argv[1])
    if sys.argv[2:] == ["recover"]:
        with filetx.file_lock(root):
            print(json.dumps(filetx.recover(root), ensure_ascii=False))
        return 0
    print(json.dumps(run_tx(root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
