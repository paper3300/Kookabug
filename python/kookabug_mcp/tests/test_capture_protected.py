"""실제 `kookabug mcp` → daemon → runner(가짜 예제 게임)로 본 정지 화면 보호 (M7 계획 3.5a, B2a).

양성 대조군(사람 연결의 원본 캡처에서 테스트 비밀값이 OCR로 읽힌다)을 먼저 확인하고, 에이전트가 받은
MCP 응답 줄 전부와 `.kookabug/cache/agent`·`cache/editor` 쓰기를 관찰한다."""

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


def test_real_mcp_capture_response_has_no_image_after_secret(
    tmp_path: Path, spawned: Spawned, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    game = prepare(tmp_path, monkeypatch, ocr_models)
    with game.daemon(game_env(tmp_path)) as d:
        mcp = mcp_for(spawned, game, tmp_path)
        try:
            act(mcp, "kb_input_click", point=list(START_BUTTON))
            # 비밀값 전: 이미지가 온다
            open_shot = mcp.call_tool("kb_screen_capture", {"window": WINDOW})
            assert any(c["type"] == "image" for c in open_shot["content"])
            act(mcp, "kb_input_click", point=list(ACCOUNT_FIELD))
            act(mcp, "kb_input_type", text="qa_tester_01")
            act(mcp, "kb_input_click", point=list(PASSWORD_FIELD))
            act(mcp, "kb_input_type", secret="acc.pw")
            before = {p for p in pngs(game.root)}
            seen = len(mcp.lines)
            shot = mcp.call_tool("kb_screen_capture", {"window": WINDOW})
            assert shot["isError"] is False, shot
            assert [c["type"] for c in shot["content"]] == ["text"]
            protected = shot["structuredContent"]["protected"]
            assert protected["reason"] == "secret_field" and protected["hint"]
            # 이 캡처로 agent·편집기 캐시에 새 PNG가 생기지 않았다
            assert {p for p in pngs(game.root)} == before
            # OCR도 거부 (값 없음)
            error = mcp.error("kb_ocr_read", {"frame_id": shot["structuredContent"]["frame_id"]})
            assert error["code"] == "frame_protected"
            # 양성 대조군: 같은 창을 사람이 캡처하면 그 칸에 값이 보인다
            with d.client() as ui:
                (window,) = ui.call("windows.list", {})["windows"]
                frame = ui.call("target.capture", {"window": window["handle"]})
                read = ui.call(
                    "target.read_text", {"frame_id": frame["frame_id"], "rect": PASSWORD_BOX}
                )
                assert SECRET in read["text"].replace(" ", "").upper(), read
            # 에이전트가 받은 MCP 응답 줄 전부에 값이 없다 (이미지 데이터 포함)
            raw = b"\n".join(mcp.lines).decode("utf-8", "replace")
            assert SECRET not in raw
            after = [json.loads(line) for line in mcp.lines[seen:]]
            assert not any(
                c.get("type") == "image"
                for m in after
                for c in (m.get("result") or {}).get("content", [])
            )
        finally:
            mcp.close()
