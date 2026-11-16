"""스텝 썸네일 (구현 계획 M3 2.6, T6, 사용자 결정 U9).

직접 캡처한 스텝이 닫힐 때 그 스텝의 마지막 캡처를 긴 변 480 JPEG로 `thumbs/<스텝>.jpg`에 남긴다.
스크린샷 정책(구간 끄기·비밀값 입력)을 그대로 따르고 막히면 `omitted`에 `kind: thumbnail`. 이벤트
`artifacts`에는 적지 않는다(파일 유무가 기준). 반복 안 스텝은 첫 회차와 마지막 두 회차만 남는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from helpers.evidence import START, SceneRun, run_scene
from helpers.graphs import subgraph_interface, target
from helpers.run import tk

from kookabug_core.engine import MemoryArtifacts
from kookabug_core.record.artifacts import Recorder, StagedFrame
from kookabug_core.record.policy import RecordPolicy
from kookabug_sdk.types import Image

PASS = {"done": "n_pass"}


def body(node: str) -> dict[str, str]:
    """반복 노드의 출구: 본문 → `node`, 끝나면 `n_pass`."""
    return {"body": node, "done": "n_pass"}


def launch(g: Any, then: str) -> Any:
    return g.node(
        "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": then}
    )


def wait_start(g: Any, node: str, then: str | None = None, **kw: Any) -> Any:
    return g.node(
        node,
        "core.image.wait",
        inputs={"target": target(START), "timeout_ms": 0},
        next={"found": then} if then else None,
        **kw,
    )


def thumbs_of(ran: SceneRun, node: str) -> list[str]:
    """그 노드 스텝들 중 썸네일이 남은 것 (스텝 순서)."""
    return [s for s in ran.steps(node) if f"thumbs/{s}.jpg" in ran.thumbs()]


def iterations(ran: SceneRun, node: str) -> list[int]:
    """그 노드 스텝들 중 썸네일이 남은 것의 회차."""
    kept = set(thumbs_of(ran, node))
    return [
        e.get("iteration", -1)
        for e in ran.of("step.start")
        if e["node"] == node and e["step"] in kept
    ]


def test_thumbnail_written_for_capturing_step(tmp_path: Path) -> None:
    g = wait_start(launch(tk().entry("n_launch"), "n_wait"), "n_wait", "n_pass")
    g.node("n_pass", "core.test.pass")
    ran = run_scene(tmp_path, g)
    assert ran.result.verdict == "pass"
    step = ran.step("n_wait")
    # 캡처한 스텝만 (띄우기·종료 노드는 캡처하지 않는다)
    assert ran.thumbs() == {f"thumbs/{step}.jpg"}
    data = (ran.folder / f"thumbs/{step}.jpg").read_bytes()
    assert data[:3] == b"\xff\xd8\xff"
    # 이벤트 artifacts에는 적지 않는다 (파일 유무가 기준)
    end = ran.end("n_wait")
    assert "artifacts" not in end and "omitted" not in end


def test_thumbnail_long_side_480_jpeg(tmp_path: Path) -> None:
    g = wait_start(launch(tk().entry("n_launch"), "n_wait"), "n_wait")
    ran = run_scene(tmp_path, g)
    pixels = ran.image(f"thumbs/{ran.step('n_wait')}.jpg")
    # 1024x640 클라이언트 → 긴 변 480 (비율 유지)
    assert pixels.shape[:2] == (300, 480)


def test_thumbnail_follows_screenshot_policy_and_capture_mark(tmp_path: Path) -> None:
    # 구간 끄기 → 썸네일 없음, omitted에 thumbnail/policy_off
    off = wait_start(
        launch(tk().entry("n_launch"), "n_wait"), "n_wait", record={"screenshots": "off"}
    )
    ran = run_scene(tmp_path / "off", off)
    assert ran.thumbs() == set()
    (omitted,) = ran.end("n_wait")["omitted"]
    assert (omitted["kind"], omitted["reason"]) == ("thumbnail", "policy_off")
    assert "n_wait" in omitted["source"]

    # Recorder 단위: 직접 캡처하지 않은 스텝은 썸네일을 남기지 않는다
    recorder = Recorder(MemoryArtifacts(), _Frames())
    recorder.redact_secrets = True
    recorder.open_step("s1", RecordPolicy())
    recorder.note_inputs("s1", {"v": _secret()}, "g#/nodes/n/in")
    recorder.captured("s1", Image(4, 3), StagedFrame("k1", "px"))
    recorder.open_step("s2", RecordPolicy())
    assert recorder.thumbnail("s2") is None  # 직접 캡처하지 않은 스텝
    assert recorder.thumbnail("s1") is None
    assert recorder.close_step("s1")[1] == [
        {"kind": "thumbnail", "reason": "secret_input", "source": "g#/nodes/n/in/v"}
    ]


def test_loop_keeps_first_and_last_two_iterations_only(tmp_path: Path) -> None:
    g = (
        launch(tk().entry("n_launch"), "n_loop")
        .node("n_loop", "core.flow.repeat", inputs={"times": 6}, next=body("n_wait"))
        .node("n_pass", "core.test.pass")
    )
    wait_start(g, "n_wait")
    ran = run_scene(tmp_path / "flat", g)
    assert ran.result.verdict == "pass", ran.result.reason
    assert len(ran.steps("n_wait")) == 6
    assert iterations(ran, "n_wait") == [0, 4, 5]

    # 중첩 반복: 바깥 회차마다 안쪽도 첫·마지막 둘, 바깥 회차가 넘어가면 안쪽 것까지 같이 지운다
    nested = (
        launch(tk().entry("n_launch"), "n_outer")
        .node("n_outer", "core.flow.repeat", inputs={"times": 4}, next=body("n_inner"))
        .node("n_inner", "core.flow.repeat", inputs={"times": 4}, next={"body": "n_wait"})
        .node("n_pass", "core.test.pass")
    )
    wait_start(nested, "n_wait")
    ran = run_scene(tmp_path / "nested", nested)
    assert ran.result.verdict == "pass", ran.result.reason
    kept = thumbs_of(ran, "n_wait")
    steps = ran.steps("n_wait")
    assert len(steps) == 16
    # 바깥 0·2·3회차마다 안쪽 0·2·3회차
    order = [steps.index(s) for s in kept]
    assert order == [o * 4 + i for o in (0, 2, 3) for i in (0, 2, 3)]

    # 반복 안에서 부른 서브그래프의 스텝도 그 반복 회차에 든다
    sub = tk("subgraph", interface=subgraph_interface()).entry("n_w")
    wait_start(sub, "n_w", "n_x")
    sub.exit("n_x", "done")
    calls = (
        launch(tk().entry("n_launch"), "n_loop")
        .node("n_loop", "core.flow.repeat", inputs={"times": 5}, next=body("n_call"))
        .call("n_call", "subs/w.graph.json")
        .node("n_pass", "core.test.pass")
    )
    ran = run_scene(tmp_path / "call", calls, subgraphs={"subs/w.graph.json": sub})
    assert ran.result.verdict == "pass", ran.result.reason
    inner = ran.steps("n_w")
    assert len(inner) == 5
    assert [inner.index(s) for s in thumbs_of(ran, "n_w")] == [0, 3, 4]


class _Frames:
    """썸네일 단위 검사용 저장소 흉내."""

    def register(
        self, capture_id: int, staged: Any, step: str, *, at_ms: int | None = None
    ) -> None:
        pass

    def close_step(self, step: str, *, parent: str | None = None) -> None:
        pass

    def mark_output(self, capture_id: int) -> None:
        pass

    def encode_png(self, capture_id: int) -> bytes:
        return b"PNG"

    def step_frames(self, step: str) -> None:
        return None

    def encode_jpeg(self, capture_id: int, long_side: int) -> bytes:
        return b"JPEG"


def _secret() -> Any:
    from kookabug_sdk import Secret

    return Secret("x")
