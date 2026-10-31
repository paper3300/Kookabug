"""daemon Python 클라이언트 (검사·CLI용, M2 계획 2.3 "클라이언트의 붙기 순서").

    with DaemonClient.connect(port, token) as client:      # 연결 + session.hello
        client.call("daemon.shutdown", {"force": False})
        event = client.notifications.get(timeout=5)

    session = attach(root, spawn=spawn_daemon)             # 붙기 순서 1~4

보내는 요청은 `Request` 봉투·params 스키마로, 받은 응답은 봉투로 검사한다
(daemon과 같은 메타스키마).
`send_text`·`send_bytes`는 검사 없이 원문을 보낸다 (전송 검사용).
"""

from __future__ import annotations

import contextlib
import itertools
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Self

from websockets.exceptions import ConnectionClosed, InvalidHandshake
from websockets.sync.client import ClientConnection, connect

from kookabug_core.win import CHILD_FLAGS
from kookabug_daemon import __version__
from kookabug_daemon.protocol import (
    MAX_FRAME,
    PROTOCOL,
    REQUEST_FAILED,
    decode,
    encode,
    methods,
    params_problems,
    response_problems,
)
from kookabug_daemon.session import (
    LOGS_DIR,
    PRIVATE_DIR,
    WAIT_TIMEOUT_S,
    SessionInfo,
    read_session,
    session_alive,
    wait_for_valid_session,
)

__all__ = [
    "UI_CLIENT",
    "ConnectionLost",
    "DaemonClient",
    "DaemonError",
    "attach",
    "probe_session",
    "spawn_daemon",
]

UI_CLIENT: Final[dict[str, Any]] = {"kind": "ui", "name": "kookabug-python", "version": __version__}
DEFAULT_TIMEOUT: Final = 30.0


class DaemonError(Exception):
    """daemon이 오류로 답했다. `kind`는 -32100이면 `data.code`, 아니면 None."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.data = data

    @property
    def kind(self) -> str | None:
        if self.code == REQUEST_FAILED and isinstance(self.data, dict):
            kind: Any = self.data.get("code")  # pyright: ignore[reportUnknownMemberType]
            return kind if isinstance(kind, str) else None
        return None


class ConnectionLost(Exception):
    """연결이 끊겼다. `code`는 받은 닫기 코드(없으면 None)."""

    def __init__(self, code: int | None, reason: str) -> None:
        super().__init__(f"연결이 끊겼다 ({code}: {reason})")
        self.code = code
        self.reason = reason


class DaemonClient:
    """연결 하나. 읽기 스레드가 응답을 id로 짝짓고 알림을 `notifications`에 넣는다."""

    def __init__(self, ws: ClientConnection, *, check: bool = True) -> None:
        self.ws = ws
        self.check = check
        self.notifications: queue.Queue[dict[str, Any]] = queue.Queue()
        self.hello_result: dict[str, Any] | None = None
        self.closed = threading.Event()
        self.close_code: int | None = None
        self.close_reason = ""
        self._ids = itertools.count(1)
        self._pending: dict[int, Future[Any]] = {}
        self._orphans: queue.Queue[dict[str, Any]] = queue.Queue()
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read, name="daemon-client", daemon=True)
        self._reader.start()

    # ---------------------------------------------------------------- 연결

    @classmethod
    def open(cls, port: int, *, timeout: float = 5.0, check: bool = True, **options: Any) -> Self:
        """연결만 한다 (hello 없음). `options`는 websockets `connect` 인자."""
        ws = connect(
            f"ws://127.0.0.1:{port}",
            open_timeout=timeout,
            compression=None,
            max_size=MAX_FRAME,
            legacy=True,  # 연결 객체를 바로 받는다 (이 클래스가 닫기를 맡는다)
            proxy=None,  # 127.0.0.1에 바로 붙는다 (websockets는 기본으로 시스템 프록시를 쓴다)
            **options,
        )
        return cls(ws, check=check)

    @classmethod
    def connect(
        cls,
        port: int,
        token: str,
        *,
        client: Mapping[str, Any] = UI_CLIENT,
        protocol: int = PROTOCOL,
        timeout: float = 5.0,
    ) -> Self:
        """연결 + `session.hello`. 실패하면 연결을 닫고 예외."""
        self = cls.open(port, timeout=timeout)
        try:
            self.hello_result = self.call(
                "session.hello",
                {"token": token, "protocol": protocol, "client": dict(client)},
                timeout=timeout,
            )
        except BaseException:
            self.close()
            raise
        return self

    @classmethod
    def from_session(cls, info: SessionInfo, **kwargs: Any) -> Self:
        return cls.connect(info.port, info.token, **kwargs)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.ws.close()
        self._reader.join(timeout=5)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ---------------------------------------------------------------- 보내기

    def request(self, method: str, params: Mapping[str, Any] | None = None) -> Future[Any]:
        values = {} if params is None else dict(params)
        # 계약에 없는 메서드는 그대로 보낸다 (daemon이 method_not_found로 답한다)
        known = method in methods()
        if self.check and known and (problems := params_problems(method, values)):
            raise ValueError(f"{method} params 형식이 틀렸다: {[d.message for d in problems]}")
        future: Future[Any] = Future()
        with self._lock:
            if self.closed.is_set():
                raise ConnectionLost(self.close_code, self.close_reason)
            request_id = next(self._ids)
            self._pending[request_id] = future
        self.send_text(
            encode({"jsonrpc": "2.0", "id": request_id, "method": method, "params": values})
        )
        return future

    def call(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Any:
        return self.request(method, params).result(timeout)

    def send_text(self, text: str) -> None:
        try:
            self.ws.send(text)
        except ConnectionClosed as exc:
            raise ConnectionLost(self.close_code, str(exc)) from exc

    def send_bytes(self, data: bytes) -> None:
        try:
            self.ws.send(data)
        except ConnectionClosed as exc:
            raise ConnectionLost(self.close_code, str(exc)) from exc

    def next_unmatched(self, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
        """짝지을 요청이 없는 응답 (id가 null인 오류 응답 등)."""
        return self._orphans.get(timeout=timeout)

    def wait_closed(self, timeout: float = DEFAULT_TIMEOUT) -> int | None:
        """daemon이 연결을 닫을 때까지 기다려 닫기 코드를 돌려준다."""
        if not self.closed.wait(timeout):
            raise TimeoutError(f"{timeout}초 안에 연결이 닫히지 않았다")
        return self.close_code

    # ---------------------------------------------------------------- 받기

    def _read(self) -> None:
        try:
            for frame in self.ws:
                if isinstance(frame, bytes):
                    raise ValueError("daemon이 바이너리 프레임을 보냈다")
                self._dispatch(decode(frame))
        except ConnectionClosed:
            pass
        finally:
            self.close_code = self.ws.close_code
            self.close_reason = self.ws.close_reason or ""
            with self._lock:
                self.closed.set()
                pending, self._pending = self._pending, {}
            for future in pending.values():
                if not future.done():
                    future.set_exception(ConnectionLost(self.close_code, self.close_reason))

    def _dispatch(self, message: Any) -> None:
        if not isinstance(message, dict):
            raise ValueError(f"daemon이 객체가 아닌 메시지를 보냈다: {message!r}")
        msg: dict[str, Any] = message
        if "method" in msg:
            self.notifications.put(msg)
            return
        if self.check and (problems := response_problems(msg)):
            raise ValueError(f"응답 봉투가 틀렸다: {[d.message for d in problems]}")
        request_id = msg.get("id")
        with self._lock:
            future = self._pending.pop(request_id, None) if isinstance(request_id, int) else None
        if future is None:
            self._orphans.put(msg)
            return
        if "error" in msg:
            error: dict[str, Any] = msg["error"]
            future.set_exception(DaemonError(error["code"], error["message"], error.get("data")))
        else:
            future.set_result(msg["result"])


# ---------------------------------------------------------------- 붙기


def probe_session(info: SessionInfo, *, timeout: float = 2.0) -> bool:
    """그 포트로 `session.hello` 인증이 성공하고 같은 daemon(`start_id`)인가."""
    try:
        with DaemonClient.from_session(info, timeout=timeout) as client:
            result = client.hello_result or {}
            return result.get("start_id") == info.start_id
    except OSError, TimeoutError, InvalidHandshake, ConnectionLost, DaemonError, ValueError:
        return False


def daemon_log_path(root: Path, now: datetime | None = None) -> Path:
    moment = datetime.now(UTC) if now is None else now
    return root / PRIVATE_DIR / LOGS_DIR / f"daemon-{moment:%Y%m%dT%H%M%S}-launch.log"


def spawn_daemon(root: Path, *, command: list[str] | None = None) -> subprocess.Popen[bytes]:
    """`kookabug daemon --workspace <루트>`를 창 없이 띄운다. stdout·stderr는 로그 파일로."""
    args = command or [sys.executable, "-m", "kookabug_cli", "daemon"]
    log = daemon_log_path(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as out:
        return subprocess.Popen(
            [*args, "--workspace", str(root)],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=out,
            creationflags=CHILD_FLAGS,
            close_fds=True,
        )


type Spawner = Callable[[Path], object]
type Prober = Callable[[SessionInfo], bool]


def attach(
    root: Path,
    *,
    spawn: Spawner = spawn_daemon,
    probe: Prober = probe_session,
    timeout: float = WAIT_TIMEOUT_S,
) -> SessionInfo | None:
    """붙기 순서 (M2 계획 2.3):

    1. `session.json`을 읽는다
    2. PID가 살아 있고 생성 시각이 같으면 `session.hello`를 해 본다
    3. 실패하면 daemon을 띄운다 (경쟁에서 지면 그 daemon은 0으로 끝난다)
    4. 유효한 세션이 생길 때까지 기다린다. 같은 `start_id`(일시적인 연결 실패)도 정상이다

    기한을 넘기면 None."""
    found = read_session(root)
    if found is not None and session_alive(found) and probe(found):
        return found
    started = time.monotonic()
    spawn(root)
    left = max(0.0, timeout - (time.monotonic() - started))
    return wait_for_valid_session(root, probe, timeout=left)
