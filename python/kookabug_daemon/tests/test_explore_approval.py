"""이 탐색 동안 허용 (`allow_session`, M7 계획 3.11 U2·B3) — 엄격: Agent 권한.

- 범위 = (연결, 세션, 도구, 권한 인자 — control은 창 제목, screens는 도구 전체). 같은 범위의
  다음 ask는 묻지 않는다. 다른 창·다른 도구는 다시 묻는다
- 메모리에만: 규칙 파일에 쓰지 않고, 세션 끝·연결 끊김·예산 다 씀·daemon 재시작에 사라진다
- deny 규칙이 먼저다 (범위는 ask만 건너뛴다)
- 세션이 없는 요청에는 쓸 수 없다(`session_not_allowed`), 게임 조작은 여전히 "항상 허용" 없음
- 승인 대기 중 세션이 끝나면(끝·끊김) 요청은 `cancelled`, 늦은 답은 아무것도 허락하지 않는다
- 예산은 판정 전에 예약한다: 승인 대기 중인 요청이 칸을 쥐어 다른 요청이 예산을 넘지 못한다

가짜 예제 게임 + 실제 runner 제어 실행. 프리셋 `explorer`(control ask, 화면 지도 쓰기 allow).
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Iterator
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env

from kb_testing.daemon import ThreadDaemon
from kb_testing.fake_game import WINDOW, FakeGame, make_fake_game
from kb_testing.proc import wait_until
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

SECRET = "PWQ4417ZX"
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-s", "attended": True}
KEY = {"window": WINDOW, "keys": "a"}


def env_of(game: FakeGame) -> dict[str, str]:
    tmp = game.root.parent
    env = cli_env(tmp, None, KOOKABUG_SECRET_ACC_PW=SECRET)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp / "user")
    return env


@pytest.fixture
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeGame:
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", SECRET)
    return make_fake_game(tmp_path, permissions={"preset": "explorer"}, screens=False)


@pytest.fixture
def daemon(game: FakeGame) -> Iterator[ThreadDaemon]:
    with game.daemon(env_of(game)) as d:
        yield d


def approval_request(client: DaemonClient, timeout: float = 15) -> dict[str, Any]:
    """ui 연결의 다음 `approval.requested` params (다른 알림은 버린다)."""
    return _next(client, "approval.requested", timeout)


def resolved(client: DaemonClient, timeout: float = 15) -> dict[str, Any]:
    return _next(client, "approval.resolved", timeout)


def _next(client: DaemonClient, method: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while (left := deadline - time.monotonic()) > 0:
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            break
        if message.get("method") == method:
            return message["params"]
    raise AssertionError(f"{timeout}초 안에 {method}이(가) 오지 않았다")


def no_request(client: DaemonClient, timeout: float = 2) -> None:
    with pytest.raises(AssertionError):
        approval_request(client, timeout)


def error_of(future: Future[Any], timeout: float = 120) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        future.result(timeout)
    return caught.value


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=120)
    return caught.value


def record(game: FakeGame, session: str) -> dict[str, Any]:
    path = game.root / "screens" / "_explored" / session / "explore.json"
    return json.loads(path.read_text(encoding="utf-8"))


def grant(ui: DaemonClient, agent: DaemonClient, params: dict[str, Any] = KEY) -> dict[str, Any]:
    """control.key를 요청하고 카드에서 "이 탐색 동안 허용"을 누른다. 그 요청의 결과."""
    future = agent.request("control.key", params)
    ask = approval_request(ui)
    ui.call("approval.respond", {"id": ask["id"], "verdict": "allow_session"})
    return future.result(120)


def test_allow_session_covers_same_window_only(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "범위"})["session"]
        future = agent.request("control.key", KEY)
        ask = approval_request(ui)
        # 카드: 지금 세션이 있으니 "이 탐색 동안 허용" 단추, 게임 조작이라 "항상 허용"은 없다
        assert ask["session"] == {"id": session, "title": "범위"}
        assert ask["always_rule"] is None and ask["arg"] == WINDOW
        ui.call("approval.respond", {"id": ask["id"], "verdict": "allow_session"})
        assert future.result(120)["verdict"] == "pass"
        assert resolved(ui)["verdict"] == "allow_session"
        # 같은 창·같은 도구: 묻지 않고 실행
        before = len(game.inputs())
        assert agent.call("control.key", KEY, timeout=120)["verdict"] == "pass"
        no_request(ui)
        assert len(game.inputs()) > before
        # 다른 창: 다시 묻는다 (거부하면 입력 없음)
        before = len(game.inputs())
        other = agent.request("control.key", {"window": "Other", "keys": "a"})
        ask = approval_request(ui)
        assert ask["arg"] == "Other"
        ui.call("approval.respond", {"id": ask["id"], "verdict": "deny"})
        assert error_of(other).kind == "approval_denied"
        # 같은 창의 다른 도구(클릭)도 다시 묻는다
        click = agent.request("control.click", {"window": WINDOW, "point": [1, 1]})
        ask = approval_request(ui)
        assert ask["tool"] == "kb_input_click"
        ui.call("approval.respond", {"id": ask["id"], "verdict": "deny"})
        assert error_of(click).kind == "approval_denied"
        assert len(game.inputs()) == before
        body = record(game, session)
        assert body["steps"] == 2
        (audit,) = body["approvals"]
        assert (audit["tool"], audit["arg"], audit["scope"]) == ("kb_input_key", WINDOW, "session")
        assert scopes(daemon) == {(audit_conn(daemon), session, "kb_input_key", WINDOW)}


def scopes(daemon: ThreadDaemon) -> set[tuple[int, str, str, str]]:
    return set(daemon.daemon.approvals.scopes())


def audit_conn(daemon: ThreadDaemon) -> int:
    (scope,) = scopes(daemon)
    return scope[0]


def test_allow_session_ends_with_session(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client() as ui:
        # 1) kb_explore_end: 범위가 사라지고 새 세션은 다시 묻는다
        with daemon.client(AGENT) as agent:
            agent.call("explore.start", {"title": "첫 세션"})
            assert grant(ui, agent)["verdict"] == "pass"
            assert scopes(daemon)
            agent.call("explore.end", {})
            wait_until(lambda: not scopes(daemon), timeout=10)
            agent.call("explore.start", {"title": "둘째 세션"})
            future = agent.request("control.key", KEY)
            ask = approval_request(ui)
            ui.call("approval.respond", {"id": ask["id"], "verdict": "allow_session"})
            assert future.result(120)["verdict"] == "pass"
            assert len(scopes(daemon)) == 1
        # 2) 연결 끊김: 범위가 사라진다 (새 연결의 세션은 다시 묻는다)
        wait_until(lambda: not scopes(daemon), timeout=30)
        with daemon.client(AGENT) as agent:
            # 3) 예산 다 씀: 마지막 스텝이 들어가면 범위가 사라진다 (세션은 그대로)
            session = agent.call("explore.start", {"title": "예산", "max_steps": 2})["session"]
            assert grant(ui, agent)["verdict"] == "pass"
            assert agent.call("control.key", KEY, timeout=120)["verdict"] == "pass"
            no_request(ui)
            wait_until(lambda: not scopes(daemon), timeout=10)
            assert refused(agent, "control.key", KEY).kind == "explore_budget_exhausted"
            assert record(game, session)["status"] == "active"


def test_allow_session_not_persisted(game: FakeGame) -> None:
    local = game.root / ".kookabug" / "local.json"
    before = local.read_bytes()
    user = game.root.parent / "user"
    with game.daemon(env_of(game)) as d, d.client() as ui, d.client(AGENT) as agent:
        agent.call("explore.start", {"title": "메모리만"})
        assert grant(ui, agent)["verdict"] == "pass"
        assert scopes(d)
    # 규칙 파일·사용자 설정에 아무것도 쓰지 않았다
    assert local.read_bytes() == before
    assert not (user / "settings.json").exists()
    # .kookabug/ 아래 설정·상태 JSON 어디에도 범위가 없다 (잠금 파일은 끊긴 연결의 세션 끝이
    # 쥘 수 있어 뺀다)
    leftovers = [
        p
        for p in (game.root / ".kookabug").rglob("*.json")
        if "allow_session" in p.read_text("utf-8", errors="replace")
    ]
    assert leftovers == []
    # daemon 재시작: 범위가 없다 (같은 에이전트의 새 세션은 다시 묻는다)
    with game.daemon(env_of(game)) as d, d.client() as ui, d.client(AGENT) as agent:
        assert not scopes(d)
        agent.call("explore.start", {"title": "재시작 뒤"})
        future = agent.request("control.key", KEY)
        ask = approval_request(ui)
        ui.call("approval.respond", {"id": ask["id"], "verdict": "deny"})
        assert error_of(future).kind == "approval_denied"


def test_deny_rule_beats_session_allow(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "거부 규칙"})
        assert grant(ui, agent)["verdict"] == "pass"
        # 사람이 그 창 입력을 deny 규칙으로 막는다 → 범위가 있어도 거부 (묻지도 않음)
        layers = ui.call("permissions.get", {})["layers"]
        project = next(layer for layer in layers if layer["layer"] == "project")
        ui.call(
            "permissions.set",
            {
                "layer": "project",
                "permissions": {
                    "preset": "explorer",
                    "rules": [{"rule": f"kb_input_key({WINDOW})", "verdict": "deny"}],
                },
                "base_revision": project["revision"],
            },
        )
        before = len(game.inputs())
        error = refused(agent, "control.key", KEY)
        assert error.kind == "permission_denied"
        no_request(ui)
        assert len(game.inputs()) == before
        assert scopes(daemon)  # 범위는 남아도 deny가 먼저다


def test_allow_session_rejected_without_session(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        future = agent.request("control.key", KEY)
        ask = approval_request(ui)
        assert ask["session"] is None  # 세션이 없으면 단추가 없다
        error = refused(ui, "approval.respond", {"id": ask["id"], "verdict": "allow_session"})
        assert error.kind == "session_not_allowed"
        # 요청은 그대로 기다린다 — 사람이 다시 답한다
        assert [r["id"] for r in ui.call("approval.list", {})["requests"]] == [ask["id"]]
        ui.call("approval.respond", {"id": ask["id"], "verdict": "deny"})
        assert error_of(future).kind == "approval_denied"
        assert not scopes(daemon)
        assert game.inputs() == []


def test_late_answer_after_session_end_grants_nothing(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client() as ui:
        # 1) 대기 중 kb_explore_end
        with daemon.client(AGENT) as agent:
            session = agent.call("explore.start", {"title": "늦은 답"})["session"]
            future = agent.request("control.key", KEY)
            ask = approval_request(ui)
            agent.call("explore.end", {})
            done = resolved(ui)
            assert (done["id"], done["verdict"]) == (ask["id"], "cancelled")
            assert error_of(future).kind == "approval_cancelled"
            for verdict in ("allow_session", "allow_once"):
                error = refused(ui, "approval.respond", {"id": ask["id"], "verdict": verdict})
                assert error.kind == "not_found"
            assert not scopes(daemon)
            body = record(game, session)
            assert (body["status"], body["steps"], body["approvals"]) == ("ended", 0, [])
        # 2) 대기 중 연결 끊김
        with daemon.client(AGENT) as agent:
            session = agent.call("explore.start", {"title": "끊김"})["session"]
            agent.request("control.key", KEY)
            ask = approval_request(ui)
        done = resolved(ui, timeout=30)
        assert (done["id"], done["verdict"]) == (ask["id"], "cancelled")
        error = refused(ui, "approval.respond", {"id": ask["id"], "verdict": "allow_session"})
        assert error.kind == "not_found"
        wait_until(lambda: record(game, session)["status"] == "ended", timeout=30)
        assert not scopes(daemon)
        assert record(game, session)["approvals"] == []
    assert game.inputs() == []


def test_control_still_no_allow_always(game: FakeGame, daemon: ThreadDaemon) -> None:
    local = game.root / ".kookabug" / "local.json"
    before = local.read_bytes()
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "항상 허용 없음"})
        future = agent.request("control.key", KEY)
        ask = approval_request(ui)
        assert ask["always_rule"] is None
        error = refused(ui, "approval.respond", {"id": ask["id"], "verdict": "allow_always"})
        assert error.kind == "always_not_allowed"
        assert local.read_bytes() == before
        ui.call("approval.respond", {"id": ask["id"], "verdict": "allow_session"})
        assert future.result(120)["verdict"] == "pass"
    assert local.read_bytes() == before


def test_budget_reserved_while_waiting(game: FakeGame, daemon: ThreadDaemon) -> None:
    """B2b 검수 Mid 2: 승인을 기다리는 요청이 예산 칸을 쥔다 — 둘째 요청은 묻기 전에 거부, 첫 요청이
    거부되면 칸이 돌아온다."""
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "예약", "max_steps": 1})["session"]
        first = agent.request("control.key", KEY)
        ask = approval_request(ui)
        assert refused(agent, "control.key", KEY).kind == "explore_budget_exhausted"
        no_request(ui)
        ui.call("approval.respond", {"id": ask["id"], "verdict": "deny"})
        assert error_of(first).kind == "approval_denied"
        # 거부로 칸이 돌아왔다: 다시 물을 수 있다
        second = agent.request("control.key", KEY)
        ask = approval_request(ui)
        ui.call("approval.respond", {"id": ask["id"], "verdict": "allow_once"})
        assert second.result(120)["verdict"] == "pass"
        assert record(game, session)["steps"] == 1
        assert refused(agent, "control.key", KEY).kind == "explore_budget_exhausted"


def test_session_end_before_start_sends_nothing(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B3 검수 Mid 1: 범위·`allow_session`으로 승인된 입력은 판정 뒤 실행 시작 전에 세션이 끝나면
    보내지 않는다 (`explore_not_active`, 예약 되돌림). 지연은 창 찾기(실행 시작 바로 앞 단계)에
    넣는다."""
    source = daemon.daemon.screen_source
    real = source.find
    reached, release = threading.Event(), threading.Event()
    armed = threading.Event()

    def slow(title: str) -> Any:
        found = real(title)
        if armed.is_set():
            reached.set()
            release.wait(30)
        return found

    monkeypatch.setattr(source, "find", slow)
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        for how in ("scope", "answer"):
            reached.clear()
            release.clear()
            armed.clear()
            session = agent.call("explore.start", {"title": f"끝 경합 {how}"})["session"]
            if how == "scope":
                assert grant(ui, agent)["verdict"] == "pass"  # 범위를 얻는다 (입력 1)
            before = len(game.inputs())
            armed.set()
            future = agent.request("control.key", KEY)
            if how == "answer":
                ask = approval_request(ui)
                ui.call("approval.respond", {"id": ask["id"], "verdict": "allow_session"})
            assert reached.wait(60)
            agent.call("explore.end", {})  # 판정은 지났고 실행 시작 전이다
            release.set()
            assert error_of(future).kind == "explore_not_active"
            assert len(game.inputs()) == before
            body = record(game, session)
            assert (body["status"], body["steps"]) == ("ended", 1 if how == "scope" else 0)
            wait_until(lambda: not scopes(daemon), timeout=10)


def test_app_launch_has_no_session_allow(game: FakeGame, daemon: ThreadDaemon) -> None:
    """B3 검수 Low 3: 게임 실행은 권한 인자(프로필)가 없어 "이 탐색 동안 허용" 대상이 아니다."""
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "게임 실행"})
        future = agent.request("app.launch", {})
        ask = approval_request(ui)
        assert ask["tool"] == "kb_app_launch" and ask["session"] is None
        error = refused(ui, "approval.respond", {"id": ask["id"], "verdict": "allow_session"})
        assert error.kind == "session_not_allowed"
        ui.call("approval.respond", {"id": ask["id"], "verdict": "deny"})
        assert error_of(future).kind == "approval_denied"
        assert not scopes(daemon)


def test_budget_spent_pending_refuses_allow_session(game: FakeGame, tmp_path: Path) -> None:
    """B3 검수 Low 4: 대기 중에 예산을 다 써 범위가 사라진 세션에는 `allow_session`이 다시 범위를
    만들지 않는다 (`session_not_allowed`). 새 요청 카드에도 단추가 없다."""
    local = game.root / ".kookabug" / "local.json"
    perms = {"preset": "explorer", "toolsets": {"screens": "ask"}}  # 화면 지도 쓰기도 확인
    local.write_text(json.dumps({"format": "kookabug.local/0", "permissions": perms}), "utf-8")
    save = {"key": "card", "frame_id": "f_missing"}
    with game.daemon(env_of(game)) as d, d.client() as ui, d.client(AGENT) as agent:
        started = agent.request("explore.start", {"title": "예산 끝", "max_steps": 1})
        ask = approval_request(ui)
        ui.call("approval.respond", {"id": ask["id"], "verdict": "allow_once"})
        started.result(60)
        pending = agent.request("screens.save", save)
        waiting = approval_request(ui)
        assert waiting["session"] is not None  # 이때는 단추가 있었다
        step = agent.request("control.key", KEY)
        ask = approval_request(ui)
        ui.call("approval.respond", {"id": ask["id"], "verdict": "allow_once"})
        assert step.result(120)["verdict"] == "pass"  # 마지막 칸 — 예산 다 씀
        wait_until(lambda: bool(d.daemon.approvals.spent()), timeout=10)
        error = refused(ui, "approval.respond", {"id": waiting["id"], "verdict": "allow_session"})
        assert error.kind == "session_not_allowed"
        assert not scopes(d)
        ui.call("approval.respond", {"id": waiting["id"], "verdict": "deny"})
        assert error_of(pending).kind == "approval_denied"
        # 새 화면 지도 요청 카드에는 단추가 없다
        again = agent.request("screens.save", save)
        ask = approval_request(ui)
        assert ask["session"] is None
        ui.call("approval.respond", {"id": ask["id"], "verdict": "deny"})
        assert error_of(again).kind == "approval_denied"
