"""uv 찾기·환경·실행 (M6 계획 D2, 3.5 "프로세스 소유").

- uv: `KOOKABUG_UV` → `<앱>\\tools\\uv\\uv.exe` → (개발) PATH
- 환경 변수: 사용자 uv 설정을 쓰지 않는다(`UV_NO_CONFIG=1`), Python을 받지 않는다
  (`UV_PYTHON_DOWNLOADS=never`), 캐시 `%LOCALAPPDATA%\\Kookabug\\uv-cache`. 다른 `UV_*`·venv·
  `PYTHONPATH` 변수는 지우고 프록시 변수는 통과. 링크 방식은 늘 복사(`UV_LINK_MODE=copy`) —
  환경끼리·캐시와 파일을 나누지 않는다
- 거래가 띄우는 모든 자식은 거래의 **설치 작업 Job**에 든다: 멈춘 채 띄워 Job에 넣고 이어 돌린다
  (`KILL_ON_JOB_CLOSE`). 취소·CLI 죽음 = Job 핸들 닫힘 = 손자까지 끝
- 모든 명령과 출력은 작업 로그에 쓴다 (URL의 사용자 정보는 가림). `calls`는 검사가 본다
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from kookabug_core.plugins.errors import PluginError
from kookabug_core.win import CHILD_FLAGS, Job, resume_suspended

__all__ = [
    "LINK_MODE",
    "UV_ENV",
    "Completed",
    "ProcessRunner",
    "app_root",
    "find_uv",
    "mask",
    "uv_env",
]

UV_ENV: Final = "KOOKABUG_UV"
LINK_MODE: Final = "copy"
"""플러그인 환경 설치의 uv 링크 방식 (완성 표식에도 적는다)."""
_CREATE_SUSPENDED: Final = 0x00000004
_DROP_PREFIXES: Final = ("UV_",)
_DROP: Final = frozenset(
    {
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PIP_REQUIRE_VIRTUALENV",
    }
)
_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/@\s]+@")


def mask(text: str) -> str:
    """URL의 사용자 정보(`user:token@`)를 가린다."""
    return _USERINFO.sub(r"\1***@", text)


def app_root() -> Path:
    """설치본 루트 (`<앱>\\python\\python.exe` → `<앱>`). 개발 환경에서는 의미 없는 경로일 수
    있다."""
    return Path(sys.base_prefix).parent


def find_uv(environ: Mapping[str, str]) -> Path:
    given = environ.get(UV_ENV)
    if given:
        path = Path(given)
        if path.is_file():
            return path
        raise PluginError("app_incomplete", f"{UV_ENV}={given}이(가) 없다")
    bundled = app_root() / "tools" / "uv" / "uv.exe"
    if bundled.is_file():
        return bundled
    found = shutil.which("uv", path=environ.get("PATH"))
    if found is None:
        raise PluginError("app_incomplete", "uv를 찾을 수 없다 (설치본 tools\\uv\\uv.exe)")
    return Path(found)


def uv_cache_dir(environ: Mapping[str, str]) -> Path:
    base = environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Kookabug" / "uv-cache"


def uv_env(environ: Mapping[str, str]) -> dict[str, str]:
    env = {
        k: v
        for k, v in environ.items()
        if k.upper() not in _DROP and not k.upper().startswith(_DROP_PREFIXES)
    }
    env["UV_NO_CONFIG"] = "1"
    env["UV_PYTHON_DOWNLOADS"] = "never"
    env["UV_CACHE_DIR"] = str(uv_cache_dir(environ))
    # 환경마다 독립된 파일 (Windows 기본은 캐시와 하드 링크: 한 환경의 제자리 쓰기가 캐시와
    # 다른 환경까지 바꾼다). 외부 값은 위에서 지웠다
    env["UV_LINK_MODE"] = LINK_MODE
    env["UV_NO_PROGRESS"] = "1"
    env["PYTHONUTF8"] = "1"
    return env


@dataclass(frozen=True, slots=True)
class Completed:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class ProcessRunner:
    """거래 하나의 자식 실행기. 모든 자식은 `job` 안이다."""

    env: dict[str, str]
    log: Path
    job: Job
    timeout_s: float = 600.0
    calls: list[tuple[str, ...]] = field(default_factory=list[tuple[str, ...]])
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def run(self, args: Sequence[str | Path], *, stage: str, cwd: Path | None = None) -> Completed:
        argv = tuple(str(a) for a in args)
        with self._lock:
            self.calls.append(argv)
        self._write(f"$ {' '.join(argv)}\n")
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=self.env,
                creationflags=CHILD_FLAGS | _CREATE_SUSPENDED,
            )
        except OSError as exc:
            raise PluginError(
                "env_create_failed", f"{Path(argv[0]).name}을(를) 띄우지 못했다: {exc}", stage=stage
            ) from exc
        try:
            self.job.assign(proc.pid)
            resume_suspended(proc.pid)
        except OSError as exc:
            with contextlib.suppress(OSError):
                proc.kill()
            proc.wait()
            raise PluginError(
                "env_create_failed", f"자식을 설치 작업 Job에 넣지 못했다: {exc}", stage=stage
            ) from exc
        try:
            out, err = proc.communicate(timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            self.job.terminate()
            out, err = proc.communicate()
            self._write(_decode(out) + _decode(err) + "\n(기한 초과로 끝냄)\n")
            raise PluginError(
                "verify_failed" if stage == "verify" else "env_create_failed",
                f"{Path(argv[0]).name}이(가) {self.timeout_s:.0f}초 안에 끝나지 않았다",
                stage=stage,
            ) from None
        done = Completed(argv, proc.returncode, _decode(out), _decode(err))
        self._write(done.stdout + done.stderr + f"(종료 {proc.returncode})\n")
        return done

    def _write(self, text: str) -> None:
        with contextlib.suppress(OSError), self._lock:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            with self.log.open("a", encoding="utf-8") as f:
                f.write(mask(text))


def _decode(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace")


def remove_tree(path: Path) -> None:
    """폴더를 지운다 (읽기 전용 파일 포함). 없으면 아무것도 하지 않는다."""

    def retry(func: object, target: str, exc: BaseException) -> None:
        os.chmod(target, 0o600)
        func(target)  # type: ignore[operator]

    if path.exists():
        shutil.rmtree(path, onexc=retry)
