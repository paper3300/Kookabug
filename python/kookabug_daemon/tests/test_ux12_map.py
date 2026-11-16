"""UX12 1 — 화면 지도 실측 후속: 실제 daemon(ThreadDaemon) + 가짜 예제 게임.

- 1a 잘못 남은 이동: 팝업 카드를 저장하기 전에 배경 카드를 다시 저장해 팝업 위의 입력이 배경 카드
  이동으로 남으면, 뒤에 팝업을 저장할 때(그 입력 직전 프레임에서 팝업 판정 조건이 맞음) 그 이동을
  팝업 카드로 옮긴다
- 1b 세션 사이 중복 카드: 승격 확인(`screens.check`)이 끝난 다른 세션의 같은 화면일 수 있는 후보를
  `same`으로 안내만 한다 (합치기는 사람이 지도의 기존 합치기로 — 검수 2 결정)
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
from kookabug_daemon.client import DaemonClient

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-ux12", "attended": False}
AGENT2 = {**AGENT, "id": "agent-ux12-b"}
TITLE_RECT = [412, 380, 200, 64]
"""타이틀 시작 단추."""
LOGIN_RECT = [400, 205, 320, 50]
LOGIN_BUTTON = (512, 408)
ERROR_HEAD = [262, 170, 500, 55]
"""로그인 실패 팝업 머리 ("로그인 실패")."""


@pytest.fixture
def game(tmp_path: Path) -> FakeGame:
    return make_fake_game(tmp_path, screens=False)


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


def step(agent: DaemonClient, **params: Any) -> dict[str, Any]:
    return agent.call("explore.step", {"window": "@game", **params}, timeout=120)


def save(
    agent: DaemonClient, frame: dict[str, Any], key: str, *rects: list[int], **extra: Any
) -> dict[str, Any]:
    params: dict[str, Any] = {"key": key, "frame_id": frame["frame_id"], "title": key, **extra}
    if rects:
        params["detect"] = {"all": [{"image": r} for r in rects]}
    return agent.call("screens.save", params, timeout=120)


def to_scene(game: FakeGame, scene: str) -> None:
    state = game.state()
    state["scene"], state["pending"], state["shown"] = scene, [], 0
    game.state_file.write_text(json.dumps(state), encoding="utf-8")


# ---------------------------------------------------------------- 1a


def test_popup_saved_later_takes_misplaced_move(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "팝업", "window": WINDOW})["session"]
        save(agent, step(agent)["frame"], "title", TITLE_RECT)
        login = step(agent, point=list(START_BUTTON))
        save(agent, login["frame"], "login", LOGIN_RECT)
        # 빈 칸으로 로그인 → 로그인 실패 팝업 (처음 보는 화면 — 대기 이동)
        popup = step(agent, point=list(LOGIN_BUTTON))
        assert popup["new_screen"] is True and game.state()["scene"] == "login_error"
        # 팝업을 저장하기 전에 배경 카드(타이틀)를 다시 저장 → 지금 화면이 타이틀로 잡힌다
        save(agent, popup["frame"], "title", description="다시 저장")
        # 팝업 위의 [확인](enter) → 로그인: 출발이 타이틀로 잘못 남는다
        back = step(agent, keys="enter")
        assert back["move"]["from"] == "title" and back["move"]["to"] == "login"
        assert {"via": {"key": "enter"}, "to": "login", "status": "tried"} in card(
            game, session, "title"
        )["moves"]
        # 팝업을 저장한다 (팝업 프레임) → 그 입력 직전 프레임에서 맞으니 이동을 팝업 카드로 옮긴다
        saved = save(agent, popup["frame"], "login_error", ERROR_HEAD, kind="popup")
        assert saved["relocated"] == [
            {"from": "title", "to": "login", "now_from": "login_error", "removed": True}
        ]
        # 타이틀에는 실제 시작 단추 클릭(→ 로그인)만 남는다
        title_moves = card(game, session, "title").get("moves") or []
        assert [(list(m["via"]), m["to"]) for m in title_moves] == [(["click"], "login")]
        popup_moves = card(game, session, "login_error")["moves"]
        assert {"via": {"key": "enter"}, "to": "login", "status": "tried"} in popup_moves
        agent.call("explore.end", {})


def test_less_specific_card_does_not_take_moves(game: FakeGame, daemon: ThreadDaemon) -> None:
    """덜 구체적인(팝업 아님·조건 수 같음) 카드를 뒤에 저장해도 옮기지 않는다."""
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "그대로", "window": WINDOW})["session"]
        first = step(agent)["frame"]
        save(agent, first, "title", TITLE_RECT)
        login = step(agent, point=list(START_BUTTON))
        save(agent, login["frame"], "login", LOGIN_RECT)
        assert card(game, session, "title")["moves"][0]["to"] == "login"
        # 같은 타이틀 프레임에서 조건 하나짜리 다른 카드 — 출발보다 구체적이지 않다
        saved = save(agent, first, "title_again", TITLE_RECT)
        assert "relocated" not in saved
        assert card(game, session, "title")["moves"][0]["to"] == "login"
        agent.call("explore.end", {})


# ---------------------------------------------------------------- 1b


def test_promote_merges_same_screen_from_other_session(
    game: FakeGame, daemon: ThreadDaemon
) -> None:
    sessions: list[str] = []
    for agent_info in (AGENT, AGENT2):
        if sessions:
            to_scene(game, "title")
        with daemon.client(agent_info) as agent:
            session = agent.call("explore.start", {"title": "세션", "window": WINDOW})["session"]
            sessions.append(session)
            save(agent, step(agent)["frame"], "title", TITLE_RECT)
            login = step(agent, point=list(START_BUTTON))
            save(agent, login["frame"], "login", LOGIN_RECT)
            agent.call("explore.end", {})
    first, second = sessions
    with daemon.client() as ui:
        request = {"session": first, "key": "title", "mode": "new"}
        checked = ui.call("screens.check", request, timeout=120)
        assert checked["ok"] is True
        # 다른 세션의 같은 화면만 안내 (같은 세션 자신·로그인 카드는 아님)
        assert checked["same"] == [{"session": second, "key": "title", "title": "title"}]
        done = ui.call(
            "screens.promote", {**request, "base_revisions": checked["revisions"]}, timeout=120
        )
        # 안내만 한다 — 승격은 그 후보 하나, 둘째 세션 후보는 그대로 (합치기는 사람이 지도에서)
        assert "merged" not in done
        explored = game.root / "screens" / "_explored"
        assert (explored / second / "title.screen.json").is_file()
        merge = {"session": second, "key": "title", "mode": "merge", "id": "title"}
        again = ui.call("screens.check", merge, timeout=120)
        assert again["ok"] is True  # 기존 합치기로 합칠 수 있다


def test_same_hint_needs_other_session(game: FakeGame, daemon: ThreadDaemon) -> None:
    """같은 세션 다른 카드·다른 세션이 없으면 안내 없음."""
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "하나", "window": WINDOW})["session"]
        save(agent, step(agent)["frame"], "title", TITLE_RECT)
        login = step(agent, point=list(START_BUTTON))
        save(agent, login["frame"], "login", LOGIN_RECT)
        agent.call("explore.end", {})
    with daemon.client() as ui:
        checked = ui.call(
            "screens.check", {"session": session, "key": "title", "mode": "new"}, timeout=120
        )
        assert checked["ok"] is True and "same" not in checked


# ---------------------------------------------------------------- 수정 라운드 2 (검수 1)

OK_BUTTON = [442, 392, 140, 52]
"""로그인 실패·점검 안내 팝업에 함께 있는 [확인] 단추 (같은 틀의 다른 팝업)."""


def test_distinct_popups_are_not_same(game: FakeGame, daemon: ThreadDaemon) -> None:
    """검수 1 High 1: 공통 [확인] 단추만으로 서로를 찾는 다른 팝업은 같은 화면 안내에 안 나온다."""
    sessions: list[str] = []
    for info, scene in [(AGENT, "login_error"), (AGENT2, "maintenance")]:
        with daemon.client(info) as agent:
            started = agent.call("explore.start", {"title": "팝업", "window": WINDOW})
            sessions.append(started["session"])
            step(agent)
            to_scene(game, scene)
            save(agent, step(agent)["frame"], scene, OK_BUTTON, kind="popup")
            agent.call("explore.end", {})
    first, _ = sessions
    with daemon.client() as ui:
        checked = ui.call(
            "screens.check", {"session": first, "key": "login_error", "mode": "new"}, timeout=120
        )
        assert checked["ok"] is True and "same" not in checked


ENTER = {"via": {"key": "enter"}, "to": "login", "status": "tried"}


def _fail_first_removal(monkeypatch: pytest.MonkeyPatch) -> None:
    """출발 카드에서 빼기를 한 번 실패시킨다 (두 카드 변경의 부분 실패)."""
    from kookabug_daemon import screen_save

    real = screen_save._take_move  # pyright: ignore[reportPrivateUsage]
    fails = [1]

    def flaky(*args: Any, remove: bool, **kw: Any) -> str:
        if remove and fails:
            fails.pop()
            return "failed"
        return real(*args, remove=remove, **kw)

    monkeypatch.setattr(screen_save, "_take_move", flaky)


def _half_relocated(game: FakeGame, agent: DaemonClient) -> tuple[str, dict[str, Any]]:
    """팝업 위 enter가 타이틀 이동으로 남은 뒤 팝업을 저장 — 팝업 카드엔 더했고 타이틀에서 빼기는
    실패한 상태. (세션, 타이틀 프레임)."""
    session = agent.call("explore.start", {"title": "재시도", "window": WINDOW})["session"]
    title = step(agent)["frame"]
    save(agent, title, "title", TITLE_RECT)
    save(agent, step(agent, point=list(START_BUTTON))["frame"], "login", LOGIN_RECT)
    popup = step(agent, point=list(LOGIN_BUTTON))
    save(agent, popup["frame"], "title", description="다시 저장")
    step(agent, keys="enter")
    first = save(agent, popup["frame"], "login_error", ERROR_HEAD, kind="popup")
    assert "relocated" not in first
    assert ENTER in card(game, session, "login_error")["moves"]
    assert ENTER in card(game, session, "title")["moves"]  # 빼기만 실패
    return session, title


def test_relocate_retry_keeps_origin_when_target_discarded(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """검수 2 High 2: 옮겨 간 카드가 버려진 뒤 다시 하면 출발 이동을 남기고 `target_gone`."""
    _fail_first_removal(monkeypatch)
    with daemon.client(AGENT) as agent, daemon.client() as ui:
        session, title = _half_relocated(game, agent)
        ui.call("screens.discard", {"session": session, "key": "login_error"})
        result = save(agent, title, "title", description="다른 카드 저장")
        assert "relocated" not in result
        assert result["relocate_kept"] == [
            {"from": "title", "to": "login", "reason": "target_gone"}
        ]
        assert ENTER in card(game, session, "title")["moves"]
        # 기록은 지웠다 — 다음 저장에서 다시 하지 않는다
        assert "relocate_kept" not in save(agent, title, "title", description="또")
        agent.call("explore.end", {})


def test_relocate_retry_checks_promoted_target(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """옮겨 간 후보가 그 사이 승격됐으면 승격된 확정 화면에서 그 이동을 확인하고 뺀다."""
    _fail_first_removal(monkeypatch)
    with daemon.client(AGENT) as agent, daemon.client() as ui:
        session, title = _half_relocated(game, agent)
        request = {"session": session, "key": "login_error", "mode": "new", "id": "login_fail"}
        checked = ui.call("screens.check", request, timeout=120)
        ui.call("screens.promote", {**request, "base_revisions": checked["revisions"]}, timeout=120)
        result = save(agent, title, "title", description="다른 카드 저장")
        assert result["relocated"] == [
            {"from": "title", "to": "login", "now_from": "login_error", "removed": True}
        ]
        assert ENTER not in card(game, session, "title").get("moves", [])
        agent.call("explore.end", {})


def test_relocate_retries_failed_removal(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """검수 1 High 3: 새 카드에 더한 뒤 배경 카드에서 빼기가 실패하면 기록을 남겨 다음 저장 때
    빼기만 다시 한다 (두 카드 변경의 부분 실패가 재시도 가능)."""
    _fail_first_removal(monkeypatch)
    with daemon.client(AGENT) as agent:
        session, _ = _half_relocated(game, agent)
        enter = ENTER
        popup_frame = step(agent)["frame"]
        assert popup_frame["frame_id"]
        again = save(agent, popup_frame, "login_error", description="다시 저장")
        assert again["relocated"] == [
            {"from": "title", "to": "login", "now_from": "login_error", "removed": True}
        ]
        assert enter not in card(game, session, "title").get("moves", [])
        assert card(game, session, "login_error")["moves"].count(enter) == 1
        agent.call("explore.end", {})


def test_manual_edit_after_record_is_preserved(game: FakeGame, daemon: ThreadDaemon) -> None:
    """High 3: 자동 기록 뒤 사람이 고친 이동은 옮기지 않고 남기며 결과에 알린다."""
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "고침", "window": WINDOW})["session"]
        save(agent, step(agent)["frame"], "title", TITLE_RECT)
        save(agent, step(agent, point=list(START_BUTTON))["frame"], "login", LOGIN_RECT)
        popup = step(agent, point=list(LOGIN_BUTTON))
        save(agent, popup["frame"], "title", description="다시 저장")
        step(agent, keys="enter")
        path = game.root / "screens" / "_explored" / session / "title.screen.json"
        doc = json.loads(path.read_text("utf-8"))
        edited = next(m for m in doc["moves"] if m["via"] == {"key": "enter"})
        edited["note"] = "사람이 확인하고 고친 이동"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        saved = save(agent, popup["frame"], "login_error", ERROR_HEAD, kind="popup")
        assert "relocated" not in saved
        assert saved["relocate_kept"] == [{"from": "title", "to": "login", "reason": "changed"}]
        assert edited in card(game, session, "title")["moves"]
        assert all(
            m["via"] != {"key": "enter"}
            for m in card(game, session, "login_error").get("moves", [])
        )
        agent.call("explore.end", {})
