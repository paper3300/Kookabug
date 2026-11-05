"""대기 추론 판단 규칙 (M4 계획 2.7, 검수 M2, Q8) — 순수. 픽셀과 함께 보는 검사는
`kookabug_platform/tests/test_recorder_waits.py`."""

from __future__ import annotations

from kookabug_core.recorder.waits import (
    WaitFacts,
    decide_wait,
    delay_ms,
    wait_timeout_ms,
)

MS = 1_000_000


def facts(**kw: object) -> WaitFacts:
    base: dict[str, object] = {
        "prev_t_ns": 0,
        "t_ns": 1200 * MS,
        "changed_ratio": 0.2,
        "last_change_ns": 200 * MS,
        "next_kind": "key",
    }
    base.update(kw)
    return WaitFacts(**base)  # pyright: ignore[reportArgumentType]


def test_no_change_no_wait() -> None:
    assert decide_wait(facts(changed_ratio=0.004)).kind == "none"
    assert decide_wait(facts(r_in_field=True)).kind == "none"  # 칸 클릭 → 입력


def test_change_then_key_waits_for_target() -> None:
    d = decide_wait(facts(wait_target=True))
    assert d.kind == "image_wait" and d.timeout_ms == 10_000 and d.needs_review == ()


def test_click_target_appearing_needs_no_wait_node() -> None:
    d = decide_wait(facts(next_kind="click", click_target_in_a=False, wait_target=True))
    assert d.kind == "none"
    d = decide_wait(facts(next_kind="click", click_target_in_a=True, wait_target=True))
    assert d.kind == "image_wait"


def test_unresolvable_region_falls_back_delay_needs_review() -> None:
    d = decide_wait(facts(wait_target=False, last_change_ns=800 * MS))
    assert d.kind == "delay" and d.ms == 1200 and d.needs_review == ("wait_target_unknown",)
    assert decide_wait(facts(last_change_ns=100 * MS)).ms == 500  # 하한


def test_option_off_emits_delay() -> None:
    d = decide_wait(facts(option_on=False, wait_target=True))
    assert d.kind == "delay" and d.ms == 1200 and d.needs_review == ()


def test_timeout_clamp() -> None:
    assert wait_timeout_ms(0, 1000 * MS, 800 * MS) == 10_000
    assert wait_timeout_ms(0, 9000 * MS, 8000 * MS) == 24_000
    assert wait_timeout_ms(0, 90_000 * MS, None) == 120_000
    assert delay_ms(0, 3000 * MS, None) == 4500
