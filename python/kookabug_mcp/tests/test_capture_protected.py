"""실제 `kookabug mcp` → daemon → runner(가짜 예제 게임)로 본 정지 화면 (M7 계획 3.5a, UX11 B).

UX11 B: 비밀값을 입력한 뒤에도 에이전트 캡처·OCR이 막히지 않는다(게임 비밀값은 가리지 않는다)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env

from kb_testing.daemon import daemon_env
from kb_testing.fake_game import (
    ACCOUNT_FIELD,
    PASSWORD_FIELD,
    START_BUTTON,
    WINDOW,
    FakeGame,
    make_fake_game,
)
from kb_testing.mcp_client import McpClient
from kb_testing.proc import Spawned

pytestmark = [pytest.mark.process, pytest.mark.timeout(600)]

SECRET = "PWQ4417ZX"
"""검사 전용 가짜 비밀값."""
PASSWORD_BOX = [400, 285, 320, 50]


def prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path) -> FakeGame:
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", SECRET)
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    return make_fake_game(tmp_path)


def game_env(tmp_path: Path) -> dict[str, str]:
    env = cli_env(tmp_path, None, KOOKABUG_SECRET_ACC_PW=SECRET)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp_path / "user")
    return env


def mcp_for(spawned: Spawned, game: FakeGame, tmp_path: Path) -> McpClient:
    mcp = McpClient.start(spawned, game.root, tmp_path / "mcp", env=daemon_env(tmp_path))
    mcp.initialize()
    mcp.data("kb_toolset_enable", {"toolsets": ["observe", "control"]})
    return mcp


def act(mcp: McpClient, tool: str, **args: Any) -> dict[str, Any]:
    result = mcp.call_tool(tool, {"window": WINDOW, **args}, timeout=180)
    assert result["isError"] is False, (tool, result, mcp.stderr())
    return result["structuredContent"]


def pngs(root: Path) -> list[Path]:
    folder = root / ".kookabug" / "cache"
    return sorted(folder.rglob("*.png")) if folder.exists() else []


def test_real_mcp_capture_after_secret_not_blocked(
    tmp_path: Path, spawned: Spawned, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    game = prepare(tmp_path, monkeypatch, ocr_models)
    with game.daemon(game_env(tmp_path)):
        mcp = mcp_for(spawned, game, tmp_path)
        try:
            act(mcp, "kb_input_click", point=list(START_BUTTON))
            act(mcp, "kb_input_click", point=list(ACCOUNT_FIELD))
            act(mcp, "kb_input_type", text="qa_tester_01")
            act(mcp, "kb_input_click", point=list(PASSWORD_FIELD))
            act(mcp, "kb_input_type", secret="acc.pw")
            shot = mcp.call_tool("kb_screen_capture", {"window": WINDOW})
            assert shot["isError"] is False, shot
            assert any(c["type"] == "image" for c in shot["content"])
            assert "protected" not in shot["structuredContent"]
            # OCR도 막히지 않고 칸의 값이 그대로 읽힌다
            frame_id = shot["structuredContent"]["frame_id"]
            read = mcp.call_tool("kb_ocr_read", {"frame_id": frame_id, "rect": PASSWORD_BOX})
            assert read["isError"] is False, read
            text = json.dumps(read["structuredContent"], ensure_ascii=False)
            assert SECRET in text.replace(" ", "").upper()
        finally:
            mcp.close()
