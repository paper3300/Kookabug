"""`kookabug` 명령 (구현 계획 M0b 2.11).

    kookabug run <그래프 경로> [--workspace DIR] [--profile 이름] [--set 키=JSON값]...
                 [--deadline-ms N] [--json] [--quiet] [--plugin-module 모듈]...

이 프로세스가 감독자다: `WorkspaceService.start_run`(권한 판정 → 감독자 시작) → 진행 출력(`follow`로
`step.end` 한 줄씩) → `RunHandle.wait()`(runner 종료 → 복구 경로) → 판정에 맞는 종료 코드.

- 워크스페이스는 `--workspace` 또는 그래프 경로에서 위로 찾는다. `--set` 값은 JSON, 아니면 문자열
- 기한: `--deadline-ms` → `kookabug.json`의 `run.deadline_ms` → 30분. 다른 시간 값은 `run` 블록 →
  감독자 기본값
- 주체: `KOOKABUG_AGENT=<연결 ID>`가 있으면 사람 없는 에이전트(ask = 거부), 없으면 사람. CLI는
  에이전트에게 승인을 주지 않는다
- Ctrl+C: 첫 번째는 취소 요청, 두 번째는 runner를 바로 끝낸다. 결과(기록 마무리)는 주 흐름의
  `wait()`가 받는다 — 신호 처리기는 기다리는 호출을 하지 않는다
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any, Final, NoReturn, Protocol, TextIO

from kookabug_core.canonical import loads_strict
from kookabug_core.permissions import Decision, Principal
from kookabug_core.record import follow
from kookabug_core.runner.spec import PlatformSpec
from kookabug_core.service import (
    RUN_START_TOOL,
    ApprovalRequired,
    PermissionDenied,
    WorkspaceService,
    cli_principal,
)
from kookabug_core.supervisor import DEFAULT_DEADLINE_MS, RunHandle, RunOutcome, StartOptions
from kookabug_core.workspace import RunConditions, Workspace, WorkspaceError
from kookabug_sdk import _faults
from kookabug_sdk.console import utf8_stdio

__all__ = [
    "EXIT_DENIED",
    "EXIT_ERROR",
    "EXIT_FAIL",
    "EXIT_INVALID",
    "EXIT_PASS",
    "EXIT_SKIPPED",
    "EXIT_USAGE",
    "InterruptHandler",
    "UsageError",
    "build_parser",
    "exit_code_of",
    "main",
    "parse_setting",
    "resolve_deadline",
    "resolve_target",
    "start_options",
]

EXIT_PASS: Final = 0
EXIT_FAIL: Final = 1
EXIT_ERROR: Final = 2
"""오류: 취소·기한 초과·runner 죽음·입력 임대권 거부·기록 마무리 실패 포함."""
EXIT_SKIPPED: Final = 3
EXIT_INVALID: Final = 4
"""실행 전 검증 오류 (`run.end` 코드 `graph_invalid`)."""
EXIT_DENIED: Final = 5
"""권한 거부·승인 필요. 실행 폴더도 프로세스도 만들지 않았다."""
EXIT_USAGE: Final = 6
"""사용법·환경 오류 (argparse 오류 포함)."""

_VERDICT_EXIT: Final = {
    "pass": EXIT_PASS,
    "fail": EXIT_FAIL,
    "error": EXIT_ERROR,
    "skipped": EXIT_SKIPPED,
}
_INVALID_CODES: Final = frozenset({"graph_invalid"})
_VERDICT_WORDS: Final = {"pass": "통과", "fail": "실패", "error": "오류", "skipped": "건너뜀"}
_STATUS_WORDS: Final = {"success": "성공", "fail": "실패", "error": "오류", "cancelled": "취소"}


class UsageError(Exception):
    """명령을 실행할 수 없다 (그래프·워크스페이스를 찾을 수 없음 등). 종료 코드 6."""


class _Parser(argparse.ArgumentParser):
    """argparse 오류도 종료 코드 6 (argparse 기본값 2는 '오류' 판정과 겹친다)."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: 오류: {message}\n")


def parse_setting(text: str) -> tuple[str, Any]:
    """`--set 키=값`: 값은 JSON으로 읽고, JSON이 아니면 문자열 그대로."""
    key, sep, raw = text.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"'{text}'이(가) 키=값 형식이 아니다")
    try:
        value = loads_strict(raw)
    except ValueError:
        value = raw
    return key, value


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"'{text}'은(는) 1 이상의 정수가 아니다")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="kookabug", description="Kookabug 명령줄 도구")
    commands = parser.add_subparsers(dest="command", required=True, metavar="명령")
    run = commands.add_parser(
        "run",
        help="그래프를 실행한다",
        description="그래프를 실행하고 판정을 종료 코드로 돌려준다 "
        "(0 통과, 1 실패, 2 오류, 3 건너뜀, 4 실행 전 검증 오류, 5 권한 거부, 6 사용법 오류)",
    )
    run.add_argument("graph", help="실행할 그래프 파일")
    run.add_argument(
        "--workspace", metavar="DIR", help="워크스페이스 루트 (기본: 그래프 경로에서 위로 찾는다)"
    )
    run.add_argument("--profile", metavar="이름", help="kookabug.json의 프로필")
    run.add_argument(
        "--set",
        dest="settings",
        action="append",
        default=[],
        type=parse_setting,
        metavar="키=JSON값",
        help="설정값 (JSON으로 읽고, 아니면 문자열). 여러 번 쓸 수 있다",
    )
    run.add_argument(
        "--deadline-ms",
        type=_positive_int,
        metavar="N",
        help="실행 전체 기한 (기본: kookabug.json의 run.deadline_ms, 없으면 30분)",
    )
    run.add_argument("--json", action="store_true", help="결과 JSON 한 개만 출력한다")
    run.add_argument("--quiet", action="store_true", help="스텝 진행 줄을 출력하지 않는다")
    run.add_argument(
        "--plugin-module",
        dest="plugin_modules",
        action="append",
        default=[],
        metavar="모듈",
        help="[개발용] 워커가 import할 플러그인 모듈 (플러그인 설치가 생기기 전까지)",
    )
    # 테스트용: 가짜 플랫폼(프레임·입력 기록·훅) 사양 JSON 파일. 도움말에 보이지 않는다
    run.add_argument("--platform-fake", metavar="FILE", help=argparse.SUPPRESS)
    return parser


# ---------------------------------------------------------------- 인수 → 실행 조건


def resolve_target(
    graph: str, workspace: str | None, cwd: Path | None = None
) -> tuple[Workspace, str]:
    """(워크스페이스, 루트 기준 그래프 경로). 그래프 경로는 현재 폴더 기준이고, `--workspace`를
    주면 워크스페이스 루트 기준 경로도 받는다."""
    here = Path.cwd() if cwd is None else cwd
    given = Path(graph)
    ws: Workspace | None = None
    try:
        if workspace is not None:
            ws = Workspace.open(here / workspace)
            candidates = [given] if given.is_absolute() else [here / given, ws.root / given]
        else:
            candidates = [given if given.is_absolute() else here / given]
        path = next((c.resolve() for c in candidates if c.is_file()), None)
        if path is None:
            raise UsageError(f"그래프 파일이 없다: {graph}")
        if ws is None:
            ws = Workspace.find(path.parent)
    except WorkspaceError as exc:
        raise UsageError(str(exc)) from exc
    rel = ws.relative(path)
    if rel is None:
        raise UsageError(f"{path}은(는) 워크스페이스 {ws.root} 밖이다")
    return ws, rel


def resolve_deadline(cli: int | None, conditions: RunConditions) -> int:
    """`--deadline-ms` → `kookabug.json`의 `run.deadline_ms` → 30분."""
    if cli is not None:
        return cli
    if conditions.deadline_ms is not None:
        return conditions.deadline_ms
    return DEFAULT_DEADLINE_MS


def read_platform_fake(path: str) -> PlatformSpec:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"--platform-fake {path}을(를) 읽을 수 없다: {exc}") from exc
    if not isinstance(data, dict):
        raise UsageError(f"--platform-fake {path}은(는) JSON 객체여야 한다")
    spec: dict[str, Any] = data
    return PlatformSpec(
        "fake",
        frames=tuple(spec.get("frames", ())),
        input_log=spec.get("input_log"),
        hooks=spec.get("hooks", {}),
    )


def start_options(args: argparse.Namespace, ws: Workspace) -> StartOptions:
    conditions = ws.run_conditions()
    timing = {
        name: value
        for name in ("worker_cancel_grace_ms", "worker_start_timeout_ms", "shutdown_grace_ms")
        if (value := getattr(conditions, name)) is not None
    }
    return StartOptions(
        deadline_ms=resolve_deadline(args.deadline_ms, conditions),
        profile=args.profile,
        settings=dict(args.settings),
        plugin_modules=tuple(args.plugin_modules),
        platform=(
            PlatformSpec() if args.platform_fake is None else read_platform_fake(args.platform_fake)
        ),
        **timing,
    )


# ---------------------------------------------------------------- 진행 출력


class Titles:
    """스텝 경로(노드 ID 목록) → 제목 경로. 실행 스냅샷의 그래프 파일을 읽는다 (`title`이 없으면
    노드 ID). 서브그래프 호출 노드는 `config.graph`로 안쪽 그래프를 찾는다."""

    def __init__(self, snapshot: Path, graph: str) -> None:
        self._snapshot = snapshot
        self._graph = graph
        self._nodes: dict[str, Mapping[str, Any]] = {}

    def _nodes_of(self, rel: str) -> Mapping[str, Any]:
        nodes = self._nodes.get(rel)
        if nodes is None:
            try:
                data = json.loads(self._snapshot.joinpath(*rel.split("/")).read_text("utf-8"))
            except OSError, ValueError:
                return {}  # 아직 없거나 읽을 수 없다: 다음에 다시 읽는다
            found = data.get("nodes") if isinstance(data, dict) else None
            nodes = self._nodes[rel] = found if isinstance(found, dict) else {}
        return nodes

    def path(self, node_path: Sequence[str]) -> list[str]:
        titles: list[str] = []
        graph: str | None = self._graph
        for node_id in node_path:
            node = self._nodes_of(graph).get(node_id) if graph is not None else None
            node = node if isinstance(node, dict) else {}
            title = node.get("title")
            titles.append(title if isinstance(title, str) and title else node_id)
            config = node.get("config")
            inner = config.get("graph") if isinstance(config, dict) else None
            graph = inner if isinstance(inner, str) else None
        return titles


class Progress:
    """`step.end`마다 한 줄: 상태, 제목 경로, 출구 또는 오류, 걸린 시간.

    스텝 경로는 열린 스텝 것만 둔다(끝난 스텝은 줄을 쓴 뒤 버린다). 긴 실행에서도 보관량이
    끝난 스텝 수에 비례해 늘지 않는다."""

    def __init__(self, titles: Titles, out: TextIO) -> None:
        self.titles = titles
        self.out = out
        self._paths: dict[str, list[str]] = {}

    @property
    def open_steps(self) -> int:
        return len(self._paths)

    def event(self, event: Mapping[str, Any]) -> None:
        kind = event.get("event")
        if kind == "step.start":
            self._paths[str(event.get("step"))] = list(event.get("path") or [])
        elif kind == "step.end":
            print(self.line(event), file=self.out, flush=True)
            self._paths.pop(str(event.get("step")), None)

    def line(self, event: Mapping[str, Any]) -> str:
        status = event.get("status")
        word = _STATUS_WORDS.get(str(status), str(status))
        where = " > ".join(self.titles.path(self._paths.get(str(event.get("step")), [])))
        text = f"  [{word}] {where}"
        error = event.get("error")
        if isinstance(error, dict):
            text += f" — {error.get('code')}: {error.get('message')}"
        elif event.get("exit") is not None:
            text += f" → {event['exit']}"
        if isinstance(event.get("duration_ms"), int):
            text += f" ({event['duration_ms']} ms)"
        return text


# ---------------------------------------------------------------- Ctrl+C


class _Stoppable(Protocol):
    def cancel(self) -> object: ...
    def hard_stop(self) -> None: ...


class InterruptHandler:
    """SIGINT 처리기. 첫 번째는 취소 요청(답을 기다리는 호출이라 별도 스레드), 두 번째부터는
    runner를 바로 끝낸다(`hard_stop`, 즉시 돌아온다). 마무리 결과는 주 흐름의 `wait()`가 받는다."""

    def __init__(self, handle: _Stoppable, err: TextIO | None = None) -> None:
        self.handle = handle
        self.err = err
        self.count = 0
        self.cancel_thread: threading.Thread | None = None

    def __call__(self, signum: int = signal.SIGINT, frame: FrameType | None = None) -> None:
        self.count += 1
        if self.count == 1:
            self._say("취소를 요청했다. 한 번 더 누르면 runner를 바로 끝낸다")
            self.cancel_thread = threading.Thread(
                target=self.handle.cancel, name="cli-cancel", daemon=True
            )
            self.cancel_thread.start()
        else:
            self._say("runner를 바로 끝낸다. 기록은 마무리한다")
            self.handle.hard_stop()

    def _say(self, message: str) -> None:
        if self.err is not None:
            print(message, file=self.err, flush=True)


# ---------------------------------------------------------------- 결과


def exit_code_of(outcome: RunOutcome) -> int:
    """`run.end` 판정 → 종료 코드. 감독자가 기록을 마무리하지 못했으면(`recover_error`) 그래프
    판정과 무관하게 오류다 — `run.json`이 `running`으로 남았을 수 있다. 판정 자체는 보존한다."""
    end = outcome.run_end
    if end is None or outcome.recover_error is not None:
        return EXIT_ERROR
    verdict = end.get("verdict")
    if verdict == "error" and end.get("code") in _INVALID_CODES:
        return EXIT_INVALID
    return _VERDICT_EXIT.get(str(verdict), EXIT_ERROR)


def decision_json(decision: Decision) -> dict[str, Any]:
    return {
        "verdict": decision.verdict,
        "final": decision.final,
        "layer": decision.layer,
        "source": decision.source,
        "reason": decision.reason,
        "diagnostics": [d.to_dict() for d in decision.diagnostics],
    }


@dataclass
class _Report:
    graph: str | None = None
    workspace: Path | None = None
    principal: Principal | None = None
    decision: Decision | None = None
    error: str | None = None

    def to_json(
        self, exit_code: int, outcome: RunOutcome | None, titles: Titles | None
    ) -> dict[str, Any]:
        end = (outcome.run_end if outcome is not None else None) or {}
        failure_path = end.get("failure_path")
        return {
            "command": "run",
            "graph": self.graph,
            "workspace": None if self.workspace is None else str(self.workspace),
            "principal": None
            if self.principal is None
            else {
                "kind": self.principal.kind,
                "id": self.principal.id,
                "attended": self.principal.attended,
            },
            "tool": RUN_START_TOOL,
            "decision": None if self.decision is None else decision_json(self.decision),
            "run_id": None if outcome is None else outcome.run_id,
            "run_dir": None if outcome is None else str(outcome.run_dir),
            "verdict": end.get("verdict"),
            "code": end.get("code"),
            "reason": end.get("reason"),
            "failure_step": end.get("failure_step"),
            "failure_path": failure_path,
            "failure_titles": titles.path(failure_path)
            if titles is not None and isinstance(failure_path, list)
            else None,
            "finalized_by": end.get("finalized_by"),
            "runner_exit_code": None if outcome is None else outcome.exit_code,
            "start_error": None if outcome is None else outcome.start_error,
            "recover_error": None if outcome is None else outcome.recover_error,
            "exit_code": exit_code,
            "error": self.error,
        }


def recover_failure(outcome: RunOutcome) -> str | None:
    """기록 마무리(감독자 복구 경로) 실패를 사람이 읽는 한 줄로. 실패가 없으면 None."""
    if outcome.recover_error is None:
        return None
    return (
        f"기록 마무리 실패: {outcome.recover_error} (실행 폴더의 run.json이 끝나지 않았을 수 있다)"
    )


def _summary(outcome: RunOutcome, titles: Titles, out: TextIO) -> None:
    end = outcome.run_end
    if end is None:
        print("판정: 알 수 없음 (run.end가 없다)", file=out)
    else:
        verdict = str(end.get("verdict"))
        print(f"판정: {_VERDICT_WORDS.get(verdict, verdict)} ({end.get('code')})", file=out)
        if end.get("reason"):
            print(f"사유: {end['reason']}", file=out)
        failure_path = end.get("failure_path")
        if isinstance(failure_path, list) and failure_path:
            print(f"실패 위치: {' > '.join(titles.path(failure_path))}", file=out)
    if outcome.start_error:
        print(f"시작 실패: {outcome.start_error}", file=out)
    failure = recover_failure(outcome)
    if failure is not None:
        print(failure, file=out)
    print(f"실행 폴더: {outcome.run_dir}", file=out, flush=True)


def _runner_gone(handle: RunHandle) -> bool:
    runner = handle.runner
    return runner is None or not runner.alive()


def _install_interrupt(handler: InterruptHandler) -> Any:
    if threading.current_thread() is not threading.main_thread():
        return None
    return signal.signal(signal.SIGINT, handler)


def run_command(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    report = _Report()

    def finish(code: int, outcome: RunOutcome | None = None, titles: Titles | None = None) -> int:
        if args.json:
            print(json.dumps(report.to_json(code, outcome, titles), ensure_ascii=False), file=out)
        if report.error is not None:
            print(f"오류: {report.error}", file=err)
        return code

    try:
        ws, rel = resolve_target(args.graph, args.workspace)
        report.graph, report.workspace = rel, ws.root
        options = start_options(args, ws)
        service = WorkspaceService(ws.root)
    except (UsageError, WorkspaceError) as exc:
        report.error = str(exc)
        return finish(EXIT_USAGE)

    principal = report.principal = cli_principal()
    _faults.set_role("supervisor")
    # 판정은 start_run 안에서 한 번만 한다. 보고하는 판정 = 집행한 판정 (핸들·예외가 돌려준다)
    try:
        handle = service.start_run(principal, rel, options)
    except (PermissionDenied, ApprovalRequired) as exc:
        report.decision = exc.decision
        report.error = str(exc)
        return finish(EXIT_DENIED)
    except OSError as exc:
        report.error = f"실행을 시작할 수 없다: {exc}"
        return finish(EXIT_USAGE)
    report.decision = handle.decision

    titles = Titles(handle.folder.snapshot, rel)
    progress = Progress(titles, out)
    show_steps = not (args.json or args.quiet)
    handler = InterruptHandler(handle, err)
    previous = _install_interrupt(handler)
    try:
        for event in follow(handle.run_dir, stop=lambda: _runner_gone(handle)):
            if show_steps:
                progress.event(event)
        outcome = handle.wait()
    finally:
        if previous is not None:
            signal.signal(signal.SIGINT, previous)
    code = exit_code_of(outcome)
    report.error = recover_failure(outcome)
    if not args.json:
        _summary(outcome, titles, out)
    return finish(code, outcome, titles)


def main(argv: Sequence[str] | None = None) -> int:
    utf8_stdio()  # 어떤 출력보다 먼저 (argparse 도움말·오류 포함)
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return run_command(args, sys.stdout, sys.stderr)
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())
