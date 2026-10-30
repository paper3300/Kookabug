"""실행 엔진 `RunEngines`와 가짜 ctx 엔진 `fake_engines` (구현 계획 M1 2.5·2.6·2.7, T9).

- 참조 이미지(저장소)와 파일 이미지가 같은 매칭·OCR을 돈다. SDK 값(`Match`·`OcrResult`)으로 바뀐다
- 영역 캡처의 원점 보정, `sensitive` → `Secret`, 버린 캡처 → `frame_expired`
- `fake_context`에 엔진을 넣지 않으면 실제 엔진(`kookabug_platform.fake_engines`)이 붙는다
- 프레임 저장소 등급의 실행기 연결: 출력으로 나간 캡처는 출력 참조, 서브그래프 안 마지막 캡처는
  부른 스텝의 증거로 넘어간다 (M1 2.15)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from helpers.graphs import make_workspace, subgraph_interface
from helpers.run import tk
from testkit import registry_with_testkit

from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.engine import ExecOptions, Executor, FakeClock, FakePlatform, MemoryArtifacts
from kookabug_core.engine.context import ObservationLimits
from kookabug_core.loader import load_program
from kookabug_core.record.artifacts import CaptureMeta, StagedFrame
from kookabug_platform.engines import RunEngines
from kookabug_platform.errors import FRAME_EXPIRED, PlatformError
from kookabug_platform.frames import FrameStore, decode_image
from kookabug_platform.vision import load_target_file
from kookabug_sdk.testing import fake_context
from kookabug_sdk.types import Image, Rect, Secret, Target, WindowRef

START = (412, 380, 200, 64)
LIMITS = ObservationLimits(5000)
WIN = WindowRef(0x10, "SampleRPG", pid=7, process_created="1", binding="r.w1")


def write_target(folder: Path, box: tuple[int, int, int, int] = START) -> Target:
    title = decode_image((FRAMES_DIR / "title.png").read_bytes())
    x, y, w, h = box
    ok, data = cv2.imencode(".png", np.ascontiguousarray(title[y : y + h, x : x + w]))
    assert ok
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "start.png").write_bytes(data.tobytes())
    body = {"format": "kookabug.target/0", "image": "start.png", "click": {"anchor": "top_left"}}
    path = folder / "start.target.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return load_target_file(path)


def stored(
    store: FrameStore, capture_id: int, name: str, region: Rect | None = None, step: str = "s1"
) -> Image:
    pixels = decode_image((FRAMES_DIR / f"{name}.png").read_bytes())
    origin = (0, 0)
    if region is not None:
        origin = (region.x, region.y)
        pixels = pixels[region.y : region.y + region.height, region.x : region.x + region.width]
    meta = CaptureMeta((1024, 640), 96, origin, "wgc", WIN, 12.5, capture_id)
    store.register(capture_id, StagedFrame((name, region), pixels.copy(), meta), step)
    return Image(
        int(pixels.shape[1]), int(pixels.shape[0]), frame=capture_id, capture_id=capture_id
    )


def test_reference_image_match_carries_frame_info_window_and_target(tmp_path: Path) -> None:
    store = FrameStore()
    engines = RunEngines(store)
    target = write_target(tmp_path)
    match = engines.find(stored(store, 1, "title"), target, limits=LIMITS)
    assert match is not None
    assert (match.rect, match.window, match.frame) == (Rect(*START), WIN, 1)
    assert match.click_point == match.click and match.click is not None
    assert (match.click.x, match.click.y) == (412, 380)  # target의 클릭 지점 (왼쪽 위)
    info = match.frame_info
    assert info is not None
    assert (info.backend, info.client_size, info.dpi, info.capture_id, info.observed_at) == (
        "wgc",
        (1024, 640),
        96,
        1,
        12.5,
    )
    assert match.target == target.name


def test_region_capture_offsets_to_client_coordinates(tmp_path: Path) -> None:
    store = FrameStore()
    engines = RunEngines(store)
    image = stored(store, 1, "title", Rect(300, 300, 400, 200))
    match = engines.find(image, write_target(tmp_path), limits=LIMITS)
    assert match is not None and match.rect == Rect(*START)
    # 검색 범위도 클라이언트 좌표: 버튼 밖이면 못 찾는다
    assert (
        engines.find(image, write_target(tmp_path), region=Rect(300, 300, 100, 50), limits=LIMITS)
        is None
    )


def test_file_and_bytes_images_use_same_matching(tmp_path: Path) -> None:
    engines = RunEngines()
    target = write_target(tmp_path)
    by_path = engines.find(Image(path=FRAMES_DIR / "title.png", frame=3), target, limits=LIMITS)
    data = (FRAMES_DIR / "title.png").read_bytes()
    by_bytes = engines.find(Image(data=data), target, limits=LIMITS)
    assert by_path is not None and by_bytes is not None
    assert by_path.rect == by_bytes.rect == Rect(*START)
    assert by_path.frame == 3 and by_path.frame_info is not None
    assert by_path.frame_info.backend == "image"


def test_diff_reference_file_and_mixed() -> None:
    store = FrameStore()
    engines = RunEngines(store)
    a, b = stored(store, 1, "title"), stored(store, 2, "title")
    c = stored(store, 3, "login", step="s2")
    assert engines.diff(a, b) == 0.0  # 같은 동일성 키
    assert engines.diff(a, c) > 0.0
    title_file = Image(path=FRAMES_DIR / "title.png")
    assert engines.diff(a, title_file) == 0.0  # 한쪽만 저장소
    assert engines.diff(title_file, Image(path=FRAMES_DIR / "login.png")) > 0.0


def gradient() -> np.ndarray[Any, np.dtype[np.uint8]]:
    """한 장의 30x20 화면 (열마다 값이 다르다)."""
    return np.broadcast_to(np.arange(30, dtype=np.uint8)[None, :, None] * 8, (20, 30, 3)).copy()


def crop_of(store: FrameStore, capture_id: int, x: int, width: int, step: str) -> Image:
    """같은 화면의 영역 캡처 (원점 (x, 0), 너비 `width`)."""
    pixels = gradient()[:, x : x + width].copy()
    meta = CaptureMeta((30, 20), origin=(x, 0))
    store.register(capture_id, StagedFrame(("g", x, width), pixels, meta), step)
    return Image(width, 20, capture_id=capture_id)


def test_diff_region_compares_same_client_area_per_image_origin(tmp_path: Path) -> None:
    """`region`은 클라이언트 좌표: 이미지마다 자기 원점을 빼고 같은 클라이언트 영역끼리 비교한다
    (T9 검수 3)."""
    store = FrameStore()
    engines = RunEngines(store)
    left = crop_of(store, 1, 0, 20, "s1")  # x 0..20
    right = crop_of(store, 2, 10, 20, "s1")  # x 10..30
    full = crop_of(store, 3, 0, 30, "s2")  # 전체
    common = Rect(10, 0, 10, 20)
    assert engines.diff(left, right, region=common) == 0.0  # 원점이 다른 두 영역 캡처
    assert engines.diff(full, right, region=common) == 0.0  # 전체 / 영역
    assert engines.diff(right, full, region=Rect(0, 0, 30, 20)) == 0.0  # 둘 다 덮는 부분만
    assert engines.diff(left, right, region=Rect(25, 0, 5, 5)) == 0.0  # 겹치는 곳 없음
    assert engines.diff(left, right) == pytest.approx(10 * 8 / 255)  # region 없으면 이미지 전체
    # 파일 이미지(원점 (0, 0)) / 참조 이미지
    path = tmp_path / "full.png"
    ok, data = cv2.imencode(".png", gradient())
    assert ok
    path.write_bytes(data.tobytes())
    assert engines.diff(Image(path=path), right, region=common) == 0.0
    assert engines.diff(left, Image(path=path), region=Rect(0, 0, 20, 20)) == 0.0
    assert engines.diff(Image(path=path), right, region=Rect(0, 0, 30, 20)) == 0.0


def test_region_diff_detects_client_resize() -> None:
    """영역을 주어도 두 관측의 클라이언트 크기가 다르면 1.0 (창 크기 변경 = 안정되지 않음, T9 2차
    검수 3). 같은 클라이언트의 다른 영역 캡처는 원점 보정으로 비교한다(위 검사)."""
    store = FrameStore()
    images = []
    for capture_id, size in ((1, 10), (2, 20)):
        meta = CaptureMeta((size, size), backend="wgc", window=WIN)
        pixels = np.zeros((size, size, 3), dtype=np.uint8)
        store.register(capture_id, StagedFrame(("z", size), pixels, meta), "s1")
        images.append(Image(size, size, capture_id=capture_id))
    engines = RunEngines(store)
    assert engines.diff(images[0], images[1]) == 1.0
    assert engines.diff(images[0], images[1], region=Rect(0, 0, 5, 5)) == 1.0
    # 영역 캡처끼리도: 클라이언트 크기가 다르면 같은 픽셀이어도 1.0
    for capture_id, client in ((3, (30, 20)), (4, (40, 20))):
        meta = CaptureMeta(client, origin=(0, 0), backend="wgc", window=WIN)
        store.register(
            capture_id, StagedFrame(("r", capture_id), np.zeros((5, 5, 3), np.uint8), meta), "s2"
        )
    assert (
        engines.diff(Image(5, 5, capture_id=3), Image(5, 5, capture_id=4), region=Rect(0, 0, 5, 5))
        == 1.0
    )


def test_expired_reference_is_frame_expired(tmp_path: Path) -> None:
    store = FrameStore()
    engines = RunEngines(store)
    image = stored(store, 1, "title")
    for capture_id in (2, 3):
        stored(store, capture_id, "login")  # 스텝 최근 두 개만 남는다
    with pytest.raises(PlatformError) as caught:
        engines.find(image, write_target(tmp_path), limits=LIMITS)
    assert caught.value.code == FRAME_EXPIRED


@pytest.mark.usefixtures("ocr_models")
def test_ocr_reference_and_sensitive_secret() -> None:
    store = FrameStore()
    engines = RunEngines(store)
    image = stored(store, 1, "world")
    plain = engines.read_text(image, limits=LIMITS)
    assert isinstance(plain.text, str) and "12,345" in plain.text
    hidden = engines.read_text(image, sensitive=True, limits=LIMITS)
    assert isinstance(hidden.text, Secret) and hidden.text.reveal() == plain.text
    assert all(isinstance(line.text, Secret) for line in hidden.lines)
    assert str(hidden.text) == Secret.MASK


def test_fake_context_default_engines_find_and_diff(tmp_path: Path) -> None:
    target = write_target(tmp_path)
    ctx = fake_context(frames=[FRAMES_DIR / "title.png", FRAMES_DIR / "login.png"])
    first = ctx.capture()
    match = ctx.vision.find(first, Target(target.name, target.path, target.spec))
    assert match is not None and match.rect == Rect(*START)
    second = ctx.capture()
    assert ctx.vision.diff(first, first) == 0.0
    assert ctx.vision.diff(first, second) > 0.0
    # 지난 노드 기한은 엔진 앞에서 막는다 (가짜 ctx)
    ctx.clock.advance(10)
    deadline = ctx.deadline(-5)
    from kookabug_sdk.errors import ObservationTimeout

    with pytest.raises(ObservationTimeout):
        ctx.vision.find(first, target, deadline=deadline)


@pytest.mark.usefixtures("ocr_models")
def test_fake_context_default_ocr_reads_sample_frame() -> None:
    ctx = fake_context(frames=[FRAMES_DIR / "world.png"])
    result = ctx.ocr.read(ctx.capture())
    assert "12,345" in str(result.text)


class RecordingStore(FrameStore):
    """스텝이 닫힐 때 그 스텝의 증거 캡처를 남긴다 (등급 승계 확인용)."""

    def __init__(self) -> None:
        super().__init__()
        self.evidence_at_close: dict[str, int | None] = {}

    def close_step(self, step: str, *, parent: str | None = None) -> None:
        self.evidence_at_close[step] = self.evidence(step)
        super().close_step(step, parent=parent)


def test_executor_output_refs_and_subgraph_evidence_to_call_step(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path / "ws")
    sub = "subgraphs/inner.graph.json"
    (
        tk("subgraph", interface=subgraph_interface())
        .entry("n_shot")
        .node("n_shot", "testkit.shot", next={"done": "n_x"})
        .exit("n_x", "done")
        .write(ws, sub)
    )
    g = (
        tk()
        .entry("n_call")
        .node("n_call", "core.graph.call", config={"graph": sub}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    g.write(ws, "tests/t.graph.json")
    program = load_program(ws, "tests/t.graph.json")
    store = RecordingStore()
    result = Executor(
        registry_with_testkit(),
        platform=FakePlatform([FRAMES_DIR / "title.png"], decode=decode_image),
        clock=FakeClock(),
        artifacts=MemoryArtifacts(),
        frames=store,
    ).run(program, ExecOptions(run_id="r1"))
    assert result.verdict == "pass", result.reason
    steps = {e["node"]: e["step"] for e in result.events if e["event"] == "step.start"}
    # 안쪽 캡처(1번)가 호출 스텝이 닫힐 때 그 스텝의 증거였다
    assert store.evidence_at_close[steps["n_shot"]] == 1
    assert store.evidence_at_close[steps["n_call"]] == 1
    # testkit.shot은 image를 출력하므로 출력 참조로 남는다
    assert store.held() == {1}
