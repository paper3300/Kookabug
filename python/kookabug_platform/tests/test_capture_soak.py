"""캡처 장시간 안정성 (구현 계획 M1 2.3 `soak`, 계획 검수 13). `KOOKABUG_SOAK=1`일 때만.

세션 열고 닫기 200회, 크기 변경 500회, 캡처 10,000회(정지·변화 섞음). 시작 대비 끝에서 핸들 수
증가 50 이하, 스레드 수 증가 2 이하, 개인 바이트 증가 64 MiB 이하, 모든 세션이 끝났고 끝난 뒤
콜백이 없어야 한다. 정지 화면 캡처 수가 많아 새 프레임 대기(`fresh_wait_ms`)를 10 ms로 줄인다 —
재사용 경로는 그대로 돈다.

예외 하나: WGC 세션을 열 때마다 `ALPC Port` 핸들이 하나씩 남는다. windows-capture 2.0.1만으로
세션을 열고 닫아도, 같은 스레드에서 열어도 같다(T4 보고서) — 우리 코드가 막을 수 없다. 그래서
`ALPC Port`는 "세션 하나에 하나 이하"로 따로 보고, 나머지 핸들 증가에 상한 50을 건다.
"""

from __future__ import annotations

import gc
import json
import time
import uuid
from itertools import cycle
from pathlib import Path

import pytest

from kb_testing import resources
from kb_testing.sample_game import launch_sample_game
from kookabug_platform.capture import CaptureService
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.tracker import WindowTracker
from kookabug_platform.windows import set_client_size

pytestmark = pytest.mark.soak

SESSIONS, RESIZES, CAPTURES = 200, 500, 10_000
MAX_HANDLES, MAX_THREADS, MAX_PRIVATE = 50, 2, 64 << 20
SIZES = [(800, 500), (1024, 640), (900, 560), (960, 600)]


@pytest.mark.timeout(1200)
def test_capture_long_run_resources_bounded(tmp_path: Path) -> None:
    title = f"KBT4 soak {uuid.uuid4().hex[:8]}"
    with launch_sample_game(("--title", title), workdir=tmp_path) as game:
        tracker = WindowTracker(run_id="soak").start()
        service = CaptureService(tracker, fresh_wait_ms=10)
        try:
            binding = tracker.bind(game.hwnd)

            def capture() -> tuple[int, int]:
                return service.capture(binding, deadline=ObservationDeadline(2000)).size

            # 처음 한 번만 생기는 것(WGC 장치·cv2·스레드 풀)을 기준에 넣는다
            for size in SIZES:
                assert set_client_size(game.hwnd, *size)
                assert capture() == size
                service.close(binding.binding_id)
                capture()
            gc.collect()
            base = resources.sample()
            base_handles = resources.open_handles()
            base_sessions = service.sessions_started
            started_at = time.monotonic()

            sizes = cycle(SIZES)
            current = SIZES[-1]
            counts = {"sessions": 0, "resizes": 0, "captures": 0, "reused": 0}
            for i in range(CAPTURES):
                if i % 20 == 10:
                    current = next(sizes)
                    assert set_client_size(game.hwnd, *current)
                    counts["resizes"] += 1
                if i % 50 == 0:
                    assert service.close(binding.binding_id)
                    counts["sessions"] += 1
                shot = service.capture(binding, deadline=ObservationDeadline(2000))
                assert shot.size == current, (i, shot.size, current)
                counts["captures"] += 1
                counts["reused"] += shot.info.reused
            elapsed = time.monotonic() - started_at

            assert service.close_all(), "세션이 끝나지 않았다"
            assert service.all_finished()
            callbacks = service.callbacks()
            time.sleep(0.5)
            assert service.callbacks() == callbacks, "닫은 뒤에도 콜백이 왔다"
        finally:
            service.close_all()
            tracker.stop()
        gc.collect()
        grown = resources.sample() - base
        kinds = resources.new_handle_types(base_handles)
    opened = service.sessions_started - base_sessions
    alpc = kinds.pop("ALPC Port", 0)
    other_handles = grown.handles - alpc

    assert counts == {
        "sessions": SESSIONS,
        "resizes": RESIZES,
        "captures": CAPTURES,
        "reused": counts["reused"],
    }
    report = {
        **counts,
        "seconds": round(elapsed, 1),
        "handles": grown.handles,
        "handles_alpc": alpc,
        "handles_other": other_handles,
        "new_handle_kinds": kinds,
        "threads": grown.threads,
        "private_mib": round(grown.private_bytes / (1 << 20), 1),
        "sessions_opened": opened,
    }
    print(f"\nSOAK {json.dumps(report, ensure_ascii=False)}")
    # 정지·변화가 둘 다 섞였다
    assert 0 < counts["reused"] < CAPTURES
    assert alpc <= opened, report
    assert other_handles <= MAX_HANDLES, report
    assert grown.threads <= MAX_THREADS, report
    assert grown.private_bytes <= MAX_PRIVATE, report
