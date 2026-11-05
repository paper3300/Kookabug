"""MCP shim 검사 공용: 예제 워크스페이스 사본 + 같은 프로세스 daemon + `kookabug mcp` 하위 프로세스.

daemon은 제품 기본값(agent 연결은 `core`만)으로 띄운다. shim은 `session.json`으로 그 daemon에
붙는다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from kb_testing.daemon import ThreadDaemon, copy_sample_workspace, daemon_env
from kb_testing.mcp_client import McpClient
from kb_testing.proc import Spawned

type StartMcp = Callable[..., McpClient]


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return copy_sample_workspace(tmp_path / "ws")


@pytest.fixture
def environ(tmp_path: Path) -> dict[str, str]:
    return {"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")}


@pytest.fixture
def daemon(ws: Path, environ: dict[str, str]) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws, environ=environ, agent_toolsets=("core",)) as d:
        yield d


@pytest.fixture
def start_mcp(spawned: Spawned, ws: Path, tmp_path: Path) -> Iterator[StartMcp]:
    clients: list[McpClient] = []

    def start(*args: str) -> McpClient:
        out = tmp_path / f"mcp{len(clients)}"
        client = McpClient.start(spawned, ws, out, *args, env=daemon_env(tmp_path))
        clients.append(client)
        return client

    yield start
    for client in clients:
        client.__exit__(None, None, None)
