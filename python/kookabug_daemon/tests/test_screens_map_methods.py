"""화면 지도 daemon 메서드 (M7 계획 3.3·3.7·3.8·R4, B4): `screens.map`(썸네일은 사람에게만),
`screens.check/promote/discard`(사람만), `screens.changed`, daemon 시작 복구, CLI 승격과 에이전트
저장의 직렬화."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from helpers.cli import cli_env
from helpers.explored import SESSION, SESSION_REL, make_explored_workspace, tree

from kb_testing.daemon import ThreadDaemon
from kb_testing.fake_game import FakeGame, make_fake_game
from kookabug_core.screen_promote import journals
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_platform.frames import encode_png

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-m", "attended": True}
CHILD = Path(__file__).parents[2] / "kookabug_core" / "tests" / "procs" / "promote_child.py"
START = [412, 380, 200, 64]


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=60)
    return caught.value


def notification(client: DaemonClient, method: str, timeout: float = 15) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while (left := deadline - time.monotonic()) > 0:
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            break
        if message.get("method") == method:
            return message["params"]
    raise AssertionError(f"{method} 알림이 오지 않았다")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = make_explored_workspace(tmp_path / "ws")
    # 진짜 PNG 대표 스크린샷 (썸네일을 만들 수 있게)
    pixels = np.zeros((640, 1024, 3), dtype=np.uint8)
    pixels[100:200, 100:300] = (40, 200, 90)
    (root / SESSION_REL / "upgrade.shot.png").write_bytes(encode_png(pixels))
    return root


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws) as d:
        yield d


def test_map_agent_has_no_thumbs(ws: Path, daemon: ThreadDaemon) -> None:
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        human = ui.call("screens.map", {})
        mine = agent.call("screens.map", {})
    by_node = {s["node"]: s for s in human["screens"]}
    thumb = by_node[f"x:{SESSION}/upgrade"]["thumb"]
    assert isinstance(thumb, str) and thumb.startswith("map_")
    cached = ws / ".kookabug" / "cache" / "editor" / thumb
    assert cached.is_file() and cached.stat().st_size > 0
    # 에이전트: 썸네일 없음 (C8), 나머지는 같다
    assert all(s["thumb"] is None for s in mine["screens"])
    strip = lambda data: [{**s, "thumb": None} for s in data["screens"]]  # noqa: E731
    assert strip(mine) == strip(human)
    assert mine["edges"] == human["edges"]


def test_layout_saved_with_revision(ws: Path, daemon: ThreadDaemon) -> None:
    """B5 카드 배치 `.kookabug/screen-map.json`: revision 대조, 형식 검사, 에이전트 불가."""
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        empty = ui.call("screens.layout_get", {})
        assert empty == {"layout": {}, "revision": None}
        layout = {
            "positions": {"lobby": [10, 20.5], f"x:{SESSION}/upgrade": [300, 40]},
            "zoom": 0.7,
        }
        saved = ui.call("screens.layout_set", {"layout": layout, "base_revision": None})
        assert saved["layout"] == layout and saved["revision"]
        assert ui.call("screens.layout_get", {}) == saved
        stale = refused(ui, "screens.layout_set", {"layout": {}, "base_revision": None})
        assert stale.kind == "revision_conflict"
        bad = refused(
            ui,
            "screens.layout_set",
            {"layout": {"positions": {"a": [1]}}, "base_revision": saved["revision"]},
        )
        assert bad.code == -32602
        for method, params in (
            ("screens.layout_get", {}),
            ("screens.layout_set", {"layout": {}, "base_revision": saved["revision"]}),
        ):
            assert refused(agent, method, params).kind == "permission_denied"
    body = json.loads((ws / ".kookabug" / "screen-map.json").read_text(encoding="utf-8"))
    assert body == {"format": "kookabug.screen-map/0", "layout": layout}


def test_check_promote_discard_human_only(ws: Path, daemon: ThreadDaemon) -> None:
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        params = {"session": SESSION, "key": "result", "id": "upgrade_result"}
        checked = ui.call("screens.check", params)
        assert checked["ok"] is True and checked["path"] == "screens/upgrade_result.screen.json"
        assert checked["shot"] == "none"  # result 후보에는 대표 스크린샷이 없다
        assert f"{SESSION_REL}/upgrade.screen.json" in checked["revisions"]
        # 에이전트는 확인·승격·버리기를 못 한다
        for method, body in (
            ("screens.check", params),
            ("screens.promote", {**params, "mode": "new", "base_revisions": checked["revisions"]}),
            ("screens.discard", {"session": SESSION, "key": "result"}),
        ):
            assert refused(agent, method, body).kind == "permission_denied"
        assert (ws / SESSION_REL / "result.screen.json").is_file()
        promoted = ui.call(
            "screens.promote", {**params, "mode": "new", "base_revisions": checked["revisions"]}
        )
        assert promoted["path"] == "screens/upgrade_result.screen.json"
        assert promoted["cleanup_pending"] is False
        assert notification(ui, "screens.changed")["revision"]
        # 같은 revision으로 다시: 이미 바뀌었다
        error = refused(
            ui, "screens.promote", {**params, "mode": "new", "base_revisions": checked["revisions"]}
        )
        assert error.kind in ("not_found", "revision_conflict", "screen_exists")
        # 미완성 후보 확인: 승격 불가 이유
        bad = ui.call("screens.check", {"session": SESSION, "key": "loading"})
        assert bad["ok"] is False and bad["code"] == "validation_failed" and bad["problems"]
        removed = ui.call("screens.discard", {"session": SESSION, "key": "loading"})["removed"]
        assert removed == [f"{SESSION_REL}/loading.screen.json"]
        assert (
            refused(ui, "screens.discard", {"session": SESSION, "key": "loading"}).kind
            == "not_found"
        )
        # 지도에 승격본이 확정 카드로
        nodes = {s["node"] for s in ui.call("screens.map", {})["screens"]}
        assert "upgrade_result" in nodes and f"x:{SESSION}/result" not in nodes


def test_daemon_start_recovers_pending_promotion(tmp_path: Path) -> None:
    """커밋 표시 뒤 죽은 승격을 daemon 시작이 앞으로 끝낸다 (app 시작 복구)."""
    done = make_explored_workspace(tmp_path / "done")
    from kookabug_core.screen_promote import PromoteRequest, check, promote

    req = PromoteRequest(SESSION, "result", id="upgrade_result")
    promote(
        done,
        PromoteRequest(
            SESSION, "result", id="upgrade_result", base_revisions=check(done, req)["revisions"]
        ),
    )
    root = make_explored_workspace(tmp_path / "ws")
    rule = [
        {
            "point": "screens.stage",
            "role": "supervisor",
            "when": {"event": "after_commit"},
            "action": "exit:9",
        }
    ]
    args = {
        "session": SESSION,
        "key": "result",
        "id": "upgrade_result",
        "base_revisions": check(root, req)["revisions"],
    }
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(CHILD), str(root), json.dumps(args)],
        env={**os.environ, "KOOKABUG_FAULTS": json.dumps(rule)},
        capture_output=True,
        timeout=120,
    )
    assert proc.returncode == 9
    assert len(journals(root)) == 1
    with ThreadDaemon(root):
        pass  # 시작만으로 복구
    assert journals(root) == []
    assert tree(root) == tree(done)


def test_cli_promote_while_daemon_saves_same_candidate(tmp_path: Path) -> None:
    """R4: CLI 승격이 잠금을 쥔 동안 에이전트가 같은 후보를 다시 저장하면 저장은 잠금을 기다리고,
    승격 뒤 잠금 안에서 확정 ID를 다시 봐 `screen_exists` — 후보가 되살아나지 않는다."""
    game: FakeGame = make_fake_game(tmp_path, draw=False)
    env = cli_env(game.root.parent, None)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(game.root.parent / "user")
    with game.daemon(env) as d, d.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "겹침"})["session"]
        (window,) = agent.call("windows.list", {})["windows"]
        frame = agent.call("target.capture", {"window": window["handle"]})
        save = {
            "key": "title_card",
            "frame_id": frame["frame_id"],
            "title": "타이틀",
            "detect": {"all": [{"image": START}]},
        }
        agent.call("screens.save", save, timeout=60)
        with d.client() as ui:
            checked = ui.call("screens.check", {"session": session, "key": "title_card"})
            assert checked["ok"] and checked["shot"] == "matched"  # 자기 스크린샷에서 맞는다
        gate = tmp_path / "gate"
        rule = [
            {
                "point": "screens.stage",
                "role": "supervisor",
                "when": {"event": "journal_write"},
                "action": f"wait:{gate}",
            }
        ]
        argv = [
            "-X",
            "utf8",
            "-m",
            "kookabug_cli",
            "screen",
            "promote",
            f"{session}/title_card",
            "--workspace",
            str(game.root),
            "--json",
        ]
        child = subprocess.Popen(
            [sys.executable, *argv],
            env={
                **{k: v for k, v in os.environ.items() if k != "KOOKABUG_AGENT"},
                "KOOKABUG_FAULTS": json.dumps(rule),
            },
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            deadline = time.monotonic() + 60
            while not Path(f"{gate}.ready").exists():
                assert time.monotonic() < deadline and child.poll() is None
                time.sleep(0.05)
            outcome: dict[str, Any] = {}

            def resave() -> None:
                try:
                    outcome["result"] = agent.call(
                        "screens.save", {**save, "title": "다시"}, timeout=60
                    )
                except DaemonError as exc:
                    outcome["error"] = exc.kind

            worker = threading.Thread(target=resave)
            worker.start()
            time.sleep(1.0)
            assert worker.is_alive()  # 저장이 화면 지도 잠금을 기다린다
            Path(f"{gate}.go").touch()
            worker.join(60)
            out, _ = child.communicate(timeout=60)
        finally:
            if child.poll() is None:
                child.kill()
    assert child.returncode == 0, out
    assert outcome == {"error": "screen_exists"}
    assert (game.root / "screens" / "title_card.screen.json").is_file()
    assert not (game.root / "screens" / "_explored" / session / "title_card.screen.json").exists()
    assert journals(game.root) == []


def test_save_refused_while_recovery_pending(tmp_path: Path) -> None:
    """B4 검수 High 1: 끝나지 않은 승격 저널이 있으면 에이전트 저장도 잠금 안에서 `recovery_pending`
    (아무것도 쓰지 않음). 사람이 남은 파일을 정리하면 다음 저장이 복구를 끝내고 지나간다."""
    game: FakeGame = make_fake_game(tmp_path, draw=False)
    env = cli_env(game.root.parent, None)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(game.root.parent / "user")
    # 사람이 고친 파일 때문에 롤백이 멈춘 저널 (바꾼 파일의 지금 바이트가 저널의 어느 쪽도 아님)
    note = game.root / "screens" / "notes.txt"
    note.write_text("사람이 고친 메모", encoding="utf-8")
    tx = game.root / ".kookabug" / "screens-tx" / "20261107000000-deadbeef"
    (tx / "backup").mkdir(parents=True)
    (tx / "backup" / "0").write_bytes(b"before")
    journal = {
        "format": "kookabug.screens-tx/0",
        "txid": tx.name,
        "phase": "prepare",
        "creates": [],
        "replaces": [
            {"path": "screens/notes.txt", "before_sha256": "0" * 64, "after_sha256": "1" * 64,
             "backup": "backup/0"}
        ],
        "deletes": [],
        "dirs": [],
        "explore": {"session": "20261107-000000-abcd", "key": "x", "id": "x"},
    }  # fmt: skip
    (tx / "journal.json").write_text(json.dumps(journal), encoding="utf-8")
    with game.daemon(env) as d, d.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "복구 대기"})["session"]
        (window,) = agent.call("windows.list", {})["windows"]
        frame = agent.call("target.capture", {"window": window["handle"]})
        save = {"key": "title_card", "frame_id": frame["frame_id"], "title": "타이틀"}
        error = refused(agent, "screens.save", save)
        assert (error.kind, error.data["paths"]) == ("recovery_pending", ["screens/notes.txt"])
        folder = game.root / "screens" / "_explored" / session
        assert sorted(p.name for p in folder.iterdir()) == ["explore.json"]
        assert note.read_text(encoding="utf-8") == "사람이 고친 메모"
        # 사람이 그 파일을 정리(지움)하면 풀린다
        note.unlink()
        assert agent.call("screens.save", save, timeout=60)["key"] == "title_card"
    assert journals(game.root) == []
