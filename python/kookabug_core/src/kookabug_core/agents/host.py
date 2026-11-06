"""에이전트 패널 세션의 실행 도우미 (M5 B5 검수 H1·M2): `kookabug agent-host`.

    kookabug agent-host --workspace <루트> [--env 이름=값]... [--secret-env 이름=키]...
                        -- <명령> [인자...]

앱(Electron 주 프로세스)이 패널 에이전트를 직접 띄우지 않고 이 도우미로 감싸 띄운다.

- 도우미는 자기 자신을 새 Job(`kill_on_close`)에 넣은 뒤 에이전트를 띄운다: 에이전트와 그 자손
  (`kookabug mcp`·npm 런처 아래 node 등)이 처음부터 같은 Job이다. 에이전트가 스스로 끝나거나
  죽으면 도우미가 Job을 끝내고 나가고, 앱이 도우미를 끝내거나 앱이 죽어 입력이 닫히면 Job이
  끝난다(핸들이 닫혀도 끝난다). 자손 `kookabug mcp`가 죽으면 daemon 연결이 끊겨 그 연결의 확인
  요청이 취소된다(B3 broker)
- stdin·stdout은 그대로 잇는다(ACP 줄). 에이전트 stderr는 버린다. 도우미 자기 오류만 stderr에
- 에이전트 환경: 도우미 환경에서 `KOOKABUG_*`를 모두 빼고 `--env`를 더하고, `--secret-env`는
  실행 직전에 워크스페이스 비밀값 제공자(`default_secrets`)에서 찾아 넣는다. 값은 어디에도 쓰지
  않는다. 못 찾으면 에이전트를 띄우지 않고 종료 코드 7
- 에이전트 stdout은 줄 단위로 모아 푼 비밀값(원문·JSON 이스케이프)을 `***`로 바꾼 뒤 앱에 넘긴다
  (검수 B5 H2 — 에이전트가 받은 값을 답·오류로 되돌려도 앱·렌더러·로그에 원문이 가지 않는다)
- Job을 만들거나 도우미를 그 Job에 넣지 못하면 에이전트를 띄우지 않고 종료 코드 8 (검수 B5 H1)
"""

from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from kookabug_core.agents.judge import Scrubber

__all__ = ["EXIT_JOB", "EXIT_SETUP", "add_parser", "agent_env", "relay_lines", "run"]

EXIT_SETUP: Final = 7
"""띄우기 전 실패 (워크스페이스·비밀값·명령을 찾지 못함)."""
EXIT_JOB: Final = 8
"""자손 정리를 보장할 Job을 만들거나 도우미를 그 Job에 넣지 못함 — 에이전트를 띄우지 않는다."""
_ENV_PREFIX: Final = "KOOKABUG_"
_CHUNK: Final = 64 * 1024


class SetupError(Exception):
    """에이전트를 띄우기 전 실패 (메시지에 비밀값 원문을 넣지 않는다)."""


def add_parser(commands: Any) -> None:
    host: argparse.ArgumentParser = commands.add_parser(
        "agent-host",
        help="에이전트 패널 세션 도우미 (앱이 쓴다): 에이전트와 자손을 한 Job에 넣어 띄운다",
        description="에이전트 CLI를 Job 하나에 넣어 띄우고 stdio를 잇는다. 에이전트가 끝나거나 "
        "입력이 닫히면 Job을 끝낸다 (7 띄우기 전 실패)",
    )
    host.add_argument("--workspace", required=True, help="워크스페이스 루트 (에이전트 작업 폴더)")
    host.add_argument("--env", action="append", default=[], metavar="이름=값")
    host.add_argument("--secret-env", action="append", default=[], metavar="이름=키")
    host.add_argument("agent", nargs=argparse.REMAINDER, help="-- 뒤에 에이전트 명령과 인자")


def _pairs(items: Sequence[str], what: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in items:
        name, sep, value = item.partition("=")
        if not sep or not name:
            raise SetupError(f"{what} 인자 형식이 틀렸다 (이름=값): {name or item[:20]}")
        out.append((name, value))
    return out


def agent_env(
    base: Mapping[str, str],
    plain: Sequence[tuple[str, str]],
    secret: Sequence[tuple[str, str]],
    lookup: Any,
    used: Scrubber | None = None,
) -> dict[str, str]:
    """에이전트 환경: `KOOKABUG_*` 제거 → 글자 값 → 비밀값(찾아서). `lookup(key) -> str | None`.
    찾은 비밀값은 `used`에 넣는다 (에이전트 출력을 앱에 넘기기 전에 가린다)."""
    env = {k: v for k, v in base.items() if not k.upper().startswith(_ENV_PREFIX)}
    for name, value in plain:
        if not name.upper().startswith(_ENV_PREFIX):
            env[name] = value
    for name, key in secret:
        if name.upper().startswith(_ENV_PREFIX):
            continue
        found = lookup(key)
        if found is None:
            raise SetupError(f"에이전트 env {name}의 비밀값 키 '{key}'를 찾지 못했다")
        env[name] = found
        if used is not None:
            used.add(found)
    return env


def _pump(src: IO[bytes], dst: IO[bytes]) -> None:
    with contextlib.suppress(OSError, ValueError):
        while True:
            data = src.read1(_CHUNK) if hasattr(src, "read1") else src.read(_CHUNK)  # pyright: ignore[reportAttributeAccessIssue]
            if not data:
                break
            dst.write(data)
            dst.flush()


def relay_lines(src: IO[bytes], dst: IO[bytes], scrub: Scrubber) -> None:
    """에이전트 stdout → 앱. ACP는 줄 단위 JSON이라 줄로 모아(줄바꿈 전 부분 데이터도 다음
    줄바꿈까지) 한 줄씩 푼 비밀값(원문·JSON 이스케이프 형태)을 `***`로 바꿔 넘긴다 — 조각 경계에
    걸친 값도 가린다. 비밀값이 없으면 바꾸지 않는다."""
    with contextlib.suppress(OSError, ValueError):
        for line in iter(src.readline, b""):
            if scrub.active:
                text = line.decode("utf-8", errors="surrogateescape")
                line = scrub(text).encode("utf-8", errors="surrogateescape")
            dst.write(line)
            dst.flush()


def run(
    args: argparse.Namespace,
    *,
    stdin: IO[bytes] | None = None,
    stdout: IO[bytes] | None = None,
    stderr: IO[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    from kookabug_core.agents.acp import _resolve  # pyright: ignore[reportPrivateUsage]
    from kookabug_core.win import CHILD_FLAGS, Job
    from kookabug_core.workspace import Workspace, default_secrets

    inp = stdin if stdin is not None else sys.stdin.buffer
    out = stdout if stdout is not None else sys.stdout.buffer
    err = stderr if stderr is not None else sys.stderr
    from kookabug_core.agents.judge import Scrubber

    base = dict(os.environ if environ is None else environ)
    scrub = Scrubber()
    command = list(args.agent)
    if command and command[0] == "--":
        command = command[1:]
    try:
        if not command:
            raise SetupError("에이전트 명령이 없다 (-- 뒤에 명령)")
        try:
            workspace = Workspace.open(Path(args.workspace))
        except Exception as exc:  # 워크스페이스 오류 종류가 여럿이다
            raise SetupError(f"워크스페이스를 열 수 없다: {exc}") from exc
        secrets = default_secrets(workspace)
        env = agent_env(
            base,
            _pairs(args.env, "--env"),
            _pairs(args.secret_env, "--secret-env"),
            secrets.get,
            scrub,
        )
        exe = _resolve(command[0], env)
        if exe is None:
            raise SetupError(f"에이전트 명령 '{command[0]}'을(를) 찾지 못했다")
    except SetupError as exc:
        print(f"agent-host: {exc}", file=err, flush=True)
        return EXIT_SETUP

    # 자손 정리를 보장하지 못하면 띄우지 않는다 (띄운 뒤 넣기는 그 사이 생긴 자손이 Job 밖에 남는다)
    try:
        job = Job.create()
    except OSError as exc:
        print(f"agent-host: 에이전트를 묶을 Job을 만들지 못했다: {exc}", file=err, flush=True)
        return EXIT_JOB
    try:
        job.assign_current()  # 이후 띄우는 에이전트와 자손은 생성 시점부터 Job 소속
    except OSError as exc:
        job.close()
        print(f"agent-host: 도우미를 Job에 넣지 못했다: {exc}", file=err, flush=True)
        return EXIT_JOB
    try:
        proc = subprocess.Popen(
            [exe, *command[1:]],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(workspace.root),
            env=env,
            creationflags=CHILD_FLAGS,
        )
    except OSError as exc:
        print(f"agent-host: 에이전트를 띄우지 못했다: {exc}", file=err, flush=True)
        job.close()
        return EXIT_SETUP
    assert proc.stdin is not None and proc.stdout is not None
    child_in, child_out = proc.stdin, proc.stdout

    def forward_input() -> None:
        _pump(inp, child_in)
        # 앱이 입력을 닫았다(세션 끝·앱 종료): 에이전트와 자손을 끝낸다
        with contextlib.suppress(OSError):
            child_in.close()
        _end(job, proc)

    reader = threading.Thread(target=relay_lines, args=(child_out, out, scrub), daemon=True)
    writer = threading.Thread(target=forward_input, daemon=True)
    reader.start()
    writer.start()
    code = proc.wait()
    reader.join(2)
    _end(job, proc)
    return code if code >= 0 else 1


def _end(job: Any, proc: subprocess.Popen[bytes]) -> None:
    """Job 안 모두를 끝낸다. 도우미도 Job 안이면 함께 끝난다(종료 코드 = 에이전트 종료 코드, 입력이
    닫혀 끝낸 경우 1) — 그래서 마지막에 부른다."""
    code = proc.returncode if proc.returncode is not None and proc.returncode >= 0 else 1
    with contextlib.suppress(OSError, ValueError):
        sys.stdout.flush()
    with contextlib.suppress(OSError):
        job.terminate(code)
    if proc.poll() is None:
        with contextlib.suppress(OSError):
            proc.kill()
