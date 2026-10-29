"""named pipe 전송 (구현 계획 3장 표, M0b 2.2). 감독자 ↔ runner, runner ↔ 워커가 같은 코드를 쓴다.

프레임: `uint32 little-endian 길이 N` + `N`바이트(UTF-8 JSON). `1 ≤ N ≤ 16 MiB`, 인증 전에는
256바이트. 보내는 쪽·받는 쪽 둘 다 검사하고, 받는 쪽은 범위 밖 길이를 프로토콜 오류로 보고
연결을 닫는다. byte mode 파이프라 한 프레임이 여러 번에 나뉘어 오거나 여러 프레임이 한 번에
와도 된다. 프레임 중간의 EOF는 연결 끊김이다.

`multiprocessing.connection`은 쓰지 않는다: Windows 구현은 message mode라 길이 접두가 아니고
`accept`·쓰기에 기한이 없다. 여기서는 CPython `_winapi`의 overlapped I/O로 모든 대기에 기한을 걸고,
`close()`가 다른 스레드에서 진행 중인 I/O를 `CancelIoEx`로 끊는다. `_winapi`는 공개 API가 아니므로
이 파일에서만 쓰고, 쓰는 이름은 `WINAPI_USED`에 모아 테스트가 확인한다.

인증 (연결 직후, 실행마다 무작위 키, 전체 기한 `AUTH_TIMEOUT`):

1. 서버 → 클라이언트: 서버 난수(32)
2. 클라이언트 → 서버: 클라이언트 난수(32) + `HMAC-SHA256(key, "client" + 서버 난수)`
3. 서버가 확인하고 `HMAC-SHA256(key, "server" + 클라이언트 난수)`. 틀리면 아무것도 보내지 않고
   닫는다
4. 클라이언트가 확인하고 `ok`. 틀리면 닫는다

그래서 이름을 아는 같은 PC의 다른 프로세스도 키 없이는 붙지 못하고, 클라이언트도 가짜 서버에
붙지 않는다.
"""

from __future__ import annotations

import _winapi
import contextlib
import hashlib
import hmac
import os
import secrets
import struct
import threading
import time
from collections.abc import Callable
from typing import Final

__all__ = [
    "ACCEPT_TIMEOUT",
    "AUTH_MAX_FRAME",
    "AUTH_TIMEOUT",
    "CONNECT_TIMEOUT",
    "KEY_SIZE",
    "MAX_FRAME",
    "WRITE_TIMEOUT",
    "AuthError",
    "AuthTimeout",
    "FrameTooLarge",
    "PipeClosed",
    "PipeConnection",
    "PipeError",
    "PipeListener",
    "PipeTimeout",
    "ProtocolError",
    "connect",
    "connect_raw",
    "new_key",
    "new_pipe_name",
]

MAX_FRAME: Final = 16 * 1024 * 1024
AUTH_MAX_FRAME: Final = 256
KEY_SIZE: Final = 32

# 기한 (초)
ACCEPT_TIMEOUT: Final = 30.0
CONNECT_TIMEOUT: Final = 30.0
AUTH_TIMEOUT: Final = 5.0
WRITE_TIMEOUT: Final = 10.0

PIPE_PREFIX: Final = "\\\\.\\pipe\\"
BUFFER_SIZE: Final = 64 * 1024
_READ_CHUNK: Final = 64 * 1024
_HEADER: Final = struct.Struct("<I")

# `_winapi`에 상수가 없는 값
PIPE_TYPE_BYTE: Final = 0x0
PIPE_READMODE_BYTE: Final = 0x0
PIPE_REJECT_REMOTE_CLIENTS: Final = 0x8
SECURITY_IDENTIFICATION: Final = 0x00010000
SECURITY_SQOS_PRESENT: Final = 0x00100000
ERROR_FILE_NOT_FOUND: Final = 2
ERROR_INVALID_HANDLE: Final = 6
ERROR_PIPE_NOT_CONNECTED: Final = 233

OPEN_MODE: Final = (
    _winapi.PIPE_ACCESS_DUPLEX
    | _winapi.FILE_FLAG_OVERLAPPED
    | _winapi.FILE_FLAG_FIRST_PIPE_INSTANCE
)
PIPE_MODE: Final = (
    PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | _winapi.PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS
)
# 클라이언트는 서버가 자기 권한으로 행세하지 못하게 식별 수준으로만 연다
CLIENT_FLAGS: Final = _winapi.FILE_FLAG_OVERLAPPED | SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION

# 이 파일이 쓰는 `_winapi` 이름 전부 (test_winapi_functions_available)
WINAPI_USED: Final = (
    "CloseHandle",
    "ConnectNamedPipe",
    "CreateFile",
    "CreateNamedPipe",
    "ERROR_BROKEN_PIPE",
    "ERROR_NETNAME_DELETED",
    "ERROR_NO_DATA",
    "ERROR_OPERATION_ABORTED",
    "ERROR_PIPE_BUSY",
    "FILE_FLAG_FIRST_PIPE_INSTANCE",
    "FILE_FLAG_OVERLAPPED",
    "GENERIC_READ",
    "GENERIC_WRITE",
    "INFINITE",
    "NULL",
    "OPEN_EXISTING",
    "Overlapped",
    "PIPE_ACCESS_DUPLEX",
    "PIPE_WAIT",
    "ReadFile",
    "WAIT_TIMEOUT",
    "WaitForSingleObject",
    "WaitNamedPipe",
    "WriteFile",
)
OVERLAPPED_USED: Final = ("GetOverlappedResult", "cancel", "event", "getbuffer")

_DISCONNECTED: Final = frozenset(
    {
        _winapi.ERROR_BROKEN_PIPE,
        _winapi.ERROR_NO_DATA,
        _winapi.ERROR_NETNAME_DELETED,
        _winapi.ERROR_OPERATION_ABORTED,
        ERROR_PIPE_NOT_CONNECTED,
        ERROR_INVALID_HANDLE,
    }
)

_AUTH_LABEL: Final = b"kookabug-pipe-auth/1 "
_AUTH_OK: Final = b"ok"
_NONCE_SIZE: Final = 32


class PipeError(Exception):
    """전송 오류."""


class PipeClosed(PipeError):
    """연결이 끊겼다 (상대가 닫음·죽음, 이쪽에서 `close()`, 프레임 중간 EOF)."""


class PipeTimeout(PipeError, TimeoutError):
    """기한 초과 (accept·connect·쓰기·인증). 쓰기 기한 초과는 연결을 닫는다."""


class ProtocolError(PipeError):
    """받은 프레임 길이가 범위 밖이다. 연결은 닫혔다."""


class FrameTooLarge(PipeError, ValueError):
    """보내려는 프레임 길이가 범위 밖이다. 아무것도 보내지 않았고 연결은 그대로다."""


class AuthError(PipeError):
    """상호 인증 실패. 연결은 닫혔다."""


class AuthTimeout(AuthError, PipeTimeout):
    """인증 기한 초과."""


def new_key() -> bytes:
    """실행마다 새로 만드는 인증 키."""
    return secrets.token_bytes(KEY_SIZE)


def new_pipe_name(tag: str = "rpc") -> str:
    r"""겹치지 않는 파이프 이름 (`\\.\pipe\kookabug-<tag>-<pid>-<난수>`)."""
    return f"{PIPE_PREFIX}kookabug-{tag}-{os.getpid()}-{secrets.token_hex(8)}"


def _check_name(name: str) -> None:
    if not name.lower().startswith(PIPE_PREFIX) or len(name) == len(PIPE_PREFIX):
        raise ValueError(f"로컬 파이프 이름이 아니다 ({PIPE_PREFIX}로 시작해야 한다): {name!r}")


def _check_key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) < 16:
        raise ValueError("인증 키는 16바이트 이상의 bytes여야 한다")


def _ms(seconds: float) -> int:
    return max(0, min(int(seconds * 1000), _winapi.INFINITE - 1))


class PipeConnection:
    """연결된 파이프 한쪽 끝. 읽기 하나와 쓰기 하나가 서로 다른 스레드에서 동시에 돌 수 있다.

    읽기는 `recv_frame()`(기본 무기한)이고, `close()`가 다른 스레드에서 끊는다. 핸들은 진행 중인
    I/O가 모두 끝난 뒤에 닫는다 (닫힌 핸들 번호가 재사용된 뒤 그 번호로 I/O를 취소하지 않게).
    """

    def __init__(self, handle: int) -> None:
        self._handle: int | None = handle
        self._lock = threading.Lock()
        self._pending: set[_winapi.Overlapped] = set()
        self._inflight = 0
        self._closed = False
        self._read_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._buffer = bytearray()
        self._max_frame = AUTH_MAX_FRAME

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def authenticated(self) -> bool:
        return self._max_frame == MAX_FRAME

    def _mark_authenticated(self) -> None:
        self._max_frame = MAX_FRAME

    # ── overlapped I/O ──────────────────────────────────────────────

    def _begin(self, start: Callable[[int], _winapi.Overlapped]) -> _winapi.Overlapped:
        with self._lock:
            if self._closed or self._handle is None:
                raise PipeClosed("연결이 닫혔다")
            try:
                ov = start(self._handle)
            except OSError as e:
                raise self._os_error(e) from e
            self._pending.add(ov)
            self._inflight += 1
            return ov

    def _finish(self, ov: _winapi.Overlapped, timeout: float | None) -> tuple[int, int, bool]:
        """I/O가 끝날 때까지(기한이면 취소하고) 기다린다. (옮긴 바이트, 오류 코드, 기한 초과)."""
        timed_out = False
        try:
            if (
                timeout is not None
                and _winapi.WaitForSingleObject(ov.event, _ms(timeout)) == _winapi.WAIT_TIMEOUT
            ):
                timed_out = True
                self._cancel(ov)
            transferred, err = ov.GetOverlappedResult(True)
            return transferred, err, timed_out
        except OSError as e:
            raise self._os_error(e) from e
        finally:
            handle = None
            with self._lock:
                self._pending.discard(ov)
                self._inflight -= 1
                if self._closed and self._inflight == 0:
                    handle, self._handle = self._handle, None
            if handle is not None:
                _winapi.CloseHandle(handle)

    def _cancel(self, ov: _winapi.Overlapped) -> None:
        # 잠금 안에서: 핸들이 닫히는 것은 잠금 안에서만 일어난다
        with self._lock, contextlib.suppress(OSError):
            ov.cancel()

    def _os_error(self, e: OSError) -> PipeError:
        if self._closed:
            return PipeClosed("연결이 닫혔다")
        if e.winerror in _DISCONNECTED:
            return PipeClosed(f"상대가 연결을 끊었다 ({e.winerror})")
        return PipeError(f"파이프 I/O 오류: {e}")

    def _aborted(self, what: str, timed_out: bool) -> PipeError:
        if self._closed:
            return PipeClosed("연결이 닫혔다")
        if timed_out:
            return PipeTimeout(f"{what} 기한 초과")
        return PipeClosed(f"{what}가 취소됐다")

    # ── 읽기 ─────────────────────────────────────────────────────────

    def recv_frame(self, timeout: float | None = None) -> bytes:
        """프레임 하나의 본문. 기한(`timeout` 초)을 넘기면 `PipeTimeout` — 연결과 받은 바이트는
        그대로다."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._read_lock:
            while True:
                frame = self._take_frame()
                if frame is not None:
                    return frame
                self._read_some(None if deadline is None else deadline - time.monotonic())

    def read_raw(self, timeout: float | None = None) -> bytes:
        """프레임으로 나누지 않은 원시 바이트 (검사용): 쌓인 바이트가 있으면 그것, 없으면 다음에
        도착하는 바이트."""
        with self._read_lock:
            if not self._buffer:
                self._read_some(timeout)
            data = bytes(self._buffer)
            self._buffer.clear()
            return data

    def _take_frame(self) -> bytes | None:
        if len(self._buffer) < _HEADER.size:
            return None
        (size,) = _HEADER.unpack_from(self._buffer)
        if not 1 <= size <= self._max_frame:
            self.close()
            raise ProtocolError(f"프레임 길이 {size}가 범위(1~{self._max_frame}) 밖이다")
        end = _HEADER.size + size
        if len(self._buffer) < end:
            return None
        frame = bytes(self._buffer[_HEADER.size : end])
        del self._buffer[:end]
        return frame

    def _read_some(self, timeout: float | None) -> None:
        if timeout is not None and timeout <= 0:
            raise PipeTimeout("읽기 기한 초과")
        try:
            ov = self._begin(lambda h: _winapi.ReadFile(h, _READ_CHUNK, overlapped=True)[0])
            transferred, err, timed_out = self._finish(ov, timeout)
        except PipeClosed as e:
            raise self._mid_frame(e) from e
        data = ov.getbuffer() if transferred else None
        if data:
            self._buffer += data
            return
        if err == _winapi.ERROR_OPERATION_ABORTED:
            error = self._aborted("읽기", timed_out)
            raise self._mid_frame(error) if isinstance(error, PipeClosed) else error
        raise self._mid_frame(PipeClosed("상대가 연결을 닫았다"))

    def _mid_frame(self, error: PipeError) -> PipeError:
        if self._buffer and not self._closed:
            return PipeClosed(
                f"프레임 중간에 연결이 끊겼다 ({len(self._buffer)}바이트 남음): {error}"
            )
        return error

    # ── 쓰기 ─────────────────────────────────────────────────────────

    def send_frame(self, body: bytes, timeout: float | None = WRITE_TIMEOUT) -> None:
        """프레임 하나를 끝까지 쓴다. 기한을 넘기면 I/O를 취소하고 연결을 닫은 뒤 `PipeTimeout`."""
        if not 1 <= len(body) <= self._max_frame:
            raise FrameTooLarge(f"프레임 길이 {len(body)}가 범위(1~{self._max_frame}) 밖이다")
        self.write_raw(_HEADER.pack(len(body)) + body, timeout)

    def write_raw(self, data: bytes, timeout: float | None = WRITE_TIMEOUT) -> None:
        """원시 바이트를 끝까지 쓴다 (프레임 검사 없음 — 검사용·`send_frame` 내부)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._write_lock:
            view = memoryview(data)
            while view:
                left = None if deadline is None else max(0.0, deadline - time.monotonic())
                chunk = bytes(view)
                ov = self._begin(lambda h, c=chunk: _winapi.WriteFile(h, c, overlapped=True)[0])
                written, err, timed_out = self._finish(ov, left)
                aborted = err == _winapi.ERROR_OPERATION_ABORTED
                if aborted or (written < len(chunk) and (timed_out or written == 0)):
                    error = self._aborted("쓰기", timed_out)
                    # 프레임 일부만 나갔을 수 있으므로 이 연결은 더 쓸 수 없다
                    self.close()
                    raise error
                view = view[written:]

    # ── 닫기 ─────────────────────────────────────────────────────────

    def close(self) -> None:
        """닫는다. 다른 스레드에서 진행 중인 읽기·쓰기·accept는 `PipeClosed`로 끝난다. 여러 번
        불러도 된다."""
        handle = None
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for ov in self._pending:
                with contextlib.suppress(OSError):
                    ov.cancel()
            if self._inflight == 0:
                handle, self._handle = self._handle, None
        if handle is not None:
            _winapi.CloseHandle(handle)

    def __enter__(self) -> PipeConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class PipeListener:
    """서버 끝. 만들 때 파이프를 만들고(같은 이름이 이미 있으면 실패 — 가로채기 방지), 클라이언트
    하나를 받는다. 받은 뒤에는 그 연결이 핸들을 가진다.
    """

    def __init__(self, name: str, *, buffer_size: int = BUFFER_SIZE) -> None:
        _check_name(name)
        try:
            handle = _winapi.CreateNamedPipe(
                name, OPEN_MODE, PIPE_MODE, 1, buffer_size, buffer_size, 0, _winapi.NULL
            )
        except OSError as e:
            raise PipeError(f"파이프를 만들 수 없다 (같은 이름이 이미 있을 수 있다): {name}") from e
        self.name = name
        self._lock = threading.Lock()
        self._conn: PipeConnection | None = PipeConnection(handle)
        self._accepting = False
        self._closed = False

    def accept(
        self, key: bytes, *, timeout: float = ACCEPT_TIMEOUT, auth_timeout: float = AUTH_TIMEOUT
    ) -> PipeConnection:
        """클라이언트가 붙을 때까지 기다리고(`timeout`) 상호 인증한다(`auth_timeout`).

        실패하면 파이프를 닫는다 — 이 리스너는 다시 쓸 수 없다.
        """
        _check_key(key)
        conn = self._start_accept()
        try:
            self._connect(conn, timeout)
            _auth_server(conn, key, auth_timeout)
        except BaseException:
            self.close()
            raise
        return self._finish_accept(conn)

    def accept_raw(self, timeout: float = ACCEPT_TIMEOUT) -> PipeConnection:
        """인증 없이 받는다 (검사용). 인증 전 프레임 상한(256바이트)이 그대로다."""
        conn = self._start_accept()
        try:
            self._connect(conn, timeout)
        except BaseException:
            self.close()
            raise
        return self._finish_accept(conn)

    def _start_accept(self) -> PipeConnection:
        with self._lock:
            if self._closed or self._conn is None:
                raise PipeClosed("리스너가 닫혔거나 이미 연결을 받았다")
            if self._accepting:
                raise PipeError("이미 accept 중이다")
            self._accepting = True
            return self._conn

    def _finish_accept(self, conn: PipeConnection) -> PipeConnection:
        with self._lock:
            closed = self._closed
            self._conn = None
        if closed:
            conn.close()
            raise PipeClosed("리스너가 닫혔다")
        return conn

    @staticmethod
    def _connect(conn: PipeConnection, timeout: float) -> None:
        ov = conn._begin(lambda h: _winapi.ConnectNamedPipe(h, overlapped=True))
        _, err, timed_out = conn._finish(ov, timeout)
        if err == _winapi.ERROR_OPERATION_ABORTED or timed_out:
            raise conn._aborted("accept", timed_out)

    def close(self) -> None:
        """닫는다. 다른 스레드의 `accept`는 `PipeClosed`로 끝난다. 이미 받은 연결은 닫지 않는다."""
        with self._lock:
            self._closed = True
            conn = self._conn
        if conn is not None:
            conn.close()

    def __enter__(self) -> PipeListener:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def connect_raw(name: str, timeout: float = CONNECT_TIMEOUT) -> PipeConnection:
    """서버에 붙는다 (인증 없음 — 검사용·`connect` 내부). 파이프가 아직 없거나 다른 클라이언트가
    쓰고 있으면 기한까지 다시 시도한다."""
    _check_name(name)
    deadline = time.monotonic() + timeout
    while True:
        try:
            handle = _winapi.CreateFile(
                name,
                _winapi.GENERIC_READ | _winapi.GENERIC_WRITE,
                0,
                _winapi.NULL,
                _winapi.OPEN_EXISTING,
                CLIENT_FLAGS,
                _winapi.NULL,
            )
            return PipeConnection(handle)
        except OSError as e:
            if e.winerror not in (ERROR_FILE_NOT_FOUND, _winapi.ERROR_PIPE_BUSY):
                raise PipeError(f"파이프에 붙을 수 없다: {name}: {e}") from e
            busy = e.winerror == _winapi.ERROR_PIPE_BUSY
        left = deadline - time.monotonic()
        if left <= 0:
            raise PipeTimeout(f"connect 기한 초과: {name}")
        if busy:
            try:
                _winapi.WaitNamedPipe(name, max(1, _ms(min(left, 0.5))))
                continue
            except OSError:
                pass
        time.sleep(min(0.01, max(left, 0.0)))


def connect(
    name: str,
    key: bytes,
    *,
    timeout: float = CONNECT_TIMEOUT,
    auth_timeout: float = AUTH_TIMEOUT,
) -> PipeConnection:
    """서버에 붙고(`timeout`) 상호 인증한다(`auth_timeout`)."""
    _check_key(key)
    conn = connect_raw(name, timeout)
    try:
        _auth_client(conn, key, auth_timeout)
    except BaseException:
        conn.close()
        raise
    return conn


# ── 인증 ─────────────────────────────────────────────────────────────


def _proof(key: bytes, label: bytes, nonce: bytes) -> bytes:
    return hmac.new(key, _AUTH_LABEL + label + nonce, hashlib.sha256).digest()


class _Deadline:
    def __init__(self, timeout: float) -> None:
        self._end = time.monotonic() + timeout

    def left(self) -> float:
        left = self._end - time.monotonic()
        if left <= 0:
            raise AuthTimeout("인증 기한 초과")
        return left


def _auth_server(conn: PipeConnection, key: bytes, timeout: float) -> None:
    deadline = _Deadline(timeout)
    try:
        server_nonce = secrets.token_bytes(_NONCE_SIZE)
        conn.send_frame(server_nonce, deadline.left())
        reply = conn.recv_frame(deadline.left())
        if len(reply) != 2 * _NONCE_SIZE:
            raise AuthError("인증 응답 형식이 틀렸다")
        client_nonce, proof = reply[:_NONCE_SIZE], reply[_NONCE_SIZE:]
        if not hmac.compare_digest(proof, _proof(key, b"client", server_nonce)):
            raise AuthError("클라이언트가 키를 증명하지 못했다")
        conn.send_frame(_proof(key, b"server", client_nonce), deadline.left())
        if conn.recv_frame(deadline.left()) != _AUTH_OK:
            raise AuthError("클라이언트가 인증을 확인하지 않았다")
    except AuthError:
        conn.close()
        raise
    except PipeError as e:
        conn.close()
        raise _auth_failure(e) from e
    conn._mark_authenticated()


def _auth_client(conn: PipeConnection, key: bytes, timeout: float) -> None:
    deadline = _Deadline(timeout)
    try:
        server_nonce = conn.recv_frame(deadline.left())
        if len(server_nonce) != _NONCE_SIZE:
            raise AuthError("인증 도전 형식이 틀렸다")
        client_nonce = secrets.token_bytes(_NONCE_SIZE)
        conn.send_frame(client_nonce + _proof(key, b"client", server_nonce), deadline.left())
        proof = conn.recv_frame(deadline.left())
        if not hmac.compare_digest(proof, _proof(key, b"server", client_nonce)):
            raise AuthError("서버가 키를 증명하지 못했다")
        conn.send_frame(_AUTH_OK, deadline.left())
    except AuthError:
        conn.close()
        raise
    except PipeError as e:
        conn.close()
        raise _auth_failure(e) from e
    conn._mark_authenticated()


def _auth_failure(e: PipeError) -> AuthError:
    if isinstance(e, PipeTimeout):
        return AuthTimeout(f"인증 기한 초과: {e}")
    return AuthError(f"인증 중 연결이 끊겼다: {e}")
