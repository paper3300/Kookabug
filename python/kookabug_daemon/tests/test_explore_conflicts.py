"""탐색 중 입력 충돌 (M7 계획 3.4 C7·B3) — 엄격: 입력 안전.

탐색 세션은 입력 임대권을 쥐지 않는다. 사람이 실행·녹화를 하거나 다른 주체가 임대권을 쥐면
에이전트 클릭은 기존 거부(`run_busy`·`recording_active`·`input_lease_busy`)로 끝나고 게임에 입력이
가지 않는다. 세션은 그대로 살아 있어 사람이 끝내면 이어서 탐색한다. 판정 전에 예약한 예산 칸은
시작하지 못한 클릭이면 돌아온다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env

from kb_testing.daemon import ThreadDaemon
from kb_testing.fake_game import START_BUTTON, WINDOW, FakeGame, make_fake_game
from kb_testing.proc import wait_until
from kookabug_core.documents import ENTRY_NODE, template
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.recorder_lease import RecorderLease
from kookabug_daemon.runs import RunManager

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-k", "attended": False}
CLICK = {"window": WINDOW, "point": list(START_BUTTON)}


def env_of(game: FakeGame) -> dict[str, str]:
    tmp = game.root.parent
    env = cli_env(tmp, None)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp / "user")
    return env


@pytest.fixture
def game(tmp_path: Path) -> FakeGame:
    # 게임 조작은 allow(무인 탐색이 되는 유일한 설정, U5) — 충돌 거부만 본다
    return make_fake_game(tmp_path, permissions={"preset": "full"}, screens=False)


@pytest.fixture
def env(game: FakeGame) -> dict[str, str]:
    """daemon·runner와 검사가 같은 입력 임대권 이름을 쓰도록 한 번만 만든다."""
    return env_of(game)


@pytest.fixture
def daemon(game: FakeGame, env: dict[str, str]) -> Iterator[ThreadDaemon]:
    with game.daemon(env) as d:
        yield d


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=120)
    return caught.value


def record(game: FakeGame, session: str) -> dict[str, Any]:
    path = game.root / "screens" / "_explored" / session / "explore.json"
    return json.loads(path.read_text(encoding="utf-8"))


def alive(daemon: ThreadDaemon, game: FakeGame, session: str) -> None:
    """세션이 끝나지 않았다 (메모리·디스크 모두)."""
    assert session in daemon.daemon.explore.live_ids()
    assert record(game, session)["status"] == "active"


def wait_graph(game: FakeGame) -> str:
    """60초 기다리는 테스트 그래프 (사람의 실행)."""
    value = template("test")
    value.pop("layout")
    value["nodes"] = {
        ENTRY_NODE: {"type": "core.graph.entry", "version": 1, "next": {"start": "n_wait"}},
        "n_wait": {
            "type": "core.flow.delay",
            "version": 1,
            "in": {"ms": 60_000},
            "next": {"done": "n_pass"},
        },
        "n_pass": {"type": "core.test.pass", "version": 1},
    }
    rel = "tests/wait.graph.json"
    (game.root / rel).parent.mkdir(exist_ok=True)
    (game.root / rel).write_text(json.dumps(value), encoding="utf-8")
    return rel


def test_run_active_refuses_click_keeps_session(game: FakeGame, daemon: ThreadDaemon) -> None:
    graph = wait_graph(game)
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "실행과 겹침", "max_steps": 1})["session"]
        started = ui.call("run.start", {"path": graph})
        try:
            error = refused(agent, "control.click", CLICK)
            assert (error.kind, error.data["run_id"]) == ("run_busy", started["run_id"])
            assert game.inputs() == []
            alive(daemon, game, session)
            assert record(game, session)["steps"] == 0  # 시작하지 못한 클릭은 칸을 돌려준다
        finally:
            ui.call("run.cancel", {"run_id": started["run_id"]})
            wait_until(
                lambda: ui.call("run.status", {"run_id": started["run_id"]})["state"] == "ended",
                timeout=60,
            )
        # 사람 실행이 끝나면 같은 세션에서 이어서 (예산 1칸이 그대로 남았다)
        assert agent.call("control.click", CLICK, timeout=120)["verdict"] == "pass"
        assert record(game, session)["steps"] == 1
        assert game.inputs()


def test_recording_refuses_click(game: FakeGame, daemon: ThreadDaemon) -> None:
    manager: RunManager = daemon.daemon.run_manager
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "녹화와 겹침"})["session"]
        reservation = manager.reserve_recording()
        try:
            for state in ("starting", "recording", "paused"):
                if state != "starting":
                    reservation.set_state(state)
                error = refused(agent, "control.click", CLICK)
                assert (error.kind, error.data["state"]) == ("recording_active", state)
        finally:
            reservation.release()
        assert game.inputs() == []
        alive(daemon, game, session)
        assert record(game, session)["steps"] == 0
        assert agent.call("control.click", CLICK, timeout=120)["verdict"] == "pass"


def test_lease_busy_refuses_click(
    game: FakeGame, env: dict[str, str], daemon: ThreadDaemon
) -> None:
    lease = RecorderLease(game.root, environ=env)
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "임대권 겹침"})["session"]
        lease.acquire()  # 다른 주체(녹화기 등 — 이 daemon 밖)가 입력 임대권을 쥐었다
        try:
            error = refused(agent, "control.click", CLICK)
            assert error.kind == "input_lease_busy"
        finally:
            lease.release()
        assert game.inputs() == []
        alive(daemon, game, session)
        assert agent.call("control.click", CLICK, timeout=120)["verdict"] == "pass"
        assert game.inputs()
