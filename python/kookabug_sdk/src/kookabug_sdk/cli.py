"""`kookabug-sdk` 명령."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from kookabug_sdk.build import BuildError, build
from kookabug_sdk.console import utf8_stdio
from kookabug_sdk.new import NewProjectError, create_project


def main(argv: Sequence[str] | None = None) -> int:
    utf8_stdio()
    parser = argparse.ArgumentParser(prog="kookabug-sdk", description="Kookabug 노드 SDK")
    commands = parser.add_subparsers(dest="command", required=True)
    build_cmd = commands.add_parser("build", help="노드 스키마 JSON을 만든다")
    build_cmd.add_argument("project", nargs="?", default=".", help="플러그인 프로젝트 폴더")
    new_cmd = commands.add_parser("new", help="플러그인 프로젝트 틀을 만든다")
    new_cmd.add_argument("folder", help="만들 폴더 (없거나 비어 있어야 한다)")
    new_cmd.add_argument("--id", required=True, help="플러그인 ID (소문자·숫자·밑줄)")
    new_cmd.add_argument("--title", help="표시 이름")
    new_cmd.add_argument("--ui", action="store_true", help="인스펙터 위젯 예제를 넣는다")
    args = parser.parse_args(argv)

    if args.command == "build":
        try:
            out = build(args.project)
        except BuildError as exc:
            for problem in exc.problems:
                print(f"오류: {problem}", file=sys.stderr)
            return 1
        print(f"{out.path} ({len(out.document['nodes'])}개 노드)")
    elif args.command == "new":
        try:
            written = create_project(args.folder, args.id, title=args.title, ui=args.ui)
        except (NewProjectError, BuildError) as exc:
            print(f"오류: {exc}", file=sys.stderr)
            return 1
        for path in written:
            print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
