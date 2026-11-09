"""자동 채택·되돌리기·묶음 수락을 자식 프로세스에서 한 번 한다 (M8 B3 실패 주입 — kill).

    python -X utf8 adopt_child.py <워크스페이스> adopt|revert|accept <변경 또는 채택 ID>

`KOOKABUG_FAULTS`(지점 `filetx.stage`, 역할 supervisor)가 있으면 그 단계에서 죽는다. 끝까지 가면
결과 JSON 한 줄을 찍고 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers.adopt_rig import CASE, FakeVerifier

from kookabug_core import adopt as rules
from kookabug_daemon.adopt import Adopter
from kookabug_sdk import _faults


def main() -> int:
    _faults.set_role("supervisor")
    root, op, arg = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    if op == "adopt":
        result = Adopter(root, FakeVerifier()).request(CASE, arg)
    elif op == "revert":
        result = rules.revert(root, arg, by="human")
    else:
        result = rules.decide(root, changes=[arg], claims=[], accept=True, by="human")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
