"""워크스페이스의 플러그인 배치 (M6 계획 3.4)와 잠금 파일 두 개.

    workspace/
    ├─ kookabug.lock                          잠금 (커밋)
    ├─ plugins/wheels/<sha256>/<wheel 파일명>  플러그인 wheel (커밋)
    └─ .kookabug/plugins/                     (Git 제외)
       ├─ envs/<환경>-<지문12>-<작업8>/        실행 환경 venv
       ├─ staging/<작업 ID>/                  거래 전용 (자동 정리는 여기만)
       ├─ logs/<작업 ID>.log                  uv·검증 원문
       ├─ busy.lock                           설치·제거·sync·relock·gc 한 번에 하나 (길게)
       └─ op.lock                             짧은 임계 구역 (잠금 읽기·바꿔 넣기·gc 판단)

잠금 파일은 바이트 하나를 `msvcrt.locking`으로 쥔다. 프로세스가 죽으면 OS가 핸들과 함께 푼다.
"""

from __future__ import annotations

import contextlib
import msvcrt
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from kookabug_core.plugins.errors import PluginError

__all__ = ["LOCK_FILE", "WHEELS_DIR", "Layout", "hold"]

LOCK_FILE: Final = "kookabug.lock"
WHEELS_DIR: Final = "plugins/wheels"
PRIVATE_DIR: Final = ".kookabug/plugins"
OP_LOCK_TIMEOUT_S: Final = 30.0


@dataclass(frozen=True, slots=True)
class Layout:
    root: Path

    @property
    def lock(self) -> Path:
        return self.root / LOCK_FILE

    @property
    def wheels(self) -> Path:
        return self.root.joinpath(*WHEELS_DIR.split("/"))

    @property
    def private(self) -> Path:
        return self.root.joinpath(*PRIVATE_DIR.split("/"))

    @property
    def envs(self) -> Path:
        return self.private / "envs"

    @property
    def staging(self) -> Path:
        return self.private / "staging"

    @property
    def logs(self) -> Path:
        return self.private / "logs"

    def wheel_path(self, rel: str) -> Path:
        """잠금의 `wheel`(워크스페이스 기준 '/' 경로) → 실제 경로."""
        return self.root.joinpath(*rel.split("/"))

    def busy(self) -> contextlib.AbstractContextManager[None]:
        """긴 작업 하나 (다른 프로세스·다른 작업이 쥐고 있으면 곧바로 `plugin_busy`)."""
        return hold(self.private / "busy.lock", wait_s=0.0)

    def op(self) -> contextlib.AbstractContextManager[None]:
        """짧은 임계 구역 (기다린다)."""
        return hold(self.private / "op.lock", wait_s=OP_LOCK_TIMEOUT_S)


@contextlib.contextmanager
def hold(path: Path, *, wait_s: float) -> Iterator[None]:
    """파일 잠금을 쥔다. `wait_s` 안에 못 쥐면 `plugin_busy`. 같은 프로세스의 다른 핸들도 막힌다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + wait_s
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise PluginError(
                        "plugin_busy", f"다른 플러그인 작업이 진행 중이다 ({path.name})"
                    ) from None
                time.sleep(0.02)
        try:
            yield
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            with contextlib.suppress(OSError):
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)
