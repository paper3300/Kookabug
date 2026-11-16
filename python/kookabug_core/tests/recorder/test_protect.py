"""녹화 상자 도구 검사 — 순수 부분.

UX11 B: 녹화는 비밀값 칸을 가리지 않는다 (`kookabug_platform/tests/test_recorder_protect_crop.py`가
"가리지 않는다"를 본다). UX12: 칸 보호 목록은 지웠다.
"""

from __future__ import annotations

from kookabug_core.recorder.protect import boxes_overlap, sanitize_name


def test_boxes_overlap() -> None:
    assert boxes_overlap((0, 0, 10, 10), (5, 5, 10, 10))
    assert not boxes_overlap((0, 0, 10, 10), (10, 0, 10, 10))  # 맞닿기만


def test_sanitize_name_for_files() -> None:
    assert sanitize_name('a/b:c*?"<>| d') == "a_b_c_d"
    assert sanitize_name("게임 시작") == "게임_시작"
    assert len(sanitize_name("x" * 50)) == 20
    assert sanitize_name("...") == ""
