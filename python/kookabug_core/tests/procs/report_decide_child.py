"""`report.decide` 한 번을 자식 프로세스에서 한다 (M8 B5 — 거래 중단 kill 검사).

    python -X utf8 report_decide_child.py <워크스페이스> <작업> <묶음 키> accept|reject

`KOOKABUG_FAULTS`(지점 `filetx.stage`, 역할 supervisor)가 있으면 그 단계에서 죽는다. 끝까지 가면
결과 JSON 한 줄을 찍고 0. daemon의 `report.decide`와 같은 조합(코어 `adopt.decide` + 보고 결정을
같은 거래에)이다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from kookabug_core import adopt as rules
from kookabug_core.agent_job import report as reports
from kookabug_sdk import _faults


def main() -> int:
    _faults.set_role("supervisor")
    root, job, group, decision = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]

    def apply(changes: list[str], accept: bool, also: Any) -> Any:
        return rules.decide(root, changes=changes, claims=[], accept=accept, by="cli", also=also)

    done = reports.decide(root, job, group, decision, apply=apply)
    print(json.dumps(done, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
