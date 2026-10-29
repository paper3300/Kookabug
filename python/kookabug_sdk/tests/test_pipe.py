"""named pipe 전송 (구현 계획 M0b 2.2): 프레임·인증·기한·취소."""

from __future__ import annotations

import _winapi
import ast
import ctypes
import hashlib
import struct
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

import pytest

from kookabug_sdk import pipe
from kookabug_sdk.pipe import (
    MAX_FRAME,
    AuthError,
    AuthTimeout,
    FrameTooLarge,
    PipeClosed,
    PipeConnection,
    PipeError,
    PipeListener,
    PipeTimeout,
    ProtocolError,
    connect,
    connect_raw,
    new_key,
    new_pipe_name,
)

pytestmark = pytest.mark.process


def in_thread(fn: Any, *args: Any, **kwargs: Any) -> tuple[threading.Thread, list[Any]]:
    """`fn`을 다른 스레드에서 돌린다. 결과(또는 예외)는 목록에 하나 들어간다."""
    out: list[Any] = []

    def run() -> None:
        try:
            out.append(fn(*args, **kwargs))
        except BaseException as e:
            out.append(e)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, out


def wait_for(condition: Any, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "조건이 기한 안에 맞지 않았다"
        time.sleep(0.005)


def joined(thread: threading.Thread, out: list[Any], timeout: float = 10) -> Any:
    thread.join(timeout)
    assert not thread.is_alive(), "스레드가 기한 안에 끝나지 않았다"
    return out[0]


def raw_pair() -> tuple[PipeListener, PipeConnection, PipeConnection]:
    """인증 없는 (리스너, 서버 끝, 클라이언트 끝)."""
    name = new_pipe_name("raw")
    listener = PipeListener(name)
    thread, out = in_thread(listener.accept_raw, 10)
    client = connect_raw(name, 10)
    return listener, joined(thread, out), client


def frame(body: bytes) -> bytes:
    return struct.pack("<I", len(body)) + body


# ── _winapi ───────────────────────────────────────────────────────────


def test_winapi_functions_available() -> None:
    missing = [n for n in pipe.WINAPI_USED if not hasattr(_winapi, n)]
    assert not missing, f"_winapi에 없다: {missing}"
    missing = [n for n in pipe.OVERLAPPED_USED if not hasattr(_winapi.Overlapped, n)]
    assert not missing, f"_winapi.Overlapped에 없다: {missing}"

    # pipe.py가 쓰는 `_winapi.X`·`ov.X`가 모두 위 목록에 있다 (목록이 실제 사용과 어긋나지 않게)
    tree = ast.parse(Path(pipe.__file__).read_text(encoding="utf-8"))
    used = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "_winapi"
    }
    assert used == set(pipe.WINAPI_USED)
    ov_used = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "ov"
    }
    assert ov_used <= set(pipe.OVERLAPPED_USED)

    # 실제로 동작하는지: 연결해 한 번 주고받는다
    listener, server, client = raw_pair()
    client.send_frame(b"x")
    assert server.recv_frame(5) == b"x"
    for conn in (listener, server, client):
        conn.close()


# ── 프레임 ────────────────────────────────────────────────────────────


def test_wire_format_length_prefix_le(pipe_pair: Any) -> None:
    server, client = pipe_pair()
    client.send_frame(b'{"a":1}')
    assert server.read_raw(5) == b'\x07\x00\x00\x00{"a":1}'

    body = b"x" * 300  # 0x012C: 바이트 순서가 보인다
    client.send_frame(body)
    got = b""
    while len(got) < 304:
        got += server.read_raw(5)
    assert got == b"\x2c\x01\x00\x00" + body


def test_frame_split_across_writes(pipe_pair: Any) -> None:
    server, client = pipe_pair()
    data = frame("한 프레임을 여러 번에".encode())
    client.write_raw(data[:2])  # 길이 접두의 절반
    with pytest.raises(PipeTimeout):
        server.recv_frame(timeout=0.2)
    client.write_raw(data[2:9])
    with pytest.raises(PipeTimeout):
        server.recv_frame(timeout=0.2)
    client.write_raw(data[9:])
    assert server.recv_frame(5) == "한 프레임을 여러 번에".encode()
    # 기한으로 끊긴 읽기 뒤에도 연결은 그대로다
    client.send_frame(b"next")
    assert server.recv_frame(5) == b"next"


def test_frames_coalesced_in_one_read(pipe_pair: Any) -> None:
    server, client = pipe_pair()
    bodies = [b"one", b"two" * 100, b"3"]
    client.write_raw(b"".join(frame(b) for b in bodies))
    assert [server.recv_frame(5) for _ in bodies] == bodies


@pytest.mark.parametrize("size", [0, MAX_FRAME + 1, 2**32 - 1])
def test_zero_or_oversize_length_rejected_by_receiver(pipe_pair: Any, size: int) -> None:
    server, client = pipe_pair()
    client.write_raw(struct.pack("<I", size) + b"xx")
    with pytest.raises(ProtocolError):
        server.recv_frame(5)
    assert server.closed
    with pytest.raises(PipeClosed):
        client.recv_frame(5)


def test_oversize_rejected_by_sender(pipe_pair: Any) -> None:
    server, client = pipe_pair()
    with pytest.raises(FrameTooLarge):
        client.send_frame(b"x" * (MAX_FRAME + 1))
    with pytest.raises(FrameTooLarge):
        client.send_frame(b"")
    # 아무것도 나가지 않았고 연결은 그대로다
    assert not client.closed
    client.send_frame(b"ok")
    assert server.recv_frame(5) == b"ok"
    # 상한 그대로는 보낼 수 있다
    big = b"y" * MAX_FRAME
    thread, out = in_thread(server.recv_frame, 30)
    client.send_frame(big, timeout=30)
    assert joined(thread, out, 30) == big


def test_eof_mid_frame_is_disconnect(pipe_pair: Any) -> None:
    server, client = pipe_pair()
    client.write_raw(struct.pack("<I", 100) + b"x" * 10)
    client.close()
    with pytest.raises(PipeClosed, match="프레임 중간"):
        server.recv_frame(5)


def test_eof_between_frames_is_disconnect(pipe_pair: Any) -> None:
    server, client = pipe_pair()
    client.send_frame(b"last")
    client.close()
    assert server.recv_frame(5) == b"last"
    with pytest.raises(PipeClosed):
        server.recv_frame(5)


# ── 만들기·플래그 ─────────────────────────────────────────────────────

SQUATTER = """\
import _winapi, sys
try:
    _winapi.CreateNamedPipe(sys.argv[1], _winapi.PIPE_ACCESS_DUPLEX, 0,
                            _winapi.PIPE_UNLIMITED_INSTANCES, 4096, 4096, 0, _winapi.NULL)
except OSError as e:
    print("denied", e.winerror, flush=True)
    raise SystemExit(3)
print("ready", flush=True)
sys.stdin.read()
"""


def squatter(name: str) -> subprocess.Popen[str]:
    # 표준 라이브러리만 쓰므로 venv 런처를 거치지 않고 기반 인터프리터를 바로 띄운다 (kill이 실제
    # 프로세스를 끝내게)
    python = getattr(sys, "_base_executable", sys.executable)
    return subprocess.Popen(
        [python, "-c", SQUATTER, name],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )


def test_first_instance_flag_blocks_squatting() -> None:
    # 다른 프로세스가 같은 이름을 먼저 만들었으면 서버 만들기가 실패한다
    name = new_pipe_name("squat")
    proc = squatter(name)
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        with pytest.raises(PipeError, match="만들 수 없다"):
            PipeListener(name)
    finally:
        proc.kill()
        proc.wait(10)

    # 거꾸로, 서버가 만든 뒤에는 다른 프로세스가 같은 이름의 인스턴스를 더 만들지 못한다
    name = new_pipe_name("squat")
    with PipeListener(name):
        proc = squatter(name)
        try:
            out, _ = proc.communicate(timeout=30)
            assert proc.returncode == 3, out
            assert out.startswith("denied")
        finally:
            proc.kill()


def test_remote_clients_rejected_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, ...]] = []
    original = _winapi.CreateNamedPipe

    def spy(*args: Any) -> int:
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(_winapi, "CreateNamedPipe", spy)
    name, key = new_pipe_name("flags"), new_key()
    listener = PipeListener(name)
    monkeypatch.undo()

    (_, open_mode, pipe_mode, max_instances, *_rest) = calls[0]
    assert pipe_mode & pipe.PIPE_REJECT_REMOTE_CLIENTS == 0x8
    assert pipe_mode & _winapi.PIPE_TYPE_MESSAGE == 0  # byte mode
    assert open_mode & _winapi.FILE_FLAG_FIRST_PIPE_INSTANCE
    assert open_mode & _winapi.FILE_FLAG_OVERLAPPED
    assert max_instances == 1

    # 실제 핸들: 서버 끝, byte mode, 인스턴스 1
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = kernel32.GetNamedPipeInfo
    get_info.argtypes = [wintypes.HANDLE, *[ctypes.POINTER(wintypes.DWORD)] * 4]
    get_info.restype = wintypes.BOOL
    flags, out_size, in_size, instances = (wintypes.DWORD() for _ in range(4))
    handle = listener._conn._handle  # pyright: ignore[reportPrivateUsage, reportOptionalMemberAccess]
    ok = get_info(
        handle,
        ctypes.byref(flags),
        ctypes.byref(out_size),
        ctypes.byref(in_size),
        ctypes.byref(instances),
    )
    assert ok, ctypes.get_last_error()
    assert flags.value & 0x1  # PIPE_SERVER_END
    assert not flags.value & 0x4  # PIPE_TYPE_MESSAGE
    assert instances.value == 1

    # 로컬 클라이언트는 붙는다
    thread, out = in_thread(listener.accept, key, timeout=10)
    client = connect(name, key, timeout=10)
    server = joined(thread, out)
    assert isinstance(server, PipeConnection)
    server.close()
    client.close()


# ── 인증 ─────────────────────────────────────────────────────────────


def test_mutual_auth_succeeds_and_raises_frame_limit(pipe_pair: Any) -> None:
    server, client = pipe_pair()
    assert server.authenticated and client.authenticated
    client.send_frame(b"z" * 1000)  # 인증 전 상한(256)보다 크다
    assert server.recv_frame(5) == b"z" * 1000


def test_mutual_auth_wrong_key_rejected_both_ways() -> None:
    # 클라이언트의 키가 틀리면 서버가 거부한다
    name = new_pipe_name("auth")
    listener = PipeListener(name)
    thread, out = in_thread(listener.accept, new_key(), timeout=10)
    with pytest.raises(AuthError):
        connect(name, new_key(), timeout=10)
    server_error = joined(thread, out)
    assert isinstance(server_error, AuthError)
    assert "클라이언트가 키를 증명하지 못했다" in str(server_error)

    # 서버가 키를 모르면(가짜 서버) 클라이언트가 거부한다. 가짜 서버는 클라이언트의 증명을 확인하지
    # 못하므로 그냥 받아들이고 엉터리 증명을 보낸다
    name, key = new_pipe_name("auth"), new_key()
    listener = PipeListener(name)
    thread, out = in_thread(connect, name, key, timeout=10)
    fake = listener.accept_raw(10)
    fake.send_frame(b"n" * 32, 5)
    assert len(fake.recv_frame(5)) == 64
    fake.send_frame(hashlib.sha256(b"guess").digest(), 5)
    client_error = joined(thread, out)
    assert isinstance(client_error, AuthError)
    assert "서버가 키를 증명하지 못했다" in str(client_error)
    with pytest.raises(PipeClosed):  # 클라이언트가 끊었다
        fake.recv_frame(5)
    fake.close()


def test_auth_rejects_reflected_proof() -> None:
    # 가짜 클라이언트가 서버의 도전을 그대로 되돌려도(반사) 통과하지 못한다
    name = new_pipe_name("auth")
    listener = PipeListener(name)
    thread, out = in_thread(listener.accept, new_key(), timeout=10)
    fake = connect_raw(name, 10)
    nonce = fake.recv_frame(5)
    fake.send_frame(nonce + nonce, 5)
    assert isinstance(joined(thread, out), AuthError)
    fake.close()


def test_pre_auth_frame_limit() -> None:
    name = new_pipe_name("auth")
    listener = PipeListener(name)
    thread, out = in_thread(listener.accept, new_key(), timeout=10)
    fake = connect_raw(name, 10)
    fake.recv_frame(5)
    fake.write_raw(frame(b"x" * 300))
    error = joined(thread, out)
    assert isinstance(error, AuthError)
    assert "범위" in str(error)
    fake.close()


def test_auth_timeout() -> None:
    # 붙기만 하고 아무것도 보내지 않는 클라이언트 → 서버 인증 기한
    name = new_pipe_name("auth")
    listener = PipeListener(name)
    thread, out = in_thread(listener.accept, new_key(), timeout=10, auth_timeout=0.3)
    silent = connect_raw(name, 10)
    started = time.monotonic()
    assert isinstance(joined(thread, out), AuthTimeout)
    assert time.monotonic() - started < 5
    silent.close()

    # 받기만 하고 도전을 보내지 않는 서버 → 클라이언트 인증 기한
    name = new_pipe_name("auth")
    listener = PipeListener(name)
    thread, out = in_thread(listener.accept_raw, 10)
    started = time.monotonic()
    with pytest.raises(AuthTimeout):
        connect(name, new_key(), timeout=10, auth_timeout=0.3)
    assert time.monotonic() - started < 5
    joined(thread, out).close()


# ── 기한 ─────────────────────────────────────────────────────────────


def test_accept_timeout_no_client() -> None:
    listener = PipeListener(new_pipe_name("accept"))
    started = time.monotonic()
    with pytest.raises(PipeTimeout):
        listener.accept(new_key(), timeout=0.3)
    assert time.monotonic() - started < 5
    # 실패한 리스너는 닫혔다
    with pytest.raises(PipeClosed):
        listener.accept(new_key(), timeout=0.3)


def test_connect_timeout_no_server() -> None:
    started = time.monotonic()
    with pytest.raises(PipeTimeout):
        connect(new_pipe_name("nobody"), new_key(), timeout=0.3)
    assert time.monotonic() - started < 5


def test_connect_timeout_when_instance_busy() -> None:
    # 인스턴스가 하나뿐이라 다른 클라이언트가 먼저 붙었으면 기한까지 기다리다 실패한다
    listener, server, client = raw_pair()
    started = time.monotonic()
    with pytest.raises(PipeTimeout):
        connect_raw(listener.name, 0.3)
    assert time.monotonic() - started < 5
    server.close()
    client.close()


def test_connect_waits_for_server_created_later() -> None:
    name, key = new_pipe_name("late"), new_key()
    thread, out = in_thread(connect, name, key, timeout=10)
    listener = PipeListener(name)
    server = listener.accept(key, timeout=10)
    client = joined(thread, out)
    assert isinstance(client, PipeConnection)
    server.close()
    client.close()


def test_write_timeout_when_peer_never_reads() -> None:
    server, client = pipe_pair_small_buffer()
    started = time.monotonic()
    with pytest.raises(PipeTimeout):
        # 읽지 않는 상대: 버퍼(4 KiB)를 넘는 프레임은 끝나지 않는다
        client.send_frame(b"x" * (1024 * 1024), timeout=0.3)
    assert time.monotonic() - started < 5
    # 프레임 일부만 나갔을 수 있으므로 연결을 닫았다
    assert client.closed
    with pytest.raises(PipeClosed):
        client.send_frame(b"again")
    server.close()


def pipe_pair_small_buffer() -> tuple[PipeConnection, PipeConnection]:
    name, key = new_pipe_name("small"), new_key()
    listener = PipeListener(name, buffer_size=4096)
    thread, out = in_thread(listener.accept, key, timeout=10)
    client = connect(name, key, timeout=10)
    return joined(thread, out), client


# ── 취소·동시성 ──────────────────────────────────────────────────────


def test_close_cancels_blocked_read_from_other_thread(pipe_pair: Any) -> None:
    server, _client = pipe_pair()
    thread, out = in_thread(server.recv_frame)  # 기한 없음
    # 읽기가 실제로 걸릴 때까지 (진행 중인 I/O가 생길 때까지) 기다린다
    wait_for(lambda: server._inflight)  # pyright: ignore[reportPrivateUsage]
    started = time.monotonic()
    server.close()
    assert isinstance(joined(thread, out, 5), PipeClosed)
    assert time.monotonic() - started < 2
    assert server._handle is None  # pyright: ignore[reportPrivateUsage]


def test_close_cancels_blocked_accept() -> None:
    listener = PipeListener(new_pipe_name("accept"))
    thread, out = in_thread(listener.accept, new_key(), timeout=60)
    conn = listener._conn  # pyright: ignore[reportPrivateUsage]
    assert conn is not None
    wait_for(lambda: conn._inflight)  # pyright: ignore[reportPrivateUsage]
    listener.close()
    assert isinstance(joined(thread, out, 5), PipeClosed)


def test_close_cancels_blocked_write(pipe_pair: Any) -> None:
    _server, client = pipe_pair()
    thread, out = in_thread(client.send_frame, b"x" * (4 * 1024 * 1024), None)
    wait_for(lambda: client._inflight)  # pyright: ignore[reportPrivateUsage]
    client.close()
    assert isinstance(joined(thread, out, 5), PipeClosed)


def test_full_duplex_read_and_write_concurrently(pipe_pair: Any) -> None:
    # 양쪽이 동시에 버퍼(64 KiB)보다 큰 프레임을 주고받는다. 한 핸들의 읽기와 쓰기가 서로를
    # 기다리면 여기서 멈춘다
    server, client = pipe_pair()
    count, size = 40, 256 * 1024

    def body(side: bytes, i: int) -> bytes:
        return side + i.to_bytes(4, "little") + bytes([i % 251]) * size

    def send(conn: PipeConnection, side: bytes) -> None:
        for i in range(count):
            conn.send_frame(body(side, i), timeout=30)

    def receive(conn: PipeConnection, side: bytes) -> bool:
        return all(conn.recv_frame(30) == body(side, i) for i in range(count))

    jobs = [
        in_thread(send, server, b"S"),
        in_thread(send, client, b"C"),
        in_thread(receive, server, b"C"),
        in_thread(receive, client, b"S"),
    ]
    results = [joined(thread, out, 50) for thread, out in jobs]
    assert results == [None, None, True, True]


def test_name_must_be_local_pipe() -> None:
    with pytest.raises(ValueError, match="로컬 파이프"):
        PipeListener("C:/tmp/x")
    with pytest.raises(ValueError, match="로컬 파이프"):
        connect_raw("\\\\server\\pipe\\x", 0.1)
    with pytest.raises(ValueError, match="인증 키"):
        connect(new_pipe_name(), b"short")
