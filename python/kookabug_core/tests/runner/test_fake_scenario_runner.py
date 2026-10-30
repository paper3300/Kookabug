"""실제 runner 프로세스로 가짜 장면(`platform.scenario`)을 끝까지 (구현 계획 M1 2.7, 계획 검수 8):
띄우기 → 찾기(프레임 저장소 픽셀·실제 매칭) → 클릭·글자·키(입력 액터 → 기록) → 장면 전이 →
스크린샷(저장소 픽셀 → PNG). 같은 그래프가 게임 없이 헤드리스로 돈다."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from helpers.graphs import target
from helpers.m1 import SCENARIO, START
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of

from kb_testing.proc import Spawned, read_fake_input_log
from kb_testing.sample_game import FRAMES_DIR
from kookabug_platform.frames import decode_image

pytestmark = pytest.mark.process

TARGET = "targets/start.target.json"


def write_start_target(root: Path) -> None:
    title = decode_image((FRAMES_DIR / "title.png").read_bytes())
    x, y, w, h = START.x, START.y, START.width, START.height
    ok, data = cv2.imencode(".png", np.ascontiguousarray(title[y : y + h, x : x + w]))
    assert ok
    folder = root / "targets"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "start.png").write_bytes(data.tobytes())
    body = {"format": "kookabug.target/0", "image": "start.png"}
    (folder / "start.target.json").write_text(json.dumps(body), encoding="utf-8")


def test_runner_fake_scenario_end_to_end(tmp_path: Path, spawned: Spawned) -> None:
    g = (
        tk()
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_fc"})
        .node(
            "n_fc",
            "testkit.m1.find_click",
            inputs={"target": target(TARGET)},
            next={"done": "n_acc"},
        )
        .node("n_acc", "testkit.m1.type", inputs={"text": "qa_tester_01"}, next={"done": "n_tab"})
        .node("n_tab", "testkit.m1.key", inputs={"key": "tab"}, next={"done": "n_pw"})
        .node(
            "n_pw", "testkit.m1.type", inputs={"text": "sample-pass-01"}, next={"done": "n_enter"}
        )
        .node("n_enter", "testkit.m1.key", inputs={"key": "enter"}, next={"done": "n_shot"})
        .node("n_shot", "testkit.shot", inputs={"save": True}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = RunnerHarness.make(tmp_path, g, scenario=str(SCENARIO))
    write_start_target(h.ws.root)
    done = h.start(spawned).finish()
    assert done.exit_code == 0
    assert done.run_end is not None and done.run_end["verdict"] == "pass", done.run_end
    events = h.events()
    _, fc = step_of(events, "n_fc")
    assert fc["outputs"]["match"]["rect"] == {"x": 412, "y": 380, "width": 200, "height": 64}
    # 입력은 입력 액터(가짜 백엔드 기록)를 거쳐 장면으로 갔다: 로비 화면이 찍혔다
    downs = [e for e in read_fake_input_log(h.input_log) if e.get("op") == "down"]
    assert downs, "입력 기록이 없다"
    _, shot = step_of(events, "n_shot")
    (saved,) = shot["artifacts"]
    pixels = decode_image((h.run_dir / saved).read_bytes())
    lobby = decode_image((FRAMES_DIR / "lobby.png").read_bytes())
    assert np.array_equal(pixels, lobby)


def test_runner_invalid_scenario_is_platform_invalid(tmp_path: Path, spawned: Spawned) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"format": "other/0"}), encoding="utf-8")
    g = tk().entry("n_pass").node("n_pass", "core.test.pass")
    done = RunnerHarness.make(tmp_path, g, scenario=str(bad)).start(spawned).finish()
    assert done.run_end is not None
    assert (done.run_end["verdict"], done.run_end["code"]) == ("error", "platform_invalid")
