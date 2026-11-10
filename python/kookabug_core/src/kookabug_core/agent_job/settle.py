"""감독자가 없어진 작업의 입력 복구 확인 (M8 9장 R8) — 엄격: 입력 안전.

daemon(작업 실행의 감독자)이 없어지면 그 실행의 runner는 감독자 유실로 스스로 취소해 입력을 풀고
끝난다(`runner.watchdog`). 그 결과는 입력 임대권 옆 파일로 확인한다:

- 소유자 없음·깨끗하게 놓음 → 확인
- 다른 워크스페이스의 살아 있는 소유자 → 확인 (임대권은 하나다 — 그 소유자가 얻을 때 깨끗하지 않게
  놓인 앞 소유자를 복구했다)
- 이 워크스페이스의 살아 있는 소유자 → 확인 못 함 (아직 입력 중일 수 있다). 감독자는 예외 — 아래처럼
  얻어 본다 (놓기 기록이 실패해 깨끗하지 않게 놓은 감독자)
- 죽은 소유자가 깨끗하게 놓지 않음 → 임대권을 얻어 **얻기 복구**(앞 소유자의 장치로 떼기)를 하고
  깨끗하게 놓는다. 못 얻거나 복구·놓기가 실패하면 확인 못 함 (얻은 임대권은 어느 경우에도 놓는다)

`agent-job`의 연결 유실 경로와 daemon 시작의 `_recover_jobs`가 같은 함수를 쓴다.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

__all__ = ["input_settled"]

POLL_S: Final = 0.2


def _lease_dir(environ: Mapping[str, str]) -> Path:
    from kookabug_core.inputs.lease import STATE_DIR_ENV

    override = environ.get(STATE_DIR_ENV)
    if override:
        return Path(override)
    base = environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Kookabug"


def _same(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _verdict(data: Mapping[str, Any] | None, root: Path) -> str:
    """`ok`(풀림) · `live`(이 워크스페이스 소유자가 살아 있음) · `dirty`(죽은 소유자가 놓지
    않음)."""
    from kookabug_core.win import ProcessId, is_alive

    if data is None or data.get("clean") is True:
        return "ok"
    owner = data.get("owner")
    if not isinstance(owner, Mapping):
        return "ok"
    found: Mapping[str, Any] = owner
    try:
        alive = is_alive(ProcessId.from_json(found))
    except Exception:
        alive = True  # 소유자를 확인하지 못하면 안전 쪽
    if alive:
        workspace = found.get("workspace")
        if isinstance(workspace, str) and not _same(workspace, root):
            return "ok"
        if found.get("kind") == "supervisor":
            # 감독자는 떼기만 한다: 놓기 기록이 실패해 깨끗하지 않게 놓았을 수 있다(이 프로세스
            # 포함). 쥐고 있으면 얻기가 기다리고, 놓았으면 얻어 깨끗하게 놓는다
            return "dirty"
        return "live"
    return "dirty"


def input_settled(root: Path, environ: Mapping[str, str], *, timeout: float = 10.0) -> bool:
    """이 워크스페이스 작업의 입력이 풀렸는지 확인한다 (막히는 호출, 최대 `timeout`초 기다린다)."""
    from kookabug_core.inputs.backends import NoneBackend
    from kookabug_core.inputs.lease import (
        InputLease,
        InputLeaseBusy,
        LeaseOwner,
        lease_name,
        read_lease_file,
    )

    directory = _lease_dir(environ)
    deadline = time.monotonic() + timeout
    while True:
        try:
            verdict = _verdict(read_lease_file(directory), root)
        except OSError:
            verdict = "live"
        if verdict == "ok":
            return True
        if verdict == "dirty":
            # 감독자 강제 복구와 같은 얻기 복구: 앞 소유자의 장치로 떼고 깨끗하게 놓는다
            owner = LeaseOwner.current("supervisor", workspace=root)
            lease = InputLease(owner, NoneBackend(), name=lease_name(environ), directory=directory)
            try:
                lease.acquire(max(0.0, deadline - time.monotonic()))
            except InputLeaseBusy:
                pass  # 그 사이 다른 주체가 얻었다 — 다시 본다
            except Exception:
                return False
            else:
                # 복구는 끝났다. 깨끗한 놓기(옆 파일 쓰기)가 실패해도 임대권을 쥔 채 두지 않는다 —
                # 깨끗하지 않게 놓고(옆 파일 = 이 감독자, 뗄 키 없음) 확인 못 함. 다음 시도가 다시
                # 얻어 깨끗하게 놓는다
                try:
                    lease.release(None)
                except Exception:
                    return False
                finally:
                    lease.abandon()
                return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_S)
