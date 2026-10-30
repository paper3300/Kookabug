"""헤드리스 장면 전이 표 `frames/scenario.json`을 게임 코드에서 다시 만든다.

    uv run python fixtures/sample-game/tools/gen_scenario.py          # 쓴다
    uv run python fixtures/sample-game/tools/gen_scenario.py --check  # 커밋된 것과 다르면 실패

상태 기계(`sample_game.flow`)나 버튼 배치(`sample_game.layout`)를 바꾸면 다시 만든다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

GAME_DIR = Path(__file__).resolve().parents[1]
SCENARIO = GAME_DIR / "frames" / "scenario.json"
sys.path.insert(0, str(GAME_DIR))

from kookabug_core.canonical import canonical_dumps  # noqa: E402
from sample_game.scenario import generate  # noqa: E402


def render() -> str:
    return canonical_dumps(generate())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="헤드리스 장면 전이 표를 다시 만든다")
    parser.add_argument("--check", action="store_true", help="쓰지 않고 다르면 종료 코드 1")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        current = SCENARIO.read_text(encoding="utf-8") if SCENARIO.exists() else ""
        if current != text:
            print(f"{SCENARIO}가 게임 코드와 다르다. 이 스크립트로 다시 만든다", file=sys.stderr)
            return 1
        return 0
    SCENARIO.parent.mkdir(parents=True, exist_ok=True)
    SCENARIO.write_text(text, encoding="utf-8", newline="\n")
    print(SCENARIO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
