"""가짜 탐색 에이전트로 본 탐색 (M7 계획 3.13, B2b): 실제 `kookabug mcp` → daemon → runner(가짜 예제
게임). 결과물을 미리 쓰지 않는다 — 각본이 도구만 부른다. 권한은 control·screens `allow`(full)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers.cli import cli_env

from kb_testing.daemon import daemon_env
from kb_testing.fake_explorer import DEFAULT_SCRIPT, run_script
from kb_testing.fake_game import make_fake_game
from kb_testing.mcp_client import McpClient
from kb_testing.proc import Spawned
from kookabug_core.screens import explored_candidates, read_screen_file
from kookabug_core.workspace import Workspace

pytestmark = [pytest.mark.process, pytest.mark.timeout(900)]

ACCOUNT = "qa_tester_01"
PASSWORD = "sample-pass-01"
"""예제 게임 로그인 값 (공개 예제 — 검사에서는 비밀값으로 넣는다)."""
SECRETS = {"KOOKABUG_SECRET_ACC_ID": ACCOUNT, "KOOKABUG_SECRET_ACC_PW": PASSWORD}


def game_env(tmp_path: Path) -> dict[str, str]:
    env = cli_env(tmp_path, None, **SECRETS)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp_path / "user")
    return env


def test_fake_explorer_sample_game(
    tmp_path: Path, spawned: Spawned, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    for key, value in SECRETS.items():
        monkeypatch.setenv(key, value)  # daemon 사전 검증·글자 검사 (이 프로세스)
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    game = make_fake_game(tmp_path, screens=False)
    script = json.loads(DEFAULT_SCRIPT.read_text(encoding="utf-8"))
    with game.daemon(game_env(tmp_path)) as d:
        mcp = McpClient.start(spawned, game.root, tmp_path / "mcp", env=daemon_env(tmp_path))
        try:
            mcp.initialize()
            summary = run_script(mcp, script)
            raw = b"\n".join(mcp.lines).decode("utf-8", "replace")
        finally:
            mcp.close()
        with d.client() as ui:
            sessions = ui.call("explore.list", {})["sessions"]
    assert summary["saved"] == [
        "title",
        "login",
        "login_error",
        "lobby",
        "loading",
        "world",
        "inventory",
    ]
    # 비밀값 칸 둘을 넣은 로그인 화면 2번 + 로딩·인벤토리(칸 자리가 민무늬라 칸 없음을 확정하지
    # 못함 — 녹화기 기준 그대로, 안전 쪽)
    assert summary["protected"] == 4
    session = summary["session"]
    (listed,) = sessions
    assert (listed["id"], listed["status"]) == (session, "ended")
    assert listed["counts"] == summary["counts"]
    assert summary["counts"]["untried"] == 1 and summary["counts"]["screens"] == 7

    folder = game.root / "screens" / "_explored" / session
    record = json.loads((folder / "explore.json").read_text("utf-8"))
    assert record["status"] == "ended" and record["steps"] >= 10
    ws = Workspace.open(game.root)
    cards = {c.key: c.screen for c in explored_candidates(ws) if c.session == session}
    assert set(cards) == set(summary["saved"])
    moves = {(key, m.to, m.status) for key, screen in cards.items() if screen for m in screen.moves}
    assert {
        ("title", "login", "tried"),
        ("login", "login_error", "tried"),
        ("login_error", "login", "tried"),
        ("login", "lobby", "tried"),
        ("lobby", "loading", "tried"),
        ("world", "inventory", "tried"),
        ("inventory", "world", "tried"),
        ("world", None, "untried"),
    } <= moves
    for key, screen in cards.items():
        assert screen is not None and screen.origin is not None, key
        assert screen.origin.session == session
        if key in ("loading", "inventory"):
            # 보호 중에 저장: 판정 조건·스크린샷 없는 미완성 후보 (사람이 채운다)
            assert screen.incomplete and screen.shot is None
            continue
        assert screen.detect(), key
        assert screen.shot is not None and (game.root / screen.shot.image).is_file(), key
    # OCR 조건·이미지 조건이 섞였다
    login_card = cards["login"]
    assert login_card is not None
    login = read_screen_file(folder / "login.screen.json", login_card.path)
    assert {c.ocr is not None for c in login.detect()} == {True, False}
    # 비밀값은 어디에도 없다: 응답 줄·탐색 결과 폴더·보호 기록
    for value in (ACCOUNT, PASSWORD):
        assert value not in raw
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix != ".png":
                assert value not in path.read_text("utf-8", "replace"), path
    protect = json.loads((game.root / ".kookabug" / "agent-protect.json").read_text("utf-8"))
    assert sorted(protect["secret_keys"]) == ["acc.id", "acc.pw"]
    # 확정 화면 경로에는 아무것도 쓰지 않았다
    assert list((game.root / "screens").glob("*.screen.json")) == []
    assert not (game.root / "targets" / "screens").exists()
