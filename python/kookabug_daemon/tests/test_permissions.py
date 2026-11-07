"""M7 권한 (계획 3.8·3.11, B3) — 엄격: Agent 권한.

- `explorer` 프리셋 표: 조회·화면 지도 쓰기·탐색 세션 allow, 게임 조작 ask, 그래프 편집·실행 deny.
  사람이 설정 화면에서 고르면(`permissions.set`) 도구별 판정이 그 표다
- 사람 전용 메서드(승격·버리기·확인·카드 배치·세션 목록·확인 답·권한 설정)는 에이전트가 어떤 프리셋
  에서도 부를 수 없다(판정 전 `permission_denied`, 처리기가 아직 없어도)
- 사람 없는 연결(`attended: false`)은 ask = 거부: `explorer`에서 탐색 클릭은 묻지 않고 거부,
  입력 없음
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env

from kb_testing.daemon import ThreadDaemon
from kb_testing.fake_game import START_BUTTON, WINDOW, FakeGame, make_fake_game
from kookabug_core.permissions import TOOLS, Policy, Principal, decide, load_policy
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.methods.tools import AGENT_DENIED, HUMAN_SCREEN_METHODS
from kookabug_mcp import tools as mcp_tools

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

ATTENDED = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-p", "attended": True}
UNATTENDED = {**ATTENDED, "attended": False}

# 계획 3.11 표의 explorer 열 (툴셋 → 변경 도구 값). 조회 도구는 모두 allow
EXPLORER = {"graph_edit": "deny", "run": "deny", "control": "ask", "screens": "allow"}
# 3.11 표 행 그대로 (도구 → explorer 값)
TABLE_3_11 = {
    "kb_screen_list": "allow",
    "kb_screen_get": "allow",
    "kb_screen_identify": "allow",
    "kb_explore_start": "allow",
    "kb_explore_end": "allow",
    "kb_screen_save": "allow",
    "kb_input_click": "ask",
    "kb_input_key": "ask",
    "kb_input_type": "ask",
    "kb_app_launch": "ask",
    "kb_graph_create": "deny",
    "kb_graph_patch": "deny",
    "kb_target_create": "deny",
    "kb_run_start": "deny",
    "kb_run_cancel": "deny",
}
HUMAN_ONLY = {
    "screens.check": {"session": "20260101-000000-abcd", "key": "title"},
    "screens.promote": {
        "session": "20260101-000000-abcd",
        "key": "title",
        "mode": "new",
        "base_revisions": {},
    },
    "screens.discard": {"session": "20260101-000000-abcd"},
    "screens.layout_get": {},
    "screens.layout_set": {"layout": {}, "base_revision": None},
    "explore.list": {},
    "approval.list": {},
    "approval.respond": {"id": "ap_0123456789abcdef", "verdict": "allow_session"},
    "permissions.set": {
        "layer": "project",
        "permissions": {"preset": "full"},
        "base_revision": None,
    },
}


def env_of(game: FakeGame) -> dict[str, str]:
    tmp = game.root.parent
    env = cli_env(tmp, None)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp / "user")
    return env


@pytest.fixture
def game(tmp_path: Path) -> FakeGame:
    return make_fake_game(tmp_path, permissions={"preset": "explorer"}, screens=False)


@pytest.fixture
def daemon(game: FakeGame) -> Iterator[ThreadDaemon]:
    with game.daemon(env_of(game)) as d:
        yield d


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=120)
    return caught.value


def expected(tool: str) -> str:
    info = TOOLS[tool]
    return EXPLORER[info.toolset] if info.mutating else "allow"


def test_explorer_preset_table(game: FakeGame, daemon: ThreadDaemon) -> None:
    # 순수 판정: 3.11 표 행 + 나머지 도구는 툴셋 규칙(조회 allow)
    policy = load_policy(game.root, game.root.parent / "user")
    assert not policy.diagnostics
    agent = Principal("agent", "agent-p", attended=True)
    for tool, value in TABLE_3_11.items():
        assert decide(policy, agent, tool).final == value, tool
    for tool in TOOLS:
        d = decide(policy, agent, tool)
        assert (d.final, d.source) == (expected(tool), "preset:explorer"), tool
    assert (
        decide(Policy(), agent, "kb_explore_end").final == "allow"
    )  # 기본 프리셋에서도 끝낼 수 있다
    # 설정 화면이 보는 도구별 판정 (ui 연결 — 사람이 지켜보는 에이전트 기준)
    with daemon.client() as ui:
        shown = {t["tool"]: t["final"] for t in ui.call("permissions.get", {})["tools"]}
        assert shown == {tool: expected(tool) for tool in TOOLS}
        project = next(
            x for x in ui.call("permissions.get", {})["layers"] if x["layer"] == "project"
        )
        assert project["permissions"]["preset"] == "explorer"
    # 에이전트 자신도 같은 표를 본다 (무인 연결은 ask가 deny)
    with daemon.client(UNATTENDED) as agent_conn:
        shown = {t["tool"]: t["final"] for t in agent_conn.call("permissions.get", {})["tools"]}
        assert shown == {
            tool: "deny" if expected(tool) == "ask" else expected(tool) for tool in TOOLS
        }


@pytest.mark.parametrize("preset", ["explorer", "full"])
def test_human_only_screen_methods_agent_denied(tmp_path: Path, preset: str) -> None:
    assert set(HUMAN_ONLY) >= HUMAN_SCREEN_METHODS
    assert set(HUMAN_ONLY) <= AGENT_DENIED
    game = make_fake_game(tmp_path, permissions={"preset": preset}, screens=False)
    with game.daemon(env_of(game)) as d, d.client(ATTENDED) as agent, d.client() as ui:
        agent.call("explore.start", {"title": "자기 결과 승격 시도"})
        for method, params in HUMAN_ONLY.items():
            error = refused(agent, method, params)
            assert error.kind == "permission_denied", (method, error)
        # 사람은 판정 없이 지나간다 — 처리기는 B4·B5 (그 전에는 method_not_found)
        for method in sorted(HUMAN_SCREEN_METHODS):
            error = refused(ui, method, HUMAN_ONLY[method])
            assert error.code == -32601, (method, error)
        # 화면 지도 파일은 그대로 (승격·버리기 없음)
        assert not (game.root / "screens" / "title.screen.json").exists()
    # MCP 도구 어디에도 이 메서드를 부르는 길이 없다
    source = Path(mcp_tools.__file__).read_text(encoding="utf-8")
    for method in HUMAN_SCREEN_METHODS | {"explore.list", "approval.respond", "permissions.set"}:
        assert f'"{method}"' not in source, method


def test_unattended_explore_click_denied(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client() as ui, daemon.client(UNATTENDED) as agent:
        session = agent.call("explore.start", {"title": "무인 탐색"})["session"]  # 세션은 allow
        for method, params in (
            ("control.click", {"window": WINDOW, "point": list(START_BUTTON)}),
            ("control.key", {"window": WINDOW, "keys": "enter"}),
            ("control.type", {"window": WINDOW, "text": "abc"}),
        ):
            error = refused(agent, method, params)
            assert error.kind == "permission_denied", error
            assert error.data["decision"]["reason"] == "unattended_ask"
        # 사람에게 묻지 않았고(카드 없음) 게임에 입력이 가지 않았다
        assert ui.call("approval.list", {})["requests"] == []
        time.sleep(0.5)
        assert not [m for m in drain(ui) if m.get("method") == "approval.requested"]
        assert game.inputs() == []
        # 거부된 클릭은 스텝이 아니다 (예약 칸이 돌아왔다), 세션은 그대로
        assert session in daemon.daemon.explore.live_ids()
        listed = {s["id"]: s for s in ui.call("explore.list", {})["sessions"]}
        assert (listed[session]["status"], listed[session]["steps"]) == ("active", 0)


def drain(client: DaemonClient) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    while not client.notifications.empty():
        out.append(client.notifications.get_nowait())
    return out
