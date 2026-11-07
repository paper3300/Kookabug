"""M7 완료 기준 (구현 계획 v0 1장 M7 행, M7 계획 5장) 인수 테스트, Python 쪽.

1. 예제 게임 탐색 결과가 `screens/_explored/`에 저장된다 — 실제 `kookabug mcp`(stdio) → daemon →
   runner(상태를 잇는 가짜 예제 게임)로 가짜 탐색 에이전트 각본을 끝까지 돈다
2. 재탐색은 아는 화면을 식별하고 합친다 — 보호가 풀리는 화면(타이틀)으로, 미완성 후보는 승격 불가
3. 그 결과가 화면 카드와 이동 그래프로 보인다 — 후보·확정 화면·실행 기록 사슬 간선
4. 사람이 확인해 `screens/`로 옮긴다 — 저널 거래, 실패 주입 대표 지점 3개(kill)
(엄격) 탐색 클릭은 M5 권한·승인·입력 안전 그대로, 입력 충돌, 비밀값은 어느 출구로도
나가지 않는다

다른 테스트 모듈을 import하지 않는다. 자세한 경우는 근거 테스트
(`kookabug_core/tests/test_screen_promote.py`·`test_screen_map.py`·`test_run_chain.py`,
`kookabug_daemon/tests/test_explore*.py`·`test_frame_guard.py`·`test_screens_save.py`·
`test_permissions.py`, `kookabug_mcp/tests/test_capture_protected.py`·`test_control_redact.py`·
`test_explore_tools.py`)에 있다. 실제 에이전트 CLI·실제 게임·사람 눈 확인은
`Docs/verification/m7-manual.md`다.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np
import pytest
from helpers.cli import cli_env
from helpers.graphs import GraphBuilder

from kb_testing.daemon import ThreadDaemon, daemon_env
from kb_testing.fake_explorer import DEFAULT_SCRIPT, run_script
from kb_testing.fake_game import (
    ACCOUNT_FIELD,
    PASSWORD_FIELD,
    START_BUTTON,
    WINDOW,
    FakeGame,
    make_fake_game,
)
from kb_testing.mcp_client import McpClient
from kb_testing.proc import Spawned
from kookabug_core.screen_promote import PromoteRequest, check, journals, promote, recover_locked
from kookabug_core.screens import explored_candidates, read_screen_file
from kookabug_core.workspace import Workspace
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(900)]

ACCOUNT: Final = "qa_tester_01"
PASSWORD: Final = "sample-pass-01"
"""예제 게임 로그인 값 (공개 예제 — 검사에서는 비밀값 `acc.id`·`acc.pw`로 넣는다)."""
SECRETS: Final = {"KOOKABUG_SECRET_ACC_ID": ACCOUNT, "KOOKABUG_SECRET_ACC_PW": PASSWORD}
SAVED: Final = ["title", "login", "login_error", "lobby", "loading", "world", "inventory"]
CHILD: Final = Path(__file__).resolve().parents[1] / "procs" / "promote_child.py"
AGENT: Final = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-m7", "attended": True}
PASSWORD_BOX: Final = [400, 285, 320, 50]
TITLE_BOX: Final = [300, 95, 424, 50]


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass
class World:
    game: FakeGame
    daemon: ThreadDaemon
    out: Path
    spawned: Spawned
    summary: dict[str, Any] = field(default_factory=dict[str, Any])
    mcp_lines: list[bytes] = field(default_factory=list[bytes])

    @property
    def root(self) -> Path:
        return self.game.root

    @property
    def session(self) -> str:
        return str(self.summary["session"])

    def mcp(self, name: str) -> McpClient:
        mcp = McpClient.start(self.spawned, self.root, self.out / name, env=daemon_env(self.out))
        mcp.initialize()
        return mcp

    def explore(self) -> dict[str, Any]:
        mcp = self.mcp("mcp-explore")
        try:
            self.summary = run_script(mcp, json.loads(DEFAULT_SCRIPT.read_text(encoding="utf-8")))
        finally:
            self.mcp_lines += mcp.lines
            mcp.close()
        return self.summary

    def reset_game(self) -> None:
        """게임을 다시 켠다: 처음 화면(장면 표의 start)·새 프로세스(다른 PID = 다른 창 바인딩).
        같은 창이면 비밀값을 넣은 창의 보호 기록이 창 수명 동안 남는다(R1)."""
        state = self.game.state() if self.game.state_file.exists() else {}
        old = state.get("window", {}).get("pid", 0)
        fresh = {
            "format": state.get("format", "kookabug.fake-game-state/1"),
            "variant": state.get("variant", "default"),
            "scene": "title",
            "shown": 0,
            "captures": 0,
            "pending": [],
            "forms": {},
            "window": {"pid": int(old) + 1000, "open": True},
        }
        if not state:
            self.game.state_file.unlink(missing_ok=True)
            return
        self.game.state_file.write_text(json.dumps(fresh), encoding="utf-8")


@contextlib.contextmanager
def world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ocr_models: Path,
    *,
    permissions: dict[str, Any] | None = None,
) -> Iterator[World]:
    for key, value in SECRETS.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    game = make_fake_game(tmp_path, screens=False, permissions=permissions)
    env = cli_env(tmp_path, None, **SECRETS)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp_path / "user")
    spawned = Spawned()
    try:
        with game.daemon(env) as d:
            yield World(game, d, tmp_path, spawned)
    finally:
        spawned.close()


def human_promote(root: Path, session: str, key: str, **kw: Any) -> dict[str, Any]:
    """사람 흐름: 확인 → 그 revision으로 승격 (CLI·대화 상자와 같은 거래)."""
    checked = check(root, PromoteRequest(session, key, **kw))
    assert checked["ok"], checked
    return promote(root, PromoteRequest(session, key, base_revisions=checked["revisions"], **kw))


def tree(root: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for top in ("screens", "targets"):
        base = root / top
        if base.is_dir():
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    out[path.relative_to(root).as_posix()] = path.read_bytes()
    return out


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=120)
    return caught.value


def next_note(client: DaemonClient, method: str, timeout: float = 20) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while (left := deadline - time.monotonic()) > 0:
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            break
        if message.get("method") == method:
            return message["params"]
    raise AssertionError(f"{method}이(가) 오지 않았다")


# ---------------------------------------------------------------- 1. 탐색 결과 저장


def test_agent_explores_sample_game_into_explored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    with world(tmp_path, monkeypatch, ocr_models) as w:
        summary = w.explore()
        with w.daemon.client() as ui:
            (listed,) = ui.call("explore.list", {})["sessions"]
    assert summary["saved"] == SAVED
    assert summary["protected"] == 4  # 비밀값 칸 둘 넣은 로그인 2번 + 로딩·인벤토리
    folder = w.root / "screens" / "_explored" / w.session
    record = json.loads((folder / "explore.json").read_text("utf-8"))
    assert (record["status"], listed["status"]) == ("ended", "ended")
    assert record["steps"] >= 10 and listed["counts"] == summary["counts"]
    cards = {
        c.key: c.screen
        for c in explored_candidates(Workspace.open(w.root))
        if c.session == w.session
    }
    assert set(cards) == set(SAVED) and all(s is not None for s in cards.values())
    # 화면 카드: 판정 조건·대표 스크린샷·UI 요소 / 보호 중 저장은 판정 조건·스크린샷 없음(미완성)
    login = cards["login"]
    assert login is not None and login.detect() and login.shot is not None and login.elements
    for bare in ("loading", "inventory"):
        screen = cards[bare]
        assert screen is not None and screen.incomplete and screen.shot is None
    # 이동: 가 본 것(출발·도착·입력)과 안 가 본 것
    moves = {(k, m.to, m.status) for k, s in cards.items() if s for m in s.moves}
    assert {
        ("title", "login", "tried"),
        ("lobby", "loading", "tried"),
        ("world", "inventory", "tried"),
    } <= moves
    assert ("world", None, "untried") in moves
    # 확정 화면(screens/의 나머지)은 건드리지 않았다 — 판정·검증은 후보를 쓰지 않는다
    assert [p for p in (w.root / "screens").glob("*.screen.json")] == []


# ---------------------------------------------------------------- 2. 재탐색 병합


def test_reexplore_marks_known_and_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    with world(tmp_path, monkeypatch, ocr_models) as w:
        w.explore()
        first = w.session
        human_promote(w.root, first, "title")
        # 미완성 후보(보호 중 저장 — 판정 조건 없음)는 새 화면으로 옮길 수 없다
        bad = check(w.root, PromoteRequest(first, "loading"))
        assert (bad["ok"], bad["code"]) == (False, "validation_failed")
        w.reset_game()
        mcp = w.mcp("mcp-again")
        try:
            mcp.data("kb_toolset_enable", {"toolsets": ["observe", "control", "screens"]})
            second = mcp.data("kb_explore_start", {"title": "다시 보기", "window": WINDOW})[
                "session"
            ]
            shot = mcp.data("kb_screen_capture", {"window": WINDOW})
            assert shot.get("protected") is None  # 보호가 풀린 화면 (타이틀)
            found = mcp.data("kb_screen_identify", {"frame_id": shot["frame_id"]})
            assert [(m["state"], m.get("id")) for m in found["matches"]] == [("confirmed", "title")]
            # 같은 화면을 새 키로 저장하면 확정 화면과 같다고 알려 준다 (중복 판정)
            dup = mcp.data(
                "kb_screen_save",
                {
                    "key": "title_dup",
                    "frame_id": shot["frame_id"],
                    "detect": {"all": [{"image": [412, 380, 200, 64]}]},
                },
            )
            assert {m["node"] for m in dup["also_matches"]} == {"title"}
            # 아는 화면에 이동을 더하는 합치기 후보
            mcp.data(
                "kb_screen_save",
                {
                    "key": "title_more",
                    "frame_id": shot["frame_id"],
                    "of": "title",
                    "moves": [
                        {"via": {"key": "f1"}, "to": None, "status": "untried", "note": "도움말"}
                    ],
                },
            )
            mcp.data("kb_explore_end", {})
        finally:
            w.mcp_lines += mcp.lines
            mcp.close()
        before = read_screen_file(
            w.root / "screens" / "title.screen.json", "screens/title.screen.json"
        )
        human_promote(w.root, second, "title_more", mode="merge")
        after = read_screen_file(
            w.root / "screens" / "title.screen.json", "screens/title.screen.json"
        )
    assert after.detect() == before.detect()  # 판정 조건은 체크하지 않으면 그대로
    assert len(after.moves) == len(before.moves) + 1 and after.moves[-1].note == "도움말"
    assert not (w.root / "screens" / "_explored" / second / "title_more.screen.json").exists()


# ---------------------------------------------------------------- 3. 카드·이동 그래프


def test_screen_map_from_explored_and_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    with world(tmp_path, monkeypatch, ocr_models) as w:
        w.explore()
        session = w.session
        human_promote(w.root, session, "title")
        human_promote(w.root, session, "lobby")
        # 실행 기록 사슬: 화면을 선언한 출구로 끝나는 이웃한 두 호출 (title → lobby)
        for name, screen in (("to_title", "title"), ("to_lobby", "lobby")):
            interface = {"exits": {"ok": {"kind": "ok", "screen": screen}}}
            GraphBuilder("subgraph", interface=interface).entry("n_exit").exit(
                "n_exit", "ok"
            ).write(w.root, f"subgraphs/{name}.graph.json")
        (
            GraphBuilder("test")
            .entry("n_a")
            .call("n_a", "subgraphs/to_title.graph.json", next={"ok": "n_b"})
            .call("n_b", "subgraphs/to_lobby.graph.json", next={"ok": "n_pass"})
            .node("n_pass", "core.test.pass")
            .write(w.root, "tests/chain.graph.json")
        )
        with w.daemon.client() as ui:
            run = ui.call("run.start", {"path": "tests/chain.graph.json"})["run_id"]
            deadline = time.monotonic() + 120
            while ui.call("run.status", {"run_id": run})["state"] != "ended":
                assert time.monotonic() < deadline
                time.sleep(0.3)
            data = ui.call("screens.map", {})
    nodes = {s["node"]: s for s in data["screens"]}
    assert {"title", "lobby"} <= set(nodes)
    for key in ("login", "login_error", "loading", "world", "inventory"):
        assert nodes[f"x:{session}/{key}"]["state"] == "explored"
    assert nodes[f"x:{session}/loading"]["incomplete"] is True
    edges = data["edges"]
    # 탐색 이동 (후보 키 → 승격 ID로 풀림)
    assert any(
        e["from"] == "title" and e["to"] == f"x:{session}/login" and e["status"] == "tried"
        for e in edges
    )
    assert any(e["to"] is None and e["status"] == "untried" for e in edges)
    # 실행 기록 사슬 (에이전트 제어 실행은 빠진다)
    chain = [e for e in edges if any(src.get("kind") == "run" for src in e["sources"])]
    assert [(e["from"], e["to"], e["label"]) for e in chain] == [
        ("title", "lobby", "to_lobby · ok")
    ]
    assert chain[0]["sources"][0]["last_run"] == run
    assert data["sessions"][0]["id"] == session
    # 썸네일은 사람 연결에만 (대표 스크린샷이 있는 카드)
    assert nodes["title"]["thumb"] is not None


# ---------------------------------------------------------------- 4. 승격 (사용자 파일)


def test_promote_moves_into_screens_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    with world(tmp_path, monkeypatch, ocr_models) as w:
        w.explore()
        session = w.session
    root = w.root
    # 기대 상태 둘: 원래 그대로 / 승격본 완전 + 후보 없음
    original = tree(root)
    done_root = tmp_path / "done"
    shutil.copytree(root, done_root, ignore=shutil.ignore_patterns("*.lock", "session.json"))
    result = human_promote(done_root, session, "lobby", id="server_select")
    assert result["path"] == "screens/server_select.screen.json" and not result["cleanup_pending"]
    promoted = tree(done_root)
    assert f"screens/_explored/{session}/lobby.screen.json" not in promoted
    card = json.loads(promoted["screens/server_select.screen.json"])
    assert (
        card["format"] == "kookabug.screen/1"
        and card["shot"]["image"] == "screens/server_select.shot.png"
    )
    # 실패 주입 대표 지점 3개 (B4 test_fault_points의 지점): 자식 프로세스 kill → 다음 잠금의 복구
    for stage, expected in (
        ("before_commit", original),
        ("after_commit", promoted),
        ("deleted", promoted),
    ):
        copy = tmp_path / f"fault_{stage}"
        shutil.copytree(root, copy, ignore=shutil.ignore_patterns("*.lock", "session.json"))
        req = check(copy, PromoteRequest(session, "lobby", id="server_select"))
        rule = [
            {
                "point": "screens.stage",
                "role": "supervisor",
                "when": {"event": stage},
                "action": "exit:9",
            }
        ]
        args = {
            "session": session,
            "key": "lobby",
            "id": "server_select",
            "base_revisions": req["revisions"],
        }
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(CHILD), str(copy), json.dumps(args)],
            env={**os.environ, "KOOKABUG_FAULTS": json.dumps(rule)},
            capture_output=True,
            timeout=120,
        )
        assert proc.returncode == 9, (stage, proc.stderr)
        recover_locked(copy)
        assert tree(copy) == expected, stage
        assert journals(copy) == []


# ---------------------------------------------------------------- 5. 권한·승인·입력 안전 (엄격)


def test_explore_click_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    with world(tmp_path, monkeypatch, ocr_models, permissions={"preset": "explorer"}) as w:
        d = w.daemon
        click = {"window": WINDOW, "point": list(START_BUTTON)}
        with d.client() as ui, d.client(AGENT) as agent:
            session = agent.call("explore.start", {"title": "권한"})[
                "session"
            ]  # explorer: 세션 allow
            future = agent.request("control.click", click)
            ask = next_note(ui, "approval.requested")
            # 게임 조작은 "항상 허용" 없음, 이 탐색 동안 허용만
            assert ask["always_rule"] is None and ask["session"]["id"] == session
            assert (
                refused(ui, "approval.respond", {"id": ask["id"], "verdict": "allow_always"}).kind
                == "always_not_allowed"
            )
            ui.call("approval.respond", {"id": ask["id"], "verdict": "allow_session"})
            assert future.result(120)["verdict"] == "pass"
            # 같은 창·같은 도구는 다시 묻지 않는다 (범위는 메모리 — 규칙 파일 없음)
            assert agent.call("control.click", click, timeout=120)["verdict"] == "pass"
            local = json.loads((w.root / ".kookabug" / "local.json").read_text("utf-8"))
            assert "rules" not in local["permissions"]
            # 에이전트는 사람 전용(승격·버리기·확인·배치·확인 답)을 부를 수 없다
            for method, params in (
                (
                    "screens.promote",
                    {"session": session, "key": "x", "mode": "new", "base_revisions": {}},
                ),
                ("screens.discard", {"session": session}),
                ("screens.check", {"session": session, "key": "x"}),
                ("approval.respond", {"id": ask["id"], "verdict": "allow_once"}),
            ):
                assert refused(agent, method, params).kind == "permission_denied", method
            agent.call("explore.end", {})
        # 사람 없는 에이전트: 탐색 클릭은 묻지 않고 거부, 입력 없음
        before = len(w.game.inputs())
        unattended = {**AGENT, "id": "agent-m7-cron", "attended": False}
        with d.client(unattended) as cron:
            cron.call("explore.start", {"title": "무인"})
            error = refused(cron, "control.click", click)
            assert (error.kind, error.data["decision"]["reason"]) == (
                "permission_denied",
                "unattended_ask",
            )
        assert len(w.game.inputs()) == before


def test_explore_conflicts_with_run_and_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    with world(tmp_path, monkeypatch, ocr_models) as w:
        d = w.daemon
        wait = (
            GraphBuilder("test")
            .entry("n_wait")
            .node("n_wait", "core.flow.delay", inputs={"ms": 60_000}, next={"done": "n_pass"})
            .node("n_pass", "core.test.pass")
        )
        wait.write(w.root, "tests/wait.graph.json")
        click = {"window": WINDOW, "point": list(START_BUTTON)}
        with d.client() as ui, d.client(AGENT) as agent:
            session = agent.call("explore.start", {"title": "충돌", "max_steps": 3})["session"]
            started = ui.call("run.start", {"path": "tests/wait.graph.json"})
            try:
                error = refused(agent, "control.click", click)
                assert (error.kind, error.data["run_id"]) == ("run_busy", started["run_id"])
            finally:
                ui.call("run.cancel", {"run_id": started["run_id"]})
                deadline = time.monotonic() + 60
                while ui.call("run.status", {"run_id": started["run_id"]})["state"] != "ended":
                    assert time.monotonic() < deadline
                    time.sleep(0.2)
            reservation = d.daemon.run_manager.reserve_recording()
            try:
                assert refused(agent, "control.click", click).kind == "recording_active"
            finally:
                reservation.release()
            assert w.game.inputs() == []  # 실행·녹화 중에는 게임에 입력이 가지 않았다
            # 세션은 그대로이고, 거부된 클릭은 예산을 쓰지 않았다 → 이어서 탐색
            assert session in d.daemon.explore.live_ids()
            assert agent.call("control.click", click, timeout=120)["verdict"] == "pass"
            listed = {s["id"]: s for s in ui.call("explore.list", {})["sessions"]}
            assert (listed[session]["status"], listed[session]["steps"]) == ("active", 1)


# ---------------------------------------------------------------- 7. 비밀값 — 모든 출구 (엄격)


class Blind:
    """OCR이 아무것도 못 읽는 엔진 (오인식·미검출 주입)."""

    name = "blind"

    def read(self, image: Any, *, region: Any = None, deadline: Any = None) -> list[Any]:
        return []


def readable(source: Path | bytes, reader: Any) -> str:
    """PNG 파일 또는 바이트를 실제 OCR로 읽은 글자 (정규화 전)."""
    data = source.read_bytes() if isinstance(source, Path) else source
    pixels = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if pixels is None:
        return ""
    return str(reader.read(np.asarray(pixels, dtype=np.uint8)).text)


SHOWN_VALUES: Final = (squash(ACCOUNT), squash(PASSWORD))
"""그림 OCR에서 찾는 값 (정규화형 — 계정·비밀번호 둘 다)."""


def mcp_images(lines: list[bytes]) -> list[bytes]:
    """MCP 응답 줄의 `content[type=image]`를 base64로 푼 그림 (에이전트가 실제로 받은 그림 —
    agent 캐시 파일은 MCP가 읽고 바로 지우므로 디스크에 남지 않는다)."""
    images: list[bytes] = []
    for line in lines:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        result = msg.get("result") if isinstance(msg, dict) else None
        content = result.get("content") if isinstance(result, dict) else None
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get("type") == "image":
                images.append(base64.b64decode(item["data"]))
    return images


def test_no_secret_through_any_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ocr_models: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="kookabug_daemon")
    notes: list[dict[str, Any]] = []
    with world(tmp_path, monkeypatch, ocr_models) as w:
        d = w.daemon
        with d.client() as ui:
            # 양성 대조군: 비밀값을 넣은 원본 프레임에는 값이 보인다 (사람 연결 캡처 + 실제 OCR)
            mcp = w.mcp("mcp-control")
            try:
                mcp.data("kb_toolset_enable", {"toolsets": ["observe", "control"]})
                for tool, args in (
                    ("kb_input_click", {"point": list(START_BUTTON)}),
                    ("kb_input_click", {"point": list(ACCOUNT_FIELD)}),
                    ("kb_input_type", {"secret": "acc.id"}),
                    ("kb_input_click", {"point": list(PASSWORD_FIELD)}),
                    ("kb_input_type", {"secret": "acc.pw"}),
                ):
                    mcp.data(tool, {"window": WINDOW, **args})
                (window,) = ui.call("windows.list", {})["windows"]
                raw = ui.call("target.capture", {"window": window["handle"]})
                text = ui.call(
                    "target.read_text", {"frame_id": raw["frame_id"], "rect": PASSWORD_BOX}
                )["text"]
                assert "samplepass01" in squash(text), text
                # 사람 연결 캡처는 사람 출구(편집기 캐시)에 값이 보이는 게 맞다
                # — 그림 검사에서 이 파일만 뺀다
                control_shots = set((w.root / ".kookabug" / "cache" / "editor").glob("*.png"))
                assert control_shots
                # 에이전트 캡처: 이미지 없음 (OCR이 아무것도 못 읽게 해도
                # — 보호는 OCR 음성에 기대지 않는다)
                targets: Any = d.daemon.targets
                engine = targets.ocr()
                for blind in (False, True):
                    targets._ocr = Blind() if blind else engine
                    shot = mcp.call_tool("kb_screen_capture", {"window": WINDOW}, timeout=60)
                    assert [c["type"] for c in shot["content"]] == ["text"], blind
                    assert shot["structuredContent"]["protected"]["reason"] == "secret_field"
                targets._ocr = engine
            finally:
                w.mcp_lines += mcp.lines
                mcp.close()
            # 탐색 각본 전체 (로그인에 비밀값 두 개) → 승격까지
            w.reset_game()
            w.explore()
            for key in ("title", "login", "lobby", "world"):
                human_promote(w.root, w.session, key)
            # 민감 target이 보이는 화면: 이미지 없음
            frames = w.game.frames
            login = cv2.imread(str(frames / "login.png"))
            assert login is not None
            x, y, width, height = TITLE_BOX
            crop = login[y : y + height, x : x + width]
            cv2.imwrite(str(w.root / "targets" / "sensitive_title.png"), crop)
            (w.root / "targets" / "sensitive_title.target.json").write_text(
                json.dumps(
                    {
                        "format": "kookabug.target/0",
                        "image": "sensitive_title.png",
                        "sensitive": True,
                    }
                ),
                encoding="utf-8",
            )
            w.reset_game()
            mcp = w.mcp("mcp-sensitive")
            try:
                mcp.data("kb_toolset_enable", {"toolsets": ["observe", "control"]})
                mcp.data("kb_input_click", {"window": WINDOW, "point": list(START_BUTTON)})
                shot = mcp.call_tool("kb_screen_capture", {"window": WINDOW}, timeout=60)
                assert [c["type"] for c in shot["content"]] == ["text"]
                assert shot["structuredContent"]["protected"]["reason"] == "sensitive_visible"
            finally:
                w.mcp_lines += mcp.lines
                mcp.close()
            while not ui.notifications.empty():
                notes.append(ui.notifications.get_nowait())
        from kookabug_platform.ocr.engine import Ocr

        reader = Ocr(d.daemon.targets.ocr())
        # 글자 출구: MCP 응답 줄 전부·RPC 알림·daemon 로그·워크스페이스와 MCP 출력 폴더의 모든 파일
        texts = [
            b"\n".join(w.mcp_lines).decode("utf-8", "replace"),
            json.dumps(notes, ensure_ascii=False),
        ]
        texts.append(
            "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("kookabug"))
        )
        # 예제 워크스페이스 원본 그대로인 파일(README의 기본 비밀번호 안내)은 출구가 아니다
        from kb_testing.packaging import REPO_ROOT

        sample = REPO_ROOT / "fixtures" / "sample-game" / "workspace"
        files = [
            p for base in (w.root, *w.out.glob("mcp-*")) for p in base.rglob("*") if p.is_file()
        ]
        for path in files:
            if path.suffix.lower() == ".png" or path.name.endswith(".lock"):
                continue
            if path.is_relative_to(w.root):
                original = sample / path.relative_to(w.root)
                if original.is_file() and original.read_bytes() == path.read_bytes():
                    continue
            data = path.read_bytes()
            texts.append(data.decode("utf-8", "replace") + data.decode("utf-16-le", "replace"))
        for text in texts:
            assert PASSWORD not in text and "samplepass01" not in squash(text)
        # 그림 출구: agent 캐시·편집기 캐시·탐색 결과·승격 파일·제어 실행 기록의 PNG 전부를
        # OCR로 읽어도 값 없음
        pictures = [
            p
            for base in (
                w.root / ".kookabug" / "cache",
                w.root / "screens",
                w.root / "targets",
                w.root / "runs",
            )
            if base.exists()
            for p in base.rglob("*.png")
            if p not in control_shots
        ]
        assert any(
            "_explored" in str(p) or "screens" in p.parts for p in pictures
        )  # 대상이 실제로 있다
        # 양성 대조: 같은 OCR 비교가 사람 캡처(값이 그려짐)에서는 두 값을 다 찾는다
        human = " ".join(squash(readable(p, reader)) for p in control_shots)
        assert all(value in human for value in SHOWN_VALUES), human
        for path in pictures:
            shown = squash(readable(path, reader))
            assert not any(value in shown for value in SHOWN_VALUES), path
        # 에이전트가 실제로 받은 그림: MCP 응답 줄의 image 내용을 풀어 같은 OCR로 읽어도 값 없음
        # (보호를 통과해 나간 그림 — 타이틀·입력 전 로그인·로비·월드 등이 실제로 있다)
        sent = mcp_images(w.mcp_lines)
        assert sent, "에이전트에게 나간 그림이 없다 (검사 대상 없음)"
        read = [squash(readable(data, reader)) for data in sent]
        assert any(read), "MCP 그림을 OCR이 하나도 읽지 못했다"  # 읽기가 실제로 된다
        for n, shown in enumerate(read):
            assert not any(value in shown for value in SHOWN_VALUES), f"MCP 그림 {n}: {shown}"
        # 에이전트 제어 실행 기록은 이미지 기록 자체가 없다 (실행별 기록 강제)
        control_runs = [
            p.parent
            for p in (w.root / "runs").glob("*/run.json")
            if json.loads(p.read_text("utf-8")).get("source") == "agent_control"
        ]
        assert control_runs
        for folder in control_runs:
            assert list(folder.rglob("*.png")) == [], folder
