"""`kookabug-sdk` 명령."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from kookabug_sdk.build import BuildError, build


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kookabug-sdk", description="Kookabug 노드 SDK")
    commands = parser.add_subparsers(dest="command", required=True)
    build_cmd = commands.add_parser("build", help="노드 스키마 JSON을 만든다")
    build_cmd.add_argument("project", nargs="?", default=".", help="플러그인 프로젝트 폴더")
    args = parser.parse_args(argv)

    if args.command == "build":
        try:
            out = build(args.project)
        except BuildError as exc:
            for problem in exc.problems:
                print(f"오류: {problem}", file=sys.stderr)
            return 1
        print(f"{out.path} ({len(out.document['nodes'])}개 노드)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
