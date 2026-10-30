"""프레임 저장소: 픽셀 공유·보관 등급·바이트 예산·`frame_expired`·PNG (구현 계획 M1 2.7,
계획 검수 6, 계획 2차 검수 Mid "연속 비교 프레임"·"픽셀 동일성")."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from helpers.graphs import make_workspace
from helpers.run import tk
from testkit import registry_with_testkit

from kookabug_core.engine import ExecOptions, Executor, FakeClock, FakePlatform, MemoryArtifacts
from kookabug_core.loader import load_program
from kookabug_core.record.artifacts import Recorder, StagedFrame
from kookabug_core.record.policy import RecordPolicy
from kookabug_core.workspace import MemorySecrets
from kookabug_platform.errors import FRAME_EXPIRED, PlatformError
from kookabug_platform.frames import (
    MIB,
    STEP_RECENT,
    FrameStore,
    decode_image,
    encode_png,
)
from kookabug_sdk.types import Image

FULL_HD = (1080, 1920, 3)


def pixels(value: int, shape: tuple[int, ...] = (4, 6, 3)) -> np.ndarray:
    return np.full(shape, value % 256, dtype=np.uint8)


def staged(key: object, value: int = 0, shape: tuple[int, ...] = (4, 6, 3)) -> StagedFrame:
    return StagedFrame(key, pixels(value, shape))


def expired(store: FrameStore, capture_id: int) -> PlatformError:
    with pytest.raises(PlatformError) as info, store.pinned(capture_id):
        pass
    assert info.value.code == FRAME_EXPIRED
    return info.value


def test_same_frame_seq_stored_once() -> None:
    store = FrameStore()
    frame = pixels(7)
    # 정지 화면 재사용: 같은 키(같은 WGC 프레임·같은 자르기)를 여러 캡처가 가리킨다
    for capture_id in (1, 2, 3):
        store.register(capture_id, StagedFrame(("wgc", 5, None), frame), f"s{capture_id}")
    assert store.bytes_held == frame.nbytes
    assert store.identity(1) == store.identity(2) == store.identity(3)
    # 같은 seq라도 다른 영역·다른 창(다른 키)은 따로 둔다
    store.register(4, StagedFrame(("wgc", 5, (0, 0, 2, 2)), frame[:2, :2].copy()), "s4")
    store.register(5, StagedFrame(("other", 5, None), frame.copy()), "s5")
    assert store.identity(4) != store.identity(1) != store.identity(5)
    assert store.bytes_held == frame.nbytes * 2 + frame[:2, :2].nbytes
    with store.pinned(1, 3) as (a, b):
        assert a is b


def test_working_pin_released_after_call() -> None:
    store = FrameStore()
    store.register(1, staged("a", 1), "s1")
    with store.pinned(1) as (held,):
        # 작업 중에는 스텝이 닫혀도 남는다
        store.close_step("s1")
        assert not store.is_expired(1)
        assert int(held[0, 0, 0]) == 1
    # 호출이 끝나면 다른 등급이 없으니 바로 버린다
    assert store.is_expired(1)
    assert store.bytes_held == 0
    assert "관측 호출이 끝남" in expired(store, 1).message


def test_step_evidence_keeps_only_last() -> None:
    store = FrameStore()
    for capture_id in range(1, 6):
        store.register(capture_id, staged(capture_id, capture_id), "s1")
    # 증거(마지막) + 연속 비교용 직전 하나만 남는다
    assert store.evidence("s1") == 5
    assert store.held() == {4, 5}
    assert STEP_RECENT == 2
    assert "밀려남" in expired(store, 3).message
    # 연속 두 관측 비교: b를 얻은 뒤에도 a를 쓸 수 있다 (계획 2차 검수 Mid)
    with store.pinned(4, 5) as (a, b):
        assert int(a[0, 0, 0]) == 4 and int(b[0, 0, 0]) == 5
    # 다른 스텝의 캡처는 이 스텝 목록과 무관하다
    store.register(6, staged(6, 6), "s2")
    assert store.held() == {4, 5, 6}
    store.close_step("s1")
    assert store.held() == {6}


def test_close_step_passes_evidence_to_parent_only_if_newer() -> None:
    store = FrameStore()
    store.register(1, staged(1), "parent")
    store.register(2, staged(2), "child")
    store.close_step("child", parent="parent")
    assert store.evidence("parent") == 2
    # 부모가 더 나중에 얻은 증거가 있으면 넘기지 않는다
    store.register(3, staged(3), "child2")
    store.register(4, staged(4), "parent")
    store.close_step("child2", parent="parent")
    assert store.evidence("parent") == 4
    assert store.is_expired(3)


def test_output_refs_capped() -> None:
    store = FrameStore(output_refs=3)
    for capture_id in range(1, 6):
        store.register(capture_id, staged(capture_id, capture_id), f"s{capture_id}")
        store.mark_output(capture_id)
        store.close_step(f"s{capture_id}")
    assert store.held() == {3, 4, 5}
    assert "출력 참조 수" in expired(store, 1).message
    # 다시 출력으로 쓰면 가장 최근으로 옮겨진다
    store.mark_output(3)
    store.register(6, staged(6), "s6")
    store.mark_output(6)
    store.close_step("s6")
    assert store.held() == {5, 3, 6}


def test_budget_evicts_output_refs_oldest_first() -> None:
    one = pixels(0, (64, 64, 3)).nbytes
    store = FrameStore(budget_bytes=one * 3, output_refs=32)
    for capture_id in range(1, 6):
        store.register(capture_id, staged(capture_id, capture_id, (64, 64, 3)), "s")
        store.mark_output(capture_id)
    # 스텝 최근 둘(4, 5)은 예산과 무관하게 지키고, 출력 참조는 오래된 것부터 버린다
    assert store.bytes_held <= one * 3
    assert store.held() == {3, 4, 5}
    assert "예산" in expired(store, 1).message
    assert store.is_expired(2)
    # 1·2등급만으로 예산을 넘어도 그것은 지킨다
    small = FrameStore(budget_bytes=one)
    small.register(1, staged(1, 1, (64, 64, 3)), "a")
    small.register(2, staged(2, 2, (64, 64, 3)), "b")
    assert small.held() == {1, 2}


def test_expired_frame_error() -> None:
    store = FrameStore()
    err = expired(store, 99)
    assert "모르는 캡처" in err.message
    store.register(1, staged(1), "s")
    store.close_step("s")
    for use in (
        lambda: store.encode_png(1),
        lambda: store.identity(1),
        lambda: store.mark_output(1),
    ):
        with pytest.raises(PlatformError) as info:
            use()
        assert info.value.code == FRAME_EXPIRED
    with pytest.raises(ValueError, match="이미 등록"):
        store.register(1, staged(1), "s")


def test_png_encode_roundtrip() -> None:
    rng = np.random.default_rng(1)
    frame = rng.integers(0, 256, (37, 53, 3), dtype=np.uint8)
    store = FrameStore()
    store.register(1, StagedFrame("k", frame), "s")
    data = store.encode_png(1)
    assert data.startswith(b"\x89PNG")
    assert np.array_equal(decode_image(data), frame)
    assert np.array_equal(decode_image(encode_png(frame)), frame)
    with pytest.raises(ValueError, match="읽을 수 없다"):
        decode_image(b"not an image")


def test_view_pixels_copied_so_budget_counts_real_allocation() -> None:
    # 큰 프레임의 작은 뷰(전체 너비 행 슬라이스는 연속 배열이라 복사가 일어나지 않는다)를 넣어도
    # 저장소는 자기 메모리를 가진 복사본만 보관한다 (검수 T4-1 High 2)
    full = np.zeros(FULL_HD, dtype=np.uint8)
    rows = full[10:12]
    assert rows.flags.c_contiguous and rows.base is full
    store = FrameStore(budget_bytes=1 << 20)
    store.register(1, StagedFrame("rows", rows), "s")
    store.register(2, StagedFrame("tiny", full[:1, :1]), "s")
    store.mark_output(1)
    store.mark_output(2)
    store.close_step("s")
    with store.pinned(1, 2) as (a, b):
        assert a.base is None and b.base is None
        assert not a.flags.writeable
        assert a.nbytes + b.nbytes == store.bytes_held <= store.budget_bytes


def test_register_rejects_non_pixel_arrays() -> None:
    store = FrameStore()
    with pytest.raises(TypeError):
        store.register(1, StagedFrame("k", b"bytes"), "s")
    with pytest.raises(TypeError):
        store.register(2, StagedFrame("k", np.zeros((2, 2, 3), dtype=np.float32)), "s")


def test_thousands_of_polls_in_one_step_bounded_and_last_kept() -> None:
    budget = 64 * MIB
    store = FrameStore(budget_bytes=budget)
    recorder = Recorder(MemoryArtifacts(), store)
    recorder.open_step("s1", RecordPolicy())
    base = np.zeros(FULL_HD, dtype=np.uint8)
    last: Image | None = None
    for n in range(1, 3001):
        # 서로 다른 1920x1080 프레임 (폴링마다 화면이 바뀐다)
        frame = base.copy()
        frame[0, :4, 0] = (n & 0xFF, (n >> 8) & 0xFF, 1, 2)
        frame[-1, -1] = n % 251
        last = recorder.captured(
            "s1", Image(width=1920, height=1080, frame=n), StagedFrame(("poll", n), frame)
        )
        assert store.bytes_held <= budget
        if n % 500 == 0:
            store.mark_output(last.capture_id or 0)  # 출력으로 나간 것도 섞는다
    assert last is not None and last.capture_id == 3000
    assert store.peak_bytes <= budget
    assert len(store.held()) <= STEP_RECENT + 6
    # 스텝 끝 증거는 마지막 프레임이고 PNG로 저장된다
    assert store.evidence("s1") == 3000
    path = recorder.error_screenshot("s1")
    assert path is not None and path.endswith("_error.png")
    saved = recorder.store.saved[path]  # type: ignore[attr-defined]
    decoded = decode_image(saved.data)
    assert decoded.shape == FULL_HD
    assert tuple(int(v) for v in decoded[0, :2, 0]) == (3000 & 0xFF, 3000 >> 8)
    recorder.close_step("s1")
    assert store.evidence("s1") is None


# ---------------------------------------------------------------- 가짜 플랫폼 → 저장소


def test_fake_platform_png_frames_go_to_store_and_saved_as_png(tmp_path: Path) -> None:
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    cv2.rectangle(frame, (5, 5), (14, 12), (0, 0, 255), -1)
    png = tmp_path / "frame.png"
    png.write_bytes(encode_png(frame))
    ws = make_workspace(tmp_path / "ws")
    g = (
        tk()
        .entry("n_shot")
        .node("n_shot", "testkit.shot", inputs={"save": True}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    g.write(ws, "tests/t.graph.json")
    program = load_program(ws, "tests/t.graph.json", secrets=MemorySecrets({}))
    store = FrameStore()
    artifacts = MemoryArtifacts()
    executor = Executor(
        registry_with_testkit(),
        platform=FakePlatform([png], decode=decode_image),
        clock=FakeClock(),
        artifacts=artifacts,
        frames=store,
    )
    result = executor.run(program, ExecOptions(run_id="r1"))
    assert result.verdict == "pass", result.reason
    (step,) = [
        e["step"] for e in result.events if e["event"] == "step.start" and e["node"] == "n_shot"
    ]
    (end,) = [e for e in result.events if e["event"] == "step.end" and e["step"] == step]
    saved_path = end["outputs"]["saved"]
    assert saved_path == f"steps/{step}_shot.png"
    assert end["artifacts"] == [saved_path]
    saved = artifacts.saved[saved_path]
    assert saved.data is not None and np.array_equal(decode_image(saved.data), frame)
    # 노드가 받은 이미지는 픽셀 없는 참조 (크기만, 바이트·경로 없음)
    image = end["outputs"]["image"]
    assert (image["width"], image["height"], image["data"], image["path"]) == (30, 20, None, None)
    assert image["capture_id"] == 1
    # 스텝이 닫혀 저장소는 비었다 (출력 참조는 T9가 건다)
    assert store.held() == set()


def test_fake_platform_staged_region_and_identity() -> None:
    frame = np.arange(4 * 5 * 3, dtype=np.uint8).reshape(4, 5, 3)
    platform = FakePlatform([Image(data=encode_png(frame), frame=0)], decode=decode_image)
    from kookabug_sdk.types import Rect

    full, staged_full = platform.capture_staged(None, None)
    _again, staged_again = platform.capture_staged(None, None)
    part, staged_part = platform.capture_staged(None, Rect(1, 1, 2, 3))
    assert (full.width, full.height, full.data, full.path) == (5, 4, None, None)
    assert staged_full.key == staged_again.key != staged_part.key
    assert (part.width, part.height) == (2, 3)
    assert np.array_equal(staged_part.pixels, frame[1:4, 1:3])
    with pytest.raises(RuntimeError, match="decode"):
        FakePlatform([Image(data=b"x")]).capture_staged(None, None)
