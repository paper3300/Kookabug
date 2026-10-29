"""`kookabug` CLI 검사 헬퍼 (M0b T11). CLI 프로세스가 감독자다.

    env = cli_env(tmp_path)
    done = run_cli(["run", "tests/t.graph.json", "--json"], cwd=ws_root, env=env)

    cli = CliProcess.start(spawned, ["run", ...], cwd=ws_root, env=env)   # 기다리지 않는다
    run_dir = cli.run_dir()          # 워크스페이스 runs/ 아래 이 실행의 폴더
    cli.runner_ident()               # run.start의 runner 식별 (런처가 아닌 실제 runner)
    cli.kill()                       # 감독자(CLI) 프로세스를 TerminateProcess로

CLI는 런처 없이 띄우고(`python_cmd`, `Popen.pid`가 CLI), runner는 제품 그대로 CLI가 띄운다
(`sys.executable -m kookabug_core.runner`).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from helpers.worker import worker_env
from kb_testing.proc import Spawned, direct_env, python_cmd, wait_until
from kookabug_core.record import RunView, read_run
from kookabug_core.runner.run import unix_micros
from kookabug_core.win import CHILD_FLAGS, Process, ProcessId, identify

__all__ = ["CLI", "CliProcess", "cli_env", "platform_file", "run_cli"]

CLI: Final = python_cmd("-m", "kookabug_cli")


def cli_env(
    tmp_path: Path, faults: Sequence[Mapping[str, Any]] | None = None, **extra: str
) -> dict[str, str]:
    """격리 환경 + testkit `PYTHONPATH` + 고장 규칙, 런처 없이 이 venv를 쓰는 환경."""
    return direct_env(worker_env(tmp_path, faults, **extra))


def platform_file(
    tmp_path: Path, hooks: Mapping[str, Mapping[str, str]] | None = None
) -> tuple[Path, Path]:
    """`--platform-fake` 사양 파일과 가짜 입력 기록 경로."""
    log = tmp_path / "input.jsonl"
    spec = tmp_path / "platform.json"
    spec.write_text(
        json.dumps(
            {"input_log": str(log), "hooks": {k: dict(v) for k, v in (hooks or {}).items()}}
        ),
        encoding="utf-8",
    )
    return spec, log


def run_cli(
    args: Sequence[str | Path], *, cwd: Path, env: Mapping[str, str], timeout: float = 90
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*CLI, *(str(a) for a in args)],
        cwd=cwd,
        env=dict(env),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


@dataclass
class CliProcess:
    proc: subprocess.Popen[bytes]
    runs: Path
    out: Path

    @classmethod
    def start(
        cls,
        spawned: Spawned,
        args: Sequence[str | Path],
        *,
        cwd: Path,
        env: Mapping[str, str],
        out: Path,
    ) -> CliProcess:
        out.mkdir(parents=True, exist_ok=True)
        with (
            (out / "cli.stdout.log").open("ab") as stdout,
            (out / "cli.stderr.log").open("ab") as stderr,
        ):
            proc = spawned.popen(
                [*CLI, *(str(a) for a in args)],
                cwd=cwd,
                env=dict(env),
                stdout=stdout,
                stderr=stderr,
                creationflags=CHILD_FLAGS,
            )
        return cls(proc, cwd / "runs", out)

    def output(self) -> str:
        parts = []
        for name in ("cli.stdout.log", "cli.stderr.log"):
            path = self.out / name
            if path.exists():
                parts.append(f"--- {name}\n{path.read_text('utf-8', errors='replace')[-4000:]}")
        folders = list(self.runs.glob("*/logs")) if self.runs.exists() else []
        for logs in folders:
            for path in sorted(logs.glob("*.stderr.log")):
                text = path.read_text("utf-8", errors="replace").strip()
                if text:
                    parts.append(f"--- {path.name}\n{text[-4000:]}")
        return "\n".join(parts)

    def run_dir(self) -> Path:
        def found() -> Path | None:
            folders = [p for p in self.runs.glob("*") if p.is_dir()] if self.runs.exists() else []
            return folders[0] if len(folders) == 1 else None

        folder = wait_until(found, message=self.output)
        assert folder is not None
        return folder

    def view(self) -> RunView:
        return read_run(self.run_dir())

    def runner_ident(self) -> ProcessId:
        def started() -> dict[str, Any] | None:
            return self.view().run_start

        # run.start의 생성 시각은 유닉스 마이크로초다. 살아 있는 runner를 PID로 식별해 맞춰 본다
        run_start = wait_until(started, message=self.output)
        assert run_start is not None
        runner = run_start["runner"]
        ident = identify(runner["pid"])
        assert ident is not None and unix_micros(ident) == runner["created"], (ident, runner)
        return ident

    def kill_runner(self) -> None:
        with Process.open(self.runner_ident(), terminate=True) as runner:
            runner.terminate(1)
            runner.wait(10)

    def kill(self) -> None:
        """감독자(CLI) 프로세스를 끝낸다 (그 Job 핸들도 OS가 닫는다)."""
        self.proc.kill()
        self.proc.wait(10)

    def wait(self, timeout: float = 60) -> int:
        return self.proc.wait(timeout)

    def stdout(self) -> str:
        return (self.out / "cli.stdout.log").read_text("utf-8", errors="replace")
