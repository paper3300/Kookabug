"""`kookabug screen test` (구현 계획 M1 2.10·2.11).

    kookabug screen test <화면 ID|*.screen.json> (--window 제목 | --hwnd N | --image PNG)
                         [--workspace DIR] [--json]

화면 판정 파일의 조건(`detect.all`·`detect.none`)을 프레임 한 장에서 보고 조건별 결과를 출력한다.
종료 코드 `0` 그 화면이 맞음, `1` 아님, `6` 사용법·환경 오류(없는·모호한 화면 ID, 파일 형식,
target 오류, 창 없음 포함).

화면 ID는 워크스페이스(`--workspace` 또는 현재 폴더에서 위로)의 `screens/`에서 찾는다(`_explored/`
제외). 파일 경로를 주면 그 파일에서 위로 워크스페이스를 찾는다 — 조건의 `$target`이 워크스페이스
루트 기준 경로이기 때문이다.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from kookabug_cli.target_cmd import (
    EXIT_FOUND,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    SourceError,
    load_frame,
    result_json,
)
from kookabug_core.screens import SUFFIX, ScreenDef, ScreenFileError, read_screen_file, screen_index
from kookabug_core.workspace import Workspace, WorkspaceError
from kookabug_platform.errors import PlatformError
from kookabug_platform.screens import ScreenResult, evaluate_screen
from kookabug_platform.vision import TargetFileError, Vision, load_target_file
from kookabug_sdk.types import Target

__all__ = ["ScreenError", "find_screen", "run"]


class ScreenError(Exception):
    """화면을 찾거나 읽을 수 없다. 종료 코드 6."""


def find_screen(
    name: str, workspace: str | None, cwd: Path | None = None
) -> tuple[Workspace, ScreenDef]:
    """화면 ID 또는 파일 경로 → (워크스페이스, 화면)."""
    here = Path.cwd() if cwd is None else cwd
    try:
        if name.endswith(SUFFIX):
            path = (here / name).resolve()
            if not path.is_file():
                raise ScreenError(f"화면 파일이 없다: {name}")
            ws = Workspace.open(here / workspace) if workspace else Workspace.find(path.parent)
            rel = ws.relative(path)
            if rel is None:
                raise ScreenError(f"{path}은(는) 워크스페이스 {ws.root} 밖이다")
            return ws, read_screen_file(path, rel)
        ws = Workspace.open(here / workspace) if workspace else Workspace.find(here)
    except WorkspaceError as exc:
        raise ScreenError(str(exc)) from exc
    except ScreenFileError as exc:
        raise ScreenError(str(exc)) from exc
    paths = screen_index(ws).get(name, [])
    if not paths:
        raise ScreenError(f"화면 '{name}'이(가) {ws.root / 'screens'}에 없다 (_explored/ 제외)")
    if len(paths) > 1:
        raise ScreenError(f"화면 '{name}' 파일이 여러 개다 (screen_ambiguous): {', '.join(paths)}")
    resolved = ws.resolve(paths[0])
    assert resolved is not None
    try:
        return ws, read_screen_file(resolved, paths[0])
    except ScreenFileError as exc:
        raise ScreenError(str(exc)) from exc


def _loader(ws: Workspace) -> Callable[[str], Target]:
    cache: dict[str, Target] = {}

    def load(rel: str) -> Target:
        if rel not in cache:
            path = ws.resolve(rel)
            if path is None:
                raise TargetFileError(f"target 경로 '{rel}'이(가) 워크스페이스 경로가 아니다")
            target = load_target_file(path)
            cache[rel] = Target(name=rel, path=target.path, spec=target.spec)
        return cache[rel]

    return load


def run(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    report: dict[str, Any] = {"command": "screen test", "screen": args.screen}

    def finish(code: int, error: str | None = None, error_code: str | None = None) -> int:
        report.update(exit_code=code, error=error, error_code=error_code)
        if args.json:
            print(json.dumps(report, ensure_ascii=False), file=out)
        elif error is not None:
            print(f"오류: {error}", file=err)
        return code

    try:
        ws, screen = find_screen(args.screen, args.workspace)
        report.update(id=screen.id, path=screen.path, title=screen.title, workspace=str(ws.root))
        frame = load_frame(args)
        report["source"] = frame.source
        result = evaluate_screen(screen, _loader(ws), frame.pixels, frame.meta, Vision())
    except (ScreenError, TargetFileError) as exc:
        return finish(EXIT_USAGE, str(exc))
    except (SourceError, PlatformError) as exc:
        return finish(EXIT_USAGE, str(exc), exc.code)

    report["matched"] = result.matched
    report["conditions"] = [
        {
            "kind": c.kind,
            "target": c.target,
            "visible": c.found,
            "ok": c.ok,
            **result_json(c.result),
        }
        for c in result.conditions
    ]
    if not args.json:
        _print_human(result, out)
    return finish(EXIT_FOUND if result.matched else EXIT_NOT_FOUND)


def _print_human(result: ScreenResult, out: TextIO) -> None:
    screen = result.screen
    name = f"{screen.id} ({screen.title})" if screen.title else screen.id
    print(f"화면 {name}: {'맞음' if result.matched else '아님'}", file=out)
    for c in result.conditions:
        best = c.result.best
        score = "-" if best is None else f"{best.score:.3f}"
        want = "보여야 함" if c.kind == "all" else "안 보여야 함"
        seen = "보임" if c.found else "안 보임"
        print(
            f"  [{'맞음' if c.ok else '틀림'}] {c.kind} {c.target}: {want}, {seen} (점수 {score})",
            file=out,
        )
    out.flush()
