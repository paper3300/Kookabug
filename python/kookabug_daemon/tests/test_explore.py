"""에이전트 탐색 세션 (M7 계획 3.4·10장 R5): `explore.start/end/list`, 연결당 하나, 끊김, 스텝
예산(판정 전), 세션이 끝나도 비밀값 보호는 그대로. 가짜 예제 게임 + 실제 runner 제어 실행."""

from __future__ import annotations

import json
import queue
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env

from kb_testing.daemon import ThreadDaemon
from kb_testing.fake_game import PASSWORD_FIELD, START_BUTTON, WINDOW, FakeGame, make_fake_game
from kb_testing.proc import wait_until
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

SECRET = "PWQ4417ZX"
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-x", "attended": False}


def env_of(game: FakeGame) -> dict[str, str]:
    tmp = game.root.parent
    env = cli_env(tmp, None, KOOKABUG_SECRET_ACC_PW=SECRET)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp / "user")
    return env


@pytest.fixture
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeGame:
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", SECRET)
    return make_fake_game(tmp_path, screens=False)


@pytest.fixture
def daemon(game: FakeGame) -> Iterator[ThreadDaemon]:
    with game.daemon(env_of(game)) as d:
        yield d


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=120)
    return caught.value


def record(game: FakeGame, session: str) -> dict[str, Any]:
    path = game.root / "screens" / "_explored" / session / "explore.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_start_end_writes_explore_json(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent, daemon.client() as ui:
        started = agent.call(
            "explore.start", {"title": "예제 탐색", "goal": "로비까지", "window": WINDOW}
        )
        session = started["session"]
        assert started["max_steps"] == 200
        assert started["folder"] == f"screens/_explored/{session}"
        body = record(game, session)
        assert body["format"] == "kookabug.explore/0" and body["status"] == "active"
        assert (body["title"], body["goal"], body["window"]) == ("예제 탐색", "로비까지", WINDOW)
        assert body["agent"]["id"] == "agent-x"
        assert [s["status"] for s in ui.call("explore.list", {})["sessions"]] == ["active"]
        ended = agent.call("explore.end", {})
        assert ended == {"session": session, "counts": {"screens": 0, "moves": 0, "untried": 0}}
        body = record(game, session)
        assert body["status"] == "ended" and body["ended_at"]
        # 사람 연결은 세션을 열지 않는다 (에이전트 전용), 에이전트는 목록을 보지 않는다 (사람 화면)
        assert refused(ui, "explore.start", {"title": "x"}).kind == "agent_only"
        assert refused(agent, "explore.list", {}).kind == "permission_denied"
        assert refused(agent, "explore.end", {}).kind == "explore_not_active"


def test_one_session_per_connection(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent, daemon.client(AGENT) as other:
        first = agent.call("explore.start", {"title": "하나"})["session"]
        assert refused(agent, "explore.start", {"title": "둘"}).kind == "explore_active"
        second = other.call("explore.start", {"title": "다른 연결"})["session"]
        assert first != second
        assert refused(other, "explore.start", {"title": "x" * 201}).code == -32602


def test_disconnect_ends_session(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "끊길 세션"})["session"]
    wait_until(lambda: record(game, session)["status"] == "ended", timeout=30)
    # 디스크가 active인데 살아 있는 세션이 아니면 목록에서 interrupted
    path = game.root / "screens" / "_explored" / session / "explore.json"
    body = record(game, session)
    body["status"] = "active"
    path.write_text(json.dumps(body), encoding="utf-8")
    with daemon.client() as ui:
        (listed,) = ui.call("explore.list", {})["sessions"]
        assert listed["status"] == "interrupted"


def test_budget_exhausted_before_approval(game: FakeGame, tmp_path: Path) -> None:
    # 예산을 다 쓰면 판정(사람 확인) 전에 거부 — control을 ask로 두어도 확인 요청이 생기지 않는다
    local = game.root / ".kookabug" / "local.json"
    # control은 ask(runner 프리셋), 화면 지도 쓰기(탐색 세션)는 allow
    permissions = {"preset": "runner", "toolsets": {"screens": "allow"}}
    body = {"format": "kookabug.local/0", "permissions": permissions}
    local.write_text(json.dumps(body), encoding="utf-8")
    attended = {**AGENT, "attended": True}
    with game.daemon(env_of(game)) as d, d.client() as ui, d.client(attended) as agent:
        session = agent.call("explore.start", {"title": "예산", "max_steps": 1})["session"]
        # 첫 스텝: 사람 확인 → 한 번 허용 → 제어 실행 (스텝 1)
        future = agent.request("control.key", {"window": WINDOW, "keys": "a"})
        ask = approval_request(ui)
        ui.call("approval.respond", {"id": ask["id"], "verdict": "allow_once"})
        assert future.result(120)["verdict"] == "pass"
        assert record(game, session)["steps"] == 1
        before = len(game.inputs())
        error = refused(agent, "control.key", {"window": WINDOW, "keys": "a"})
        assert error.kind == "explore_budget_exhausted"
        with pytest.raises(AssertionError):
            approval_request(ui, timeout=2)  # 묻지 않았다 (판정 전에 거부)
        assert len(game.inputs()) == before
        assert record(game, session)["status"] == "active"  # 세션은 그대로


def approval_request(client: DaemonClient, timeout: float = 15) -> dict[str, Any]:
    """ui 연결의 다음 `approval.requested` params."""
    deadline = time.monotonic() + timeout
    while (left := deadline - time.monotonic()) > 0:
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            break
        if message.get("method") == "approval.requested":
            return message["params"]
    raise AssertionError("approval.requested가 오지 않았다")


def test_protection_survives_explore_end(game: FakeGame, daemon: ThreadDaemon) -> None:
    # R5: 탐색 세션이 끝나도(연결도 끊겨도) 비밀값을 입력한 창의 보호는 그대로
    with daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "보호"})
        for point in (START_BUTTON, PASSWORD_FIELD):
            agent.call("control.click", {"window": WINDOW, "point": list(point)}, timeout=120)
        agent.call("control.type", {"window": WINDOW, "secret": "acc.pw"}, timeout=120)
        agent.call("explore.end", {})
        (window,) = agent.call("windows.list", {})["windows"]
        frame = agent.call("target.capture", {"window": window["handle"]})
        assert frame["protected"]["reason"] == "secret_field"
    with daemon.client(AGENT) as again:
        (window,) = again.call("windows.list", {})["windows"]
        frame = again.call("target.capture", {"window": window["handle"]})
        assert frame["protected"]["reason"] == "secret_field" and "agent_image" not in frame
