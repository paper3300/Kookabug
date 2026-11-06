"""`kookabug plugin …` (M6 계획 3.7).

    kookabug plugin add <원천> [--ref R] [--sha256 H] [--isolation auto|shared|isolated]
                        [--yes] [--json]
        원천: git+<url>[@ref] · wheel 파일 · https://…whl(--sha256 필수) · 폴더
    kookabug plugin remove <id> [--yes] [--json]
    kookabug plugin upgrade <id> [--ref R] [--sha256 H] [--yes] [--json]
    kookabug plugin sync [--yes] [--json]      잠금 → 환경 (커밋된 wheel만, 잠금을 쓰지 않음)
    kookabug plugin relock [--yes] [--json]    앱 Python·SDK로 다시 잠금
    kookabug plugin list [--json]
    kookabug plugin verify [--json]
    kookabug plugin gc [--yes] [--json]

- 설치·제거·upgrade·sync·relock·정리는 사람만: `KOOKABUG_AGENT`가 있으면 아무것도 하지 않고 종료 5.
  목록·검증은 누구나
- 신뢰 확인: `--yes` 또는 대화형 질문. 대화형이 아닌데 `--yes`가 없으면 종료 6 (아무것도 안 바뀜).
  sync는 이 PC에서 신뢰한 잠금이면 묻지 않는다
- 종료 코드: 0 성공, 2 작업 실패(`--json`에 `{error: {code, stage, message}}`, 조건 다름
  `plugin_env_stale` 포함, 예상 밖 예외는 `unexpected_error`), 5 에이전트, 6 사용법·워크스페이스
  없음·확인 필요
- 오류 출력에는 인증 정보가 없다: `PluginError`는 만들 때 가리고, 그 밖의 예외도 이 명령의 최상위
  경계에서 종류 + 가린 문구로만 낸다(원문 traceback 없음, `KOOKABUG_PLUGIN_DEBUG`면 가린 traceback)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, TextIO

__all__ = ["add_parser", "run"]

EXIT_OK: Final = 0
EXIT_FAILED: Final = 2
EXIT_DENIED: Final = 5
EXIT_USAGE: Final = 6
_HUMAN_ONLY: Final = frozenset({"add", "remove", "upgrade", "sync", "relock", "gc"})
_KEEPS: Final = frozenset({"add", "upgrade", "sync", "relock"})
DEBUG_ENV: Final = "KOOKABUG_PLUGIN_DEBUG"
"""있으면 예상 밖 오류의 traceback(인증 정보 가림)을 오류 출력에 낸다."""


class _NeedsConfirm(Exception):
    """대화형이 아니라 신뢰 확인을 받을 수 없다."""


def add_parser(commands: Any) -> None:
    plugin: argparse.ArgumentParser = commands.add_parser(
        "plugin",
        help="플러그인 설치·제거·목록·검증·정리",
        description="플러그인 관리 (0 성공, 2 작업 실패, 5 에이전트 거부, 6 사용법·확인 필요)",
    )
    actions = plugin.add_subparsers(dest="action", required=True, metavar="동작")

    def common(p: argparse.ArgumentParser, *, yes: bool) -> None:
        p.add_argument(
            "--workspace", metavar="DIR", help="워크스페이스 루트 (기본: 현재 폴더에서 위로 찾는다)"
        )
        p.add_argument("--json", action="store_true", help="결과 JSON 한 개만 출력한다")
        if yes:
            p.add_argument(
                "--yes", action="store_true", help="확인 없이 진행한다 (출처를 믿을 때만)"
            )

    def isolation(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--isolation",
            choices=("auto", "shared", "isolated"),
            help="환경 (기본: 매니페스트, 없으면 auto — 충돌하면 그 플러그인만 격리)",
        )

    add = actions.add_parser("add", help="플러그인을 설치한다 (git·wheel·폴더)")
    add.add_argument(
        "source", help="git+<url>[@ref] · wheel 파일(*.whl) · https://…whl · 플러그인 폴더"
    )
    add.add_argument("--ref", metavar="R", help="git 태그·브랜치·커밋 (기본 HEAD)")
    add.add_argument("--sha256", metavar="H", help="wheel의 sha256 (https wheel은 필수)")
    isolation(add)
    common(add, yes=True)
    remove = actions.add_parser("remove", help="플러그인을 뺀다 (폴더·wheel은 gc가 치운다)")
    remove.add_argument("id", help="플러그인 ID")
    common(remove, yes=True)
    upgrade = actions.add_parser("upgrade", help="잠금의 원천을 다시 받아 바꾼다")
    upgrade.add_argument("id", help="플러그인 ID")
    upgrade.add_argument("--ref", metavar="R", help="git 원천의 새 ref (기본: 잠금의 ref)")
    upgrade.add_argument("--sha256", metavar="H", help="https wheel 원천의 새 sha256")
    isolation(upgrade)
    common(upgrade, yes=True)
    common(
        actions.add_parser(
            "sync", help="잠금대로 환경을 준비한다 (커밋된 wheel만, 빌드·잠금 쓰기 없음)"
        ),
        yes=True,
    )
    common(
        actions.add_parser("relock", help="앱의 Python·SDK로 다시 잠근다 (조건이 다를 때)"),
        yes=True,
    )
    common(actions.add_parser("list", help="설치된 플러그인과 환경 상태"), yes=False)
    common(actions.add_parser("verify", help="환경 파일·커밋된 wheel을 잠금과 대조한다"), yes=False)
    common(actions.add_parser("gc", help="안 쓰는 환경·wheel을 지운다"), yes=True)


def run(args: argparse.Namespace, out: TextIO, err: TextIO, *, stdin: TextIO | None = None) -> int:
    from kookabug_core.plugins import PluginError, PluginOps
    from kookabug_core.service import AGENT_ENV
    from kookabug_core.workspace import Workspace, WorkspaceError
    from kookabug_sdk import _faults

    action: str = args.action

    def finish(code: int, body: dict[str, Any], text: str | None = None) -> int:
        if args.json:
            print(json.dumps({"command": f"plugin {action}", **body}, ensure_ascii=False), file=out)
        elif text:
            print(text, file=out if code == EXIT_OK else err)
        return code

    if action in _HUMAN_ONLY and AGENT_ENV in os.environ:
        message = "플러그인 설치·제거·정리는 사람만 한다 (KOOKABUG_AGENT)"
        return finish(
            EXIT_DENIED,
            {
                "ok": False,
                "error": {"code": "permission_denied", "stage": None, "message": message},
            },
            f"오류: {message}",
        )
    try:
        ws = Workspace.open(Path(args.workspace)) if args.workspace else Workspace.find(Path.cwd())
    except WorkspaceError as exc:
        return finish(
            EXIT_USAGE,
            {"ok": False, "error": {"code": "usage", "message": str(exc)}},
            f"오류: {exc}",
        )
    _faults.set_role("plugin")
    ops = PluginOps(ws.root)
    reader = stdin if stdin is not None else sys.stdin
    confirm = _confirmer(bool(getattr(args, "yes", False)), reader, err)
    try:
        if action in ("add", "upgrade"):
            if action == "add":
                result = ops.add(
                    args.source,  # 상대 경로는 현재 폴더 기준 (parse_source)
                    isolation=args.isolation,
                    sha256=args.sha256,
                    ref=args.ref,
                    confirm=lambda p: confirm(_preview_text(p.to_json())),
                )
            else:
                result = ops.upgrade(
                    args.id,
                    ref=args.ref,
                    sha256=args.sha256,
                    isolation=args.isolation,
                    confirm=lambda p: confirm(_preview_text(p.to_json())),
                )
            plugin = result["plugin"]
            return finish(
                EXIT_OK,
                {"ok": True, **result},
                f"설치했다: {plugin['id']} {plugin['version']} (환경 {result['env']})",
            )
        if action == "remove":
            result = ops.remove(
                args.id,
                confirm=lambda p: confirm(
                    f"{p['id']} {p['version']}을(를) 뺀다" + _untrusted_text(p["untrusted"])
                ),
            )
            return finish(EXIT_OK, {"ok": True, **result}, f"뺐다: {args.id}")
        if action == "sync":
            result = ops.sync(confirm=lambda p: confirm(_sync_text(p)))
            text = (
                f"환경을 만들었다: {', '.join(result['created'])}"
                if result["created"]
                else "환경이 이미 준비돼 있다"
            )
            return finish(EXIT_OK, {"ok": True, **result}, text)
        if action == "relock":
            result = ops.relock(confirm=lambda p: confirm(_relock_text(p)))
            text = "다시 잠갔다" if result["changed"] else "잠금 조건이 이미 앱과 같다"
            return finish(EXIT_OK, {"ok": True, **result}, text)
        if action == "list":
            result = ops.status()
            return finish(EXIT_OK, {"ok": True, **result}, _list_text(result))
        if action == "verify":
            result = ops.verify()
            text = (
                "환경이 잠금과 같다"
                if result["ok"]
                else "\n".join(
                    f"문제: {p.get('env') or p.get('plugin')}: {p['problem']}"
                    for p in result["problems"]
                )
            )
            return finish(EXIT_OK if result["ok"] else EXIT_FAILED, result, text)
        if action == "gc":
            result = ops.gc(confirm=lambda names: confirm(_gc_text(names)))
            removed = sum(len(v) for v in result["removed"].values())
            return finish(EXIT_OK, {"ok": not result["failed"], **result}, f"지웠다: {removed}개")
    except _NeedsConfirm:
        message = "확인이 필요하다: 대화형이 아니면 --yes를 준다 (아무것도 바꾸지 않았다)"
        return finish(
            EXIT_USAGE,
            {"ok": False, "error": {"code": "confirm_required", "message": message}},
            f"오류: {message}",
        )
    except PluginError as exc:
        return finish(
            EXIT_FAILED,
            {"ok": False, "error": exc.to_json()},
            f"오류: {exc.code}: {exc.message}"
            + ("\n기존 플러그인·환경은 그대로다" if action in _KEEPS else ""),
        )
    except Exception as exc:
        return _unexpected(exc, action, finish, err)
    raise AssertionError(action)


def _unexpected(exc: Exception, action: str, finish: Callable[..., int], err: TextIO) -> int:
    """`PluginError`가 아닌 예외(받기·하위 프로세스·예상 밖 오류): 예외 문구에 URL·인증 값이
    있을 수 있어 종류와 가린 문구만 낸다 (종료 2). `KOOKABUG_PLUGIN_DEBUG`가 있으면 가린
    traceback을 오류 출력에."""
    import traceback

    from kookabug_core.plugins.redact import mask

    message = f"예상하지 못한 오류 {type(exc).__name__}: {mask(str(exc))}"
    if os.environ.get(DEBUG_ENV):
        print(mask("".join(traceback.format_exception(exc))), file=err)
    return finish(
        EXIT_FAILED,
        {"ok": False, "error": {"code": "unexpected_error", "stage": None, "message": message}},
        f"오류: {message}" + ("\n기존 플러그인·환경은 그대로다" if action in _KEEPS else ""),
    )


def _interactive(stream: TextIO) -> bool:
    """사람이 답할 수 있는 콘솔 입력인가. Windows의 `NUL`은 `isatty()`가 참이라 콘솔 모드로 본다."""
    try:
        if not stream.isatty():
            return False
        fd = stream.fileno()
    except OSError, ValueError:
        return False
    import ctypes
    import msvcrt

    mode = ctypes.c_uint32()
    handle = msvcrt.get_osfhandle(fd)
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))


def _confirmer(yes: bool, stdin: TextIO, err: TextIO) -> Callable[[str], bool]:
    def confirm(text: str) -> bool:
        if yes:
            return True
        if not _interactive(stdin):
            raise _NeedsConfirm
        print(text, file=err)
        print("진행할까? [y/N] ", end="", file=err, flush=True)
        return stdin.readline().strip().lower() in ("y", "yes", "예")

    return confirm


def _source_text(source: dict[str, Any]) -> str:
    if source.get("kind") == "git":
        ref = source.get("ref") or "HEAD"
        return f"git {source['url']} @ {ref} ({str(source['commit'])[:12]})"
    return f"{source.get('kind')} {source.get('path') or source.get('url')}"


def _untrusted_text(ids: list[str]) -> str:
    if not ids:
        return ""
    return (
        "\n  이 PC에서 아직 신뢰 확인하지 않은 잠금이다. 진행하면 잠금의 다른 플러그인도 모두 "
        "신뢰한다 (이 PC에서 실행될 수 있다): " + ", ".join(ids)
    )


def _preview_text(p: dict[str, Any]) -> str:
    lines = [
        "이 플러그인은 내 PC에서 내 권한으로 실행된다. 출처를 믿을 때만 설치한다.",
        f"  이름  {p.get('title') or p['id']} ({p['id']} {p['version']}, {p['dist']})",
        f"  출처  {_source_text(p['source'])}",
        f"  권한  {', '.join(p['permissions']) or '없음'}",
        f"  의존성 {len(p['dependencies'])}개: {', '.join(p['dependencies']) or '없음'}",
    ]
    if p.get("replaces"):
        lines.append(f"  바꾸는 판 {p['replaces']} → {p['version']}")
    return "\n".join(lines) + _untrusted_text(p.get("untrusted") or [])


def _sync_text(p: dict[str, Any]) -> str:
    lines = [
        "잠금(kookabug.lock)의 플러그인을 이 PC에 준비한다. 플러그인은 내 PC에서 내 권한으로 "
        "실행된다. 출처를 믿을 때만 진행한다.",
        *(
            f"  {x['id']} {x['version']}  {_source_text(x['source'])}  권한 "
            f"{', '.join(x['permissions']) or '없음'}"
            for x in p["plugins"]
        ),
    ]
    return "\n".join(lines)


def _relock_text(p: dict[str, Any]) -> str:
    return (
        f"잠금을 앱 조건으로 바꾼다: Python {p['from']['python']} → {p['to']['python']}, "
        f"SDK {p['from']['sdk']} → {p['to']['sdk']}\n"
        + "\n".join(f"  {x['id']} {x['version']}" for x in p["plugins"])
        + _untrusted_text(p.get("untrusted") or [])
    )


def _list_text(result: dict[str, Any]) -> str:
    if not result["plugins"]:
        return "설치된 플러그인이 없다"
    lines = [f"{p['id']} {p['version']}  {p['env']}  {p['env_status']}" for p in result["plugins"]]
    if result.get("stale_reason"):
        lines.append(f"조건 다름: {result['stale_reason']} (kookabug plugin relock)")
    return "\n".join(lines)


def _gc_text(names: dict[str, list[str]]) -> str:
    return "지울 것: " + ", ".join(f"{k} {len(v)}개" for k, v in names.items())
