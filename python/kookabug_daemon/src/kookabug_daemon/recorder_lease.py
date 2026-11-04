"""녹화 세션의 입력 임대권 (M4 계획 2.3, C1).

녹화 세션 동안 daemon이 임대권을 `kind: "recorder"`·장치 `none`으로 쥔다. 실행이 없으므로 실행
ID·폴더는 null이다. 녹화는 입력을 보내지 않으니 액터 없이 깨끗하게 놓는다(`release_idle`).

- 뮤텍스 이름·상태 폴더는 daemon이 띄우는 runner와 같은 환경(`KOOKABUG_INPUT_LEASE_NAME`·
  `KOOKABUG_STATE_DIR`)으로 정한다 — 그래야 같은 임대권을 다툰다
- 뮤텍스는 `InputLease`의 전용 스레드가 얻고 놓는다. `acquire`는 앞 소유자가 남긴 키를 떼는 복구와
  파일 쓰기를 하므로 막히는 호출이다 — 이벤트 루프가 아니라 작업 스레드에서 부른다
- 다른 주체가 쥐고 있으면 `input_lease_busy`(살아 있음이 확인된 소유자, 알림 값 규칙으로 바꾼 것)

녹화 세션 서비스(T8)가 시작 예약(`RunManager.reserve_recording`) 뒤에 얻고, 정지 때 훅·캡처를
닫은 뒤 놓는다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from kookabug_core.inputs.backends import NoneBackend
from kookabug_core.inputs.lease import (
    Acquired,
    InputLease,
    InputLeaseBusy,
    LeaseOwner,
    lease_name,
)
from kookabug_daemon.lease_watch import lease_dir, wire_safe
from kookabug_daemon.protocol import RequestFailed

__all__ = ["RecorderLease"]


class RecorderLease:
    """녹화 세션 하나의 임대권. `acquire()` → (녹화) → `release()` (또는 `abandon()`)."""

    def __init__(
        self,
        workspace: str | os.PathLike[str],
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        """`environ`은 daemon이 runner에 넘기는 환경 (없으면 이 프로세스 환경)."""
        # 이름·상태 폴더 모두 고른 환경 하나로만 정한다 (부모 환경으로 되돌아가지 않는다)
        self.name = lease_name(environ)
        self.directory: Path = lease_dir(environ)
        self.owner = LeaseOwner.current("recorder", workspace=workspace)
        self._lease = InputLease(
            self.owner, NoneBackend(), name=self.name, directory=self.directory
        )

    @property
    def held(self) -> bool:
        return self._lease.held

    def acquire(self) -> Acquired:
        """기다리지 않고 얻는다. 다른 주체가 쥐고 있으면 `RequestFailed("input_lease_busy")`."""
        try:
            return self._lease.acquire(0)
        except InputLeaseBusy as exc:
            raise RequestFailed("input_lease_busy", str(exc), owner=_wire_owner(exc.owner)) from exc

    def release(self) -> None:
        """깨끗하게 놓는다 (쥐고 있지 않으면 아무것도 하지 않는다)."""
        if self._lease.held:
            self._lease.release_idle()

    def abandon(self) -> None:
        """깨끗하지 않게 놓는다 (프로세스가 죽은 것과 같다 — 다음 획득자는 뗄 것 없이 넘어간다)."""
        self._lease.abandon()


def _wire_owner(owner: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if owner is None:
        return None
    value: dict[str, Any] = wire_safe(dict(owner))
    return value
