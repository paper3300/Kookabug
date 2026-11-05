"""MCP stdio 전송 (M5 계획 D1): 줄 하나 = JSON-RPC 2.0 메시지 하나, UTF-8.

stdout은 프로토콜 전용이다. `protect_stdout()`이 진짜 stdout(fd 1)을 복제해 프로토콜에 쓰고, fd 1과
`sys.stdout`은 stderr로 돌린다 — 실수로 찍힌 `print`나 자식 프로세스 출력이 프로토콜을 깨지 않는다.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Iterator, Mapping
from typing import Any, BinaryIO, Final

__all__ = ["MAX_LINE", "StdioChannel", "encode_line", "protect_stdout"]

MAX_LINE: Final = 16 * 1024 * 1024
"""한 메시지 상한 (daemon 프레임 상한과 같다). 넘는 줄은 읽지 않고 버린다."""


def protect_stdout() -> BinaryIO:
    """프로토콜용 stdout을 떼어 내고 나머지 출력은 stderr로 보낸다. 진입점에서 한 번 부른다."""
    sys.stdout.flush()
    proto = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return proto


def encode_line(message: Mapping[str, Any]) -> bytes:
    text = json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return text.encode("utf-8") + b"\n"


class StdioChannel:
    """읽기는 한 스레드(서버 주 루프), 쓰기는 여러 스레드(도구 호출 작업자)가 한다."""

    def __init__(self, reader: BinaryIO, writer: BinaryIO) -> None:
        self.reader = reader
        self.writer = writer
        self._lock = threading.Lock()
        self.closed = False

    def lines(self) -> Iterator[bytes | None]:
        """받은 줄 (끝의 개행 없이). 상한을 넘은 줄은 None 하나로 알린다. EOF면 끝난다."""
        while True:
            line = self.reader.readline(MAX_LINE + 1)
            if not line:
                return
            if len(line) > MAX_LINE and not line.endswith(b"\n"):
                # 나머지를 버린다
                while line and not line.endswith(b"\n"):
                    line = self.reader.readline(MAX_LINE + 1)
                yield None
                continue
            stripped = line.strip()
            if stripped:
                yield stripped

    def send(self, message: Mapping[str, Any]) -> None:
        data = encode_line(message)
        with self._lock:
            if self.closed:
                return
            try:
                self.writer.write(data)
                self.writer.flush()
            except OSError, ValueError:
                self.closed = True  # 상대가 파이프를 닫았다
