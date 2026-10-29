"""입력 임대권 프로세스 테스트 헬퍼 (M0b T6).

env = LeaseEnv.make(tmp_path)              # 테스트마다 다른 뮤텍스 이름·상태 폴더·가짜 입력 기록
a = spawn_holder(spawned, env, "a", script=[{"op": "key", "key": "ctrl"}], hooks=...)
a.wait_status("acquired.json")
b = env.lease("b")                          # 이 프로세스 안의 임대권 (같은 이름·상태 폴더)
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kb_testing.proc import (
    PROCS_DIR,
    Spawned,
    direct_env,
    faults_env,
    isolated_env,
    python_cmd,
    read_fake_input_log,
    wait_until,
)
from kookabug_core.inputs import FakeBackend, HookAction, InputActor, InputLease, LeaseOwner
from kookabug_core.inputs.lease import LEASE_NAME_ENV, STATE_DIR_ENV
from kookabug_core.record import Journal
from kookabug_core.record.runfolder import EVENTS_FILE

__all__ = ["Holder", "InProcess", "LeaseEnv", "spawn_holder", "spawn_sleeper"]


@dataclass(slots=True)
class InProcess:
    """이 프로세스 안의 임대권 소유자 (runner 역할)."""

    run_id: str
    run_dir: Path
    journal: Journal
    backend: FakeBackend
    lease: InputLease
    gate: threading.Event

    def actor(self) -> InputActor:
        return InputActor(self.backend, emit=self.journal.emit, gate=self.gate).start()


@dataclass(slots=True)
class LeaseEnv:
    root: Path
    env: dict[str, str]
    log: Path

    @classmethod
    def make(cls, tmp_path: Path) -> LeaseEnv:
        return cls(tmp_path, isolated_env(tmp_path), tmp_path / "input.jsonl")

    @property
    def name(self) -> str:
        return self.env[LEASE_NAME_ENV]

    @property
    def state_dir(self) -> Path:
        return Path(self.env[STATE_DIR_ENV])

    def run_dir(self, label: str) -> Path:
        return self.root / "runs" / label

    def lease(
        self,
        label: str,
        *,
        hooks: Mapping[str, Mapping[str, HookAction]] | None = None,
    ) -> InProcess:
        run_id = run_id_for(label)
        run_dir = self.run_dir(label)
        run_dir.mkdir(parents=True, exist_ok=True)
        journal = Journal(run_dir / EVENTS_FILE, run_id)
        gate = threading.Event()
        backend = FakeBackend(self.log, run=run_id, by=label, hooks=hooks, gate=gate)
        owner = LeaseOwner.current("runner", run_id=run_id, run_dir=run_dir)
        lease = InputLease(
            owner, backend, name=self.name, directory=self.state_dir, emit=journal.emit
        )
        return InProcess(run_id, run_dir, journal, backend, lease, gate)

    def log_lines(self) -> list[dict[str, Any]]:
        return read_fake_input_log(self.log)

    def wait_log(self, **match: Any) -> list[dict[str, Any]]:
        """`match`의 필드가 모두 같은 줄이 생길 때까지 기다려 기록 전체를 돌려준다."""

        def found() -> list[dict[str, Any]]:
            lines = self.log_lines()
            hit = any(all(line.get(k) == v for k, v in match.items()) for line in lines)
            return lines if hit else []

        return wait_until(found, message=f"가짜 입력 기록에 {match}")


def run_id_for(label: str) -> str:
    """테스트 실행 ID (`[a-z0-9]` 8자)."""
    return (label + "00000000")[:8]


@dataclass(slots=True)
class Holder:
    """`procs/lease_holder.py` 프로세스."""

    label: str
    proc: subprocess.Popen[bytes]
    out: Path
    run_dir: Path
    run_id: str
    files: dict[str, Path] = field(default_factory=dict[str, Path])

    def status(self, name: str) -> Any:
        path = self.out / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def wait_status(self, name: str, timeout: float = 30) -> Any:
        wait_until(
            lambda: (self.out / name).exists() or self.proc.poll() is not None,
            timeout=timeout,
            message=f"{self.label}: {name}",
        )
        value = self.status(name)
        if value is None:
            raise AssertionError(
                f"{self.label}가 {name} 없이 끝났다 (종료 코드 {self.proc.poll()}): {self.stderr()}"
            )
        return value

    def cancel(self) -> None:
        (self.out / "cancel").touch()

    def stderr(self) -> str:
        path = self.files.get("stderr")
        return path.read_text(encoding="utf-8", errors="replace") if path else ""


def spawn_holder(
    spawned: Spawned,
    env: LeaseEnv,
    label: str,
    *,
    mode: str = "hold",
    script: Sequence[Mapping[str, Any]] = (),
    hooks: Mapping[str, Mapping[str, str]] | None = None,
    faults: Sequence[Mapping[str, Any]] = (),
    lease_timeout: float = 0,
    target: Path | None = None,
    timeout: float = 10,
) -> Holder:
    out = env.root / "holders" / label
    out.mkdir(parents=True, exist_ok=True)
    run_id = run_id_for(label)
    run_dir = env.run_dir(label)
    spec: dict[str, Any] = {
        "mode": mode,
        "out": str(out),
        "by": label,
        "input_log": str(env.log),
        "hooks": dict(hooks or {}),
        "run_dir": str(run_dir),
        "run_id": run_id,
        "lease_timeout": lease_timeout,
        "script": list(script),
        "timeout": timeout,
    }
    if target is not None:
        spec["target_run_dir"] = str(target)
    spec_path = out / "spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    proc_env = faults_env(faults, env.env) if faults else dict(env.env)
    stdout, stderr = out / "stdout.log", out / "stderr.log"
    with stdout.open("wb") as o, stderr.open("wb") as e:
        proc = spawned.popen(
            python_cmd(PROCS_DIR / "lease_holder.py", spec_path),
            env=direct_env(proc_env),
            stdout=o,
            stderr=e,
        )
    return Holder(label, proc, out, run_dir, run_id, {"stdout": stdout, "stderr": stderr})


def spawn_sleeper(spawned: Spawned, env: LeaseEnv) -> subprocess.Popen[bytes]:
    """아무것도 하지 않는 감독자 역할 프로세스 (이중 고장에서 함께 죽인다)."""
    return spawned.popen(python_cmd("-c", "import time; time.sleep(600)"), env=direct_env(env.env))
