"""`kookabug screen test`·`kookabug screen list` (구현 계획 M1 2.10·2.11, M7 계획 3.10).

    kookabug screen test <화면 ID|*.screen.json> (--window 제목 | --hwnd N | --image PNG)
                         [--workspace DIR] [--json]
    kookabug screen list [--explored] [--workspace DIR] [--json]
    kookabug screen promote <세션>/<키> [--id ID] [--merge] [--replace-shot] [--replace-detect]
                            [--folder F] [--title T] [--workspace DIR] [--json]

`test`는 화면 판정 파일의 조건(`detect.all`·`detect.none` — target과 OCR 조건)을 프레임 한 장에서
보고 조건별 결과를 출력한다. 종료 코드 `0` 그 화면이 맞음, `1` 아님, `3` 판정 불가(확인하지 않은
조건만 남음 — 아래, 또는 판정 조건이 없는 후보), `6` 사용법·환경 오류(없는·모호한 화면 ID, 파일
형식, target 오류, OCR 모델 없음, 창 없음 포함). OCR 조건은 읽은 글자 앞 40자를 같이 보인다(사람이
조건을 고칠 때 쓴다).

`KOOKABUG_AGENT`(에이전트가 부른 CLI)면 OCR 조건을 **평가하지 않는다**(엔진을 만들지도 않는다). 이
경로는 민감 target·비밀 입력 창 보호 판정(M7 3.5a)을 거치지 않으므로, 읽은 글자뿐 아니라 일치
여부·종료 코드도 보호된 글자를 맞히는 통로가 된다. 에이전트의 OCR 조건 판정은 daemon
`screens.identify`만 한다.

화면 ID는 워크스페이스(`--workspace` 또는 현재 폴더에서 위로)의 `screens/`에서 찾는다(`_explored/`
제외). 파일 경로를 주면 그 파일에서 위로 워크스페이스를 찾는다 — 조건의 `$target`이 워크스페이스
루트 기준 경로이기 때문이다.

`list`는 `screens/`의 화면(ID·제목·경로, 읽지 못한 파일은 이유)을, `--explored`면
`screens/_explored/<세션>/`의 탐색 결과 후보(사람 확인 전)도 보인다.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TextIO, cast

from kookabug_cli.target_cmd import (
    EXIT_FOUND,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    SourceError,
    load_frame,
    result_json,
)
from kookabug_core.screens import (
    SUFFIX,
    ExploredCandidate,
    ScreenDef,
    ScreenFileError,
    explored_candidates,
    read_screen_file,
    screen_index,
)
from kookabug_core.workspace import Workspace, WorkspaceError
from kookabug_platform.errors import PlatformError
from kookabug_platform.screens import ConditionResult, ScreenResult, TextReader, evaluate_screen
from kookabug_platform.vision import TargetFileError, Vision, load_target_file
from kookabug_sdk.types import Target

__all__ = ["ScreenError", "find_screen", "run"]

AGENT_ENV = "KOOKABUG_AGENT"
"""`kookabug_core.service.AGENT_ENV`와 같은 이름 (service는 실행 관리까지 읽어 무겁다)."""
EXIT_UNKNOWN = 3
"""판정 불가: 틀린 조건은 없지만 확인하지 않은 조건이 있거나 조건이 없다."""


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
        ws = _workspace(workspace, here)
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


def _workspace(workspace: str | None, here: Path) -> Workspace:
    return Workspace.open(here / workspace) if workspace else Workspace.find(here)


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


def _reader(ws: Workspace) -> TextReader:
    """`kookabug.json` `ocr` 설정의 엔진 (실행기와 같은 규칙: `engine` 기본 rapidocr, 나머지는
    엔진 설정). 모델이 없으면 첫 읽기에서 `PlatformError`(ocr_model_missing)."""
    from kookabug_platform.ocr.engine import Ocr, create_engine

    block = ws.config.get("ocr")
    options = dict(cast(Mapping[str, Any], block)) if isinstance(block, dict) else {}
    engine = str(options.pop("engine", "rapidocr"))
    try:
        return Ocr(create_engine(engine, options))
    except ValueError as exc:
        raise ScreenError(f"kookabug.json ocr 설정: {exc}") from exc


def run(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    if args.action == "list":
        return _run_list(args, out, err)
    if args.action == "protect":
        return _run_protect(args, out, err)
    if args.action == "promote":
        return _run_promote(args, out, err)
    if args.action == "recover":
        return _run_recover(args, out, err)
    report: dict[str, Any] = {"command": "screen test", "screen": args.screen}

    def finish(code: int, error: str | None = None, error_code: str | None = None) -> int:
        report.update(exit_code=code, error=error, error_code=error_code)
        if args.json:
            print(json.dumps(report, ensure_ascii=False), file=out)
        elif error is not None:
            print(f"오류: {error}", file=err)
        return code

    human = AGENT_ENV not in os.environ
    try:
        ws, screen = find_screen(args.screen, args.workspace)
        report.update(id=screen.id, path=screen.path, title=screen.title, workspace=str(ws.root))
        frame = load_frame(args)
        report["source"] = frame.source
        # 에이전트면 OCR 조건을 평가하지 않는다 (보호 판정 없는 경로 — 모듈 설명)
        has_ocr = human and any(c.ocr is not None for c in screen.detect())
        result = evaluate_screen(
            screen,
            _loader(ws),
            frame.pixels,
            frame.meta,
            Vision(),
            ocr=_reader(ws) if has_ocr else None,
            reveal_text=human,
        )
    except (ScreenError, TargetFileError) as exc:
        return finish(EXIT_USAGE, str(exc))
    except (SourceError, PlatformError) as exc:
        return finish(EXIT_USAGE, str(exc), exc.code)

    report["matched"] = result.matched
    report["state"] = result.state
    report["conditions"] = [_condition_json(c) for c in result.conditions]
    if not human and any(c.ocr is not None for c in result.conditions):
        report["ocr_skipped"] = "agent"
    if not args.json:
        _print_human(result, out, ocr_skipped="ocr_skipped" in report)
    codes = {"matched": EXIT_FOUND, "not_matched": EXIT_NOT_FOUND, "unknown": EXIT_UNKNOWN}
    return finish(codes[result.state])


def _condition_json(c: ConditionResult) -> dict[str, Any]:
    if c.ocr is None:
        assert c.result is not None
        return {
            "kind": c.kind,
            "condition": "image",
            "target": c.target,
            "visible": c.found,
            "ok": c.ok,
            **result_json(c.result),
        }
    entry: dict[str, Any] = {
        "kind": c.kind,
        "condition": "ocr",
        "rect": list(c.ocr.rect),
        "text": c.ocr.text,
        "region": None if c.region is None else list(c.region),
        "visible": c.found,
        "ok": c.ok,
    }
    if c.read is not None:
        entry["read"] = c.read
    return entry


def _print_human(result: ScreenResult, out: TextIO, *, ocr_skipped: bool = False) -> None:
    screen = result.screen
    name = f"{screen.id} ({screen.title})" if screen.title else screen.id
    verdict = {"matched": "맞음", "not_matched": "아님", "unknown": "판정 불가"}[result.state]
    print(f"화면 {name}: {verdict}", file=out)
    if not result.conditions:
        print("  판정 조건이 없다 (탐색 후보)", file=out)
    if ocr_skipped:
        print(
            "  에이전트가 부른 CLI는 OCR 조건을 보지 않는다 (kb_screen_identify를 쓴다)", file=out
        )
    for c in result.conditions:
        mark = {True: "맞음", False: "틀림", None: "모름"}[c.ok]
        if c.ocr is None:
            assert c.result is not None
            best = c.result.best
            score = "-" if best is None else f"{best.score:.3f}"
            want = "보여야 함" if c.kind == "all" else "안 보여야 함"
            seen = "보임" if c.found else "안 보임"
            line = f"{c.kind} {c.target}: {want}, {seen} (점수 {score})"
        else:
            want = "들어 있어야 함" if c.kind == "all" else "없어야 함"
            seen = {True: "들어 있음", False: "없음", None: "읽지 않음"}[c.found]
            read = "" if c.read is None else f" (읽음 {json.dumps(c.read, ensure_ascii=False)})"
            text = json.dumps(c.ocr.text, ensure_ascii=False)
            line = f"{c.kind} OCR {text} {list(c.region or ())}: {want}, {seen}{read}"
        print(f"  [{mark}] {line}", file=out)
    out.flush()


# ---------------------------------------------------------------- list


def _run_list(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    try:
        ws = _workspace(args.workspace, Path.cwd())
    except WorkspaceError as exc:
        if args.json:
            report = {"command": "screen list", "exit_code": EXIT_USAGE, "error": str(exc)}
            print(json.dumps(report, ensure_ascii=False), file=out)
        else:
            print(f"오류: {exc}", file=err)
        return EXIT_USAGE
    screens: list[dict[str, Any]] = []
    for sid, paths in sorted(screen_index(ws).items()):
        for rel in paths:
            entry: dict[str, Any] = {"id": sid, "path": rel}
            if len(paths) > 1:
                entry["problem"] = "같은 ID의 파일이 여러 개다 (screen_ambiguous)"
            path = ws.resolve(rel)
            assert path is not None
            try:
                screen = read_screen_file(path, rel)
            except ScreenFileError as exc:
                entry["problem"] = str(exc)
            else:
                if screen.title is not None:
                    entry["title"] = screen.title
            screens.append(entry)
    report: dict[str, Any] = {
        "command": "screen list",
        "workspace": str(ws.root),
        "screens": screens,
    }
    if args.explored:
        report["explored"] = [_candidate_json(c) for c in explored_candidates(ws)]
    report["exit_code"] = 0
    if args.json:
        print(json.dumps(report, ensure_ascii=False), file=out)
    else:
        _print_list(report, out)
    return 0


def _candidate_json(candidate: ExploredCandidate) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "session": candidate.session,
        "key": candidate.key,
        "path": candidate.path,
        "placement": candidate.placement,
        "promotable": candidate.promotable,
    }
    if candidate.problem is not None:
        entry["problem"] = candidate.problem
    screen = candidate.screen
    if screen is None:
        return entry
    if screen.title is not None:
        entry["title"] = screen.title
    if screen.of is not None:
        entry["of"] = screen.of
    elif screen.incomplete:
        entry["incomplete"] = True
    return entry


def _print_list(report: Mapping[str, Any], out: TextIO) -> None:
    screens: list[dict[str, Any]] = report["screens"]
    print(f"화면 {len(screens)}개", file=out)
    for s in screens:
        note = f" — {s['problem']}" if "problem" in s else ""
        print(f"  {s['id']}  {s.get('title', '')}  {s['path']}{note}", file=out)
    explored: list[dict[str, Any]] | None = report.get("explored")
    if explored is not None:
        print(f"탐색 결과 (확인 전) {len(explored)}개", file=out)
        for c in explored:
            if "problem" in c:
                note = f" — {c['problem']}"
            elif "of" in c:
                note = f" (합칠 화면 {c['of']})"
            else:
                note = " (판정 조건 없음)" if c.get("incomplete") else ""
            name = c["path"] if c["placement"] == "misplaced" else f"{c['session']}/{c['key']}"
            print(f"  {name}  {c.get('title', '')}{note}", file=out)
    out.flush()


# ---------------------------------------------------------------- protect (M7 R1)

EXIT_DENIED = 5


def _run_protect(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    """`screen protect --clear-keys`: 저장 글자 검사의 비밀값 키 목록을 비운다 (사람만, daemon이
    꺼져 있을 때 — daemon 잠금을 쥔 채 바꾼다). 기록 파일이 손상됐으면 바꾸지 않는다(사람이 직접
    고치거나 지운다). 창 보호 기록은 그대로 둔다."""
    import json as _json

    from kookabug_core.documents import DocumentError, write_atomic
    from kookabug_daemon.frame_guard import FILE, ProtectFileError, parse_protect_file
    from kookabug_daemon.session import DaemonLock, LockBusy

    def finish(code: int, text: str, **extra: Any) -> int:
        if args.json:
            body = {"command": "screen protect", "exit_code": code, "message": text, **extra}
            print(_json.dumps(body, ensure_ascii=False), file=out)
        else:
            print(text, file=out if code == 0 else err)
        return code

    if AGENT_ENV in os.environ:
        return finish(EXIT_DENIED, "보호 기록은 사람만 바꾼다 (KOOKABUG_AGENT)")
    try:
        ws = _workspace(args.workspace, Path.cwd())
    except WorkspaceError as exc:
        return finish(EXIT_USAGE, f"오류: {exc}")
    path = ws.root.joinpath(*FILE.split("/"))
    try:
        lock = DaemonLock.acquire(ws.root)
    except LockBusy:
        return finish(EXIT_USAGE, "daemon이 돌고 있다 — 앱·daemon을 끈 뒤 다시 한다")
    except OSError as exc:
        return finish(EXIT_USAGE, f"오류: {exc}")
    with lock:
        if not path.exists():
            return finish(0, "보호 기록이 없다 (지울 키 없음)", cleared=0)
        raw = path.read_bytes()
        try:
            keys, _records = parse_protect_file(raw)
        except ProtectFileError as exc:
            return finish(
                EXIT_USAGE, f"보호 기록 파일이 손상됐다 — 직접 확인해 고치거나 지운다: {exc}"
            )
        body = _json.loads(raw.decode("utf-8"))
        body["secret_keys"] = []
        try:
            write_atomic(path, _json.dumps(body, ensure_ascii=False, indent=1).encode("utf-8"))
        except DocumentError as exc:
            return finish(EXIT_USAGE, f"오류: {exc}")
    return finish(0, f"비밀값 키 {len(keys)}개를 지웠다 (창 보호 기록은 그대로)", cleared=len(keys))


# ---------------------------------------------------------------- promote (M7 3.7·3.10)

EXIT_REFUSED = 1
"""승격하지 않았다 (이미 있는 ID·판정 조건 없음·바뀜·잠금 사용 중 등)."""


def _run_promote(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    """`screen promote <세션>/<키>`: 탐색 후보를 확정 화면으로 옮기거나 합친다 (사람만). daemon과
    같은 잠금·거래(`kookabug_core.screen_promote`)를 쓴다. 확인(check)으로 받은 revision 그대로
    승격하므로 그 사이 바뀌면 `revision_conflict`. 시작 때 남은 거래를 복구한다."""
    from kookabug_core.screen_promote import PromoteError, PromoteRequest, check, promote
    from kookabug_sdk import _faults

    report: dict[str, Any] = {"command": "screen promote", "candidate": args.candidate}

    def finish(code: int, text: str, **extra: Any) -> int:
        report.update(exit_code=code, message=text, **extra)
        if args.json:
            print(json.dumps(report, ensure_ascii=False), file=out)
        else:
            print(text, file=out if code == 0 else err)
        return code

    if AGENT_ENV in os.environ:
        return finish(EXIT_DENIED, "승격은 사람만 한다 (KOOKABUG_AGENT)", error_code="agent_only")
    session, _, key = str(args.candidate).replace("\\", "/").partition("/")
    if not session or not key:
        return finish(EXIT_USAGE, "후보는 <세션 ID>/<키> 형식이다", error_code="usage")
    try:
        ws = _workspace(args.workspace, Path.cwd())
    except WorkspaceError as exc:
        return finish(EXIT_USAGE, f"오류: {exc}")
    _faults.set_role("supervisor")  # 검사의 실패 주입 (규칙이 없으면 아무것도 안 함)
    request = PromoteRequest(
        session=session,
        key=key,
        mode="merge" if args.merge else "new",
        id=args.id,
        title=args.title,
        folder=args.folder,
        replace_shot=args.replace_shot,
        replace_detect=args.replace_detect,
    )
    try:
        checked = check(ws.root, request)
        if not checked["ok"]:
            return finish(
                EXIT_REFUSED,
                "승격하지 않았다: " + "; ".join(checked["problems"]),
                error_code=checked.get("code"),
                warnings=checked["warnings"],
            )
        result = promote(ws.root, _with_revisions(request, checked["revisions"]))
    except PromoteError as exc:
        return finish(EXIT_REFUSED, f"승격하지 않았다: {exc.message}", error_code=exc.code)
    report.update(result)
    text = f"{session}/{key} → {result['path']}"
    if result["cleanup_pending"]:
        text += " (마무리는 다음 화면 지도 작업 때 끝난다)"
    for warning in result["warnings"]:
        text += f"\n  경고: {warning}"
    return finish(0, text)


def _run_recover(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    """`screen recover [--show]`: 남은 승격 거래 저널을 복구하고(기본) 남은 것을 보인다. `--show`면
    바꾸지 않고 보이기만. 저널을 억지로 지우는 옵션은 없다 — 저널 단계별 안내(`guide`)대로 사람이
    정리하면(커밋 뒤면 `explore.json`의 `promoted`, 아니면 바뀐 파일을 원래 바이트로) 다음 복구가
    끝낸다. 사람만."""
    from kookabug_core.screen_promote import PromoteError, pending, recover_locked

    report: dict[str, Any] = {"command": "screen recover"}

    def finish(code: int, text: str, **extra: Any) -> int:
        report.update(exit_code=code, message=text, **extra)
        if args.json:
            print(json.dumps(report, ensure_ascii=False), file=out)
        else:
            print(text, file=out if code == 0 else err)
        return code

    if AGENT_ENV in os.environ:
        return finish(
            EXIT_DENIED, "화면 지도 복구는 사람만 한다 (KOOKABUG_AGENT)", error_code="agent_only"
        )
    try:
        ws = _workspace(args.workspace, Path.cwd())
    except WorkspaceError as exc:
        return finish(EXIT_USAGE, f"오류: {exc}")
    warnings: list[str] = []
    if not args.show:
        try:
            warnings = recover_locked(ws.root)
        except PromoteError as exc:
            return finish(EXIT_REFUSED, f"복구하지 않았다: {exc.message}", error_code=exc.code)
    left = pending(ws.root)
    if not left:
        return finish(0, "남은 승격 거래가 없다", journals=[], warnings=warnings)
    lines = [f"남은 승격 거래 {len(left)}개 — 안내대로 정리하면 다음 화면 지도 작업 때 풀린다:"]
    for entry in left:
        lines.append(f"  {entry['txid']} ({entry['phase']})")
        lines.append(f"    할 일: {entry['guide']}")
        lines.extend(f"    파일: {p}" for p in entry["paths"])
        lines.extend(f"    원래 바이트: {p} ← {b}" for p, b in entry["backups"].items())
        lines.extend(f"    경고: {w}" for w in entry["warnings"])
    return finish(EXIT_REFUSED, "\n".join(lines), journals=left, warnings=warnings)


def _with_revisions(request: Any, revisions: Mapping[str, str | None]) -> Any:
    import dataclasses

    return dataclasses.replace(request, base_revisions=dict(revisions))  # pyright: ignore[reportUnknownVariableType]
