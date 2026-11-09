"""`python -m sample_shop [--buy-moved | --buy-missing] [--title 제목] [--event-log FILE]`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sample_shop import TITLE
from sample_shop.app import Options, run
from sample_shop.render import FontMissing, font_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sample_shop", description="예제 상점 (Kookabug 검사용)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--buy-moved", action="store_true", help="구매 단추가 오른쪽 아래로 옮겨진다"
    )
    group.add_argument("--buy-missing", action="store_true", help="구매 단추가 없다")
    parser.add_argument("--title", default=TITLE)
    parser.add_argument("--event-log", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        font_file()
    except FontMissing as exc:
        print(str(exc), file=sys.stderr)
        return 3
    layout = "moved" if args.buy_moved else "missing" if args.buy_missing else "default"
    return run(Options(layout=layout, title=args.title, event_log=args.event_log))


if __name__ == "__main__":
    raise SystemExit(main())
