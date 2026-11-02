"""앱·창·입력 노드를 실제 runner(`platform.kind: windows`)로 예제 게임에 돌린다 (구현 계획 M1 T10).

게임은 `core.app.launch`가 실행 Job 안에서 띄운다(실행이 끝나면 Job이 정리한다). 증거는 게임의
입력 수신 기록(`--event-log`)이다. 실제 입력 검사는 시작 전에 눌린 키가 없는지 보고, 끝에 눌린
것을 뗀다(`kb_testing.keys`).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import link, target
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of

from kb_testing.keys import assert_no_keys_held, release_all_for_test
from kb_testing.proc import Spawned, python_cmd, wait_until
from kb_testing.sample_game import GAME_DIR

ACCOUNT = "qa_tester_01"
PASSWORD = "sample-pass-01"


def game_inputs(title: str, event_log: Path) -> dict[str, Any]:
    """`core.app.launch` 입력: 기반 인터프리터로 예제 게임을 띄운다(`-m`은 cwd에서 찾는다)."""
    python, *args = python_cmd("-m", "sample_game")
    options = ["--title", title, "--event-log", str(event_log), "--dpi-awareness", "pmv2"]
    return {
        "path": python,
        "args": [*args, *options, "--size", "1024x640"],
        "cwd": str(GAME_DIR),
        "window_title": title,
        "timeout_ms": 20000,
    }


def game_events(event_log: Path) -> list[dict[str, Any]]:
    if not event_log.exists():
        return []
    lines = event_log.read_bytes().split(b"\n")
    return [json.loads(line) for line in lines[:-1] if line.strip()]


@pytest.fixture
def no_keys_left() -> Iterator[None]:
    assert_no_keys_held()
    try:
        yield
    finally:
        release_all_for_test()


def run_windows(tmp_path: Path, graph: Any) -> RunnerHarness:
    """`platform.kind: windows` runner (실제 캡처·SendInput)."""
    return RunnerHarness.make(tmp_path, graph, windows=True, fake_input=False)


@pytest.mark.desktop
def test_launch_sample_game_and_close(tmp_path: Path, spawned: Spawned) -> None:
    title = f"KB T10 {uuid.uuid4().hex[:8]}"
    event_log = tmp_path / "game.jsonl"
    signal = tmp_path / "first-screen.signal"
    g = (
        tk()
        .entry("n_launch")
        .node(
            "n_launch",
            "core.app.launch",
            inputs=game_inputs(title, event_log),
            next={"attached": "n_attach"},
        )
        .node(
            "n_attach",
            "core.window.attach",
            inputs={"title": title},
            next={"found": "n_gate"},
        )
        # 창은 첫 화면을 그리기 전에 보인다(게임이 창을 띄운 뒤 준비를 마치고 첫 `screen`을 기록).
        # 그 전에 닫으면 준비 중에 끝나 정상 종료를 볼 수 없다: 검사가 첫 화면 기록을 본 뒤 연다
        .node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_close"})
        .node(
            "n_close",
            "core.app.close",
            inputs={"process": link("n_launch.process"), "force_after_ms": 10000},
            next={"closed": "n_ok"},
        )
        .node(
            "n_ok",
            "core.assert.compare",
            inputs={"a": link("n_attach.window"), "op": "==", "b": link("n_launch.window")},
            next={"ok": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    h = run_windows(tmp_path, g).start(spawned)
    first = wait_until(
        lambda: next((e for e in game_events(event_log) if e["event"] == "screen"), None),
        timeout=30,
        message=lambda: f"게임이 첫 화면을 기록하지 않았다: {game_events(event_log)}",
    )
    assert first is not None and first["scene"] == "title", first
    signal.write_text("", encoding="utf-8")
    done = h.finish(timeout=60)
    assert done.run_end is not None and done.run_end["verdict"] == "pass", done.run_end
    _, launched = step_of(h.events(), "n_launch")
    assert launched["exit"] == "attached"
    window = launched["outputs"]["window"]
    assert window["title"] == title and window["pid"] == launched["outputs"]["process"]["pid"]
    # 게임은 창 닫기를 받아 스스로 끝났다 (강제 종료가 아니다: 메인 루프가 끝나며 exit 0을 기록)
    _, closed = step_of(h.events(), "n_close")
    assert closed["exit"] == "closed"
    last = game_events(event_log)[-1]
    assert (last["event"], last.get("code")) == ("exit", 0), last


@pytest.mark.desktop_input
@pytest.mark.usefixtures("no_keys_left")
def test_click_and_type_into_login_form(tmp_path: Path, spawned: Spawned, targets: Any) -> None:
    title = f"KB T10 {uuid.uuid4().hex[:8]}"
    event_log = tmp_path / "game.jsonl"
    g = (
        tk()
        .entry("n_launch")
        .node(
            "n_launch",
            "core.app.launch",
            inputs=game_inputs(title, event_log),
            next={"attached": "n_settle"},
        )
        # 창이 뜬 뒤 첫 화면이 그려질 시간 (대기 노드는 T11)
        .node("n_settle", "core.flow.delay", inputs={"ms": 1000}, next={"done": "n_start"})
        .node("n_start", "core.input.click", inputs={"point": [512, 412]}, next={"done": "n_wait"})
        .node("n_wait", "core.flow.delay", inputs={"ms": 500}, next={"done": "n_acc"})
        .node(
            "n_acc",
            "core.input.type_text",
            inputs={"target": target(targets.ACCOUNT), "text": ACCOUNT, "clear": True},
            next={"done": "n_pw"},
        )
        .node(
            "n_pw",
            "core.input.type_text",
            inputs={"target": target(targets.PASSWORD), "text": PASSWORD, "clear": True},
            next={"done": "n_enter"},
        )
        .node("n_enter", "core.input.key", inputs={"keys": "enter"}, next={"done": "n_after"})
        .node("n_after", "core.flow.delay", inputs={"ms": 500}, next={"done": "n_ok"})
        .node(
            "n_ok",
            "core.assert.compare",
            inputs={"a": 1, "op": "==", "b": 1},
            next={"ok": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    h = run_windows(tmp_path, g)
    targets.login(h.ws.root)
    h.start(spawned)
    done = h.finish(timeout=90)
    events = game_events(event_log)
    assert done.run_end is not None and done.run_end["verdict"] == "pass", (done.run_end, events)
    # 게임이 실제로 받은 것: 타이틀 → 로그인 → (칸 두 개에 글자) → 로비
    scenes = [e["scene"] for e in events if e["event"] == "screen"]
    assert scenes[:2] == ["title", "login"] and scenes[-1] == "lobby", scenes
    typed = "".join(e["text"] for e in events if e["event"] == "char")
    assert ACCOUNT in typed and PASSWORD in typed, typed
    clicks = [(e["x"], e["y"]) for e in events if e["event"] == "mouse_down"]
    assert clicks[:3] == [(512, 412), (560, 230), (560, 310)], clicks
