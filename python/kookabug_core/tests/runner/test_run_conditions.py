"""실행 조건(`run.json`의 `plugins`·`conditions.settings`)은 확정되는 대로 running 파일에 남고,
runner가 죽어도 감독자 마무리 결과에 남는다 (스키마 v0 5장, 검수 T9-1 R2·R4).

설정은 그래프의 `$setting`(로드 때)과 노드의 `ctx.setting()`(실행 중) 둘 다 실제로 쓴 값·계층이다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import setting
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of

from kb_testing.proc import Spawned, wait_until

pytestmark = pytest.mark.process

TESTKIT = {"id": "testkit", "version": "0+dev"}


def settings_of(run_json: dict[str, Any] | None) -> dict[str, Any]:
    assert run_json is not None
    return run_json["conditions"]["settings"]


def test_runtime_setting_is_in_finished_conditions(tmp_path: Path, spawned: Spawned) -> None:
    graph = (
        tk()
        .entry("n_read")
        .node(
            "n_read",
            "testkit.ctx_roundtrip",
            inputs={"setting_key": "label"},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    h = RunnerHarness.make(tmp_path, graph, settings={"label": "runtime-value"})
    h.frames = [h.frame("sample")]
    h.start(spawned)
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    _, end = step_of(done.view.events, "n_read")
    assert end is not None and end["outputs"]["setting"] == "runtime-value"
    assert settings_of(done.run_json) == {"label": {"layer": "options", "value": "runtime-value"}}


def test_killed_runner_preserves_settings_and_plugins(tmp_path: Path, spawned: Spawned) -> None:
    # 그래프의 $setting(로드 때)과 ctx.setting(실행 중)을 쓴 뒤 runner를 죽인다
    graph = (
        tk()
        .entry("n_text")
        .node(
            "n_text",
            "testkit.read_text",
            inputs={"text": setting("title")},
            next={"done": "n_read"},
        )
        .node(
            "n_read",
            "testkit.ctx_roundtrip",
            inputs={"setting_key": "label"},
            next={"done": "n_block"},
        )
        .node("n_block", "testkit.block")
    )
    h = RunnerHarness.make(
        tmp_path,
        graph,
        settings={"title": "review-value"},
        ws_settings={"label": "from-workspace"},
    )
    h.frames = [h.frame("sample")]
    h.start(spawned)
    h.wait_log("blocking")
    h.kill_runner()
    done = h.finish()
    assert done.run_end is not None and done.run_end["code"] == "runner_died"
    assert settings_of(done.run_json) == {
        "label": {"layer": "workspace", "value": "from-workspace"},
        "title": {"layer": "options", "value": "review-value"},
    }
    assert done.run_json is not None and TESTKIT in done.run_json["plugins"]
    assert done.run_json["run_json_repaired"] is True


def test_killed_during_worker_start_keeps_loaded_settings(tmp_path: Path, spawned: Spawned) -> None:
    # 설정은 스냅샷(로드) 직후 남는다: 워커 hello를 기다리는 중 죽어도 남아 있다
    faults = [{"point": "worker.before_hello_reply", "role": "worker", "action": "hang"}]
    graph = (
        tk().entry("n_text").node("n_text", "testkit.read_text", inputs={"text": setting("title")})
    )
    h = RunnerHarness.make(tmp_path, graph, settings={"title": "early"}, faults=faults)
    h.start(spawned)
    h.wait_event("worker.start")
    wait_until(lambda: settings_of(h.run_json()) != {})
    h.kill_runner()
    done = h.finish()
    assert done.run_end is not None and done.run_end["code"] == "runner_died"
    assert settings_of(done.run_json) == {"title": {"layer": "options", "value": "early"}}
    assert done.run_json is not None and done.run_json["plugins"] == []  # hello 전: 아직 모름
