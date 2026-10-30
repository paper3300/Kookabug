"""창 수명 추적기의 바인딩 판정 (구현 계획 M1 2.2, 계획 검수 7). 이벤트는 직접 넣는다."""

from __future__ import annotations

import pytest

from kb_testing.fake_win32 import FakeWindowApi
from kookabug_platform.errors import WINDOW_GONE, PlatformError
from kookabug_platform.tracker import WindowTracker

HWND = 0x1234
PID = 77


@pytest.fixture
def api() -> FakeWindowApi:
    fake = FakeWindowApi()
    fake.add(HWND, PID, title="Game")
    return fake


def gone(tracker: WindowTracker, binding: object) -> PlatformError:
    with pytest.raises(PlatformError) as info:
        tracker.check(binding)  # type: ignore[arg-type]
    assert info.value.code == WINDOW_GONE
    return info.value


def test_destroy_event_kills_binding_and_same_hwnd_new_window_is_gone(api: FakeWindowApi) -> None:
    tracker = WindowTracker(api)
    old = tracker.bind(HWND)
    tracker.check(old)
    before = tracker.generation
    # 창이 파괴되고, 같은 프로세스(같은 PID·생성 시각)가 같은 hwnd 값으로 새 창을 만들었다
    tracker.notify_destroyed(HWND)
    api.destroy(HWND)
    api.add(HWND, PID, title="Game")
    assert tracker.generation == before + 1
    # IsWindow·PID·생성 시각은 모두 맞지만 옛 바인딩은 죽었다
    err = gone(tracker, old)
    assert "파괴 이벤트" in err.message
    assert not tracker.is_alive(old)
    # 같은 바인딩 ID로 다시 풀어도 옛 창으로 쓰지 않는다
    with pytest.raises(PlatformError):
        tracker.resolve(HWND, pid=PID, process_created=old.process_created, binding=old.binding_id)
    # 새 창은 새 바인딩을 따로 만든다
    new = tracker.bind(HWND)
    assert new.binding_id != old.binding_id
    tracker.check(new)
    # 다른 hwnd의 파괴 이벤트는 바인딩에 영향 없음
    tracker.notify_destroyed(HWND + 1)
    tracker.check(new)


def test_wgc_closed_marks_dead(api: FakeWindowApi) -> None:
    tracker = WindowTracker(api)
    first, second = tracker.bind(HWND), tracker.bind(HWND)
    before = tracker.generation
    tracker.notify_capture_closed(first.binding_id)
    assert tracker.generation == before + 1
    err = gone(tracker, first)
    assert "on_closed" in err.message
    # 그 바인딩만 죽는다 (같은 창의 다른 바인딩은 그대로)
    tracker.check(second)
    tracker.notify_capture_closed(first.binding_id)  # 두 번 와도 그대로
    assert tracker.generation == before + 1


def test_binding_created_on_first_use_of_unbound_ref(api: FakeWindowApi) -> None:
    tracker = WindowTracker(api)
    created = api.process_created(PID)
    assert created is not None
    # 바인딩 없는 참조(다른 실행·플러그인이 만든 것) → 처음 쓸 때 만든다
    first = tracker.resolve(HWND, pid=PID, process_created=created)
    assert (first.hwnd, first.pid, first.process_created) == (HWND, PID, created)
    # 같은 참조를 다시 쓰면 같은 바인딩
    assert tracker.resolve(HWND, pid=PID, process_created=created) == first
    # 이 실행이 모르는 바인딩 ID(다른 실행)도 바인딩 없는 참조로 본다
    assert tracker.resolve(HWND, pid=PID, process_created=created, binding="w999") == first
    # 그사이 창이 닫혔다가 같은 값으로 다시 생겼으면 그 참조는 window_gone
    tracker.notify_destroyed(HWND)
    with pytest.raises(PlatformError) as info:
        tracker.resolve(HWND, pid=PID, process_created=created)
    assert info.value.code == WINDOW_GONE


def test_ref_of_other_process_is_gone(api: FakeWindowApi) -> None:
    tracker = WindowTracker(api)
    # 참조한 PID·생성 시각과 지금 그 hwnd의 프로세스가 다르다 (hwnd 재사용)
    for pid, created in ((PID + 1, 0), (PID, 5)):
        with pytest.raises(PlatformError) as info:
            tracker.resolve(HWND, pid=pid, process_created=created)
        assert info.value.code == WINDOW_GONE


def test_known_binding_id_from_other_run_validates_identity(api: FakeWindowApi) -> None:
    # 이전 실행이 (hwnd, PID 77, w1)을 남겼다. 이번 실행에서 같은 hwnd를 PID 88이 재사용하고
    # 이번 추적기도 그 창에 w1을 붙였다 (run_id 없이 번호가 겹친 경우)
    old = WindowTracker(api).bind(HWND)
    api.destroy(HWND)
    api.add(HWND, PID + 11)
    current_tracker = WindowTracker(api)
    current = current_tracker.bind(HWND)
    assert current.binding_id == old.binding_id == "w1" and current.pid != old.pid
    for binding in ("foreign", old.binding_id):  # 모르는 ID와 겹친 ID 모두 거부
        with pytest.raises(PlatformError) as info:
            current_tracker.resolve(
                HWND, pid=old.pid, process_created=old.process_created, binding=binding
            )
        assert info.value.code == WINDOW_GONE
    # 생성 시각만 달라도 거부, 식별이 맞는 참조·식별 없는 참조는 그 바인딩
    with pytest.raises(PlatformError):
        current_tracker.resolve(HWND, pid=current.pid, process_created=1, binding="w1")
    ok = current_tracker.resolve(
        HWND, pid=current.pid, process_created=current.process_created, binding="w1"
    )
    assert ok == current and current_tracker.resolve(HWND, binding="w1") == current


def test_run_id_makes_binding_ids_unique_across_runs(api: FakeWindowApi) -> None:
    first = WindowTracker(api, run_id="r1").bind(HWND)
    second_tracker = WindowTracker(api, run_id="r2")
    second = second_tracker.bind(HWND)
    assert (first.binding_id, second.binding_id) == ("r1.w1", "r2.w1")
    # 다른 실행의 ID는 이 실행에서 모르는 ID: 참조 단위로 새 바인딩을 만든다
    made = second_tracker.resolve(
        HWND, pid=first.pid, process_created=first.process_created, binding=first.binding_id
    )
    assert made.binding_id.startswith("r2.") and made.hwnd == HWND


def test_check_detects_closed_or_reused_without_event(api: FakeWindowApi) -> None:
    # 이벤트가 아직 안 왔어도(보장 범위 밖 틈) IsWindow·PID·생성 시각으로 잡히는 경우
    tracker = WindowTracker(api)
    binding = tracker.bind(HWND)
    api.destroy(HWND)
    assert "IsWindow" in gone(tracker, binding).message
    binding = tracker.bind(api.add(0x2000, PID))
    api.windows[0x2000].pid = PID + 5
    assert "다른 프로세스" in gone(tracker, binding).message
    binding = tracker.bind(api.add(0x3000, PID))
    api.created[PID] = 1
    assert "생성 시각" in gone(tracker, binding).message


def test_death_listener_called_once_per_binding_outside_lock(api: FakeWindowApi) -> None:
    # 캡처 서비스가 죽은 바인딩의 세션 픽셀을 놓는 데 쓴다 (T4 검수 Mid 3)
    tracker = WindowTracker(api)
    heard: list[str] = []

    def listener(binding_id: str) -> None:
        tracker.get(binding_id)  # 잠금 밖에서 불리므로 추적기를 다시 불러도 막히지 않는다
        heard.append(binding_id)

    tracker.on_death(listener)
    a, b = tracker.bind(HWND), tracker.bind(HWND)
    tracker.notify_destroyed(HWND)
    assert sorted(heard) == sorted([a.binding_id, b.binding_id])
    c = tracker.bind(api.add(0x2000, PID))
    tracker.notify_capture_closed(c.binding_id)
    tracker.notify_capture_closed(c.binding_id)  # 두 번째는 이미 죽어 알리지 않는다
    d = tracker.bind(api.add(0x3000, PID))
    api.destroy(0x3000)
    gone(tracker, d)
    gone(tracker, d)
    assert heard[2:] == [c.binding_id, d.binding_id]


def test_bind_missing_window_is_gone(api: FakeWindowApi) -> None:
    tracker = WindowTracker(api)
    with pytest.raises(PlatformError) as info:
        tracker.bind(0x9999)
    assert info.value.code == WINDOW_GONE
