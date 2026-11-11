"""`kookabug agent-job` (M8 계획 3.9·3.10·3.15) — 외부 Agent CLI 무인 감독. 사람만 쓴다.

    kookabug agent-job run --workspace WS --playbook init|followup|triage|repair|explore|author|lint
            [--agent claude|codex|custom] [--agent-command "<명령줄>"] [--basis working|team]
            [--minutes N] [--runs N] [--trigger manual|schedule|ci] [--pass-env 이름]... [--json]
    kookabug agent-job status [JOB] | list | cancel JOB | probe --agent ID [--agent-command ...]
    kookabug agent-job schedule install|remove|show --workspace WS --playbook triage
            --daily HH:MM [--agent ID] [--dry-run]
    kookabug agent-job playbooks

- `KOOKABUG_AGENT`가 있으면 아무것도 하지 않고 종료 5 (Agent는 작업을 만들지 못한다 — 재귀 금지)
- 종료 코드: 0 작업 `done`·명령 성공, 1 작업이 다른 상태로 끝남(failed·cancelled·budget_exhausted·
  interrupted)·명령 거부, 3 `job_active`(이 워크스페이스에 다른 작업), 4 `prep_failed`, 5 에이전트,
  6 워크스페이스·daemon·사용법 오류
- 토큰은 출력·인자·`job.json`에 남지 않는다. 첫 출력은 보안 경계 문구(3.15)다
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Final, TextIO

__all__ = ["AGENT_ENV", "EXIT_DENIED", "add_parser", "connect_daemon", "run"]

AGENT_ENV: Final = "KOOKABUG_AGENT"
EXIT_OK: Final = 0
EXIT_REFUSED: Final = 1
EXIT_DENIED: Final = 5
EXIT_USAGE: Final = 6


def add_parser(commands: Any) -> None:
    from kookabug_core.playbooks import NAMES

    job: argparse.ArgumentParser = commands.add_parser(
        "agent-job", help="외부 Agent CLI 무인 작업 (사람만)"
    )
    actions = job.add_subparsers(dest="action", required=True, metavar="동작")

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--workspace", metavar="DIR", help="워크스페이스 루트 (기본: 현재 폴더에서 위로 찾는다)"
        )
        sub.add_argument("--json", action="store_true", help="결과 JSON 한 개만 출력한다")

    def agent_args(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--agent", help="Agent 프로필 claude·codex·custom (기본: custom이면 명령 필요)"
        )
        sub.add_argument("--agent-command", help="custom 프로필의 명령줄 (프롬프트는 stdin)")
        sub.add_argument(
            "--pass-env",
            action="append",
            default=[],
            metavar="이름",
            help="자식에 더 넘길 환경 변수 이름 (허용 목록 밖, KOOKABUG_SECRET_*는 안 됨)",
        )
        sub.add_argument("--grace-s", type=float, default=None, help=argparse.SUPPRESS)

    run = actions.add_parser("run", help="작업 하나를 끝까지 감독한다")
    common(run)
    agent_args(run)
    run.add_argument("--playbook", required=True, choices=[n for n in NAMES if n != "probe"])
    run.add_argument("--basis", choices=["working", "team"], default="working")
    run.add_argument("--minutes", type=int, help="시간 예산 (기본 kookabug.json automation.budget)")
    run.add_argument("--runs", type=int, help="실행 수 예산")
    run.add_argument("--trigger", choices=["manual", "schedule", "ci"], default="manual")
    run.add_argument(
        "--launch-tag",
        metavar="HEX32",
        help="실행 표지 (앱이 자기가 띄운 작업을 목록에서 알아본다, job.json launch_tag). "
        "비밀 아님·권한 없음, 소문자 hex 32자",
    )

    status = actions.add_parser("status", help="작업 상태 (job.json)")
    common(status)
    status.add_argument("job", nargs="?", help="작업 ID (없으면 마지막 작업)")
    listing = actions.add_parser("list", help="작업 목록")
    common(listing)
    cancel = actions.add_parser("cancel", help="작업을 취소한다 (실행 정리·보고)")
    common(cancel)
    cancel.add_argument("job", help="작업 ID")
    probe = actions.add_parser("probe", help="연결 시험: kb_project_info 한 번 (60초)")
    common(probe)
    agent_args(probe)

    schedule = actions.add_parser("schedule", help="예약 실행 (Windows 작업 스케줄러)")
    schedule.add_argument("op", choices=["install", "remove", "show"])
    common(schedule)
    schedule.add_argument("--playbook", required=True, choices=[n for n in NAMES if n != "probe"])
    schedule.add_argument("--daily", default="09:00", metavar="HH:MM", help="매일 시작 시각")
    schedule.add_argument("--agent", help="Agent 프로필")
    schedule.add_argument("--dry-run", action="store_true", help="XML·명령만 출력한다")

    playbooks = actions.add_parser("playbooks", help="배포된 플레이북과 판")
    playbooks.add_argument("--json", action="store_true", help="결과 JSON 한 개만 출력한다")


# ---------------------------------------------------------------- daemon 연결


class _Link:
    """소유 연결 (`ui`, 이름 agent-job). `runner.DaemonLink`."""

    def __init__(self, root: Path) -> None:
        from kookabug_cli import __version__
        from kookabug_daemon.client import DaemonClient, attach, spawn_daemon

        info = attach(root, spawn=spawn_daemon)
        if info is None:
            raise ConnectionError(f"{root}의 daemon에 붙지 못했다 (기한 초과)")
        self.ident = info.ident
        client = {"kind": "ui", "name": "agent-job", "version": __version__}
        self.client = DaemonClient.connect(info.port, info.token, client=client)
        self.notifications = self.client.notifications

    def call(self, method: str, params: Any, timeout: float = 60.0) -> Any:
        return self.client.call(method, dict(params), timeout=timeout)

    @property
    def lost(self) -> bool:
        return self.client.closed.is_set()

    def gone(self, timeout: float) -> bool:
        """붙었던 daemon 프로세스(PID + 생성 시각)가 없어졌다. 살아 있으면(같은 프로세스 안의 daemon
        인스턴스만 끝난 경우 포함) 그 감독이 끝났다고 보지 않는다."""
        import time

        from kookabug_core.win import is_alive

        deadline = time.monotonic() + timeout
        while True:
            try:
                alive = is_alive(self.ident)
            except Exception:
                alive = True
            if not alive:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)

    def close(self) -> None:
        self.client.close()


def connect_daemon(root: Path) -> _Link:
    return _Link(root)


# ---------------------------------------------------------------- 실행


def _root(given: str | None) -> Path:
    from kookabug_core.workspace import Workspace

    return (Workspace.open(Path(given)) if given else Workspace.find(Path.cwd())).root


def _profile(args: argparse.Namespace) -> str:
    from kookabug_core.agent_job.profiles import PROFILES

    agent = args.agent or ("custom" if args.agent_command else None)
    if agent is None:
        raise ValueError("--agent 또는 --agent-command가 필요하다")
    if agent not in PROFILES:
        raise ValueError(f"모르는 Agent 프로필이다: {agent} (claude·codex·custom)")
    return agent


def run(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    report: dict[str, Any] = {"command": f"agent-job {args.action}"}
    as_json = bool(getattr(args, "json", False))

    def finish(code: int, text: str, /, **extra: Any) -> int:
        # 위치 전용: 작업 결과의 `code`(예: job_active)가 종료 코드 인자와 부딪히지 않게
        report.update(extra)
        report.update(exit_code=code, message=text)
        if as_json:
            print(json.dumps(report, ensure_ascii=False), file=out)
        else:
            print(text, file=out if code == 0 else err)
        return code

    if AGENT_ENV in os.environ:
        return finish(
            EXIT_DENIED, "agent-job은 사람만 쓴다 (KOOKABUG_AGENT)", error_code="agent_only"
        )
    if args.action == "playbooks":
        from kookabug_core import playbooks

        versions = playbooks.versions()
        text = "\n".join(f"{name} 판 {v}" for name, v in versions.items())
        return finish(EXIT_OK, text, playbooks=versions)
    from kookabug_core.workspace import WorkspaceError

    try:
        root = _root(args.workspace)
    except WorkspaceError as exc:
        return finish(EXIT_USAGE, f"오류: {exc}", error_code="workspace_invalid")
    try:
        if args.action in ("run", "probe"):
            return _run(args, root, out, err, finish)
        if args.action in ("status", "list"):
            return _status(args, root, finish)
        if args.action == "cancel":
            return _cancel(args, root, finish)
        return _schedule(args, root, finish)
    except ValueError as exc:
        return finish(EXIT_USAGE, f"오류: {exc}", error_code="usage")


def _run(args: argparse.Namespace, root: Path, out: TextIO, err: TextIO, finish: Any) -> int:
    from kookabug_core.agent_job.jobdir import LAUNCH_TAG
    from kookabug_core.agent_job.runner import JobOptions, run_job

    probe = args.action == "probe"
    tag = None if probe else args.launch_tag
    if tag is not None and not LAUNCH_TAG.fullmatch(tag):
        raise ValueError("--launch-tag는 소문자 hex 32자다")
    options = JobOptions(
        root=root,
        playbook="probe" if probe else args.playbook,
        agent=_profile(args),
        agent_command=args.agent_command,
        basis="team" if probe else args.basis,
        minutes=1 if probe else args.minutes,
        runs=1 if probe else args.runs,
        trigger="manual" if probe else args.trigger,
        pass_env=list(args.pass_env),
        launch_tag=tag,
    )
    if args.grace_s is not None:
        options.grace_s = float(args.grace_s)
    outcome = run_job(options, out=err if args.json else out, connect=connect_daemon)
    data = outcome.to_json()
    if probe:
        ok = outcome.exit_code in (0, 1) and bool(outcome.extra.get("probe_ok"))
        code = EXIT_OK if ok else (outcome.exit_code if outcome.exit_code > 1 else EXIT_REFUSED)
        text = "연결 시험 성공 (kb_project_info 호출을 봤다)" if ok else "연결 시험 실패"
        data.pop("exit_code", None)
        data.pop("message", None)
        return finish(code, text, **data)
    data.pop("exit_code", None)
    message = data.pop("message", "")
    text = f"작업 {outcome.job or '-'}: {outcome.state or message}"
    return finish(outcome.exit_code, text, **data)


def _status(args: argparse.Namespace, root: Path, finish: Any) -> int:
    from kookabug_core.agent_job import jobdir

    jobs = list(jobdir.list_jobs(root))
    if args.action == "list":
        lines = [f"{j.get('id')} {j.get('playbook')} {j.get('state')}" for j in jobs]
        return finish(EXIT_OK, "\n".join(lines) or "작업이 없다", jobs=jobs)
    if args.job:
        doc = jobdir.read_job(root, args.job) if jobdir.JOB_ID.fullmatch(args.job) else None
    else:
        doc = jobs[-1] if jobs else None
    if doc is None:
        return finish(EXIT_REFUSED, "그런 작업이 없다", error_code="not_found")
    return finish(EXIT_OK, f"{doc.get('id')} {doc.get('playbook')} {doc.get('state')}", job=doc)


def _cancel(args: argparse.Namespace, root: Path, finish: Any) -> int:
    from kookabug_core.agent_job import jobdir

    if not jobdir.JOB_ID.fullmatch(args.job):
        raise ValueError(f"작업 ID 형식이 틀렸다: {args.job}")
    try:
        link = connect_daemon(root)
    except Exception as exc:
        return finish(EXIT_USAGE, f"오류: daemon에 붙지 못했다: {exc}", error_code="daemon")
    try:
        ended = link.call("job.end", {"job": args.job, "reason": "cancelled"}, timeout=300)
    except Exception as exc:
        kind = getattr(exc, "kind", None) or "daemon"
        return finish(EXIT_REFUSED, f"오류: 취소하지 못했다 ({kind})", error_code=kind)
    finally:
        link.close()
    return finish(EXIT_OK, f"작업 {args.job}: {ended.get('state')}", **ended)


def _schedule(args: argparse.Namespace, root: Path, finish: Any) -> int:
    from kookabug_core.agent_job import schedule
    from kookabug_core.workspace import Workspace, ensure_workspace_id, workspace_id

    wid = workspace_id(Workspace.open(root))
    if args.op == "install" and not args.dry_run and wid is None:
        wid = ensure_workspace_id(root)
    try:
        made = schedule.plan(
            root,
            workspace_id=wid or "unassigned",
            playbook=args.playbook,
            daily=args.daily,
            agent=args.agent,
        )
    except schedule.ScheduleError as exc:
        return finish(EXIT_USAGE, f"오류: {exc}", error_code=exc.code)
    if args.op == "install":
        if args.dry_run:
            return finish(
                EXIT_OK,
                f"{made.xml}\n{' '.join(made.command)}",
                name=made.name,
                xml=made.xml,
                xml_path=made.xml_rel,
                schtasks=made.command,
                dry_run=True,
            )
        code = schedule.install(root, made)
        return finish(
            EXIT_OK if code == 0 else EXIT_REFUSED,
            f"예약 등록 {made.name} (schtasks {code})",
            name=made.name,
        )
    command = (
        schedule.delete_command(made.name)
        if args.op == "remove"
        else schedule.query_command(made.name)
    )
    if args.dry_run:
        return finish(EXIT_OK, " ".join(command), name=made.name, schtasks=command, dry_run=True)
    code = schedule.remove(made.name) if args.op == "remove" else _query(command)
    return finish(
        EXIT_OK if code == 0 else EXIT_REFUSED,
        f"{args.op} {made.name} (schtasks {code})",
        name=made.name,
    )


def _query(command: list[str]) -> int:
    import subprocess

    return subprocess.run(command, stdin=subprocess.DEVNULL, check=False).returncode
