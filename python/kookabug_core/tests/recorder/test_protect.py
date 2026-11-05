"""보호 영역 공용 검사 (M4 계획 2.6 "비밀값 보호 영역", 검수 M6, T6) — 순수 부분.

자르기·넓히기·대기 자르기와 맞물린 검사는 `kookabug_platform/tests/test_recorder_protect_crop.py`.
"""

from __future__ import annotations

import pytest

from kookabug_core.recorder.fields import SecretText
from kookabug_core.recorder.protect import (
    ProtectionSet,
    SecretRegionOverlap,
    safe_name,
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


def test_ocr_name_not_containing_secret() -> None:
    secret = SecretText("hunter22")
    assert safe_name("로그인", [secret], "click_3") == "로그인"
    assert safe_name("pw hunter22!", [secret], "click_3") == "click_3"
    assert safe_name("HUNTER22", [secret], "click_3") == "click_3"  # 대소문자 무시
    assert safe_name("hunter", [secret], "click_3") == "click_3"  # 원문 일부도 버림
    assert safe_name(None, [secret], "click_3") == "click_3"
    assert safe_name("  ", [secret], "click_3") == "click_3"


def test_one_char_secret_name_falls_back() -> None:
    # review_B2_1 H2: 한 글자 비밀값도 이름·제목에 들어가지 않는다 (길이 예외 없음)
    from kookabug_core.recorder.build import click_drafts

    secret = SecretText("Q")
    name = safe_name("Q", [secret], "click_2")
    assert name == "click_2"
    assert safe_name("Quit", [secret], "click_2") == "click_2"  # 짧은 값 때문에 대체 — 감수
    assert '"Q"' not in click_drafts(f"targets/{name}.target.json", name)[0].title
    assert safe_name("로그인", [secret], "click_2") == "로그인"


def test_sanitize_name_for_files() -> None:
    assert sanitize_name('a/b:c*?"<>| d') == "a_b_c_d"
    assert sanitize_name("게임 시작") == "게임_시작"
    assert len(sanitize_name("x" * 50)) == 20
    assert sanitize_name("...") == ""
