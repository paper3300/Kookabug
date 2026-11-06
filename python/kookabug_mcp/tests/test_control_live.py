"""실제 게임 창을 MCP로 클릭한다 (M5 B3, desktop_input — 조율자가 잠금 해제 PC에서 돌린다).

`kookabug mcp` → daemon `control.click` → 제어 실행(runner·SendInput) → 예제 게임이 타이틀에서
로그인 화면으로 넘어간다. `KOOKABUG_DESKTOP_INPUT=1`일 때만 돈다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.mcp_client import McpClient
from kb_testing.sample_game import launch_sample_game

pytestmark = [pytest.mark.desktop_input, pytest.mark.process, pytest.mark.timeout(180)]

START_BUTTON = (512, 412)
"""타이틀 화면 "시작" 단추 가운데 (클라이언트 픽셀, 장면 표의 클릭 전이 영역)."""


def test_mcp_click_sample_game(
    tmp_path: Path, ws: Path, environ: dict[str, str], start_mcp: Callable[..., McpClient]
) -> None:
    local = ws / ".kookabug" / "local.json"
    local.parent.mkdir(exist_ok=True)
    body = {"format": "kookabug.local/0", "permissions": {"preset": "full"}}
    local.write_text(json.dumps(body), encoding="utf-8")
    game = launch_sample_game(workdir=tmp_path / "game")
    try:
        game.wait_screen("title")
        after = game.last_seq()
        with ThreadDaemon(ws, environ=environ, agent_toolsets=("core",)):
            mcp = start_mcp()
            mcp.initialize()
            mcp.data("kb_toolset_enable", {"toolsets": ["control"]})
            done = mcp.data("kb_input_click", {"window": "SampleRPG", "point": list(START_BUTTON)})
            assert done["verdict"] == "pass", done
            game.wait_screen("login", after=after, timeout=15)
            assert mcp.close() == 0
        runs = sorted((ws / "runs").iterdir())
        assert len(runs) == 1
        data = json.loads((runs[0] / "run.json").read_text(encoding="utf-8"))
        assert data["source"] == "agent_control"
    finally:
        game.close()
