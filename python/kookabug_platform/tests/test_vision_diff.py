"""프레임 비교 `vision.diff` (구현 계획 M1 2.5, 계획 검수 3, 2차 검수 N3).

실제 프레임 저장소(`FrameStore`)에 예제 게임 화면 PNG를 캡처처럼 등록해 본다. 픽셀 동일성 키는
캡처 서비스와 같은 모양 `(백엔드, frame_seq, 자르기, 영역)`을 쓴다.
"""

from __future__ import annotations

from collections.abc import Hashable

import numpy as np
import pytest

from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.record.artifacts import StagedFrame
from kookabug_platform import vision as vision_module
from kookabug_platform.errors import FRAME_EXPIRED, PlatformError
from kookabug_platform.frames import FrameStore, decode_image
from kookabug_platform.vision import Pixels, Vision, diff_pixels
from kookabug_sdk.types import Rect


def frame(name: str) -> Pixels:
    return decode_image((FRAMES_DIR / f"{name}.png").read_bytes())


def key(seq: int, crop: tuple[int, int, int, int] = (0, 0, 1024, 640)) -> Hashable:
    return ("wgc", seq, crop, None)


def register(store: FrameStore, capture_id: int, pixels: Pixels, k: Hashable, step: str) -> int:
    store.register(capture_id, StagedFrame(k, pixels), step)
    return capture_id


def test_same_content_different_capture_ids_diff_zero() -> None:
    # 픽셀은 같지만 다른 프레임(다른 키): 계산해서 0
    store = FrameStore()
    lobby = frame("lobby")
    a = register(store, 1, lobby, key(10), "s1")
    b = register(store, 2, lobby.copy(), key(11), "s1")
    assert store.identity(a) != store.identity(b)
    assert Vision(store).diff(a, b) == 0.0


def test_same_frame_seq_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FrameStore()
    lobby = frame("lobby")
    # 정지 화면 재사용: 두 캡처가 같은 픽셀(같은 키)을 가리킨다 → 계산 없이 0
    a = register(store, 1, lobby, key(10), "s1")
    b = register(store, 2, lobby, key(10), "s1")
    calls: list[int] = []

    def counting(*args: object, **kwargs: object) -> float:
        calls.append(1)
        return diff_pixels(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(vision_module, "diff_pixels", counting)
    assert Vision(store).diff(a, b) == 0.0
    assert calls == []
    # frame_seq만 같고 자르기가 다르면 같은 픽셀이 아니다 (N3): 계산한다
    left = np.ascontiguousarray(lobby[:, :512])
    right = np.ascontiguousarray(lobby[:, 512:])
    c = register(store, 3, left, key(20, (0, 0, 512, 640)), "s2")
    d = register(store, 4, right, key(20, (512, 0, 512, 640)), "s2")
    assert Vision(store).diff(c, d) > 0.0
    assert calls == [1]


def test_changed_content_same_size_positive() -> None:
    store = FrameStore()
    a = register(store, 1, frame("lobby"), key(1), "s1")
    b = register(store, 2, frame("lobby_server1"), key(2), "s1")  # 서버 하나를 고른 화면
    value = Vision(store).diff(a, b)
    assert 0.0 < value < 0.1
    c = register(store, 3, frame("title"), key(3), "s2")
    d = register(store, 4, frame("world"), key(4), "s2")
    assert Vision(store).diff(c, d) > value
    assert Vision(store).diff(a, b) == Vision(store).diff(b, a)


def test_different_size_is_one() -> None:
    store = FrameStore()
    lobby = frame("lobby")
    a = register(store, 1, lobby, key(1), "s1")
    b = register(store, 2, np.ascontiguousarray(lobby[:600]), key(2, (0, 0, 1024, 600)), "s1")
    assert Vision(store).diff(a, b) == 1.0


def test_region_diff() -> None:
    lobby, picked = frame("lobby"), frame("lobby_server1")
    changed = np.argwhere(np.any(lobby != picked, axis=2))
    (y0, x0), (y1, x1) = changed.min(axis=0), changed.max(axis=0)
    store = FrameStore()
    a = register(store, 1, lobby, key(1), "s1")
    b = register(store, 2, picked, key(2), "s1")
    vision = Vision(store)
    whole = vision.diff(a, b)
    inside = vision.diff(a, b, region=Rect(int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1)))
    assert inside > whole > 0.0
    # 바뀐 곳 밖(위쪽 제목줄)은 0
    assert vision.diff(a, b, region=(0, 0, 1024, int(y0))) == 0.0
    # 이미지 밖으로 나간 부분은 잘라 본다, 전부 밖이면 비교할 픽셀이 없어 1 (같다고 보지 않는다)
    assert vision.diff(a, b, region=(-100, -100, 2000, 2000)) == pytest.approx(whole)
    assert vision.diff(a, b, region=(5000, 0, 10, 10)) == 1.0


def test_expired_frame_error() -> None:
    store = FrameStore()
    lobby = frame("lobby")
    a = register(store, 1, lobby, key(1), "s1")
    register(store, 2, frame("lobby_server1"), key(2), "s1")
    c = register(store, 3, frame("lobby_server2"), key(3), "s1")  # 스텝 최근 2개 → 1은 버려짐
    assert store.is_expired(a)
    with pytest.raises(PlatformError) as caught:
        Vision(store).diff(a, c)
    assert caught.value.code == FRAME_EXPIRED
    # 같은 키를 가리켰더라도 버린 캡처는 0으로 단축하지 않고 frame_expired
    d = register(store, 4, lobby, key(1), "s2")
    with pytest.raises(PlatformError) as caught:
        Vision(store).diff(a, d)
    assert caught.value.code == FRAME_EXPIRED
    # 비교가 끝나면 작업 중 고정은 풀린다
    assert Vision(store).diff(c, d) > 0.0
    assert store.held() == {2, 3, 4}
