"""UX11 A — 화면 지도가 끊기지 않게: 실제 daemon(ThreadDaemon) + 가짜 예제 게임.

- A1 저절로 바뀌는 전환: 입력 없는 걸음에서 화면이 바뀌면 via `{"wait": {}}` 이동 (지도 이름표
  "저절로")
- A2 겹친 화면: 여럿 맞으면 팝업 → 조건 많은 것 → 지금 순서. 도착은 더 구체적인 화면
- A3 `screens.link`: 프레임 없이 이동만 잇기 (끝낸 직후 세션에도, 같은 이동은 합침)
- A4 `explore.end`의 `disconnected`: 처음 저장한 화면 말고 들어오는 이동이 없는 화면
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
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.screen_save import arrival, specificity

INVALID_PARAMS = -32602

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-ux11", "attended": False}
TITLE_RECT = [412, 380, 200, 64]
"""타이틀 시작 단추."""
LOGO_RECT = [330, 160, 365, 70]
"""타이틀 로고 글자."""
LOGIN_RECT = [400, 205, 320, 50]
LOADING_RECT = [310, 348, 404, 24]
"""불러오는 중 진행 막대."""
WORLD_RECT = [822, 18, 186, 186]
"""월드 작은 지도."""


@pytest.fixture
def game(tmp_path: Path) -> FakeGame:
    def slow_loading(table: dict[str, Any]) -> None:
        # 로딩 → 월드 자동 전이를 캡처 몇 장 늦춘다 (첫 걸음에서는 로딩이 보이게)
        for t in table["transitions"]:
            if t["from"] == "loading" and "on" not in t:
                t["after_frames"] = 6

    return make_fake_game(tmp_path, screens=False, scenario_patch=slow_loading)


@pytest.fixture
def daemon(game: FakeGame) -> Iterator[ThreadDaemon]:
    tmp = game.root.parent
    env = cli_env(tmp, None)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp / "user")
    with game.daemon(env) as d:
        yield d


def card(game: FakeGame, session: str, key: str) -> dict[str, Any]:
    path = game.root / "screens" / "_explored" / session / f"{key}.screen.json"
    return json.loads(path.read_text(encoding="utf-8"))


def to_scene(game: FakeGame, scene: str) -> None:
    state = game.state()
    state["scene"], state["pending"], state["shown"] = scene, [], 0
    game.state_file.write_text(json.dumps(state), encoding="utf-8")


def step(agent: DaemonClient, **params: Any) -> dict[str, Any]:
    return agent.call("explore.step", {"window": "@game", **params}, timeout=120)


def save(
    agent: DaemonClient, frame: dict[str, Any], key: str, *rects: list[int], **extra: Any
) -> None:
    detect = {"all": [{"image": r} for r in rects]}
    agent.call(
        "screens.save",
        {"key": key, "frame_id": frame["frame_id"], "title": key, "detect": detect, **extra},
        timeout=120,
    )


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=120)
    return caught.value


# ---------------------------------------------------------------- A2 (순수 함수)


def m(key: str, kind: str = "screen", conditions: int = 1) -> dict[str, Any]:
    return {"node": key, "state": "explored", "key": key, "title": key, "kind": kind,
            "conditions": conditions}  # fmt: skip


def test_specificity_popup_then_conditions_then_order() -> None:
    found = [m("title"), m("logged", conditions=2), m("popup", "popup"), m("title2")]
    assert [x["key"] for x in sorted(found, key=specificity)] == [
        "popup", "logged", "title", "title2",
    ]  # fmt: skip


def test_arrival_prefers_other_screen_when_tied_with_origin() -> None:
    # 출발 화면과 같은 정도로 구체적인 다른 화면도 맞으면 그 화면
    assert arrival([m("title"), m("other")], ("explored", "title"))["key"] == "other"  # type: ignore[index]
    # 더 구체적인 화면이 맞으면 출발 화면이 앞이어도 그쪽
    assert arrival([m("title"), m("popup", "popup")], ("explored", "title"))["key"] == "popup"  # type: ignore[index]
    # 출발 화면이 가장 구체적이고 덜 구체적인 화면만 함께 맞으면 그대로
    assert arrival([m("popup", "popup"), m("title")], ("explored", "popup"))["key"] == "popup"  # type: ignore[index]
    assert arrival([], ("explored", "title")) is None


# ---------------------------------------------------------------- daemon


def test_overlapping_screens_arrive_at_more_specific(game: FakeGame, daemon: ThreadDaemon) -> None:
    """반투명 팝업(뒤 타이틀 글자가 보임)·로그인된 타이틀: 더 구체적인 화면에 도착 (A2)."""
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "겹침", "window": WINDOW})["session"]
        first = step(agent)["frame"]
        save(agent, first, "title", TITLE_RECT)
        save(agent, first, "logged", TITLE_RECT, LOGO_RECT)  # 조건 하나 더 (로그인된 타이틀)
        save(agent, first, "popup", LOGO_RECT, kind="popup")
        login = step(agent, point=list(START_BUTTON))
        assert login["new_screen"] is True and game.state()["scene"] == "login"
        save(agent, login["frame"], "login", LOGIN_RECT)
        to_scene(game, "title")
        back = step(agent, keys="esc", wait_ms=500)
        keys = [x["key"] for x in back["identify"]["matches"]]
        assert keys == ["popup", "logged", "title"]
        assert back["identify"]["matches"][0]["kind"] == "popup"
        assert back["move"]["from"] == "login" and back["move"]["to"] == "popup"
        assert card(game, session, "login")["moves"] == [
            {"via": {"key": "esc"}, "to": "popup", "status": "tried"}
        ]
        agent.call("explore.end", {})


def test_wait_move_link_and_disconnected(game: FakeGame, daemon: ThreadDaemon) -> None:
    """로딩 → 월드(입력 없이 기다리는 동안)도, 걸음 사이에 이미 바뀐 타이틀 → 로딩도 wait 이동이다
    (A1, 검수 1 Mid 3). 끊김 없음 (A4), 같은 이동을 다시 이으면 합친다 (A3)."""
    with daemon.client(AGENT) as agent, daemon.client() as ui:
        session = agent.call("explore.start", {"title": "저절로", "window": WINDOW})["session"]
        save(agent, step(agent)["frame"], "title", TITLE_RECT)
        # 걸음 사이에 화면이 바뀌었다 (기다림 동안은 그대로): 직전 걸음 프레임과 달라 대기 이동
        to_scene(game, "loading")
        loading = step(agent)
        assert loading["new_screen"] is True and loading["changed"] is False
        assert loading["move"] == {"from": "title", "to": None, "status": "pending"}
        save(agent, loading["frame"], "loading", LOADING_RECT)
        assert card(game, session, "title")["moves"] == [
            {"via": {"wait": {}}, "to": "loading", "status": "tried"}
        ]
        # 입력 없이 기다리는 동안 월드로 바뀐다: 처음 보는 화면이면 대기 이동
        world = step(agent, wait_ms=8000)
        assert world["changed"] is True and world["input"] is None
        assert world["move"] == {"from": "loading", "to": None, "status": "pending"}
        assert game.state()["scene"] == "world"
        save(agent, world["frame"], "world", WORLD_RECT)
        assert card(game, session, "loading")["moves"] == [
            {"via": {"wait": {}}, "to": "world", "status": "tried"}
        ]
        # 지도: 저절로 이동은 via wait, 이름표 "저절로"
        edges = ui.call("screens.map", {})["edges"]
        auto = [e for e in edges if e["via"] == {"wait": {}}]
        assert sorted((e["from"], e["to"], e["label"]) for e in auto) == [
            (f"x:{session}/loading", f"x:{session}/world", "저절로"),
            (f"x:{session}/title", f"x:{session}/loading", "저절로"),
        ]
        # 끝: 모두 이어져 끊김 없음
        assert agent.call("explore.end", {})["disconnected"] == []
        # 끝낸 직후에도 이 연결의 세션에 잇는다 — 같은 이동은 합친다
        again = agent.call(
            "screens.link", {"from": "title", "to": "loading", "via": {"wait": {}}}, timeout=120
        )
        assert again == {"card": "title", "from": "title", "to": "loading", "disconnected": []}
        assert card(game, session, "title")["moves"] == [
            {"via": {"wait": {}}, "to": "loading", "status": "tried"}
        ]


def test_link_refusals_and_point(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent, daemon.client() as ui:
        early = refused(agent, "screens.link", {"from": "a", "to": "b", "via": {"wait": {}}})
        assert early.kind == "explore_not_active"
        session = agent.call("explore.start", {"title": "잇기", "window": WINDOW})["session"]
        first = step(agent)["frame"]
        save(agent, first, "title", TITLE_RECT)
        save(agent, first, "other", LOGO_RECT)
        bad = refused(agent, "screens.link", {"from": "nope", "to": "title", "via": {"wait": {}}})
        assert bad.code == INVALID_PARAMS and "kb_screen_save" in bad.message
        same = refused(agent, "screens.link", {"from": "title", "to": "title", "via": {"wait": {}}})
        assert same.code == INVALID_PARAMS
        far = {"click": {"point": [1.5, 0.2]}}
        with pytest.raises(ValueError):  # 비율 밖 점은 스키마가 먼저 거부한다
            agent.call("screens.link", {"from": "title", "to": "other", "via": far}, timeout=120)
        element = {"click": {"element": "없는 단추"}}
        missing = refused(agent, "screens.link", {"from": "title", "to": "other", "via": element})
        assert missing.kind == "validation_failed"
        # 사람 연결은 쓰지 않는다
        human = refused(ui, "screens.link", {"from": "title", "to": "other", "via": {"key": "esc"}})
        assert human.kind in ("agent_only", "ui_only", "method_not_allowed") or human.code < 0
        # 끝: 처음 저장한 title 말고 들어오는 이동이 없는 other가 끊김 (A4)
        ended = agent.call("explore.end", {})
        assert ended["disconnected"] == [{"key": "other", "title": "other"}]
        # 끝낸 직후에도 프레임 없이 잇는다 (A3)
        linked = agent.call(
            "screens.link",
            {"from": "title", "to": "other", "via": {"click": {"point": [0.5, 0.65]}}},
            timeout=120,
        )
        assert linked == {"card": "title", "from": "title", "to": "other", "disconnected": []}
        assert card(game, session, "title")["moves"] == [
            {"via": {"click": {"point": [0.5, 0.65]}}, "to": "other", "status": "tried"}
        ]


# ---------------------------------------------------------------- 검수 1 재현 (Mid 2·3)


@pytest.fixture
def overlay(tmp_path: Path) -> FakeGame:
    """로그인 장면 = 타이틀 위 로그인 팝업 (타이틀 시작 단추가 그대로 보인다)."""
    import cv2

    game = make_fake_game(tmp_path, screens=False, draw=False)
    title = cv2.imread(str(game.frames / "title.png"))
    login = cv2.imread(str(game.frames / "login.png"))
    assert title is not None and login is not None
    title[205:255, 400:720] = login[205:255, 400:720]
    assert cv2.imwrite(str(game.frames / "login.png"), title)
    return game


@pytest.fixture
def overlay_daemon(overlay: FakeGame) -> Iterator[ThreadDaemon]:
    tmp = overlay.root.parent
    env = cli_env(tmp, None)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp / "user")
    with overlay.daemon(env) as d:
        yield d


def test_known_overlap_between_steps_records_wait(
    overlay: FakeGame, overlay_daemon: ThreadDaemon
) -> None:
    """걸음 사이에 뜬 더 구체적인 팝업(배경 타이틀 단추도 보임): 무변화여도 팝업 도착 + wait."""
    with overlay_daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "겹침", "window": WINDOW})["session"]
        save(agent, step(agent)["frame"], "title", TITLE_RECT)
        to_scene(overlay, "login")
        save(agent, step(agent)["frame"], "popup", LOGIN_RECT, kind="popup")
        to_scene(overlay, "title")
        back = step(agent, keys="esc", wait_ms=0)
        assert back["identify"]["matches"][0]["key"] == "title"
        to_scene(overlay, "login")  # 다음 걸음 전에 팝업이 이미 떴다
        result = step(agent)
        assert [m["key"] for m in result["identify"]["matches"]] == ["popup", "title"]
        assert result["changed"] is False
        assert result["move"] == {
            "from": "title",
            "to": "popup",
            "status": "recorded",
            "card": "title",
        }
        moves = card(overlay, session, "title")["moves"]
        assert {"via": {"wait": {}}, "to": "popup", "status": "tried"} in moves
        # 같은 화면에서 입력도 변화도 없는 걸음은 그대로 (팝업에 머문다 — 오가지 않는다)
        assert step(agent)["move"] is None
        agent.call("explore.end", {})


def test_unknown_transition_between_steps_records_pending(
    overlay: FakeGame, overlay_daemon: ThreadDaemon
) -> None:
    with overlay_daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "사이", "window": WINDOW})
        save(agent, step(agent)["frame"], "title", TITLE_RECT)
        # 조건 없는 카드가 늘 새 화면으로 보이는 잡음: 화면이 그대로면 대기 이동을 만들지 않는다
        bare = step(agent)["frame"]
        agent.call(
            "screens.save",
            {"key": "bare", "frame_id": bare["frame_id"], "title": "bare"},
            timeout=120,
        )
        assert step(agent)["move"] is None
        to_scene(overlay, "world")  # 다음 걸음 전에 새 화면으로 바뀌었다
        result = step(agent)
        assert result["new_screen"] is True
        assert result["move"] == {"from": "title", "to": None, "status": "pending"}
        agent.call("explore.end", {})
