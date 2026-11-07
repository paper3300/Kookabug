"""승격 거래를 자식 프로세스에서 한 번 한다 (M7 B4 실패 주입 — kill·대기).

    python -X utf8 promote_child.py <워크스페이스> <요청 JSON>

`KOOKABUG_FAULTS`(지점 `screens.stage`, 역할 supervisor)가 있으면 그 단계에서 죽거나 기다린다.
끝까지 가면 결과 JSON 한 줄을 찍고 0, 거부면 오류 코드를 찍고 3.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from kookabug_core.screen_promote import PromoteError, PromoteRequest, promote
from kookabug_sdk import _faults


def main() -> int:
    root = Path(sys.argv[1])
    request = PromoteRequest(**json.loads(sys.argv[2]))
    _faults.set_role("supervisor")
    try:
        result = promote(root, request)
    except PromoteError as exc:
        print(json.dumps({"error": exc.code}))
        return 3
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
