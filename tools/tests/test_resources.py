"""프로세스 자원 측정 헬퍼 (kb_testing.resources)."""

import threading

from kb_testing import resources
from kookabug_core.win import WinEvent


def test_sample_current_process() -> None:
    s = resources.sample()
    assert s.handles > 0
    assert s.threads >= 1
    assert s.private_bytes > 0


def test_sample_tracks_threads_handles_and_private_bytes() -> None:
    before = resources.sample()
    stop = threading.Event()
    threads = [threading.Thread(target=stop.wait) for _ in range(3)]
    for t in threads:
        t.start()
    events = [WinEvent.create() for _ in range(20)]
    block = bytearray(64 * 1024 * 1024)
    try:
        delta = resources.sample() - before
        assert delta.threads >= 3
        assert delta.handles >= 20
        assert delta.private_bytes >= 48 * 1024 * 1024
    finally:
        stop.set()
        for t in threads:
            t.join()
        for e in events:
            e.close()
        del block


def test_new_handle_types_counts_by_kind() -> None:
    before = resources.open_handles()
    assert before and all(h > 0 for h in before)
    events = [WinEvent.create() for _ in range(5)]
    try:
        kinds = resources.new_handle_types(before)
        assert kinds.get("Event", 0) >= 5
    finally:
        for e in events:
            e.close()
    assert resources.new_handle_types(before).get("Event", 0) < 5
