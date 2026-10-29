"""프로세스 테스트 공용 헬퍼 (구현 계획 M0b 2.3 "동기화 규칙"·2.12).

테스트는 `events.jsonl`, 가짜 입력 기록, 장벽 `.ready` 파일만으로 기다린다(`wait_until`).
순서를 맞추려는 `sleep`은 쓰지 않는다. 죽이기는 `TerminateProcess`만.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from kookabug_core.win import Process, ProcessId, is_alive

__all__ = [
    "DIRECT_PYTHON",
    "PROCS_DIR",
    "Barrier",
    "Spawned",
    "assert_no_live",
    "barrier",
    "direct_env",
    "faults_env",
    "inner_pytest",
    "isolated_env",
    "python_cmd",
    "read_fake_input_log",
    "read_tree",
    "wait_until",
]

DEFAULT_TIMEOUT: Final = 30.0
DEFAULT_INTERVAL: Final = 0.02

TOOLS_DIR: Final = Path(__file__).resolve().parents[1]

# venv의 python.exe(`sys.executable`)는 실제 인터프리터를 자식으로 띄우는 런처이고, 런처가 끝나면
# 자기 Job으로 자손까지 끝낸다. 그 정리가 Job 수명·고아 정리 검사의 결과를 대신하지 않게, 그런
# 검사는 기반 인터프리터를 직접 띄우고 `__PYVENV_LAUNCHER__`로 이 venv를 쓰게 한다 (런처가 하는
# 일과 같다). 그러면 `Popen.pid`가 실제 파이썬의 PID다
VENV_PYTHON: Final = sys.executable
DIRECT_PYTHON: Final = getattr(sys, "_base_executable", sys.executable)
# 테스트 보조 스크립트 (자식·손자를 띄우고 식별을 쓰는 스크립트 등)
PROCS_DIR: Final = TOOLS_DIR.parent / "python/kookabug_core/tests/procs"


def wait_until[T](
    condition: Callable[[], T],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
    message: str | Callable[[], str] = "",
) -> T:
    """조건이 참이 될 때까지 기다려 그 값을 돌려준다. 기한을 넘기면 `AssertionError`."""
    deadline = time.monotonic() + timeout
    while True:
        value = condition()
        if value:
            return value
        if time.monotonic() >= deadline:
            detail = message() if callable(message) else message
            raise AssertionError(f"{timeout}초 안에 조건이 맞지 않았다: {detail}")
        time.sleep(interval)


def isolated_env(
    tmp_path: Path, base: Mapping[str, str] | None = None, **extra: str
) -> dict[str, str]:
    """개발자 PC·다른 테스트와 부딪히지 않는 환경 변수. 바깥의 `KOOKABUG_*`는 모두 지운다.

    두 실행이 임대권을 다투는 테스트는 같은 `KOOKABUG_INPUT_LEASE_NAME`을 일부러 넘긴다.
    """
    env = {
        name: value
        for name, value in (os.environ if base is None else base).items()
        if not name.upper().startswith("KOOKABUG_")
    }
    env["KOOKABUG_INPUT_LEASE_NAME"] = f"Local\\Kookabug.InputLease.test-{uuid.uuid4().hex}"
    env["KOOKABUG_STATE_DIR"] = str(tmp_path / "state")
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp_path / "user-config")
    env.update(extra)
    return env


def faults_env(
    rules: Sequence[Mapping[str, Any]], base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """고장 주입 규칙(`kookabug_sdk._faults`)을 실은 환경 변수."""
    env = dict(os.environ if base is None else base)
    env["KOOKABUG_FAULTS"] = json.dumps(list(rules))
    return env


@dataclass(frozen=True, slots=True)
class Barrier:
    """파일 장벽. 기다리는 쪽(`_faults`의 `wait:<경로>` 동작 등)이 `<경로>.ready`를 만들고
    `<경로>.go`가 생길 때까지 기다린다."""

    path: Path

    @property
    def action(self) -> str:
        """고장 규칙의 `action` 값."""
        return f"wait:{self.path}"

    @property
    def ready_file(self) -> Path:
        return Path(f"{self.path}.ready")

    @property
    def go_file(self) -> Path:
        return Path(f"{self.path}.go")

    def is_ready(self) -> bool:
        return self.ready_file.exists()

    def wait_ready(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        wait_until(self.is_ready, timeout=timeout, message=f"장벽 {self.ready_file}")

    def go(self) -> None:
        self.go_file.touch()


def barrier(path: Path) -> Barrier:
    path.parent.mkdir(parents=True, exist_ok=True)
    return Barrier(path)


def read_fake_input_log(path: Path) -> list[dict[str, Any]]:
    """가짜 입력 백엔드의 JSONL 기록. 쓰는 중에 죽어 잘린 끝 줄은 버린다."""
    if not path.exists():
        return []
    lines = path.read_bytes().split(b"\n")
    return [json.loads(line) for line in lines[:-1] if line.strip()]


def read_tree(out_dir: Path) -> dict[int, dict[str, Any]]:
    """`procs/tree.py`가 쓴 단계별 식별(`level<N>.json`)."""
    return {
        int(path.stem.removeprefix("level")): json.loads(path.read_text(encoding="utf-8"))
        for path in out_dir.glob("level*.json")
    }


def assert_no_live(idents: Iterable[ProcessId], timeout: float = DEFAULT_TIMEOUT) -> None:
    """모든 프로세스가 끝났다 (PID+생성 시각으로 판정, 종료 반영까지 기다린다)."""
    targets = list(idents)
    wait_until(
        lambda: not any(is_alive(i) for i in targets),
        timeout=timeout,
        message=lambda: f"아직 살아 있다: {[i for i in targets if is_alive(i)]}",
    )


def direct_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """`DIRECT_PYTHON`이 이 venv의 패키지를 쓰게 하는 환경 변수."""
    env = dict(os.environ if base is None else base)
    env["__PYVENV_LAUNCHER__"] = VENV_PYTHON
    return env


def python_cmd(*args: str | Path) -> list[str]:
    """런처 없이 이 venv의 파이썬을 띄우는 명령 (환경은 `direct_env()`)."""
    return [DIRECT_PYTHON, *(str(a) for a in args)]


def inner_pytest(
    test_file: Path, *args: str, plugin: bool = True, timeout: float = 120
) -> subprocess.CompletedProcess[str]:
    """별도 pytest 프로세스로 검사 파일 하나를 런처 없이 돌린다.
    `plugin`이면 같은 플러그인(세션 Job·정리 픽스처)을 쓴다 (False는 음성 대조용)."""
    env = direct_env({**os.environ, "PYTHONPATH": str(TOOLS_DIR)})
    env.pop("KOOKABUG_FAULTS", None)
    cmd = python_cmd("-m", "pytest", test_file, "-p", "no:cacheprovider")
    if plugin:
        cmd += ["-p", "kb_testing.pytest_plugin"]
    cmd += ["--rootdir", str(test_file.parent), "-q", *args]
    return subprocess.run(
        cmd,
        cwd=test_file.parent,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


class Spawned:
    """테스트가 띄운 프로세스 목록. `close()`가 남은 것을 `TerminateProcess`로 끝낸다.

    일반 실패에서는 이것이 먼저 정리하고, pytest가 timeout으로 강제 종료되면 세션 Job이 정리한다.
    """

    def __init__(self) -> None:
        self._items: list[subprocess.Popen[Any] | ProcessId] = []

    def track[P: (subprocess.Popen[Any], ProcessId)](self, item: P) -> P:
        self._items.append(item)
        return item

    def popen(self, args: Sequence[str | Path], **kwargs: Any) -> subprocess.Popen[bytes]:
        return self.track(subprocess.Popen([str(a) for a in args], **kwargs))

    def close(self, timeout: float = 10.0) -> None:
        items, self._items = self._items, []
        for item in items:
            if isinstance(item, ProcessId):
                try:
                    with Process.open(item, terminate=True) as proc:
                        proc.terminate()
                        proc.wait(timeout)
                except ProcessLookupError:
                    pass
            elif item.poll() is None:
                item.kill()
                item.wait(timeout)
