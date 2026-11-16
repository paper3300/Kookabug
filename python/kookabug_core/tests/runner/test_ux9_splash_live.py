"""UX9 A 실제 프로세스: 예제 게임이 시작 화면 창(같은 제목, 작음)을 띄웠다 닫고 본 창을 새로 만든다
(`--splash`). `kookabug run`의 `core.app.launch`가 시작 화면 창에 붙은 뒤에도 다음 대기 노드가 본
창에서 찾는다 (`window.changed`, 제목 없음). 입력은 보내지 않는다."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env, run_cli

from kb_testing.sample_game import EXAMPLE_SECRET_ENV, copy_example_workspace
from kookabug_core.record import read_run

pytestmark = [pytest.mark.desktop, pytest.mark.timeout(300)]

GRAPH = "tests/ux9_splash.graph.json"


def write_graph(ws: Path) -> None:
    body = {
        "format": "kookabug.graph/0",
        "kind": "test",
        "nodes": {
            "n_entry": {"next": {"start": "n_launch"}, "type": "core.graph.entry", "version": 1},
            "n_launch": {
                "in": {
                    "args": {"$setting": "game.args"},
                    "cwd": {"$setting": "game.cwd"},
                    "path": {"$setting": "game.executable"},
                    "timeout_ms": 30000,
                    "window_title": {"$setting": "game.title"},
                },
                "next": {"attached": "n_wait"},
                "type": "core.app.launch",
                "version": 1,
            },
            "n_wait": {
                "in": {
                    "target": {"$target": "targets/title/start_button.target.json"},
                    "timeout_ms": 30000,
                },
                "next": {"found": "n_pass"},
                "type": "core.image.wait",
                "version": 1,
            },
            "n_pass": {"type": "core.test.pass", "version": 1},
        },
        "plugins": {"core": "0.1.0"},
    }
    (ws / GRAPH).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def game_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def test_launch_follows_splash_to_main_window(tmp_path: Path) -> None:
    ws = copy_example_workspace(tmp_path)
    write_graph(ws)
    title = f"KBU9 {uuid.uuid4().hex[:8]}"
    log = tmp_path / "game.jsonl"
    args = ["-m", "sample_game", "--title", title, "--event-log", str(log), "--splash", "3000"]
    env = cli_env(tmp_path, None, **EXAMPLE_SECRET_ENV)
    done = run_cli(
        [
            "run",
            GRAPH,
            "--json",
            "--set",
            f"game.args={json.dumps(args)}",
            "--set",
            f"game.title={json.dumps(title)}",
        ],
        cwd=ws,
        env=env,
        timeout=240,
    )
    assert done.stdout.strip(), done.stderr
    out = json.loads(done.stdout)
    seen = game_events(log) if log.exists() else []
    assert out["verdict"] == "pass", (out.get("code"), out.get("reason"), seen[-5:])
    splash = next(e for e in seen if e["event"] == "splash")["hwnd"]
    main = next(e for e in seen if e["event"] == "ready")["hwnd"]
    assert splash != main
    events = read_run(out["run_dir"]).events
    starts = {e["step"]: e["node"] for e in events if e["event"] == "step.start"}
    ends = {starts[e["step"]]: e for e in events if e["event"] == "step.end"}
    # 게임 실행은 먼저 뜬 시작 화면 창에 붙었고, 대기 노드가 본 창으로 바꿔 찾았다
    assert ends["n_launch"]["outputs"]["window"]["handle"] == splash
    (changed,) = [e for e in events if e["event"] == "window.changed"]
    assert (changed["from_hwnd"], changed["hwnd"], changed["node"]) == (splash, main, "n_wait")
    assert title not in json.dumps(changed, ensure_ascii=False)
    assert ends["n_wait"]["exit"] == "found"
