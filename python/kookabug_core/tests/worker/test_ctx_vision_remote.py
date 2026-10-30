"""워커의 관측 RPC (구현 계획 M1 2.7·2.8): 캡처는 참조 이미지(픽셀은 runner 저장소), 찾기·비교는
runner가 저장소 픽셀로 한다, 효과 재검사, 버린 프레임 → `frame_expired`, 노드 기한 전파.

장면은 예제 게임 `FakeScenario`(PNG를 풀어 프레임 저장소에), 엔진은 실제 `RunEngines`(opencv).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from helpers.graphs import make_workspace, target
from helpers.m1 import SCENARIO, START, ScenePlatform
from helpers.run import tk
from helpers.worker import WorkerHarness

from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.engine import RunResult
from kookabug_core.engine.context import ObservationLimits
from kookabug_core.engine.errors import EngineError
from kookabug_core.engine.scenario import FakeScenario
from kookabug_core.record.artifacts import StagedFrame
from kookabug_platform.engines import RunEngines, deadline_of
from kookabug_platform.frames import FrameStore, decode_image
from kookabug_sdk.types import Image, Rect, WindowRef

pytestmark = pytest.mark.process

TARGET = "targets/start.target.json"


def write_start_target(root: Path) -> None:
    """타이틀 화면에서 "게임 시작" 버튼을 잘라 target으로."""
    title = decode_image((FRAMES_DIR / "title.png").read_bytes())
    x, y, w, h = START.x, START.y, START.width, START.height
    ok, data = cv2.imencode(".png", np.ascontiguousarray(title[y : y + h, x : x + w]))
    assert ok
    folder = root / "targets"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "start.png").write_bytes(data.tobytes())
    body = {"format": "kookabug.target/0", "image": "start.png"}
    (folder / "start.target.json").write_text(json.dumps(body), encoding="utf-8")


def real_platform(store: FrameStore, cls: type[ScenePlatform] = ScenePlatform) -> ScenePlatform:
    return cls(FakeScenario.load(SCENARIO), decode=decode_image, engines=RunEngines(store))


def run(
    tmp_path: Path,
    body: tuple[str, dict[str, Any]],
    *,
    store: FrameStore | None = None,
    platform_cls: type[ScenePlatform] = ScenePlatform,
    trace: Any = None,
    capture_timeout_ms: int = 2000,
) -> tuple[RunResult, ScenePlatform]:
    store = store or FrameStore()
    platform = real_platform(store, platform_cls)
    ws = make_workspace(tmp_path / "ws")
    write_start_target(ws.root)
    node_type, inputs = body
    ok_exit = "found" if node_type == "testkit.m1.find" else "done"
    (
        tk()
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_body"})
        .node("n_body", node_type, inputs=inputs, next={ok_exit: "n_pass"})
        .node("n_pass", "core.test.pass")
        .write(ws, "tests/t.graph.json")
    )
    h = WorkerHarness(
        ws,
        "tests/t.graph.json",
        tmp_path,
        platform=platform,
        frames_store=store,
        trace=trace,
        capture_timeout_ms=capture_timeout_ms,
    )
    return h.run_all(), platform


def body_end(result: RunResult) -> dict[str, Any]:
    steps = [
        e["step"] for e in result.events if e["event"] == "step.start" and e["node"] == "n_body"
    ]
    (found,) = [e for e in result.events if e["event"] == "step.end" and e["step"] in steps]
    return found


def test_worker_capture_returns_reference_only(tmp_path: Path) -> None:
    sizes: dict[str, int] = {}

    def trace(direction: str, body: bytes) -> None:
        if b'"image"' in body and b"capture_id" in body:
            sizes[direction] = max(sizes.get(direction, 0), len(body))

    result, _ = run(tmp_path, ("testkit.m1.capture_ref", {}), trace=trace)
    assert result.verdict == "pass", result.reason
    outputs = body_end(result)["outputs"]
    assert outputs["has_pixels"] is False
    assert outputs["image"]["width"] == 1024 and outputs["image"]["height"] == 640
    # 1024x640 프레임이 워커로 가지 않는다 (참조만: 수백 바이트)
    assert sizes and max(sizes.values()) < 1000, sizes


def test_worker_vision_find_uses_runner_pixels(tmp_path: Path) -> None:
    result, _ = run(tmp_path, ("testkit.m1.find", {"target": target(TARGET)}))
    assert result.verdict == "pass", result.reason
    match = body_end(result)["outputs"]["match"]
    assert match["rect"] == {"x": 412, "y": 380, "width": 200, "height": 64}
    assert match["frame_info"]["backend"] == "fake"
    assert match["target"] == TARGET


def test_worker_vision_diff_same_content_zero_changed_positive(tmp_path: Path) -> None:
    same, _ = run(tmp_path / "same", ("testkit.m1.diff", {}))
    assert same.verdict == "pass", same.reason
    out = body_end(same)["outputs"]
    assert (out["value"], out["same_ids"]) == (0.0, False)  # 다른 캡처 번호, 같은 픽셀
    # 두 캡처 사이 "게임 시작" 클릭: 타이틀 → 로그인 (연속 두 관측이 같은 스텝에서 남아 있다)
    changed, platform = run(
        tmp_path / "changed", ("testkit.m1.diff", {"click": [START.center.x, START.center.y]})
    )
    assert changed.verdict == "pass", changed.reason
    assert body_end(changed)["outputs"]["value"] > 0.01
    assert platform.scenario.latest().state.scene == "login"


def test_worker_undeclared_capture_effect_rejected_by_runner(tmp_path: Path) -> None:
    result, _ = run(tmp_path, ("testkit.m1.vision_sneak", {}))
    assert (result.verdict, result.code) == ("error", "context_violation")


def test_expired_frame_from_worker_is_frame_expired(tmp_path: Path) -> None:
    result, _ = run(tmp_path / "raised", ("testkit.m1.expired", {"target": target(TARGET)}))
    assert (result.verdict, result.code) == ("error", "frame_expired")
    caught, _ = run(
        tmp_path / "caught", ("testkit.m1.expired", {"target": target(TARGET), "catch": True})
    )
    assert caught.verdict == "pass", caught.reason
    assert body_end(caught)["outputs"]["code"] == "frame_expired"


class SlowPlatform(ScenePlatform):
    """캡처가 기한까지 프레임을 주지 않는다 (기한 종류에 맞는 예외로 끝난다)."""

    def capture_staged(
        self, window: WindowRef | None, region: Rect | None, limits: Any = None
    ) -> tuple[Image, StagedFrame]:
        deadline = deadline_of(limits)
        assert isinstance(limits, ObservationLimits) and deadline is not None
        cond = threading.Condition()
        with cond:
            deadline.wait(cond, lambda: False, lambda: EngineError("capture_timeout", "설정 기한"))
        raise AssertionError("기다림이 끝나지 않았다")


def test_worker_observation_deadline_propagated(tmp_path: Path) -> None:
    result, _ = run(
        tmp_path,
        ("testkit.m1.capture_wait", {"timeout_ms": 100}),
        platform_cls=SlowPlatform,
        capture_timeout_ms=10_000,
    )
    end = body_end(result)
    # 워커 노드 기한 100 ms → runner 관측의 노드 기한 → ObservationTimeout이 워커 쪽 예외로
    assert (end["status"], end["exit"]) == ("fail", "timeout"), end.get("error")
    assert 90 <= end["outputs"]["elapsed_ms"] < 2000


def test_worker_config_deadline_is_capture_timeout(tmp_path: Path) -> None:
    result, _ = run(
        tmp_path,
        ("testkit.m1.capture_wait", {"timeout_ms": 5_000}),
        platform_cls=SlowPlatform,
        capture_timeout_ms=100,
    )
    assert (result.verdict, result.code) == ("error", "capture_timeout")
