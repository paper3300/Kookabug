"""저장·내보내는 글자 검사 (M7 계획 3.5b, UX11 B).

UX11 B: 게임 비밀값(워크스페이스 비밀값)은 가리지 않는다 — 화면 저장·탐색 세션 글자에 들어 있어도
그대로 저장한다. 작업 토큰(Kookabug 자체 자격 증명) 검사는 `test_job_supervision.py`가 본다.
에이전트 ID·표시 이름 형식 검사는 그대로다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env

from kb_testing.daemon import ThreadDaemon
from kb_testing.fake_game import FakeGame, make_fake_game
from kb_testing.proc import wait_until
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

SECRET = "PWQ4417ZX"
"""검사 전용 가짜 비밀값."""
SPACED = "pwq 4417 zx"
"""공백·대소문자만 다른 같은 값."""
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-t", "attended": False}


@pytest.fixture
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeGame:
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", SECRET)
    return make_fake_game(tmp_path, draw=False)


@pytest.fixture
def daemon(game: FakeGame) -> Iterator[ThreadDaemon]:
    env = cli_env(game.root.parent, None, KOOKABUG_SECRET_ACC_PW=SECRET)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(game.root.parent / "user")
    with game.daemon(env) as d:
        yield d


def capture(client: DaemonClient) -> dict[str, Any]:
    (window,) = client.call("windows.list", {})["windows"]
    return client.call("target.capture", {"window": window["handle"]})


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=60)
    return caught.value


# 화면 카드 글자 필드마다 게임 비밀값 — 모두 그대로 저장된다
SAVE_CASES: list[tuple[str, dict[str, Any]]] = [
    ("title", {"title": f"로그인 {SPACED}"}),
    ("description", {"description": f"비밀번호는 {SECRET}"}),
    ("elements[0].name", {"elements": [{"name": SECRET, "kind": "text", "rect": [0, 0, 8, 8]}]}),
    (
        "moves[0].note",
        {"moves": [{"via": {"key": "esc"}, "to": None, "status": "untried", "note": SECRET}]},
    ),
]


@pytest.mark.parametrize(("field", "extra"), SAVE_CASES, ids=[c[0] for c in SAVE_CASES])
def test_save_field_with_game_secret_kept(
    game: FakeGame, daemon: ThreadDaemon, field: str, extra: dict[str, Any]
) -> None:
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "글자 검사"})["session"]
        frame = capture(agent)
        params = {"key": "card", "frame_id": frame["frame_id"], **extra}
        assert agent.call("screens.save", params)["key"] == "card"
    card = game.root / "screens" / "_explored" / session / "card.screen.json"
    assert SECRET in card.read_text("utf-8").upper().replace(" ", ""), field


def test_session_fields_with_game_secret_kept(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "탐색", "goal": f"x {SECRET}"})["session"]
    path = game.root / "screens" / "_explored" / session / "explore.json"
    wait_until(lambda: '"ended"' in path.read_text("utf-8"), timeout=30)
    assert json.loads(path.read_text("utf-8"))["goal"] == f"x {SECRET}"


@pytest.mark.parametrize(
    ("client", "expected"),
    [
        ({**AGENT, "id": "a" * 201}, ("validation_failed", None)),
    ],
    ids=["id_too_long"],
)
def test_agent_identity_checked(
    game: FakeGame, daemon: ThreadDaemon, client: dict[str, Any], expected: tuple[str, Any]
) -> None:
    """B2b 검수 Low 6: `explore.json`에 남는 에이전트 ID는 형식 검사."""
    with daemon.client(client) as agent:
        error = refused(agent, "explore.start", {"title": "식별자"})
        assert (error.kind, error.data.get("field")) == expected
    assert not (game.root / "screens" / "_explored").exists()


def test_agent_id_control_char_refused_at_hello(game: FakeGame, daemon: ThreadDaemon) -> None:
    """제어 문자 ID는 연결부터 거부한다 (UX5: 작업 토큰 없는 Agent ID는 공백 없는 ASCII만)."""
    with pytest.raises(DaemonError) as caught, daemon.client({**AGENT, "id": "agent\x07bell"}):
        pass
    assert caught.value.kind == "job_token_invalid"
    assert not (game.root / "screens" / "_explored").exists()


def test_agent_client_name_cleaned(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client({**AGENT, "name": "mcp\x1b[31m " + "x" * 300}) as agent:
        session = agent.call("explore.start", {"title": "표시 이름"})["session"]
    path = game.root / "screens" / "_explored" / session / "explore.json"
    wait_until(lambda: '"ended"' in path.read_text("utf-8"), timeout=30)
    client = json.loads(path.read_text("utf-8"))["agent"]["client"]
    assert client.isprintable() and len(client) == 200 and client.startswith("mcp[31m ")
