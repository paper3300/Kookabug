"""`run.json`의 관측 환경과 재시도 끝 성공 스텝 수 (구현 계획 M3 2.6, T6).

- `observed`: 실행에서 처음 관측한 창의 캡처 방식·클라이언트 크기·DPI (지난 성공과 비교의 환경,
  RUN 탭 머리). runner가 처음 관측할 때 실행 중 `run.json`에 바로 남겨 감독자가 다시 만들어도 남는다
- `retried_steps`: `step.end.retried`인 스텝 수 ("불안정" 배지). runner가 세고, 감독자가 다시 만들
  때는 저널에서 센다
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder, target
from helpers.m1 import write_target
from helpers.runner import RunnerHarness

from kb_testing.proc import Spawned
from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.record import Journal, write_run_json
from kookabug_core.record.finalize import finalize_run
from kookabug_core.record.runfolder import read_run_json
from kookabug_core.schema import check_shape

LOBBY = "targets/lobby.target.json"
RUN = "r8k2x7qm"


def write_scenario(folder: Path, after_frames: int) -> Path:
    """타이틀 화면이 캡처 `after_frames`번 뒤 저절로 로비로 넘어가는 가짜 장면."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("title", "lobby"):
        shutil.copyfile(FRAMES_DIR / f"{name}.png", folder / f"{name}.png")
    spec = {
        "format": "kookabug.fake-scenario/0",
        "launch": [{"variant": "default"}],
        "process": {"name": "python.exe"},
        "scenes": {"title": "title.png", "lobby": "lobby.png"},
        "start": "title",
        "transitions": [{"after_frames": after_frames, "from": "title", "to": "lobby"}],
        "variants": ["default"],
        "window": {"client_size": [1024, 640], "dpi": 96, "title": "SampleRPG"},
    }
    path = folder / "scenario.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


@pytest.mark.process
def test_run_json_observed_and_retried_steps(tmp_path: Path, spawned: Spawned) -> None:
    # 로비 대기(한 번만 보고 timeout)를 재시도 5번까지: 타이틀 3프레임 뒤 로비 → 4번째 시도에 찾음
    g = (
        GraphBuilder()
        .entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_wait"}
        )
        .node(
            "n_wait",
            "core.image.wait",
            inputs={"target": target(LOBBY), "timeout_ms": 0},
            config={"retry": {"max_attempts": 5}},
            next={"found": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    scenario = write_scenario(tmp_path / "scene", 3)
    h = RunnerHarness.make(tmp_path, g, plugin_modules=(), scenario=str(scenario))
    write_target(h.ws, LOBBY, image="lobby.png")
    done = h.start(spawned).finish()
    assert done.run_end is not None and done.run_end["verdict"] == "pass", done.run_end
    (end,) = [e for e in done.of("step.end") if e.get("retried")]
    assert end["attempt"] == 4
    data = done.run_json
    assert data is not None and not check_shape(data), data
    assert data["retried_steps"] == 1
    assert data["observed"] == {"backend": "fake", "client_size": [1024, 640], "dpi": 96}
    assert "run_json_repaired" not in data


@pytest.mark.process
def test_observed_saved_while_running_survives_runner_kill(
    tmp_path: Path, spawned: Spawned
) -> None:
    """처음 관측하자마자 실행 중 `run.json`에 `observed`가 있고, runner가 죽어 감독자가 다시 만든
    `run.json`에도 남는다 (검수 T6-1 Low)."""
    g = (
        GraphBuilder()
        .entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_wait"}
        )
        .node(
            "n_wait",
            "core.image.wait",
            inputs={"target": target(LOBBY), "timeout_ms": 0},
            config={"retry": {"max_attempts": 5}},
            next={"found": "n_hold"},
        )
        .node("n_hold", "core.flow.delay", inputs={"ms": 30_000}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    scenario = write_scenario(tmp_path / "scene", 3)
    h = RunnerHarness.make(tmp_path, g, plugin_modules=(), scenario=str(scenario))
    write_target(h.ws, LOBBY, image="lobby.png")
    h.start(spawned)
    h.wait_event("step.start", node="n_hold")
    running = h.run_json()
    assert running is not None and running["status"] == "running"
    assert running["observed"] == {"backend": "fake", "client_size": [1024, 640], "dpi": 96}
    h.kill_runner()
    done = h.finish()
    assert done.run_end is not None and done.run_end["code"] == "runner_died"
    data = done.run_json
    assert data is not None and not check_shape(data), data
    assert data.get("run_json_repaired") is True
    assert data["observed"] == running["observed"]
    assert data["retried_steps"] == 1


def test_supervisor_rebuild_counts_retried_steps_and_keeps_observed(tmp_path: Path) -> None:
    """감독자가 다시 만든 `run.json`: 재시도 수는 저널에서 세고, runner가 남긴 관측은 그대로."""
    folder = tmp_path / f"2026-10-29T06-02-11_t_{RUN}"
    folder.mkdir()
    observed = {"backend": "wgc", "client_size": [1280, 720], "dpi": 144}
    write_run_json(
        folder / "run.json",
        {
            "format": "kookabug.run/0",
            "graph": "tests/t.graph.json",
            "observed": observed,
            "run_id": RUN,
            "started_at": "2026-10-29T06:02:11.000Z",
            "status": "running",
        },
    )
    stamp = datetime(2026, 10, 29, 6, 2, 11, tzinfo=UTC)
    events: list[dict[str, Any]] = [
        {
            "event": "run.start",
            "graph": "tests/t.graph.json",
            "protocol": 1,
            "runner": {"created": 1, "pid": 1, "version": "0"},
        }
    ]
    for n, retried in ((1, True), (2, False), (3, True)):
        step = f"s{n}"
        events.append(
            {
                "attempt": 1,
                "event": "step.start",
                "node": f"n{n}",
                "parent": None,
                "path": [f"n{n}"],
                "step": step,
            }
        )
        end: dict[str, Any] = {
            "attempt": 2 if retried else 1,
            "duration_ms": 1,
            "event": "step.end",
            "exit": "done",
            "outputs": {},
            "status": "success",
            "step": step,
        }
        if retried:
            end["retried"] = True
        events.append(end)
    with Journal(folder / "events.jsonl", RUN, now=lambda: stamp) as journal:
        for event in events:
            journal.emit(event)
    result = finalize_run(folder, runner_exit_code=1)
    assert result.run_json_repaired
    data = read_run_json(folder / "run.json")
    assert data is not None and not check_shape(data), data
    assert data["retried_steps"] == 2
    assert data["observed"] == observed
