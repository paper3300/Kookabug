"""알림 `lease.changed` (M2 계획 2.4·2.8): 입력 임대권 옆 파일을 폴링한다.

옆 파일(`<상태 폴더>/input-lease.json`)은 임대권을 쥔 주체(runner·감독자 복구)만 쓴다. daemon은
읽기만 하고, `owner`가 바뀌면 모든 연결에 `{owner}`를 알린다(놓였으면 null). 연결이 인증되면
그 연결에 지금 소유자를 한 번 보낸다(M2 T5 5절 결정: 붙은 직후 상태 바 첫 표시). 상태 바
"입력: 실행 #…"에 쓴다. 상태 폴더는 daemon이 띄우는 runner와 같은 환경 값(`KOOKABUG_STATE_DIR`)으로
정한다.

옆 파일의 프로세스 생성 시각(FILETIME, 100ns 단위)은 2^53을 넘는다. 알림 값 규칙(정수 ±(2^53-1))에
맞게 그 범위 밖 정수는 10진 문자열로 바꿔 보낸다.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from kookabug_core.inputs.lease import STATE_DIR_ENV, read_lease_file

__all__ = ["LEASE_INTERVAL_S", "LeaseWatcher", "lease_dir"]

log = logging.getLogger(__name__)

LEASE_INTERVAL_S: Final = 0.25
_MAX_SAFE: Final = 2**53 - 1


def wire_safe(value: Any) -> Any:
    """값 규칙 밖 정수(±(2^53-1) 밖)를 10진 문자열로 바꾼 사본."""
    if isinstance(value, dict):
        items: dict[Any, Any] = value
        return {k: wire_safe(v) for k, v in items.items()}
    if isinstance(value, list):
        elements: list[Any] = value
        return [wire_safe(v) for v in elements]
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > _MAX_SAFE:
        return str(value)
    return value


def lease_dir(environ: Mapping[str, str] | None) -> Path:
    """runner가 쓰는 상태 폴더 (`kookabug_core.inputs.lease.state_dir`와 같은 규칙, 환경은
    감독자가 runner에 넘기는 환경)."""
    env = os.environ if environ is None else environ
    override = env.get(STATE_DIR_ENV)
    if override:
        return Path(override)
    base = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Kookabug"


def _owner(data: Mapping[str, Any] | None) -> dict[str, Any] | None:
    owner = None if data is None else data.get("owner")
    return wire_safe(owner) if isinstance(owner, dict) else None


class LeaseWatcher:
    def __init__(
        self,
        directory: Path,
        publish: Callable[[dict[str, Any] | None], None],
        interval_s: float = LEASE_INTERVAL_S,
    ) -> None:
        self.directory = directory
        self.publish = publish
        self.interval_s = interval_s
        self.owner: dict[str, Any] | None = None

    def _read(self) -> dict[str, Any] | None:
        try:
            return _owner(read_lease_file(self.directory))
        except OSError as exc:  # 교체 중 오래 잠김 등: 이번 폴링은 건너뛴다
            log.debug("입력 임대권 옆 파일을 읽지 못했다: %s", exc)
            return self.owner

    def current(self) -> dict[str, Any] | None:
        """지금 옆 파일의 소유자 (막히는 호출 — `job.begin` 준비 확인)."""
        return self._read()

    async def run(self) -> None:
        # 첫 읽기도 바뀜으로 본다: 그 전에 붙은 연결은 hello 때 "없음"(null)을 받았다
        while True:
            owner = await asyncio.to_thread(self._read)
            if owner != self.owner:
                self.owner = owner
                self.publish(owner)
            await asyncio.sleep(self.interval_s)
