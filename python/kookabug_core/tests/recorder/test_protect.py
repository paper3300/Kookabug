"""칸 상자 목록 `ProtectionSet` 공용 검사 (M4 계획 2.6) — 순수 부분.

UX11 B: 녹화는 이 목록으로 비밀값 칸을 가리지 않는다 (`kookabug_platform/tests/
test_recorder_protect_crop.py`가 "가리지 않는다"를 본다). 이름도 원문을 걸러 내지 않는다.
"""

from __future__ import annotations

import pytest

from kookabug_core.recorder.protect import (
    ProtectionSet,
    SecretRegionOverlap,
    sanitize_name,
)

PW = (400, 285, 320, 50)
MS = 1_000_000


def protected() -> ProtectionSet:
    p = ProtectionSet()
    p.add(7, PW, 1000 * MS)
    return p


def test_manual_region_overlap_rejected() -> None:
    p = protected()
    with pytest.raises(SecretRegionOverlap) as caught:
        p.require_clear((380, 300, 100, 100), 2000 * MS)
    assert caught.value.spans == (7,) and caught.value.code == "secret_region_overlap"
    p.require_clear((380, 300, 100, 100), 500 * MS)  # 구간 시작 전 프레임은 보호 밖
    p.require_clear((0, 0, 100, 100), 2000 * MS)  # 겹치지 않음
    with pytest.raises(SecretRegionOverlap):
        p.require_clear((380, 300, 100, 100), None)  # 시각 모름 = 보수적


def test_ended_protection_judged_per_frame() -> None:
    # 끝난 보호도 목록에 남고, 자를 그 프레임에서 칸이 없다는 근거가 있을 때만 겹침을 허용한다
    box = (380, 300, 100, 100)
    p = protected()
    p.end(7, 5000 * MS)
    with pytest.raises(SecretRegionOverlap):
        p.require_clear(box, 6000 * MS, "frame")  # 판정기 없음 = 보호
    seen: list[tuple[int, object]] = []

    def absent_in(span: int, region: tuple[int, int, int, int], frame: object) -> bool:
        seen.append((span, frame))
        assert region == PW
        return frame == "gone"

    p.absent_in = absent_in
    p.require_clear(box, 6000 * MS, "gone")  # 그 프레임에 칸이 없음
    for frame in ("partial", None):  # 일부 가림·프레임 모름 = 보호
        with pytest.raises(SecretRegionOverlap):
            p.require_clear(box, 6000 * MS, frame)
    assert p.avoid(box, (430, 320), 6000 * MS, frame="gone") == box
    assert p.avoid(box, (430, 320), 6000 * MS, frame="partial") is None  # 점이 칸 안
    shrunk = p.avoid(box, (430, 350), 6000 * MS, frame="partial")  # 점이 칸 아래: 줄임
    assert shrunk is not None and not p.overlaps(shrunk, 6000 * MS, "partial")
    assert (7, "gone") in seen

    def broken(span: int, region: tuple[int, int, int, int], frame: object) -> bool:
        raise RuntimeError("판정 실패")

    p.absent_in = broken
    assert p.overlaps(box, 6000 * MS, "gone")  # 판정 불가 = 보호
    # 진행 중인 보호는 판정기와 무관하게 늘 보호
    q = protected()
    q.absent_in = absent_in
    assert q.overlaps(box, 6000 * MS, "gone")


def test_released_span_is_not_protected_until_marked_again() -> None:
    p = protected()
    p.release(7)
    assert not p.overlaps(PW, 2000 * MS)
    p.protect_again(7)
    assert p.overlaps(PW, 2000 * MS)


def test_avoid_shrinks_keeps_point_or_gives_up() -> None:
    p = protected()
    box = (380, 200, 400, 140)  # 계정 칸 + 비밀번호 칸을 덮는 상자
    safe = p.avoid(box, (560, 230), 2000 * MS)
    assert safe is not None and not p.overlaps(safe, 2000 * MS)
    assert safe[0] <= 560 < safe[0] + safe[2] and safe[1] <= 230 < safe[1] + safe[3]
    assert p.avoid(box, (560, 310), 2000 * MS) is None  # 점이 비밀 칸 안
    assert p.avoid((380, 200, 400, 90), (560, 230), 2000 * MS, min_size=(16, 120)) is None


def test_sanitize_name_for_files() -> None:
    assert sanitize_name('a/b:c*?"<>| d') == "a_b_c_d"
    assert sanitize_name("게임 시작") == "게임_시작"
    assert len(sanitize_name("x" * 50)) == 20
    assert sanitize_name("...") == ""
