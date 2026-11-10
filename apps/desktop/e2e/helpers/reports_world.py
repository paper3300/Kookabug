"""보고함 E2E 준비 (M8 B7): B6 시나리오와 같은 예제 상점 워크스페이스와 가짜 게임 사양을 만든다.

    python reports_world.py <임시 폴더> <moved|missing>   → 표준 출력 {"root", "platform"}

보고 JSON은 만들지 않는다 — 검사가 실제 `kookabug agent-job run`(가짜 QA CLI 각본)으로 만든다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from kb_testing.fake_game import make_fake_game
from kb_testing.sample_game import EXAMPLE_LOCAL


def main() -> int:
    tmp = Path(sys.argv[1])
    variant = sys.argv[2]
    game = make_fake_game(tmp, scenario="shop", variant=variant, permissions={"preset": "curator"})
    local = game.root / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["settings"] = dict(EXAMPLE_LOCAL)  # 사람마다 다른 실행 설정 (가짜 플랫폼은 띄우지 않는다)
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"root": str(game.root), "platform": str(game.platform)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
