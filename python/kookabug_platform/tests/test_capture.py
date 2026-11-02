"""WGC 캡처 실제 검사 (구현 계획 M1 2.3, 예제 게임·대화형 데스크톱).

입력은 보내지 않는다 — 화면 변화는 게임의 로딩 타이머·창 크기 바꾸기로 만든다. 콜백을 막거나
망가뜨리는 검사는 실제 WGC 백엔드를 감싼 `Gate`로 한다. 정답 픽셀은 제품 코드와 독립인
`capture_client`로 구한다.
"""

from __future__ import annotations

import ctypes
import hashlib
import threading
import time
import uuid
import warnings
from collections.abc import Callable, Iterator
from ctypes import wintypes
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from kb_testing.proc import wait_until
from kb_testing.sample_game import (
    SampleGame,
    capture_client,
    client_rect,
    launch_sample_game,
    send_signal,
)
from kookabug_core.engine.cancel import Cancelled, CancelToken
from kookabug_platform.capture import (
    CapturedFrame,
    CaptureHandle,
    CaptureService,
    WgcBackend,
    wall_time,
)
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.dpi import per_monitor_v2_thread
from kookabug_platform.errors import (
    CAPTURE_FAILED,
    CAPTURE_TIMEOUT,
    WINDOW_GONE,
    WINDOW_MINIMIZED,
    PlatformError,
)
from kookabug_platform.tracker import WindowBinding, WindowTracker
from kookabug_platform.win32 import user32
from kookabug_platform.windows import activate, set_client_size, window_info

pytestmark = pytest.mark.desktop

SW_MINIMIZE, SW_RESTORE = 6, 9
CONFIG_MS = 2000


class Gate:
    """실제 WGC 백엔드를 감싸 세션별로 프레임을 막거나(`allow`) 다음 프레임을 망가뜨린다
    (`poison`)."""

    def __init__(self) -> None:
        self.inner = WgcBackend()
        self.allow: Callable[[int], bool] = lambda _index: True
        self.poison = False
        self.started = 0
        self.passed = 0
        self.start_ended_at = 0.0
        """마지막 세션 시작(끊을 수 없는 네이티브 호출)이 돌아온 시각 (`time.monotonic`)."""

    def start(
        self, hwnd: int, on_frame: Callable[[Any], None], on_closed: Callable[[], None]
    ) -> CaptureHandle:
        index = self.started
        self.started += 1
        try:
            return self._start(index, hwnd, on_frame, on_closed)
        finally:
            self.start_ended_at = time.monotonic()

    def _start(
        self,
        index: int,
        hwnd: int,
        on_frame: Callable[[Any], None],
        on_closed: Callable[[], None],
    ) -> CaptureHandle:

        def gated(buffer: Any) -> None:
            if not self.allow(index):
                return
            if self.poison:
                self.poison = False
                on_frame(np.zeros((2, 2, 3), dtype=np.uint8))  # BGRA가 아님 → 콜백 예외
                return
            self.passed += 1
            on_frame(buffer)

        return self.inner.start(hwnd, gated, on_closed)


class Rig:
    def __init__(self, game: SampleGame, backend: Any = None) -> None:
        self.game = game
        self.tracker = WindowTracker(run_id=f"t{uuid.uuid4().hex[:6]}").start()
        self.service = CaptureService(self.tracker, backend=backend)
        self.binding: WindowBinding = self.tracker.bind(game.hwnd)

    def capture(self, ms: int = CONFIG_MS, **kw: Any) -> CapturedFrame:
        return self.service.capture(self.binding, deadline=ObservationDeadline(ms, **kw))

    def fails(self, code: str, ms: int = CONFIG_MS) -> PlatformError:
        with pytest.raises(PlatformError) as info:
            self.capture(ms)
        assert info.value.code == code, info.value.message
        return info.value

    def close(self) -> None:
        try:
            assert self.service.close_all(), "캡처 세션이 끝나지 않았다"
            assert self.service.all_finished()
        finally:
            self.tracker.stop()


@pytest.fixture
def title() -> str:
    return f"KBT4 {uuid.uuid4().hex[:8]}"


def launch(tmp_path: Path, title: str, *options: str) -> SampleGame:
    return launch_sample_game(("--title", title, *options), workdir=tmp_path)


@pytest.fixture
def game(tmp_path: Path, title: str) -> Iterator[SampleGame]:
    with launch(tmp_path, title) as g:
        yield g


@pytest.fixture
def rig(game: SampleGame) -> Iterator[Rig]:
    r = Rig(game)
    yield r
    r.close()


def move_window(hwnd: int, dx: int, dy: int) -> None:
    with per_monitor_v2_thread():
        rect = window_info(hwnd).window_rect
        flags = user32.SWP_NOSIZE | user32.SWP_NOZORDER | user32.SWP_NOACTIVATE
        assert user32.SetWindowPos(hwnd, None, rect[0] + dx, rect[1] + dy, 0, 0, flags)


def test_frame_is_client_area_only(rig: Rig) -> None:
    shot = rig.capture()
    x, y, w, h = client_rect(rig.game.hwnd)  # 제품 코드와 독립인 기준값
    assert shot.size == (w, h) == shot.info.client_size
    assert shot.info.client_origin_screen == (x, y)
    assert np.array_equal(shot.pixels, capture_client(rig.game.hwnd))
    assert shot.pixels.dtype == np.uint8 and shot.pixels.shape == (h, w, 3)


def foreground_is(hwnd: int) -> bool:
    fg = user32.GetForegroundWindow()
    return bool(fg) and user32.GetAncestor(fg, user32.GA_ROOT) == hwnd


SETTLE_RUN = 10
"""정지 판정: 재사용 캡처가 이만큼 연속 (캡처마다 새 프레임 대기 50 ms)."""
SETTLE_SPAN_S = 0.5
"""정지 판정: 그 연속이 이 시간 이상 이어져야 한다."""


def settled(rig: Rig, timeout: float = 10.0) -> CapturedFrame:
    """화면이 멈출 때까지 캡처하고, 멈춘 뒤의 캡처를 준다.

    막 뜬(또는 복원된) 창은 열기·복원 애니메이션과 활성화 동안 프레임이 이어 온다(잠금 해제 상태
    실측). 재사용 한 번은 "그 요청의 새 프레임 대기 동안 프레임이 없었다"일 뿐이라 정지의 근거가
    못 된다. 그래서 **재사용 캡처가 `SETTLE_RUN`번 연속, `SETTLE_SPAN_S` 이상, 같은 `frame_seq`·
    같은 픽셀 해시**일 때만 멈췄다고 본다. 사이에 새 프레임이 하나라도 오면 처음부터 다시 센다.
    """
    end = time.monotonic() + timeout
    run: list[tuple[CapturedFrame, str]] = []
    while time.monotonic() < end:
        shot = rig.capture()
        digest = hashlib.sha256(shot.pixels.tobytes()).hexdigest()
        if not shot.info.reused:
            run = []
            continue
        if run and (run[0][0].info.frame_seq, run[0][1]) != (shot.info.frame_seq, digest):
            run = []
        run.append((shot, digest))
        span = shot.info.observed_at - run[0][0].info.observed_at
        if len(run) >= SETTLE_RUN and span >= SETTLE_SPAN_S:
            return shot
    raise AssertionError(f"{timeout:g}초 안에 화면이 멈추지 않았다 (마지막 연속 {len(run)}번)")


STATIC_ATTEMPTS = 5


def test_static_screen_repeated_captures_reuse_latest(rig: Rig) -> None:
    # 포그라운드가 바뀔 때마다 DWM이 제목 표시줄·테두리를 다시 그려 WGC가 **클라이언트는 같은**
    # 새 프레임을 0.3~0.7초 동안 10여 개 준다(실측: 다른 창 활성화·닫기). 앞 검사의 창이 닫히는
    # 것 같은 바깥 사건이라 막을 수 없다. 그래서 20번 연속 재사용 단언은 그대로 두고, 측정 중
    # 클라이언트가 같은 새 프레임(바깥 사건)이 끼면 정지를 다시 판정해 처음부터 잰다(최대 5번).
    # 클라이언트가 다른 새 프레임은 정지 화면에서 있을 수 없으므로 바로 실패다
    hwnd = rig.game.hwnd
    wait_until(lambda: activate(hwnd), timeout=5, message="게임 창을 앞으로 못 가져옴")
    interrupted: list[list[tuple[int, int, bool]]] = []
    for _ in range(STATIC_ATTEMPTS):
        first = settled(rig)
        shots = [rig.capture() for _ in range(20)]
        fresh = [
            (i, s.info.frame_seq, foreground_is(hwnd))
            for i, s in enumerate(shots)
            if not s.info.reused
        ]
        changed = [i for i, s in enumerate(shots) if not np.array_equal(s.pixels, first.pixels)]
        assert not changed, f"정지 화면인데 클라이언트 픽셀이 바뀐 캡처: {changed}"
        if not fresh:
            break
        interrupted.append(fresh)  # (번째, seq, 포그라운드) — 바깥 사건의 새 프레임
    else:
        raise AssertionError(
            f"{STATIC_ATTEMPTS}번 모두 바깥 사건의 새 프레임이 끼었다: {interrupted}"
        )
    assert all(s.info.reused for s in shots)
    assert {s.info.pixels_at for s in shots} == {first.info.pixels_at}
    assert {s.info.frame_seq for s in shots} == {first.info.frame_seq}
    observed = [first.info.observed_at] + [s.info.observed_at for s in shots]
    assert observed == sorted(observed) and len(set(observed)) == len(observed)
    assert all(np.array_equal(s.pixels, first.pixels) for s in shots)


def test_change_after_static_gives_new_frame(tmp_path: Path, title: str) -> None:
    # 로딩 화면이 정지 판정(열기 애니메이션 + 0.5초 이상)보다 넉넉히 머물게
    game = launch(tmp_path, title, "--start-scene", "loading", "--slow-loading", "3000")
    with game:
        r = Rig(game)
        try:
            loading = settled(r)  # 로딩 화면은 (창 열기 애니메이션 뒤) 멈춰 있다
            game.wait_screen("world")

            def changed() -> CapturedFrame | None:
                shot = r.capture()
                return shot if shot.info.frame_seq != loading.info.frame_seq else None

            world = wait_until(changed, timeout=5, message="월드 화면 프레임이 오지 않았다")
            assert world is not None
            assert world.info.pixels_at > loading.info.pixels_at
            assert not np.array_equal(world.pixels, loading.pixels)
            assert np.array_equal(world.pixels, capture_client(game.hwnd))
        finally:
            r.close()


def test_resize_waits_matching_frame(rig: Rig) -> None:
    rig.capture()
    assert set_client_size(rig.game.hwnd, 800, 500)
    shot = rig.capture()  # 크기를 바꾼 바로 뒤 — 새 크기 프레임을 기다린다
    assert shot.size == (800, 500) == shot.info.client_size
    assert not shot.info.reused
    # 그 프레임은 게임이 다시 그리는 중일 수 있다. 다 그린 뒤의 화면은 독립 캡처와 같다
    reference = capture_client(rig.game.hwnd)
    settled = rig.capture()
    assert settled.size == (800, 500)
    assert np.array_equal(settled.pixels, reference)


def test_resize_without_new_frame_is_capture_timeout(game: SampleGame) -> None:
    gate = Gate()
    r = Rig(game, gate)
    try:
        r.capture()
        gate.allow = lambda _index: False  # 이제 콜백이 프레임을 넘기지 않는다
        assert set_client_size(game.hwnd, 800, 500)
        start = time.monotonic()
        err = r.fails(CAPTURE_TIMEOUT, ms=600)
        # 0.25초 뒤 세션을 한 번 다시 열지만 그 세션도 프레임이 없다
        assert "크기·DPI가 바뀌어 세션을 다시 연 뒤" in err.message
        assert gate.started == 2
        assert 0.55 <= time.monotonic() - start <= 1.2
    finally:
        r.close()


def test_move_does_not_change_frame(rig: Rig) -> None:
    before = rig.capture()
    move_window(rig.game.hwnd, 40, 30)
    after = rig.capture()
    ox, oy = before.info.client_origin_screen
    assert after.info.client_origin_screen == (ox + 40, oy + 30)
    assert after.size == before.size
    assert np.array_equal(after.pixels, before.pixels)


def fit_on_monitor(hwnd: int) -> None:
    """창 전체를 그 모니터 안에 둔다 (넘치면 클라이언트를 줄여 모니터 왼쪽 위로).

    CI 러너 화면은 1024x768이라 기본 배치의 1024x640 클라이언트 오른쪽 8열이 화면 밖이다. 복원
    검사가 CI에서 한 번 오른쪽 모서리만 달랐다(이어 온 세션은 흰색, 새 세션은 검정, 둘 다 게임
    배경색이 아님). 화면 밖 픽셀이 세션마다 다르다는 것은 **가설**이다(로컬에서 재현 안 됨) — 화면
    밖에 걸친 배치는 `test_restore_offscreen_columns`가 따로 진단한다. 이 배치는 그 대조 조건이다.
    """
    info = window_info(hwnd)
    ml, mt, mr, mb = info.monitor
    wl, wt, wr, wb = info.window_rect
    if ml <= wl and mt <= wt and wr <= mr and wb <= mb:
        return
    cw, ch = info.client_size
    w = min(cw, (mr - ml) - ((wr - wl) - cw))
    h = min(ch, (mb - mt) - ((wb - wt) - ch))
    if (w, h) != (cw, ch):
        assert set_client_size(hwnd, w, h)
    with per_monitor_v2_thread():
        flags = user32.SWP_NOSIZE | user32.SWP_NOZORDER | user32.SWP_NOACTIVATE
        assert user32.SetWindowPos(hwnd, None, ml, mt, 0, 0, flags)
    x, y, w, h = client_rect(hwnd)
    assert ml <= x and mt <= y and x + w <= mr and y + h <= mb, ((x, y, w, h), info.monitor)


def pixel_diff(a: Any, b: Any) -> str:
    """다른 픽셀 수와 범위 (실패 메시지)."""
    if a.shape != b.shape:
        return f"크기가 다르다: {a.shape} != {b.shape}"
    ys, xs = np.nonzero(np.any(a != b, axis=2))
    if not len(xs):
        return "같다"
    return f"{len(xs)}픽셀 다름, x {xs.min()}~{xs.max()}, y {ys.min()}~{ys.max()}"


def monitor_rects() -> list[tuple[int, int, int, int]]:
    """모든 모니터의 `(left, top, right, bottom)` (물리 픽셀)."""
    rects: list[tuple[int, int, int, int]] = []
    proto = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    def each(_monitor: Any, _dc: Any, rect: Any, _param: Any) -> bool:
        r = rect.contents
        rects.append((r.left, r.top, r.right, r.bottom))
        return True

    callback = proto(each)
    with per_monitor_v2_thread():
        assert ctypes.windll.user32.EnumDisplayMonitors(None, None, callback, 0)
    return rects


def on_screen_mask(hwnd: int) -> Any:
    """클라이언트 픽셀 중 어느 모니터 안에 있는 것 (`(h, w)` bool)."""
    x, y, w, h = client_rect(hwnd)
    mask = np.zeros((h, w), dtype=bool)
    for left, top, right, bottom in monitor_rects():
        x0, y0 = max(left, x) - x, max(top, y) - y
        x1, y1 = min(right, x + w) - x, min(bottom, y + h) - y
        if x0 < x1 and y0 < y1:
            mask[y0:y1, x0:x1] = True
    return mask


def frame_note(name: str, shot: CapturedFrame) -> str:
    info = shot.info
    return f"{name} seq {info.frame_seq} pixels_at {info.pixels_at:.3f} reused {info.reused}"


def minimize_and_restore(rig: Rig, on_minimized: Callable[[], None] | None = None) -> float:
    """최소화 → (`on_minimized`) → 복원. 복원을 요청한 시각(`pixels_at`과 같은 시계)을 준다."""
    hwnd = rig.game.hwnd
    user32.ShowWindow(hwnd, SW_MINIMIZE)
    wait_until(lambda: window_info(hwnd).minimized, timeout=5, message="최소화 안 됨")
    assert "최소화" in rig.fails(WINDOW_MINIMIZED).message
    if on_minimized is not None:
        on_minimized()
    restored_at = wall_time(time.monotonic())
    user32.ShowWindow(hwnd, SW_RESTORE)
    wait_until(lambda: not window_info(hwnd).minimized, timeout=5, message="복원 안 됨")
    return restored_at


def test_minimized_is_window_minimized(rig: Rig) -> None:
    # 대조 조건: 창 전체가 모니터 안, 복원 전후 장면 같음 (복원 뒤 장면이 바뀌는 경우는
    # test_restore_shows_scene_changed_while_minimized)
    fit_on_monitor(rig.game.hwnd)
    before = rig.capture()
    minimize_and_restore(rig)
    # 복원 애니메이션 동안의 프레임은 다 그린 화면이 아닐 수 있다 — 멈춘 뒤 독립 캡처와 비교
    shot = settled(rig)
    reference = capture_client(rig.game.hwnd)
    assert np.array_equal(shot.pixels, reference), (
        f"{frame_note('복원 전', before)}, {frame_note('복원 뒤', shot)}: "
        f"{pixel_diff(shot.pixels, reference)}, 클라이언트 {client_rect(rig.game.hwnd)}, "
        f"모니터 {monitor_rects()}"
    )


OFFSCREEN_COLUMNS = 8
"""화면 밖 배치에서 모니터 밖에 둘 클라이언트 오른쪽 열 (CI 러너 기본 배치와 같은 8열)."""


def place_offscreen(hwnd: int, columns: int = OFFSCREEN_COLUMNS) -> None:
    """클라이언트 오른쪽 `columns`열이 어느 모니터에도 없게 (이미 화면 밖에 걸쳐 있으면 그대로 —
    CI 러너의 기본 배치)."""
    if not on_screen_mask(hwnd).all():
        return
    _left, top, right, _bottom = max(monitor_rects(), key=lambda r: r[2])
    x, _y, w, _h = client_rect(hwnd)
    rect = window_info(hwnd).window_rect
    with per_monitor_v2_thread():
        flags = user32.SWP_NOSIZE | user32.SWP_NOZORDER | user32.SWP_NOACTIVATE
        dx = right + columns - (x + w)
        assert user32.SetWindowPos(hwnd, None, rect[0] + dx, top + 50, 0, 0, flags)


def test_restore_offscreen_columns(rig: Rig) -> None:
    # 진단: CI 기본 배치처럼 클라이언트 오른쪽이 화면 밖인 채 최소화·복원. 화면 안 픽셀은 반드시
    # 독립 캡처와 같아야 한다. 화면 밖 열만 다른 것은 허용한다 — DWM이 합성하지 않는 픽셀이라
    # 세션마다 다를 수 있다는 가설 때문이며, 다르면 경고로 범위·좌표·프레임 번호를 남긴다
    # (통과해도 CI 로그 warnings summary에 보인다)
    hwnd = rig.game.hwnd
    place_offscreen(hwnd)
    rig.capture()
    before = settled(rig)
    mask = on_screen_mask(hwnd)
    assert mask.any() and not mask.all(), (client_rect(hwnd), monitor_rects())
    minimize_and_restore(rig)
    shot = settled(rig)
    reference = capture_client(hwnd)
    again = capture_client(hwnd)
    assert mask.shape == on_screen_mask(hwnd).shape, "복원 뒤 클라이언트 크기가 바뀌었다"
    inside = np.where(mask[..., None], shot.pixels, 0), np.where(mask[..., None], reference, 0)
    outside = np.where(mask[..., None], 0, shot.pixels), np.where(mask[..., None], 0, reference)
    note = (
        f"{frame_note('복원 전', before)}, {frame_note('복원 뒤', shot)}, "
        f"화면 안 {pixel_diff(*inside)}, 화면 밖 {pixel_diff(*outside)}, "
        f"독립 캡처 두 번 {pixel_diff(reference, again)}, 화면 밖 열 {int((~mask).any(0).sum())}, "
        f"클라이언트 {client_rect(hwnd)}, 모니터 {monitor_rects()}"
    )
    assert np.array_equal(*inside), note
    if not np.array_equal(*outside):
        warnings.warn(f"복원 뒤 화면 밖 픽셀만 다름 (허용): {note}", stacklevel=1)


HOLD_LOADING_MS = 600_000
"""장면 변경 검사의 로딩 시간: 게임 타이머가 검사 중에 끝나지 않게 한다. 월드로 바꾸는 것은
검사가 최소화를 확인한 뒤 보내는 신호(`send_signal(..., "fire")`)뿐이라 시작 시각과 경쟁하지
않는다."""


def check_restore_shows_new_scene(
    rig: Rig, signal: Path, on_minimized: Callable[[], None] | None = None
) -> None:
    """로딩 화면이 멈춘 뒤 최소화 → 최소화를 확인한 뒤 신호로 월드로 바꿈(입력 없음) → 복원. 복원
    뒤 관측은 복원 전과 다른 새 프레임이어야 하고 독립 캡처와 같아야 한다."""
    game = rig.game
    loading = settled(rig)
    # 기준은 최소화 전: 그 뒤의 월드 기록은 (최소화 확인 직후 이미 와 있어도) 모두 받는다
    before = game.last_seq()
    early = [e for e in game.events() if e["event"] == "screen" and e["scene"] == "world"]
    assert not early, f"신호 전에 월드로 바뀌었다: {early}"

    def change_while_minimized() -> None:
        send_signal(signal, "fire")
        game.wait_screen("world", after=before)
        assert window_info(game.hwnd).minimized, "월드로 바뀐 뒤 최소화 상태가 아니다"
        if on_minimized is not None:
            on_minimized()

    restored_at = minimize_and_restore(rig, change_while_minimized)

    def fresh() -> CapturedFrame | None:
        shot = rig.capture()
        return shot if shot.info.pixels_at >= restored_at else None

    # 복원 뒤 픽셀을 받은 프레임이 오지 않으면(최소화 전·중 프레임만 재사용) 정해진 메시지로 실패.
    # frame_seq만 보면 최소화 애니메이션 동안 온 (로딩 화면) 프레임이 "새 프레임"으로 통과한다
    wait_until(
        fresh, timeout=5, message=lambda: f"복원 뒤 새 프레임이 없다: {frame_note('로딩', loading)}"
    )
    shot = settled(rig)
    reference = capture_client(game.hwnd)
    note = f"{frame_note('복원 전', loading)}, {frame_note('복원 뒤', shot)}"
    assert shot.info.pixels_at > loading.info.pixels_at, note
    assert not np.array_equal(shot.pixels, loading.pixels), f"복원 뒤에도 로딩 화면: {note}"
    assert np.array_equal(shot.pixels, reference), f"{note}: {pixel_diff(shot.pixels, reference)}"


def test_restore_shows_scene_changed_while_minimized(tmp_path: Path, title: str) -> None:
    signal = tmp_path / "game.signal"
    game = launch(
        tmp_path,
        title,
        "--start-scene",
        "loading",
        "--slow-loading",
        str(HOLD_LOADING_MS),
        "--signal-file",
        str(signal),
    )
    with game:
        fit_on_monitor(game.hwnd)
        r = Rig(game)
        try:
            check_restore_shows_new_scene(r, signal)
        finally:
            r.close()


def test_closed_window_is_window_gone(rig: Rig) -> None:
    rig.capture()
    rig.game.close()
    # 파괴 이벤트나 WGC on_closed가 바인딩을 죽인다
    wait_until(
        lambda: not rig.tracker.is_alive(rig.binding), timeout=5, message="바인딩이 살아 있다"
    )
    rig.fails(WINDOW_GONE)
    assert rig.service.all_finished()


def test_first_frame_missing_is_capture_timeout_and_cancellable(game: SampleGame) -> None:
    gate = Gate()
    gate.allow = lambda _index: False
    r = Rig(game, gate)
    try:
        start = time.monotonic()
        err = r.fails(CAPTURE_TIMEOUT, ms=300)
        assert "첫 프레임" in err.message
        assert 0.25 <= time.monotonic() - start <= 0.8
        # 기다리는 중 취소되면 50 ms 조각 안에 끝난다. 세션 시작(끊을 수 없는 네이티브 호출)은
        # 부하에 따라 길어질 수 있어, 취소 시각과 시작이 돌아온 시각 중 늦은 것부터 잰다
        token = CancelToken()
        cancelled_at: list[float] = []

        def cancel() -> None:
            cancelled_at.append(time.monotonic())
            token.cancel()

        threading.Timer(0.2, cancel).start()
        with pytest.raises(Cancelled):
            r.capture(10_000, check=token.check)
        ended = time.monotonic()
        assert cancelled_at
        assert ended - max(cancelled_at[0], gate.start_ended_at) <= 0.05 + 0.1
    finally:
        r.close()


def test_session_dead_recreated_once_then_capture_failed(game: SampleGame) -> None:
    gate = Gate()
    r = Rig(game, gate)
    try:
        r.capture()
        # 다음 프레임에서 콜백 예외 → 세션이 죽는다. 다시 만든 세션에는 프레임을 주지 않는다
        gate.poison = True
        gate.allow = lambda index: index == 0
        assert set_client_size(game.hwnd, 900, 560)  # 프레임을 하나 오게 한다
        wait_until(lambda: not gate.poison, timeout=5, message="망가진 프레임이 오지 않았다")
        err = r.fails(CAPTURE_FAILED, ms=500)
        assert "다시 만들었지만" in err.message
        assert gate.started == 2 and r.service.sessions_started == 2
        # 장애가 풀리면 같은 바인딩으로 다시 캡처된다
        gate.allow = lambda _index: True
        set_client_size(game.hwnd, 880, 540)
        shot = wait_until(lambda: r.capture(), timeout=5, message="장애 뒤 캡처")
        assert shot.size == (880, 540)
    finally:
        r.close()


_COM_TEARDOWN_SCRIPT = """
import sys
from kookabug_platform.capture import CaptureService
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.tracker import WindowTracker

hwnd = int(sys.argv[1])
tracker = WindowTracker(run_id="mta")
service = CaptureService(tracker)
binding = tracker.bind(hwnd)
service.capture(binding, deadline=ObservationDeadline(3000))
assert service.close(binding.binding_id)
import onnxruntime  # 프로세스 MTA를 없앤다 (실측)
for _ in range(3):
    service.capture(binding, deadline=ObservationDeadline(3000))
    assert service.close(binding.binding_id)
assert service.close_all()
print("sessions", service.sessions_started)
"""


def test_new_session_after_other_library_tears_down_mta(game: SampleGame) -> None:
    # 세션 → import onnxruntime → 새 세션: MTA를 잡아 두지 않으면 접근 위반으로 프로세스가
    # 죽는다(T4-3 검수, `.orchestration/M1/wgc_mta_repro.py`). 죽어도 pytest가 살게 하위 프로세스
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", _COM_TEARDOWN_SCRIPT, str(game.hwnd)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (result.returncode, result.stderr[-2000:])
    assert "sessions 4" in result.stdout


def test_frame_info_fields(rig: Rig) -> None:
    shot = rig.capture()
    info = shot.info
    x, y, w, h = client_rect(rig.game.hwnd)
    assert info.backend == "wgc"
    assert info.window == rig.binding and info.window.pid == rig.game.pid
    assert (info.client_size, info.client_origin_screen) == ((w, h), (x, y))
    assert info.dpi == int(user32.GetDpiForWindow(rig.game.hwnd))
    assert info.region is None and not info.fullscreen
    assert info.pixels_at <= info.observed_at <= time.time() + 0.01
    assert time.time() - info.observed_at < 5
    assert info.frame_seq > 0 and isinstance(info.reused, bool)


@pytest.mark.desktop_input
def test_cursor_not_captured(game: SampleGame) -> None:
    point = wintypes.POINT()
    user32_dll = ctypes.WinDLL("user32")
    user32_dll.GetCursorPos(ctypes.byref(point))
    saved = (point.x, point.y)
    x, y, w, h = client_rect(game.hwnd)
    left = window_info(game.hwnd).frame_bounds[0]
    away = (left - 20, y + 5) if left > 40 else (x + w + 40, y + 5)
    try:
        frames = []
        for spot in ((x + w // 2, y + h // 2), away):
            with per_monitor_v2_thread():
                assert user32_dll.SetCursorPos(*spot)
            time.sleep(0.1)
            r = Rig(game)
            try:
                frames.append(r.capture().pixels)
            finally:
                r.close()
        # 커서가 클라이언트 한가운데 있을 때도 커서 없는 화면과 같다
        assert np.array_equal(frames[0], frames[1])
    finally:
        user32_dll.SetCursorPos(*saved)
