"""가짜 MCP 클라이언트 (M5 계획 3.13): `kookabug mcp`를 띄워 stdio로 묻는 pytest 헬퍼.

    with McpClient.start(spawned, root, tmp_path / "mcp", env=env) as mcp:
        mcp.initialize()
        names = mcp.tool_names()
        result = mcp.call_tool("kb_project_info", {})

- stdout의 모든 줄을 기록한다(`lines`). 줄마다 JSON-RPC 2.0 객체여야 한다 —
  `assert_protocol_only()`가 프로토콜 밖 출력이 없는지 본다
- stderr는 `out/stderr.log` 파일로 (실패 메시지에 붙인다)
"""

from __future__ import annotations

import contextlib
import itertools
import json
import queue
import subprocess
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Self

from kb_testing.proc import Spawned, python_cmd
from kookabug_core.win import CHILD_FLAGS

__all__ = ["MCP_CMD", "McpClient", "McpError"]

MCP_CMD: Final = python_cmd("-m", "kookabug_cli", "mcp")
TIMEOUT: Final = 60.0


class McpError(Exception):
    """JSON-RPC 오류 응답."""

    def __init__(self, error: Mapping[str, Any]) -> None:
        super().__init__(f"{error.get('code')}: {error.get('message')}")
        self.code = error.get("code")
        self.message = str(error.get("message", ""))


class McpClient:
    def __init__(self, proc: subprocess.Popen[bytes], out: Path) -> None:
        self.proc = proc
        self.out = out
        self.lines: list[bytes] = []
        """stdout에서 받은 줄 전부 (개행 제외)."""
        self.notifications: queue.Queue[dict[str, Any]] = queue.Queue()
        self._responses: dict[Any, queue.Queue[dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._reader = threading.Thread(target=self._read, name="mcp-client", daemon=True)
        self._reader.start()

    @classmethod
    def start(
        cls,
        spawned: Spawned,
        root: Path,
        out: Path,
        *args: str,
        env: Mapping[str, str],
    ) -> Self:
        out.mkdir(parents=True, exist_ok=True)
        cmd = [*MCP_CMD, "--workspace", str(root), *args]
        with (out / "stderr.log").open("ab") as stderr:
            proc = spawned.popen(
                cmd,
                env=dict(env),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                creationflags=CHILD_FLAGS,
            )
        return cls(proc, out)

    # ---------------------------------------------------------------- 받기

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            line = raw.rstrip(b"\r\n")
            self.lines.append(line)
            try:
                message = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            if "method" in message:
                self.notifications.put(message)
                continue
            with self._lock:
                box = self._responses.setdefault(message.get("id"), queue.Queue())
            box.put(message)

    def stderr(self) -> str:
        path = self.out / "stderr.log"
        return path.read_text("utf-8", errors="replace")[-4000:] if path.exists() else ""

    def assert_protocol_only(self) -> None:
        """stdout의 모든 줄이 JSON-RPC 2.0 객체 하나다."""
        for line in self.lines:
            message = json.loads(line.decode("utf-8"))
            assert isinstance(message, dict) and message.get("jsonrpc") == "2.0", line

    # ---------------------------------------------------------------- 보내기

    def send(self, message: Mapping[str, Any]) -> None:
        assert self.proc.stdin is not None
        data = json.dumps(dict(message), ensure_ascii=False).encode("utf-8") + b"\n"
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def request(
        self, method: str, params: Mapping[str, Any] | None = None, *, timeout: float = TIMEOUT
    ) -> dict[str, Any]:
        """응답 메시지 전체 (오류 응답이면 `McpError`)."""
        request_id = next(self._ids)
        with self._lock:
            box = self._responses.setdefault(request_id, queue.Queue())
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = dict(params)
        self.send(message)
        deadline = time.monotonic() + timeout
        while True:
            try:
                reply = box.get(timeout=0.2)
                break
            except queue.Empty:
                # shim이 끝났으면 기다리지 않는다 (응답은 이미 읽기 스레드가 넣었을 것이다)
                exited = self.proc.poll() is not None and not self._reader.is_alive()
                if exited and box.empty():
                    raise RuntimeError(
                        f"{method}: shim이 끝났다 (종료 코드 {self.proc.returncode})\n"
                        f"--- stderr\n{self.stderr()}"
                    ) from None
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"{method}: {timeout}초 안에 답이 없다\n--- stderr\n{self.stderr()}"
                    ) from None
        if "error" in reply:
            raise McpError(reply["error"])
        return reply

    def notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = dict(params)
        self.send(message)

    def initialize(self, version: str = "2025-06-18") -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": version,
                "capabilities": {},
                "clientInfo": {"name": "kb-test", "version": "0"},
            },
        )["result"]
        self.notify("notifications/initialized")
        return result

    def tool_names(self) -> list[str]:
        return [t["name"] for t in self.request("tools/list")["result"]["tools"]]

    def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None = None, *, timeout: float = TIMEOUT
    ) -> dict[str, Any]:
        """`tools/call` 결과 (`isError`도 그대로 돌려준다)."""
        params = {"name": name, "arguments": dict(arguments or {})}
        return self.request("tools/call", params, timeout=timeout)["result"]

    def data(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """성공해야 하는 도구 호출의 `structuredContent`."""
        result = self.call_tool(name, arguments)
        assert result["isError"] is False, (name, result, self.stderr())
        return result["structuredContent"]

    def error(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """실패해야 하는 도구 호출의 `structuredContent.error`."""
        result = self.call_tool(name, arguments)
        assert result["isError"] is True, (name, result)
        text = result["content"][0]["text"]
        error = result["structuredContent"]["error"]
        assert text.startswith(f"{error['code']}: "), text
        return error

    # ---------------------------------------------------------------- 끝내기

    def close(self, timeout: float = 30.0) -> int:
        """stdin을 닫고 끝나기를 기다린다. 종료 코드."""
        if self.proc.stdin is not None and not self.proc.stdin.closed:
            with contextlib.suppress(OSError):
                self.proc.stdin.close()
        code = self.proc.wait(timeout)
        self._reader.join(timeout)
        return code

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self.proc.poll() is None:
            try:
                self.close(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
