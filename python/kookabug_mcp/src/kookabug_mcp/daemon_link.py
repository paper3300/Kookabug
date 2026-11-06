"""MCP shim ↔ daemon 연결 (M5 계획 3.1·D2).

- 앱과 같은 붙기 순서(`client.attach`, daemon이 없으면 띄움)로 붙고 agent 주체로 hello한다
  (`client = {kind: agent, id, attended, name}`). 판정·상태는 전부 daemon에 있다
- daemon이 끊기면 그때 진행 중인 호출은 오류(`daemon_disconnected`)로 답하고, 다음 호출에서 한 번
  다시 붙는다(같은 `agent-id` → 중복 방지 키 범위 유지). 다시 붙은 연결의 툴셋은 기억한 것으로 켠다
- daemon 알림(작업 공간 변경 등)은 쓰지 않으므로 받는 대로 버린다 (큐가 쌓이지 않게)
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from kookabug_daemon.client import (
    ConnectionLost,
    DaemonClient,
    DaemonError,
    attach,
    spawn_daemon,
)
from kookabug_daemon.session import SessionInfo
from kookabug_mcp import __version__
from kookabug_mcp.results import ToolError

__all__ = ["DEFAULT_TIMEOUT", "DaemonLink", "LinkError"]

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT: Final = 240.0
"""daemon 호출 하나의 기한. 사람 확인 대기(120초) + 제어 실행(기한 30초·마무리)보다 길다 (M5 B3)."""


class LinkError(Exception):
    """daemon에 붙지 못했다 (종료 코드 6)."""


type Attacher = Callable[[Path], SessionInfo | None]


def _default_attach(root: Path) -> SessionInfo | None:
    return attach(root, spawn=spawn_daemon)


class DaemonLink:
    def __init__(
        self,
        root: Path,
        *,
        agent_id: str,
        attended: bool,
        name: str,
        attacher: Attacher = _default_attach,
    ) -> None:
        self.root = root
        self.client_info: dict[str, Any] = {
            "kind": "agent",
            "id": agent_id,
            "attended": attended,
            "name": name,
            "version": __version__,
        }
        self.attacher = attacher
        self.principal: dict[str, Any] | None = None
        self.toolsets: frozenset[str] = frozenset({"core"})
        """켜진 툴셋 (daemon이 마지막으로 알려 준 것). 다시 붙을 때 이것으로 켠다."""
        self._client: DaemonClient | None = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 붙기

    def connect(self) -> None:
        """처음 붙기. 실패하면 `LinkError` (워크스페이스 daemon 판이 다른 경우 포함)."""
        with self._lock:
            self._client = self._open()

    def _open(self) -> DaemonClient:
        info = self.attacher(self.root)
        if info is None:
            raise LinkError(f"{self.root}의 daemon에 붙지 못했다 (기한 초과)")
        try:
            client = DaemonClient.connect(info.port, info.token, client=self.client_info)
        except DaemonError as exc:
            if exc.kind == "protocol_mismatch":
                raise LinkError(f"daemon 프로토콜 판이 다르다: {exc.message}") from exc
            raise LinkError(f"daemon이 연결을 거부했다: {exc.message}") from exc
        except (OSError, TimeoutError, ConnectionLost) as exc:
            raise LinkError(f"daemon에 붙지 못했다: {exc}") from exc
        hello = client.hello_result or {}
        self.principal = hello.get("principal")
        threading.Thread(
            target=_drain, args=(client,), name="mcp-daemon-notify", daemon=True
        ).start()
        wanted = sorted(self.toolsets - {"core"})
        try:
            if wanted:
                result = client.call("agent.toolsets.enable", {"toolsets": wanted})
            else:
                result = client.call("agent.toolsets.get")
            self.toolsets = frozenset(result["enabled"])
        except DaemonError as exc:
            # kb_toolset_enable이 거부된 정책: 붙기는 그대로 하고 daemon 기본(core)으로 본다
            log.warning("툴셋을 맞추지 못했다 (core만): %s", exc)
            self.toolsets = frozenset({"core"})
        except (ConnectionLost, TimeoutError) as exc:
            client.close()
            raise LinkError(f"툴셋을 맞추지 못했다: {exc}") from exc
        log.info("daemon에 붙었다 (포트 %d, 주체 %s)", info.port, self.principal)
        return client

    def _live(self) -> DaemonClient:
        with self._lock:
            client = self._client
            if client is not None and not client.closed.is_set():
                return client
            if client is not None:
                client.close()
            self._client = None
            log.warning("daemon 연결이 끊겨 다시 붙는다")
            try:
                self._client = self._open()
            except LinkError as exc:
                raise ToolError("daemon_unavailable", str(exc)) from exc
            return self._client

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    # ---------------------------------------------------------------- 부르기

    def call(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Any:
        """daemon 메서드 하나. 오류 응답은 `DaemonError`, 연결이 끊기면 `ToolError`."""
        client = self._live()
        try:
            return client.call(method, params, timeout=timeout)
        except ConnectionLost as exc:
            raise ToolError(
                "daemon_disconnected", "daemon 연결이 끊겼다. 다시 시도하면 다시 붙는다"
            ) from exc
        except TimeoutError as exc:
            raise ToolError("daemon_timeout", f"daemon이 {timeout:g}초 안에 답하지 않았다") from exc
        except ValueError as exc:  # 보내기 전 계약 검사 (daemon도 같은 스키마로 거부한다)
            raise ToolError("invalid_params", str(exc)) from exc

    def enable(self, toolsets: list[str]) -> dict[str, Any]:
        result = self.call("agent.toolsets.enable", {"toolsets": toolsets})
        self.toolsets = frozenset(result["enabled"])
        return result


def _drain(client: DaemonClient) -> None:
    while not client.closed.is_set():
        try:
            client.notifications.get(timeout=1.0)
        except queue.Empty:
            continue
