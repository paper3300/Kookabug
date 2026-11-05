"""실제 runner에서 느린 첫 OCR 준비 (M2 사람 확인 S 결함 ②).

설치본 앱(가짜 플랫폼)에서 예제 `smoke_headless`의 첫 OCR 스텝(`n_check_title`)이 모델 준비를 설정
기한(2초) 안에 하다가 `capture_timeout`으로 끝났다. 같은 그래프·장면 표를 실제 runner로 돌리면서
OCR 엔진 준비를 고장 주입(`ocr.before_load` wait)으로 설정 기한보다 오래 붙잡는다. 그 스텝은 준비를
기다렸다가 정상으로 읽어 통과해야 한다. 대기 노드는 준비가 노드 기한보다 길어도 준비 뒤 자기 기한을
온전히 받아 다시 관측한다. OCR 노드가 없는 실행은 준비를 띄우지 않는다.
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from helpers.m1 import SCENARIO
from helpers.run import tk
from helpers.runner import RunnerHarness, events_of, step_of

from kb_testing.proc import Spawned
from kb_testing.sample_game import FRAMES_DIR, GAME_DIR
from kookabug_core.record.video import TEST_ENV as VIDEO_TEST_ENV

pytestmark = pytest.mark.process

SMOKE = "tests/smoke_headless.graph.json"
EXAMPLE = GAME_DIR / "workspace"
CAPTURE_TIMEOUT_MS = 500
HOLD_S = 1.5
"""준비를 붙잡는 시간: 첫 OCR 스텝이 시작한 뒤부터 잰다 (설정 기한 0.5초의 세 배)."""


def wait_for(cond: Callable[[], bool], timeout: float = 30.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("기다리던 상태가 오지 않았다")


def harness(tmp_path: Path, ocr_models: Path, gate: Path) -> RunnerHarness:
    rule = {"point": "ocr.before_load", "role": "runner", "action": f"wait:{gate}"}
    return RunnerHarness.make(
        tmp_path,
        scenario=str(SCENARIO),
        capture_timeout_ms=CAPTURE_TIMEOUT_MS,
        faults=[rule],
        plugin_modules=(),
        env_extra={"KOOKABUG_OCR_MODELS": str(ocr_models)},
    )


def test_slow_ocr_preparation_does_not_time_out_first_ocr_step(
    tmp_path: Path, spawned: Spawned, ocr_models: Path
) -> None:
    gate = tmp_path / "ocr"
    h = harness(tmp_path, ocr_models, gate)
    h.graph = SMOKE
    (h.ws.root / "tests").mkdir(exist_ok=True)
    shutil.copy2(EXAMPLE / SMOKE, h.ws.root / SMOKE)
    shutil.copytree(EXAMPLE / "targets", h.ws.root / "targets", dirs_exist_ok=True)
    h.start(spawned)
    # 준비는 실행 시작 때 띄워져(첫 OCR 스텝보다 먼저) 붙잡혀 있다
    wait_for(lambda: Path(f"{gate}.ready").exists())
    wait_for(
        lambda: any(e.get("node") == "n_check_title" for e in events_of(h.events(), "step.start"))
    )
    time.sleep(HOLD_S)
    Path(f"{gate}.go").write_text("", encoding="utf-8")
    done = h.finish()
    assert done.run_end is not None, h.stderr()
    assert done.run_end["verdict"] == "pass", (done.run_end, h.stderr())
    _, end = step_of(h.events(), "n_check_title")
    assert end["status"] == "success" and end["exit"] == "ok", end
    assert end["duration_ms"] >= HOLD_S * 1000 * 0.9  # 준비를 기다렸다 (설정 기한 0.5초보다 길게)
    assert "OCR 엔진 준비에" in h.stderr()


def write_title_to_lobby(folder: Path) -> Path:
    """타이틀 화면이 캡처 2번 뒤 저절로 로비로 넘어가는 가짜 장면 (로딩 중 화면이 바뀌는 대역)."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("title", "lobby"):
        shutil.copyfile(FRAMES_DIR / f"{name}.png", folder / f"{name}.png")
    spec = {
        "format": "kookabug.fake-scenario/0",
        "launch": [{"variant": "default"}],
        "process": {"name": "python.exe"},
        "scenes": {"title": "title.png", "lobby": "lobby.png"},
        "start": "title",
        "transitions": [{"after_frames": 2, "from": "title", "to": "lobby"}],
        "variants": ["default"],
        "window": {"client_size": [1024, 640], "dpi": 96, "title": "SampleRPG"},
    }
    path = folder / "scenario.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


WAIT_TIMEOUT_MS = 1500
WAIT_HOLD_S = 2.5
"""대기 노드 기한(1.5초)보다 길게 준비를 붙잡는다."""


def test_slow_preparation_leaves_wait_node_its_whole_timeout(
    tmp_path: Path, spawned: Spawned, ocr_models: Path
) -> None:
    """준비가 대기 노드의 기한보다 오래 걸리고 첫 관측(타이틀)이 기다리는 글자와 다르면, 준비 뒤에도
    노드 기한이 그대로 남아 다음 관측(로비)에서 찾는다 (sfix 2 검수 Mid). 준비를 노드 기한 안에서
    기다리면 첫 관측 하나로 기한이 지나 `timeout`이었다."""
    gate = tmp_path / "ocr"
    scene = write_title_to_lobby(tmp_path / "scene")
    rule = {"point": "ocr.before_load", "role": "runner", "action": f"wait:{gate}"}
    g = (
        tk()
        .entry("launch")
        .node("launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "wait"})
        .node(
            "wait",
            "core.ocr.wait_text",
            inputs={
                "region": [262, 190, 500, 170],
                "contains": "Server 1",
                "timeout_ms": WAIT_TIMEOUT_MS,
            },
            next={"found": "pass"},
        )
        .node("pass", "core.test.pass")
    )
    h = RunnerHarness.make(
        tmp_path,
        g,
        scenario=str(scene),
        faults=[rule],
        plugin_modules=(),
        env_extra={
            "KOOKABUG_OCR_MODELS": str(ocr_models),
            VIDEO_TEST_ENV: json.dumps({"encoder": "fake"}),
        },
    )
    h.start(spawned)
    wait_for(lambda: Path(f"{gate}.ready").exists())
    wait_for(lambda: any(e.get("node") == "wait" for e in events_of(h.events(), "step.start")))
    time.sleep(WAIT_HOLD_S)
    Path(f"{gate}.go").write_text("", encoding="utf-8")
    done = h.finish()
    _, end = step_of(h.events(), "wait")
    assert end["exit"] == "found", (end, h.stderr())
    assert end["duration_ms"] >= WAIT_HOLD_S * 1000 * 0.9  # 준비를 기다렸다 (노드 기한보다 길게)
    assert done.run_end is not None and done.run_end["verdict"] == "pass", done.run_end


def test_run_without_ocr_nodes_does_not_prepare(
    tmp_path: Path, spawned: Spawned, ocr_models: Path
) -> None:
    gate = tmp_path / "ocr"
    g = tk().entry("n_pass").node("n_pass", "core.test.pass")
    h = harness(tmp_path, ocr_models, gate)
    g.write(h.ws, h.graph)
    done = h.start(spawned).finish()
    assert done.run_end is not None and done.run_end["verdict"] == "pass"
    assert not Path(f"{gate}.ready").exists()
