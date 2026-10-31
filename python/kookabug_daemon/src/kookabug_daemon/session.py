"""잠금 파일과 `session.json` (M2 계획 2.3).

- `.kookabug/daemon.lock`을 공유 없이 열어 daemon이 살아 있는 동안 쥔다. 프로세스가 죽으면 OS가
  핸들을 닫아 잠금이 풀린다. 잠금이 판단 근거다
- `session.json`은 잠금을 얻은 뒤 임시 파일 + `os.replace`로 쓰고, 끝날 때 자기 `start_id`인
  경우에만 지운다. PID·생성 시각은 클라이언트가 붙기 전에 보는 빠른 확인이다
- **유효한 세션** = 형식이 맞고, PID·생성 시각이 살아 있고, 그 포트로 `session.hello` 인증이 성공한
  것. 잠금 경쟁에서 진 daemon과 클라이언트는 이것이 나올 때까지 기다린다
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from kookabug_core.schema import check_shape
from kookabug_core.win import ProcessId, current, is_alive
from kookabug_core.win import _kernel32 as k
from kookabug_daemon.options import SESSION_WAIT_S
from kookabug_sdk.rpc import decode_text

__all__ = [
    "LOCK_FILE",
    "LOGS_DIR",
    "PRIVATE_DIR",
    "SESSION_FILE",
    "SESSION_FORMAT",
    "WAIT_INTERVAL_S",
    "WAIT_TIMEOUT_S",
    "DaemonLock",
    "LockBusy",
    "SessionInfo",
    "own_session",
    "read_session",
    "remove_session",
    "session_alive",
    "session_path",
    "timestamp",
    "wait_for_valid_session",
    "write_session",
]

PRIVATE_DIR: Final = ".kookabug"
LOCK_FILE: Final = "daemon.lock"
SESSION_FILE: Final = "session.json"
LOGS_DIR: Final = "logs"
SESSION_FORMAT: Final = "kookabug.session/0"
WAIT_TIMEOUT_S: Final = SESSION_WAIT_S
WAIT_INTERVAL_S: Final = 0.1

_GENERIC_READ: Final = 0x80000000
_GENERIC_WRITE: Final = 0x40000000
_ERROR_SHARING_VIOLATION: Final = 32
_ERROR_LOCK_VIOLATION: Final = 33
_MAX_DWORD: Final = 0xFFFF_FFFF
_MAX_FILETIME: Final = 2**64 - 1
# session.json replace가 읽는 쪽과 겹쳐 거부될 때 다시 해 보는 횟수
# (Windows는 다른 프로세스가 열고 있는 파일을 바꾸지 못한다)
_REPLACE_TRIES: Final = 50
_REPLACE_PAUSE_S: Final = 0.02


class LockBusy(Exception):
    """다른 프로세스가 잠금을 쥐고 있다 (경쟁에서 짐). 접근 거부·I/O 오류는 OSError다."""


class DaemonLock(k.OwnedHandle):
    """`.kookabug/daemon.lock`의 공유 없는 핸들. 상속되지 않는다 (runner가 쥐고 남지 않게)."""

    __slots__ = ("path",)

    def __init__(self, handle: int, path: Path) -> None:
        super().__init__(handle)
        self.path = path

    @classmethod
    def acquire(cls, root: Path) -> DaemonLock:
        """잠금을 얻는다. 잠금 충돌이면 `LockBusy`, 그 밖의 실패(접근 거부 등)는 `OSError`."""
        path = root / PRIVATE_DIR / LOCK_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = k.CreateFileW(
            str(path),
            _GENERIC_READ | _GENERIC_WRITE,
            0,  # 공유 없음
            None,  # 보안 속성 없음 = 상속 안 됨
            k.OPEN_ALWAYS,
            k.FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if handle is None or handle == k.INVALID_HANDLE_VALUE:
            code = ctypes.get_last_error()
            if code in (_ERROR_SHARING_VIOLATION, _ERROR_LOCK_VIOLATION):
                raise LockBusy(f"{path}을(를) 다른 daemon이 쥐고 있다")
            raise k.win_error(f"잠금 파일 {path}을(를) 열 수 없다", code)
        return cls(handle, path)


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """`session.json` 한 개 (session.schema.json)."""

    pid: int
    process_created: str
    start_id: str
    protocol: int
    daemon_version: str
    port: int
    token: str
    workspace: str
    started_at: str
    format: str = SESSION_FORMAT

    @property
    def ident(self) -> ProcessId:
        return ProcessId(self.pid, int(self.process_created))

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    def public(self) -> dict[str, Any]:
        """토큰을 뺀 정보 (`--json` 출력·로그용. 토큰은 session.json에서만 읽는다)."""
        data = self.to_json()
        del data["token"]
        return data

    @classmethod
    def from_json(cls, data: Any) -> SessionInfo | None:
        """형식이 틀리면 None (손상된 파일은 오래된 파일과 같게 본다).

        스키마에 더해 프로세스 식별로 바꿀 수 있는 값인지 본다: 스키마의 `integer`는 `1234.0`도
        받고, `process_created`는 자릿수 제한이 없다. PID는 DWORD, 생성 시각은 FILETIME(64비트)."""
        try:
            if check_shape(data, "session"):
                return None
        except RecursionError:
            return None
        if not all(type(data[name]) is int for name in ("pid", "port", "protocol")):
            return None
        created: str = data["process_created"]
        if data["pid"] > _MAX_DWORD or len(created) > 20 or int(created) > _MAX_FILETIME:
            return None
        return cls(**data)


def timestamp(now: datetime | None = None) -> str:
    """`started_at` 형식: UTC, 밀리초까지 (2026-10-29T06:02:11.104Z)."""
    moment = datetime.now(UTC) if now is None else now
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def own_session(
    *, root: Path, port: int, start_id: str, token: str, protocol: int, daemon_version: str
) -> SessionInfo:
    """이 프로세스의 세션 정보 (PID·생성 시각은 지금 프로세스)."""
    me = current()
    return SessionInfo(
        pid=me.pid,
        process_created=str(me.created),
        start_id=start_id,
        protocol=protocol,
        daemon_version=daemon_version,
        port=port,
        token=token,
        workspace=str(root),
        started_at=timestamp(),
    )


def session_path(root: Path) -> Path:
    return root / PRIVATE_DIR / SESSION_FILE


def read_session(root: Path) -> SessionInfo | None:
    """지금 `session.json`. 없거나 읽을 수 없거나 형식이 틀리면 None — 예외를 내지 않는다.

    JSON은 전송과 같은 값 규칙(중첩 128단, NaN·범위 밖 정수 거부)으로 읽는다. 아주 깊은 배열 같은
    손상 파일이 형식 검사에서 `RecursionError`를 내지 않게 하기 위함이다."""
    try:
        data = decode_text(session_path(root).read_bytes().decode("utf-8"))
    except OSError, ValueError, TypeError, RecursionError:
        return None
    return SessionInfo.from_json(data)


def _replace(src: Path, dst: Path) -> None:
    for attempt in range(_REPLACE_TRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_TRIES - 1:
                raise
            time.sleep(_REPLACE_PAUSE_S)


def write_session(root: Path, info: SessionInfo) -> None:
    """같은 폴더 임시 파일 → flush·fsync → replace. 형식이 틀린 값은 쓰지 않는다."""
    data = info.to_json()
    if problems := check_shape(data, "session"):
        raise ValueError(f"session.json 형식이 틀렸다: {[d.message for d in problems]}")
    target = session_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{SESSION_FILE}.{info.start_id}.tmp")
    try:
        with temp.open("wb") as out:
            # ASCII 이스케이프: 경로에 짝 없는 대리 문자가 있어도 UTF-8로 쓸 수 있다
            out.write(json.dumps(data, ensure_ascii=True, indent=2).encode("ascii") + b"\n")
            out.flush()
            os.fsync(out.fileno())
        _replace(temp, target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp.unlink()


def remove_session(root: Path, start_id: str) -> bool:
    """자기 `start_id`인 경우에만 지운다. 지웠으면 True."""
    found = read_session(root)
    if found is None or found.start_id != start_id:
        return False
    with contextlib.suppress(FileNotFoundError):
        session_path(root).unlink()
    return True


def session_alive(info: SessionInfo) -> bool:
    """PID가 살아 있고 생성 시각이 같다 (빠른 확인). 식별로 바꿀 수 없는 값이면 False."""
    try:
        return is_alive(info.ident)
    except OSError, ValueError, OverflowError, ctypes.ArgumentError:
        return False


type Probe = Callable[[SessionInfo], bool]


def wait_for_valid_session(
    root: Path,
    probe: Probe,
    *,
    timeout: float = WAIT_TIMEOUT_S,
    interval: float = WAIT_INTERVAL_S,
) -> SessionInfo | None:
    """유효한 세션(형식·살아 있는 PID·`probe` = `session.hello` 인증 성공)이 나올 때까지 다시
    읽는다. 기한을 넘기면 None. 같은 `start_id`에 다시 붙는 것도 정상이다 (새 ID를 요구하지
    않음)."""
    deadline = time.monotonic() + timeout
    while True:
        info = read_session(root)
        if info is not None and session_alive(info) and probe(info):
            return info
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)
