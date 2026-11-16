"""UX7 daemon 쪽 — 실제 daemon(ThreadDaemon)과 가짜 예제 게임(실제 runner 제어 실행)으로.

- `explore.step`(kb_explore_step): 입력 → 기다림 → 캡처 → 판별 → 이동 자동 기록. 새 화면은
  대기 이동, `kb_screen_save`(새 후보)가 그 키로 `to`를 채운다. 비밀값 입력도 같은 제어 경로(값이
  결과·기록에 없음)
- `window: "@game"`: 기억한 게임 프로세스의 창 — 제목이 바뀌어도 붙는다. 결과·기록에 실제 제목
  없음
- `run.start{attach, from_node}`: 새로 띄우지 않고(게임 실행·종료 노드 대신),
  `source: agent_attach`, 사건·지식 근거로 거부(`basis_probe`)
- `question.wait`·`job.progress`·`wiki.read`, 작업 활동은 MCP 호출 번호 하나 = 한 줄
- 권한 거부: 명시 deny 규칙이면 창이 없어도 `permission_denied`가 먼저
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env

from kb_testing.daemon import ThreadDaemon
from kb_testing.fake_game import PASSWORD_FIELD, START_BUTTON, WINDOW, FakeGame, make_fake_game
from kb_testing.proc import wait_until
from kb_testing.sample_game import copy_example_workspace
from kookabug_core.agent_job import jobdir
from kookabug_core.documents import template
from kookabug_core.workspace import secret_env_name
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

SECRET = "PWQ4417ZX"
ACCOUNT_ID = "qa-acct-77Q"
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-ux7", "attended": False}
TITLE_RECT = [412, 380, 200, 64]
"""타이틀 화면 시작 단추 자리 (로그인 화면에는 없다)."""
LOGIN_RECT = [400, 205, 320, 50]
"""로그인 화면 계정 칸 자리."""


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


def card(game: FakeGame, session: str, key: str) -> dict[str, Any]:
    path = game.root / "screens" / "_explored" / session / f"{key}.screen.json"
    return json.loads(path.read_text(encoding="utf-8"))


def to_scene(game: FakeGame, scene: str) -> None:
    """검사: 가짜 게임 장면을 바로 바꾼다 (같은 창·프로세스)."""
    state = game.state()
    state["scene"], state["pending"] = scene, []
    game.state_file.write_text(json.dumps(state), encoding="utf-8")


def texts_under(*folders: Path) -> str:
    out: list[str] = []
    for folder in folders:
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix in (".json", ".jsonl", ".md", ".txt", ".log"):
                out.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(out)


def deny(game: FakeGame, tool: str) -> None:
    local = game.root / ".kookabug" / "local.json"
    rules = [{"rule": tool, "verdict": "deny"}]
    body = {"format": "kookabug.local/0", "permissions": {"preset": "full", "rules": rules}}
    local.write_text(json.dumps(body), encoding="utf-8")


# ---------------------------------------------------------------- C 탐색 한 걸음


def test_explore_step_records_move_and_fills_to(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent, daemon.client() as ui:
        session = agent.call("explore.start", {"title": "접속 경로", "window": WINDOW})["session"]
        # 입력 없이: 첫 화면 (처음 보는 화면 — 이동 없음)
        first = agent.call("explore.step", {"window": "@game"}, timeout=120)
        assert first["window"] == "@game" and first["input"] is None
        assert first["new_screen"] is True and first["move"] is None
        agent.call(
            "screens.save",
            {
                "key": "title",
                "frame_id": first["frame"]["frame_id"],
                "title": "타이틀",
                "detect": {"all": [{"image": TITLE_RECT}]},
            },
            timeout=120,
        )
        # 시작 단추 → 로그인 (처음 보는 화면: 대기 이동)
        step = agent.call(
            "explore.step", {"window": "@game", "point": list(START_BUTTON)}, timeout=120
        )
        assert step["input"]["verdict"] == "pass" and step["changed"] is True
        assert step["new_screen"] is True
        assert step["move"] == {"from": "title", "to": None, "status": "pending"}
        assert game.state()["scene"] == "login"
        agent.call(
            "screens.save",
            {
                "key": "login",
                "frame_id": step["frame"]["frame_id"],
                "title": "로그인",
                "detect": {"all": [{"image": LOGIN_RECT}]},
            },
            timeout=120,
        )
        # 새 화면을 저장하자 출발 카드에 tried로 채워졌다 (to 없는 이동을 에이전트가 맞추지 않는다)
        moves = card(game, session, "title")["moves"]
        width, height = step["frame"]["width"], step["frame"]["height"]
        point = [round(START_BUTTON[0] / width, 4), round(START_BUTTON[1] / height, 4)]
        assert moves == [{"via": {"click": {"point": point}}, "to": "login", "status": "tried"}]
        # 이미 아는 화면으로 가는 걸음은 바로 기록 (recorded)
        to_scene(game, "title")
        back = agent.call("explore.step", {"window": "@game"}, timeout=120)
        assert [m["key"] for m in back["identify"]["matches"]] == ["title"]
        again = agent.call(
            "explore.step", {"window": "@game", "point": list(START_BUTTON)}, timeout=120
        )
        assert again["new_screen"] is False
        assert again["move"] == {
            "from": "title",
            "to": "login",
            "status": "recorded",
            "card": "title",
        }
        assert len(card(game, session, "title")["moves"]) == 1  # 같은 이동은 합친다
        # 입력 없이 로그인 → 타이틀로 바뀐 것은 저절로 바뀐 이동 (UX11 A1)
        assert back["move"] == {
            "from": "login",
            "to": "title",
            "status": "recorded",
            "card": "login",
        }
        assert card(game, session, "login")["moves"] == [
            {"via": {"wait": {}}, "to": "title", "status": "tried"}
        ]
        # 지도 탭: 저장·이동 기록 뒤 explore.changed (후보·이동 수가 는다)
        listed = ui.call("explore.list", {})["sessions"]
        assert listed[0]["counts"] == {"screens": 2, "moves": 2, "untried": 0}
        agent.call("explore.end", {})


def test_screen_save_tried_move_without_to_waits(game: FakeGame, daemon: ThreadDaemon) -> None:
    """`to` 없는 tried 이동은 오류가 아니라 대기 — 다음 새 후보 저장 때 그 키로 채운다."""
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "대기 이동", "window": WINDOW})["session"]
        frame = agent.call("explore.step", {"window": WINDOW}, timeout=120)["frame"]
        agent.call(
            "screens.save",
            {
                "key": "title",
                "frame_id": frame["frame_id"],
                "moves": [{"via": {"key": "enter"}, "status": "tried"}],
            },
            timeout=120,
        )
        assert "moves" not in card(game, session, "title")
        frame = agent.call("explore.step", {"window": WINDOW}, timeout=120)["frame"]
        agent.call(
            "screens.save", {"key": "next_screen", "frame_id": frame["frame_id"]}, timeout=120
        )
        assert card(game, session, "title")["moves"] == [
            {"via": {"key": "enter"}, "to": "next_screen", "status": "tried"}
        ]
        # of가 확정 화면이 아니면 고칠 방법을 알려 준다
        error = refused(
            agent, "screens.save", {"key": "x_screen", "frame_id": frame["frame_id"], "of": "title"}
        )
        assert "kb_screen_list" in error.message and "key" in error.message


def test_explore_step_secret_input_not_protected(game: FakeGame, daemon: ThreadDaemon) -> None:
    """UX11 B: 비밀값 입력 뒤 화면도 가리지 않는다 (이미지가 온다)."""
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "비밀값", "window": WINDOW})["session"]
        agent.call("explore.step", {"window": "@game", "point": list(START_BUTTON)}, timeout=120)
        assert game.state()["scene"] == "login"
        agent.call("explore.step", {"window": "@game", "point": list(PASSWORD_FIELD)}, timeout=120)
        typed = agent.call(
            "explore.step", {"window": "@game", "secret": "acc.pw", "wait_ms": 1000}, timeout=120
        )
        assert typed["input"]["verdict"] == "pass", typed["input"]
        assert "protected" not in typed["frame"] and typed["frame"]["agent_image"]
        agent.call("explore.end", {})
    assert session
    assert game.state()["forms"]["login"]["values"]["password"] == SECRET


def test_explore_step_permission_denied_first(game: FakeGame) -> None:
    deny(game, "kb_explore_step")
    with game.daemon(env_of(game)) as d, d.client(AGENT) as agent:
        before = len(game.inputs())
        for params in (
            {"window": WINDOW, "keys": "enter"},
            {"window": WINDOW},
            {"window": "없는 창", "keys": "enter"},
            {"window": "@game", "keys": "enter"},  # 기억한 게임이 없어도 판정이 먼저
        ):
            assert refused(agent, "explore.step", params).kind == "permission_denied", params
        assert len(game.inputs()) == before
        assert not (game.root / "runs").exists()


def test_explore_step_one_input_only(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        error = refused(agent, "explore.step", {"window": WINDOW, "keys": "a", "text": "b"})
        assert error.code == -32602
        assert refused(agent, "explore.step", {"window": "없는 창"}).kind == "window_not_found"


# ---------------------------------------------------------------- C2 @game


def retitle(game: FakeGame, title: str) -> None:
    """검사: 가짜 게임 창 제목을 바꾼다 (로그인 뒤 제목에 서버·계정이 붙는 게임 흉내)."""
    path = game.frames / "scenario.json"
    table = json.loads(path.read_text(encoding="utf-8"))
    table["window"]["title"] = title
    path.write_text(json.dumps(table), encoding="utf-8")


def test_game_window_survives_title_change(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        # 기억이 없으면 window_not_found
        assert refused(agent, "control.key", {"window": "@game", "keys": "a"}).kind == (
            "window_not_found"
        )
        # 제목으로 한 번 입력하면 그 프로세스를 게임으로 기억한다
        assert (
            agent.call("control.key", {"window": WINDOW, "keys": "a"}, timeout=120)["verdict"]
            == "pass"
        )
        retitle(game, f"{WINDOW} [Server : 1][Account : {ACCOUNT_ID}]")
        # 옛 제목으로는 붙지 않는다 (제목 정확히 같음) — @game은 붙는다
        old = agent.call("control.key", {"window": WINDOW, "keys": "a"}, timeout=120)
        assert old["verdict"] != "pass"
        done = agent.call("control.key", {"window": "@game", "keys": "b"}, timeout=120)
        assert done["verdict"] == "pass"
        assert ACCOUNT_ID not in json.dumps(done)
        games = agent.call("windows.list", {"game": True})["windows"]
        assert len(games) == 1
    # 실행 기록(스냅샷 그래프·사양)에 바뀐 제목(계정 ID)이 없다
    assert ACCOUNT_ID not in texts_under(game.root / "runs")


def test_game_window_permission_uses_real_title(game: FakeGame) -> None:
    """권한 판정 인자는 지금 실제 제목: 그 제목만 막는 규칙이 @game에도 걸린다."""
    local = game.root / ".kookabug" / "local.json"
    rules = [{"rule": f"kb_input_key({WINDOW})", "verdict": "deny"}]
    body = {"format": "kookabug.local/0", "permissions": {"preset": "full", "rules": rules}}
    with game.daemon(env_of(game)) as d, d.client(AGENT) as agent:
        agent.call("explore.start", {"title": "기억", "window": WINDOW})
        agent.call("explore.end", {})
        local.write_text(json.dumps(body), encoding="utf-8")
        before = len(game.inputs())
        assert refused(agent, "control.key", {"window": "@game", "keys": "a"}).kind == (
            "permission_denied"
        )
        assert len(game.inputs()) == before


# ---------------------------------------------------------------- D 붙여 실행


LAUNCH_GRAPH = "subgraphs/common/game_launch.graph.json"
ATTACH_GRAPH = "tests/ux7_attach.graph.json"


def write_graphs(root: Path) -> None:
    launch = template("subgraph", "게임 실행")
    launch.pop("layout", None)
    launch["interface"] = {
        "exits": {"ok": {"kind": "ok"}},
        "outputs": {"window": {"type": "window"}, "process": {"type": "process"}},
    }
    launch["nodes"] = {
        "n_entry": {"type": "core.graph.entry", "version": 1, "next": {"start": "n_launch"}},
        "n_launch": {
            "type": "core.app.launch",
            "version": 1,
            "in": {"path": "C:/no/such/game.exe", "timeout_ms": 1000},
            "next": {"attached": "n_exit"},
        },
        "n_exit": {
            "type": "core.graph.exit",
            "version": 1,
            "config": {"exit": "ok"},
            "in": {
                "window": {"$link": "n_launch.window"},
                "process": {"$link": "n_launch.process"},
            },
        },
    }
    test = template("test", "붙여 실행")
    test.pop("layout", None)
    test["nodes"] = {
        "n_entry": {"type": "core.graph.entry", "version": 1, "next": {"start": "n_call"}},
        "n_call": {
            "type": "core.graph.call",
            "version": 1,
            "config": {"graph": LAUNCH_GRAPH},
            "next": {"ok": "n_click"},
        },
        "n_click": {
            "type": "core.input.click",
            "version": 1,
            "in": {"point": list(START_BUTTON)},
            "next": {"done": "n_close"},
        },
        "n_close": {
            "type": "core.app.close",
            "version": 1,
            "in": {"process": {"$link": "n_call.process"}},
            "next": {"closed": "n_pass"},
        },
        "n_pass": {"type": "core.test.pass", "version": 1},
        "n_fail": {"type": "core.test.fail", "version": 1, "in": {"reason": "끝"}},
    }
    for rel, value in ((LAUNCH_GRAPH, launch), (ATTACH_GRAPH, test)):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def run_json(game: FakeGame, run_id: str) -> dict[str, Any]:
    folder = next(p for p in game.run_folders() if p.name.endswith(f"_{run_id}"))
    return json.loads((folder / "run.json").read_text(encoding="utf-8"))


def wait_run(client: DaemonClient, run_id: str) -> dict[str, Any]:
    status = client.call("run.status", {"run_id": run_id, "wait_ms": 30000}, timeout=120)
    assert status["state"] == "ended", status
    return status


def test_attach_run_uses_running_game(game: FakeGame, daemon: ThreadDaemon) -> None:
    write_graphs(game.root)
    with daemon.client(AGENT) as agent:
        # 기억한 게임이 없으면 window_not_found
        error = refused(
            agent, "run.start", {"path": ATTACH_GRAPH, "idempotency_key": "a0", "attach": True}
        )
        assert error.kind == "window_not_found"
        agent.call("explore.start", {"title": "기억", "window": WINDOW})
        agent.call("explore.end", {})
        agent.call("explore.step", {"window": "@game"}, timeout=120)  # 캡처 한 번 (상태 파일)
        before = game.state()["window"]
        started = agent.call(
            "run.start", {"path": ATTACH_GRAPH, "idempotency_key": "a1", "attach": True}
        )
        status = wait_run(agent, started["run_id"])
        if status["outcome"]["verdict"] != "pass":
            failure = agent.call("run.failure", {"run_id": started["run_id"]})
            pytest.fail(f"붙여 실행 실패: {status} {failure}")
        body = run_json(game, started["run_id"])
        assert body["source"] == "agent_attach"
        # 새로 띄우지 않았고(같은 창·프로세스) 끄지도 않았다 — 클릭은 그 게임에 갔다
        after = game.state()
        assert after["window"] == before and after["window"].get("open", True) is not False
        assert after["scene"] == "login"
        # from_node: 고친 노드부터 (그 앞 노드는 건너뛴다)
        to_scene(game, "title")
        again = agent.call(
            "run.start",
            {"path": ATTACH_GRAPH, "idempotency_key": "a2", "attach": True, "from_node": "n_click"},
        )
        assert wait_run(agent, again["run_id"])["outcome"]["verdict"] == "pass"
        assert game.state()["scene"] == "login"
        # 없는 노드는 실행 오류
        bad = agent.call(
            "run.start",
            {"path": ATTACH_GRAPH, "idempotency_key": "a3", "attach": True, "from_node": "n_x"},
        )
        assert wait_run(agent, bad["run_id"])["outcome"]["verdict"] == "error"
        assert run_json(game, bad["run_id"])["code"] == "from_node_unknown"
        # from_node만 (attach 없이)는 받지 않는다
        error = refused(
            agent,
            "run.start",
            {"path": ATTACH_GRAPH, "idempotency_key": "a4", "from_node": "n_click"},
        )
        assert error.kind == "validation_failed"


def test_attach_run_is_not_basis(game: FakeGame, daemon: ThreadDaemon) -> None:
    write_graphs(game.root)
    with daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "기억", "window": WINDOW})
        agent.call("explore.end", {})
        failed = agent.call(
            "run.start",
            {"path": ATTACH_GRAPH, "idempotency_key": "f1", "attach": True, "from_node": "n_fail"},
        )
        assert wait_run(agent, failed["run_id"])["outcome"]["verdict"] == "fail"
        # 사건 근거가 아니다
        error = refused(agent, "cases.open", {"run": failed["run_id"]})
        assert error.kind == "basis_probe"
        # 지식 근거도 아니다
        lesson = {
            "id": "lesson.attach",
            "advice": "붙여 실행 기록",
            "basis": [{"type": "run", "ref": failed["run_id"]}],
        }
        doc = agent.call("knowledge.get", {"file": "lessons"}).get("doc") or {}
        op = {
            "op": "add",
            "file": "lessons",
            "base_revision": int(doc.get("revision", 0)),
            "item": lesson,
        }
        error = refused(agent, "knowledge.apply", {"request_id": "r-attach", "ops": [op]})
        assert error.kind in ("basis_probe", "validation_failed"), error
        if error.kind == "validation_failed":
            pytest.fail(f"교훈 형식이 틀려 근거 검사까지 가지 않았다: {error.message}")


def test_attach_run_permission_denied(game: FakeGame) -> None:
    write_graphs(game.root)
    deny(game, "kb_run_start")
    with game.daemon(env_of(game)) as d, d.client(AGENT) as agent:
        agent.call("explore.start", {"title": "기억", "window": WINDOW})
        agent.call("explore.end", {})
        error = refused(
            agent,
            "run.start",
            {"path": ATTACH_GRAPH, "idempotency_key": "d1", "attach": True, "from_node": "n_click"},
        )
        assert error.kind == "permission_denied"
    assert not (game.root / "runs").exists()


# ---------------------------------------------------------------- 검수 1 (High 1·3·Mid 4)


def test_attach_run_records_title_and_secret_as_is(game: FakeGame) -> None:
    """종단 (UX11 B — 가리지 않는다): 실제 runner가 쓴 `events.jsonl`·`run.json`과 daemon
    `run.events` RPC. 판정 값과 같은 워크스페이스 비밀값(`pass`)과 계정이 든 창 제목에서도 실행이
    끝까지 가고, 구조 필드는 그대로, 글(판정 사유·창 붙기 출력 제목)도 원문 그대로 남는다."""
    write_graphs(game.root)
    path = game.root / ATTACH_GRAPH
    graph = json.loads(path.read_text(encoding="utf-8"))
    graph["nodes"]["n_call"]["next"]["ok"] = "n_attach"
    graph["nodes"]["n_attach"] = {
        "type": "core.window.attach",
        "version": 1,
        "in": {"title": WINDOW},
        "next": {"found": "n_click"},
    }
    path.write_text(json.dumps(graph), encoding="utf-8")
    env = {**env_of(game), "KOOKABUG_SECRET_UX7_VERDICT": "pass"}
    with game.daemon(env) as d, d.client(AGENT) as agent:
        agent.call("explore.start", {"title": "기억", "window": WINDOW})
        agent.call("explore.end", {})
        retitle(game, f"{WINDOW} [Account : {ACCOUNT_ID}]")
        run = agent.call(
            "run.start", {"path": ATTACH_GRAPH, "idempotency_key": "e1", "attach": True}
        )
        status = wait_run(agent, run["run_id"])
        assert status["outcome"]["verdict"] == "pass", status
        events = agent.call("run.events", {"run_id": run["run_id"], "limit": 500})["events"]
    folder = next(p for p in game.run_folders() if p.name.endswith(run["run_id"]))
    body = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    on_disk = [
        json.loads(x) for x in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert body["verdict"] == "pass" and body["source"] == "agent_attach"
    assert all(e["run"] == run["run_id"] for e in on_disk)
    (end,) = [e for e in on_disk if e["event"] == "run.end"]
    assert end["verdict"] == "pass"
    assert [e["event"] for e in events] == [e["event"] for e in on_disk]
    attached = [e for e in events if e.get("event") == "step.end" and e.get("outputs")]
    titles = [(e["outputs"].get("window") or {}).get("title") for e in attached]
    assert f"{WINDOW} [Account : {ACCOUNT_ID}]" in titles, titles
    for text in (
        (folder / "events.jsonl").read_text(encoding="utf-8"),
        json.dumps(events, ensure_ascii=False),
    ):
        assert ACCOUNT_ID in text and "[가림]" not in text and "***" not in text
    assert "***" not in str(body.get("reason")) and "***" not in str(end.get("reason"))


def test_denied_explore_does_not_select_game(game: FakeGame) -> None:
    """거부된 탐색 요청은 게임 기억을 바꾸지 않는다 (High 3) — 허용된 입력 뒤에만 바뀐다."""
    deny(game, "kb_explore_step")
    with game.daemon(env_of(game)) as d, d.client(AGENT) as agent, d.client() as ui:
        assert agent.call("windows.list", {"game": True})["windows"] == []
        error = refused(agent, "explore.step", {"window": WINDOW, "keys": "a"})
        assert error.kind == "permission_denied"
        assert agent.call("windows.list", {"game": True})["windows"] == []
        # 사람 연결은 기억을 쓰지도 읽지도 않는다
        assert ui.call("windows.list", {"game": True})["windows"] == []
        # 양성 대조: 허용된 입력(kb_input_key)이 성공한 뒤에는 그 창이 이 Agent의 게임이다
        done = agent.call("control.key", {"window": WINDOW, "keys": "a"}, timeout=120)
        assert done["verdict"] == "pass"
        assert len(agent.call("windows.list", {"game": True})["windows"]) == 1
        assert ui.call("windows.list", {"game": True})["windows"] == []


def test_attach_does_not_use_another_agents_game(game: FakeGame, daemon: ThreadDaemon) -> None:
    """게임 기억은 주체별: 다른 Agent가 기억한 창으로 붙여 실행·@game 입력을 하지 않는다
    (High 3)."""
    write_graphs(game.root)
    with daemon.client(AGENT) as owner:
        owner.call("explore.start", {"title": "기억", "window": WINDOW})
        owner.call("explore.end", {})
    other = {**AGENT, "id": "ux7-other-agent"}
    before = len(game.inputs())
    with daemon.client(other) as agent:
        error = refused(
            agent,
            "run.start",
            {"path": ATTACH_GRAPH, "idempotency_key": "o1", "attach": True, "from_node": "n_click"},
        )
        assert error.kind == "window_not_found"
        error = refused(agent, "control.key", {"window": "@game", "keys": "a"})
        assert error.kind == "window_not_found"
    assert len(game.inputs()) == before
    # 기억한 주체 자신은 그대로 쓴다 (같은 agent ID로 다시 붙어도)
    with daemon.client(AGENT) as owner:
        done = owner.call("control.key", {"window": "@game", "keys": "a"}, timeout=120)
        assert done["verdict"] == "pass"


def test_pid_reuse_rejected(game: FakeGame, daemon: ThreadDaemon) -> None:
    """같은 PID라도 프로세스 생성 시각이 다르면 @game으로 붙지 않는다."""
    with daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "기억", "window": WINDOW})
        agent.call("explore.end", {})
        agent.call("explore.step", {"window": "@game"}, timeout=120)
        game.set_window(created="987654321")
        error = refused(agent, "control.key", {"window": "@game", "keys": "a"})
        assert error.kind == "window_not_found"


def test_pending_click_preserves_pixel_coordinate_move(
    game: FakeGame, daemon: ThreadDaemon
) -> None:
    """to 없는 tried 클릭 이동도 프레임 기준으로 검증·정규화(픽셀→비율)해 두고 note를 지킨다
    (Mid 4)."""
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "대기", "window": WINDOW})["session"]
        frame = agent.call("explore.step", {"window": "@game"}, timeout=120)["frame"]
        agent.call(
            "screens.save",
            {
                "key": "first",
                "frame_id": frame["frame_id"],
                "moves": [
                    {"via": {"click": {"point": [64, 48]}}, "status": "tried", "note": "왼쪽 위"}
                ],
            },
            timeout=120,
        )
        # 프레임 밖 점은 대기 이동이라도 저장 전에 거부
        error = refused(
            agent,
            "screens.save",
            {
                "key": "bad",
                "frame_id": frame["frame_id"],
                "moves": [{"via": {"click": {"point": [99999, 1]}}, "status": "tried"}],
            },
        )
        assert error.code == -32602
        agent.call("screens.save", {"key": "second", "frame_id": frame["frame_id"]}, timeout=120)
        moves = card(game, session, "first").get("moves", [])
        point = [round(64 / frame["width"], 4), round(48 / frame["height"], 4)]
        assert moves == [
            {
                "via": {"click": {"point": point}},
                "to": "second",
                "status": "tried",
                "note": "왼쪽 위",
            }
        ]


def test_pending_move_kept_and_reported_when_attach_fails(
    game: FakeGame, daemon: ThreadDaemon
) -> None:
    """대기 이동을 출발 카드에 붙이지 못하면 버리지 않고 오류로 알린다 (Mid 4) — 출발 카드에 없는
    요소를 가리키는 이동."""
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "실패", "window": WINDOW})["session"]
        frame = agent.call("explore.step", {"window": "@game"}, timeout=120)["frame"]
        agent.call(
            "screens.save",
            {
                "key": "first",
                "frame_id": frame["frame_id"],
                "moves": [{"via": {"click": {"element": "없는 단추"}}, "status": "tried"}],
            },
            timeout=120,
        )
        error = refused(agent, "screens.save", {"key": "second", "frame_id": frame["frame_id"]})
        assert error.kind == "validation_failed" and "대기 이동" in error.message
        # 후보 저장은 됐고, 대기 이동은 남았다 (출발 카드에 요소를 더하면 다음 저장 때 붙는다)
        assert card(game, session, "second")["format"] == "kookabug.screen/1"
        elements = [{"name": "없는 단추", "kind": "button", "rect": [10, 10, 40, 20]}]
        agent.call(
            "screens.save",
            {"key": "first", "frame_id": frame["frame_id"], "elements": elements},
            timeout=120,
        )
        agent.call("screens.save", {"key": "third", "frame_id": frame["frame_id"]}, timeout=120)
        assert card(game, session, "first")["moves"] == [
            {"via": {"click": {"element": "없는 단추"}}, "to": "second", "status": "tried"}
        ]


def test_wiki_keeps_game_secret(game: FakeGame, daemon: ThreadDaemon) -> None:
    """UX11 B: 게임 비밀값이 든 위키 페이지도 그대로 쓰고 읽는다."""
    path = game.root / "wiki" / "review-notes.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(f"테스트 계정: {SECRET}", encoding="utf-8")
    with daemon.client(AGENT) as agent:
        agent.call("control.type", {"window": WINDOW, "secret": "acc.pw"}, timeout=120)
        agent.call("wiki.write", {"path": "wiki/kept.md", "text": SECRET, "base_sha256": None})
        assert (game.root / "wiki" / "kept.md").read_text(encoding="utf-8") == SECRET
        read = agent.call("wiki.read", {"path": "wiki/review-notes.md"})
        assert read["text"] == f"테스트 계정: {SECRET}"


# ---------------------------------------------------------------- B·E·F 작업 연결


def job_agent(agent_id: str, token: str) -> dict[str, Any]:
    return {"kind": "agent", "name": "mcp", "version": "0", "id": agent_id, "job_token": token}


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = copy_example_workspace(tmp_path)
    local = root / ".kookabug" / "local.json"
    local.parent.mkdir(exist_ok=True)
    local.write_text(
        json.dumps({"format": "kookabug.local/0", "permissions": {"preset": "curator"}}), "utf-8"
    )
    return root


@pytest.fixture
def job_daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws) as d:
        yield d


def begin(daemon: ThreadDaemon, ws: Path, playbook: str) -> dict[str, Any]:
    job = daemon.begin_job({"playbook": playbook})
    (ws / jobdir.JOBS_DIR / job["job"]).mkdir(parents=True, exist_ok=True)
    return job


LOGIN_QUESTION = {
    "question": "로그인 팝업에서 테스트 계정이 필요해요",
    "human_only": True,
    "blocks": [],
    "how": "등록",
    "kind": "credential",
    "secret_keys": ["login.id", "login.password"],
}


def add_unknown(conn: DaemonClient, rid: str, item: dict[str, Any]) -> str:
    doc = conn.call("knowledge.get", {"file": "unknowns"}).get("doc") or {}
    op = {
        "op": "add",
        "file": "unknowns",
        "base_revision": int(doc.get("revision", 0)),
        "item": item,
    }
    conn.call("knowledge.apply", {"request_id": rid, "ops": [op]}, timeout=60)
    doc = conn.call("knowledge.get", {"file": "unknowns"})["doc"]
    return str(doc["unknowns"][-1]["id"])


def test_question_wait_returns_when_registered(
    job_daemon: ThreadDaemon, ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = begin(job_daemon, ws, "entry")
    value = "ux7-pass-Wq92"
    with (
        job_daemon.client(job_agent(job["agent_id"], job["token"])) as conn,
        job_daemon.client() as ui,
    ):
        uid = add_unknown(conn, "q1", LOGIN_QUESTION)
        # 바로 돌아오기 (wait_ms 0) — MCP 호출 번호를 다는 것처럼 요청마다 다른 번호
        quick = conn.call("question.wait", {"id": uid, "wait_ms": 0}, call=101)
        assert (quick["state"], quick["answered"], quick["kind"]) == ("open", False, "credential")
        future = conn.request("question.wait", {"id": uid, "wait_ms": 60000}, call=102)
        # 기다리는 동안 작업 상태 줄: 계정 등록 대기
        wait_until(
            lambda: (
                (ui.call("jobs.activity", {"job": job["job"]})["waiting"] or {}).get("kind")
                == "credential"
            ),
            timeout=20,
        )
        # 사람이 진행 중에 계정을 등록한다
        monkeypatch.setenv(secret_env_name("login.id"), "qa")
        monkeypatch.setenv(secret_env_name("login.password"), value)
        item = ui.call("knowledge.get", {"file": "unknowns", "id": uid})["item"]
        ui.call("unknowns.answer", {"id": uid, "base_rev": item["rev"], "text": "등록함"})
        done = future.result(120)
        assert done["answered"] is True and done["secret_keys"] == ["login.id", "login.password"]
        assert value not in json.dumps(done)
        assert ui.call("jobs.activity", {"job": job["job"]})["waiting"] is None
        # 없는 질문
        assert refused(conn, "question.wait", {"id": "u-20260101-000000-abcd"}).kind == "not_found"
        # 기다림은 MCP 호출 한 번 = 한 줄 (안쪽 폴링은 세지 않는다)
        wait_until(
            lambda: (
                [e["tool"] for e in ui.call("jobs.activity", {"job": job["job"]})["entries"]].count(
                    "kb_question_wait"
                )
                == 3
            ),
            timeout=15,
        )
    activity = (ws / jobdir.JOBS_DIR / job["job"] / "activity.jsonl").read_text("utf-8")
    assert value not in activity


def test_job_progress_shown_and_checked(job_daemon: ThreadDaemon, ws: Path) -> None:
    job = begin(job_daemon, ws, "entry")
    with (
        job_daemon.client(job_agent(job["agent_id"], job["token"])) as conn,
        job_daemon.client() as ui,
    ):
        done = conn.call(
            "job.progress",
            {"step": 2, "total": 4, "title": "경로 걷기", "doing": "타이틀 터치 → 로그인 팝업"},
        )
        assert done == {"job": job["job"], "step": 2, "total": 4}
        got = ui.call("jobs.activity", {"job": job["job"]})
        assert got["progress"]["title"] == "경로 걷기" and got["progress"]["step"] == 2
        listed = next(j for j in ui.call("jobs.list", {})["jobs"] if j["job"] == job["job"])
        assert listed["progress"]["doing"] == "타이틀 터치 → 로그인 팝업"
        # 줄바꿈·너무 긴 글·step > total은 거부 (필드 이름만)
        for bad in (
            {"step": 1, "total": 4, "title": "a\nb"},
            {"step": 1, "total": 4, "title": "x" * 61},
            {"step": 5, "total": 4, "title": "x"},
        ):
            assert refused(conn, "job.progress", bad).kind == "validation_failed"
        # 작업 토큰 값은 글자 검사에 걸린다 (남지 않는다)
        error = refused(conn, "job.progress", {"step": 1, "total": 4, "title": job["token"]})
        assert error.kind in ("secret_in_text", "validation_failed")
        assert job["token"] not in json.dumps(ui.call("jobs.activity", {"job": job["job"]}))
        # 보고 메모의 한 줄 결과
        conn.call(
            "job.note",
            {
                "text": "로그인 팝업까지 왔다\n다음: 기능 테스트 만들기",
                "headline": "로그인 팝업까지 — 계정 필요",
            },
        )
        listed = next(j for j in ui.call("jobs.list", {})["jobs"] if j["job"] == job["job"])
        assert listed["headline"] == "로그인 팝업까지 — 계정 필요"
    # 작업 밖 Agent는 쓰지 못한다
    with job_daemon.client(AGENT) as other:
        assert (
            refused(other, "job.progress", {"step": 1, "total": 1, "title": "x"}).kind == "job_only"
        )


def test_job_progress_permission_denied(ws: Path) -> None:
    local = ws / ".kookabug" / "local.json"
    rules = [
        {"rule": "kb_job_progress", "verdict": "deny"},
        {"rule": "kb_question_wait", "verdict": "deny"},
    ]
    body = {"format": "kookabug.local/0", "permissions": {"preset": "curator", "rules": rules}}
    local.write_text(json.dumps(body), "utf-8")
    with ThreadDaemon(ws) as d:
        job = begin(d, ws, "entry")
        with d.client(job_agent(job["agent_id"], job["token"])) as conn:
            error = refused(conn, "job.progress", {"step": 1, "total": 1, "title": "x"})
            assert error.kind == "permission_denied"
            error = refused(conn, "question.wait", {"id": "u-20261115-000000-abcd"})
            assert error.kind == "permission_denied"


def test_wiki_read_and_conflict_revision(job_daemon: ThreadDaemon, ws: Path) -> None:
    job = begin(job_daemon, ws, "entry")
    with job_daemon.client(job_agent(job["agent_id"], job["token"])) as conn:
        assert refused(conn, "wiki.read", {"path": "wiki/ux7-notes.md"}).kind == "not_found"
        wrote = conn.call(
            "wiki.write", {"path": "wiki/ux7-notes.md", "text": "첫 줄\n", "base_sha256": None}
        )
        got = conn.call("wiki.read", {"path": "wiki/ux7-notes.md"})
        assert got["text"] == "첫 줄\n" and got["sha256"] == wrote["sha256"]
        # 낡은 base로 쓰면 revision_conflict + 지금 sha256
        error = refused(
            conn,
            "wiki.write",
            {"path": "wiki/ux7-notes.md", "text": "둘째\n", "base_sha256": "0" * 64},
        )
        assert error.kind == "revision_conflict"
        assert (error.data or {}).get("revision") == got["sha256"]
        assert "kb_wiki_read" in error.message
        # 그 값으로 다시 쓰면 된다 (조각 페이지를 새로 만들지 않는다)
        conn.call(
            "wiki.write",
            {"path": "wiki/ux7-notes.md", "text": "둘째\n", "base_sha256": got["sha256"]},
        )
        # index.md도 읽을 수 있다(쓰기는 안 됨), 위키 밖은 허용 경로 예와 함께 거부
        assert conn.call("wiki.read", {"path": "wiki/index.md"})["path"] == "wiki/index.md"
        error = refused(conn, "wiki.read", {"path": "knowledge/unknowns.json"})
        assert error.kind == "policy_path" and "wiki/environment.md" in error.message


def test_activity_counts_one_line_per_mcp_call(job_daemon: ThreadDaemon, ws: Path) -> None:
    job = begin(job_daemon, ws, "entry")
    with (
        job_daemon.client(job_agent(job["agent_id"], job["token"])) as conn,
        job_daemon.client() as ui,
    ):
        # MCP 도구 호출 하나(번호 7)가 daemon 요청 넷 — 한 줄, 호출 수 1
        for method in ("workspace.info", "permissions.get", "plugins.list", "project.qa_info"):
            conn.call(method, {}, call=7)
        conn.call("knowledge.get", {"file": "unknowns"}, call=8)
        conn.call("knowledge.get", {"file": "unknowns"}, call=9)
        wait_until(
            lambda: len(ui.call("jobs.activity", {"job": job["job"]})["entries"]) >= 3, timeout=15
        )
        got = ui.call("jobs.activity", {"job": job["job"]})
        assert [e["tool"] for e in got["entries"]] == [
            "kb_project_info",
            "kb_knowledge_get",
            "kb_knowledge_get",
        ]
        assert got["used"]["tool_calls"] == 3


def test_validation_message_names_missing_field(job_daemon: ThreadDaemon, ws: Path) -> None:
    job = begin(job_daemon, ws, "entry")
    with job_daemon.client(job_agent(job["agent_id"], job["token"])) as conn:
        # op 없는 연산: 빠진 필드 이름과 허용 필드 목록
        op = {"file": "lessons", "base_revision": 0, "item": {"id": "l.x"}}
        error = refused(conn, "knowledge.apply", {"request_id": "v1", "ops": [op]})
        assert error.kind == "validation_failed"
        assert "missing_field 'op'" in error.message and "허용:" in error.message
        assert "file" in error.message.split("허용:", 1)[1]


@pytest.mark.process
@pytest.mark.timeout(120)
def test_game_control_approval_log_omits_runtime_title(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """`@game` 입력의 사람 확인 로그에는 판정용 실제 제목 대신 `@game`이 남는다 (재검수5)."""
    game = make_fake_game(tmp_path, permissions={"preset": "explorer"}, screens=False)
    account = "qa-approval-account-77"
    caplog.set_level(logging.INFO, logger="kookabug_daemon.approvals")
    with (
        game.daemon(env_of(game)) as d,
        d.client() as ui,
        d.client({**AGENT, "attended": True}) as agent,
    ):
        agent.call("explore.start", {"title": "기억", "window": WINDOW})
        retitle(game, f"{WINDOW} [Account : {account}]")
        pending = agent.request("control.key", {"window": "@game", "keys": "a"})
        while True:
            notification = ui.notifications.get(timeout=15)
            if notification.get("method") == "approval.requested":
                ask = notification["params"]
                break
        ui.call("approval.respond", {"id": ask["id"], "verdict": "deny"})
        with pytest.raises(DaemonError) as failed:
            pending.result(30)
        assert failed.value.kind == "approval_denied"
    logs = "\n".join(
        r.getMessage() for r in caplog.records if r.name == "kookabug_daemon.approvals"
    )
    assert "확인 요청" in logs and "@game" in logs
    assert account not in logs
