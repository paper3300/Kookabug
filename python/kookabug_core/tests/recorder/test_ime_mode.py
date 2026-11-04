"""키의 IME 모드 정하기 (순수, M4 계획 2.1 "IME 모드 표본", 2차 검수 N2·3차 N6)."""

from __future__ import annotations

from typing import Any

from kookabug_core.recorder.contract import obs_usable
from kookabug_core.recorder.ime import ime_changes, ime_mode_at

MS = 1_000_000
VK_A, VK_HANGUL = 0x41, 0x15


def sample(
    at_ms: float,
    mode: str = "native",
    *,
    status: str = "ok",
    started_ms: float | None = None,
    fg: int | None = 1001,
    hkl: str | None = "4120412",
) -> dict[str, Any]:
    at = int(at_ms * MS)
    return {
        "query_started_ns": at if started_ms is None else int(started_ms * MS),
        "sampled_at_ns": at,
        "fg": fg,
        "fg_thread": None if fg is None else fg + 10_000,
        "hkl": hkl,
        "status": status,
        "trigger": "periodic",
        "mode": mode if status == "ok" else "unknown",
    }


def key_up(at_ms: float, vk: int = VK_A) -> dict[str, Any]:
    return {"kind": "key_up", "vk": vk, "t_ns": int(at_ms * MS)}


def obs(at_ms: float, fg: int | None = 1001, hkl: str | None = "4120412") -> dict[str, Any]:
    return {"obs_at_ns": int(at_ms * MS), "fg": fg, "hkl": hkl}


def mode(t_ms: float, samples: list[dict[str, Any]], changes: Any = ()) -> str | None:
    return ime_mode_at(int(t_ms * MS), samples, list(changes))


def test_fast_typing_stable_mode_determined() -> None:
    # 0·40·80 ms 키, 표본 하나(키 앞) → 셋 다 정해진다
    for value in ("native", "alphanumeric"):
        samples = [sample(-20, value)]
        assert [mode(t, samples) for t in (0, 40, 80)] == [value, value, value]
    # 표본이 키 뒤에만 있어도 (첫 키 직후 표본)
    samples = [sample(90, "native")]
    assert [mode(t, samples) for t in (0, 40, 80)] == ["native"] * 3


def test_toggle_mid_typing_both_sides_determined() -> None:
    # 영문 표본 → 키 둘 → 한/영 키 뗌(100 ms) → 30 ms 뒤 한글 표본 → 키 둘
    samples = [sample(0, "alphanumeric"), sample(130, "native"), sample(250, "native")]
    events = [key_up(30), key_up(60), key_up(100, VK_HANGUL), key_up(160), key_up(200)]
    changes = ime_changes(events, samples=samples)
    assert changes == [(100 * MS, 100 * MS)]
    # 전환 키 앞 키는 앞 표본, 뒤 키는 뒤 표본
    assert [mode(t, samples, changes) for t in (30, 60)] == ["alphanumeric"] * 2
    assert mode(95, samples, changes) == "alphanumeric"  # 전환 키 자신의 누름
    assert [mode(t, samples, changes) for t in (160, 200)] == ["native"] * 2


def test_mode_changed_without_key_is_undetermined() -> None:
    # 앞뒤 표본이 어긋나는데 사이 변화가 기록되지 않음 (마우스로 IME 표시줄 클릭 등)
    samples = [sample(0, "native"), sample(200, "alphanumeric")]
    assert mode(100, samples) is None
    # 한쪽만 있으면 그 모드
    assert mode(100, [sample(0, "native")]) == "native"
    assert mode(100, []) is None


def test_sample_older_than_300ms_not_used() -> None:
    samples = [sample(0, "native")]
    assert mode(300, samples) == "native"  # 경계 포함
    assert mode(301, samples) is None
    assert mode(-301, samples) is None  # 300 ms 넘게 뒤의 표본도 쓰지 않는다
    assert mode(-300, samples) == "native"


def test_fg_or_hkl_change_between_invalidates_sample() -> None:
    samples = [sample(0, "native")]
    # 표본 뒤 키 전에 포그라운드가 바뀜 → 그 표본은 쓰지 않는다
    changes = ime_changes([], obs=[obs(10), obs(50, fg=1002)])
    # 바뀐 때는 앞 관측(10 ms) ~ 바뀐 것을 본 관측(50 ms) 사이 어딘가
    assert changes == [(10 * MS, 50 * MS)]
    assert mode(100, samples, changes) is None
    assert mode(40, samples, changes) is None  # 40 ms에 이미 바뀌었을 수 있다
    assert mode(5, samples, changes) == "native"
    # 자판(hkl)이 바뀜
    changes = ime_changes([], obs=[obs(10), obs(50, hkl="4090409")])
    assert mode(100, samples, changes) is None
    # 이웃한 표본의 fg·hkl이 다르면 그 사이 어딘가에서 바뀌었다 (구간)
    two = [sample(0, "native"), sample(200, "native", fg=1002)]
    changes = ime_changes([], samples=two)
    assert changes == [(0, 200 * MS - 1)]  # 뒤 표본 조회 시작 전
    assert mode(100, two, changes) is None
    # 정상 표본이라도 자기 조회 구간 안에 변화가 있으면 쓰지 않는다
    slow = [sample(60, "native", started_ms=40)]
    assert mode(100, slow, [(50 * MS, 50 * MS)]) is None


def test_delayed_observation_does_not_reuse_old_window_mode() -> None:
    """검수 T3-1 지적 3: 창·자판이 35 ms에 바뀌고 40 ms 키의 관측이 50 ms에 늦게 왔다."""
    samples = [sample(25, "alphanumeric", started_ms=20, fg=1001, hkl="409")]
    observations = [
        {**obs(10, fg=1001, hkl="409"), "cause_event_id": 1, "table_changed_ns": 0},
        {**obs(50, fg=1002, hkl="412"), "cause_event_id": 2, "table_changed_ns": 35 * MS},
    ]
    key = {"event_id": 2, "t_ns": 40 * MS, "kind": "key_down", "vk": VK_A}
    assert obs_usable(key, observations[1])  # 관측 자체는 쓸 수 있다 (10 ms 뒤, 표 갱신은 앞)
    changes = ime_changes([key], observations, samples)
    assert changes == [(10 * MS, 50 * MS)]
    assert ime_mode_at(40 * MS, samples, changes) is None
    # 변화 구간을 몰라도, 키 관측의 창·자판과 다른 표본은 쓰지 않는다
    assert ime_mode_at(40 * MS, samples, key_obs=observations[1]) is None
    assert ime_mode_at(40 * MS, samples, key_obs=observations[0]) == "alphanumeric"
    # 새 창 B의 표본이 생기면 바뀐 것을 본 뒤의 키는 정해진다 (40 ms 키는 여전히 판정 불가)
    b = sample(60, "native", started_ms=55, fg=1002, hkl="412")
    changes = ime_changes([key], observations, [*samples, b])
    b_obs = {**obs(85, fg=1002, hkl="412"), "cause_event_id": 3, "table_changed_ns": 35 * MS}
    assert ime_mode_at(80 * MS, [*samples, b], changes, key_obs=b_obs) == "native"
    assert ime_mode_at(40 * MS, [*samples, b], changes, key_obs=observations[1]) is None


def test_failed_sample_overlapping_window_is_undetermined() -> None:
    """3차 N6 대비: 앞 정상 표본이 유효해도, 그 뒤 조회가 실패하면 판정 불가."""
    ok = sample(0, "native")
    assert mode(100, [ok]) == "native"
    failed = sample(130, status="timeout", started_ms=80)
    assert mode(100, [ok, failed]) is None
    # 조회 구간이 (앞 표본, 키+300 ms) 밖이면 상관없다
    late = sample(500, status="timeout", started_ms=450)
    assert mode(100, [ok, late]) == "native"
    early = sample(-10, status="failed", started_ms=-60)  # 앞 표본보다 먼저 끝남
    assert mode(100, [ok, early]) == "native"
    # 뒤 정상 표본이 있으면 구간은 (앞, 뒤) — 그 뒤 실패는 상관없다
    after = sample(150, "native")
    assert mode(100, [ok, after, sample(400, status="timeout", started_ms=350)]) == "native"
    # 표본 없이 실패만 있어도 판정 불가
    assert mode(100, [failed]) is None
    # IME가 없는 창(no_ime)도 정상 표본이 아니다
    assert mode(100, [sample(50, status="no_ime")]) is None
