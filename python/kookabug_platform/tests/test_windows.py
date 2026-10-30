"""창 찾기·정보·포그라운드·점 아래 창·창 수명 추적 (구현 계획 M1 2.2, 예제 게임·대화형 데스크톱).

게임은 테스트 세션 Job 안에서 뜬다. 입력은 보내지 않는다 — 포그라운드는 `activate`로만 바꾸고,
점 아래 창은 `WindowFromPoint` 판정만 본다(실제 클릭은 T5 `desktop_input`).
"""

from __future__ import annotations

import ctypes
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from kb_testing.proc import wait_until
from kb_testing.sample_game import SampleGame, client_rect, launch_sample_game
from kookabug_platform.dpi import client_to_screen
from kookabug_platform.errors import (
    POINT_OBSCURED,
    WINDOW_GONE,
    WINDOW_MINIMIZED,
    WINDOW_NOT_FOREGROUND,
    PlatformError,
)
from kookabug_platform.tracker import WindowTracker
from kookabug_platform.win32 import user32
from kookabug_platform.windows import (
    activate,
    check_foreground,
    check_not_minimized,
    check_point,
    find_window,
    find_windows,
    set_client_size,
    window_info,
)

pytestmark = pytest.mark.desktop

SW_MINIMIZE, SW_RESTORE = 6, 9


@pytest.fixture
def title() -> str:
    # 다른 창과 겹치지 않는 제목 (다른 검사의 예제 게임 포함)
    return f"KBT3 {uuid.uuid4().hex[:8]}"


def launch(tmp_path: Path, title: str, *options: str) -> SampleGame:
    return launch_sample_game(("--title", title, *options), workdir=tmp_path)


@pytest.fixture
def game(tmp_path: Path, title: str) -> Iterator[SampleGame]:
    with launch(tmp_path, title) as g:
        yield g


def bring_front(hwnd: int) -> None:
    wait_until(lambda: activate(hwnd), timeout=5, message=lambda: f"{hwnd:#x}를 앞으로 못 가져옴")


def independent_monitor_dpi(hwnd: int) -> int:
    """제품 코드와 따로: PMv2 스레드에서 `GetDpiForMonitor`(가상화되지 않은 실제 모니터 DPI)."""
    shcore = ctypes.WinDLL("shcore")
    u32 = ctypes.WinDLL("user32")
    u32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    u32.SetThreadDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
    u32.MonitorFromWindow.restype = ctypes.c_void_p
    u32.MonitorFromWindow.argtypes = (ctypes.c_void_p, ctypes.c_uint)
    previous = u32.SetThreadDpiAwarenessContext(-4)
    try:
        dx, dy = ctypes.c_uint(), ctypes.c_uint()
        monitor = u32.MonitorFromWindow(hwnd, 2)
        hr = shcore.GetDpiForMonitor(
            ctypes.c_void_p(monitor), 0, ctypes.byref(dx), ctypes.byref(dy)
        )
        assert hr == 0, hr
        return dx.value
    finally:
        u32.SetThreadDpiAwarenessContext(previous)


def refused(code: str, fn: object, *args: object) -> PlatformError:
    with pytest.raises(PlatformError) as info:
        fn(*args)  # type: ignore[operator]
    assert info.value.code == code, info.value.message
    return info.value


def test_find_by_title_substring_and_regex(game: SampleGame, title: str) -> None:
    assert find_window(title=title.lower()) == game.hwnd  # 대소문자 무시 부분 일치
    assert find_window(title=title.split()[1].upper()) == game.hwnd
    assert find_window(title=f"/^{title}$/") == game.hwnd
    assert find_window(title=f"/^{title}x$/") is None
    assert find_windows(title=title, pids=[game.pid]) == [game.hwnd]
    assert find_windows(title=title, pids=[game.pid + 4]) == []


def test_find_by_process_name(game: SampleGame, title: str) -> None:
    info = window_info(game.hwnd)
    assert info.process_name.lower().startswith("python") and info.pid == game.pid
    assert game.hwnd in find_windows(process_name=info.process_name.upper())
    assert find_window(process_name=info.process_name, title=title) == game.hwnd
    assert find_windows(process_name="no-such-game.exe", title=title) == []


def test_find_owned_popup_only_with_owned_flag(tmp_path: Path, title: str) -> None:
    with launch(tmp_path, title, "--owned-popup") as game:
        popup = game.ready["windows"]["popup"]
        assert find_windows(title=f"{title} Notice") == []  # 기본은 소유자 없는 창만
        assert find_windows(title=f"{title} Notice", owned=True) == [popup]
        # 부분 일치 제목에 둘 다 맞으면 소유 팝업이 Z 순서 앞
        assert find_windows(title=title) == [game.hwnd]
        assert find_windows(title=title, owned=True) == [popup, game.hwnd]


@pytest.mark.parametrize("mode", ["pmv2", "unaware"])
def test_client_rect_physical_pixels(tmp_path: Path, title: str, mode: str) -> None:
    with launch(tmp_path, title, "--dpi-awareness", mode, "--size", "800x500") as game:
        info = window_info(game.hwnd)
        assert game.ready["dpi_awareness"] == mode
        x, y, w, h = client_rect(game.hwnd)  # 제품 코드와 독립인 물리 픽셀 기준값
        assert info.client_origin == (x, y) and info.client_size == (w, h)
        # 모니터의 실제 배율은 창 DPI와 따로 구한다 (unaware 창의 GetDpiForWindow는 늘 96)
        monitor_dpi = independent_monitor_dpi(game.hwnd)
        assert info.monitor_dpi == monitor_dpi
        if mode == "pmv2":
            # PMv2 게임의 Tk는 요청 크기를 물리 픽셀로 쓴다: 배율과 무관하게 800x500
            assert info.dpi == monitor_dpi
            assert info.client_size == (800, 500)
        else:
            # unaware 게임은 논리 800x500을 그리고 시스템이 모니터 배율만큼 확대한다
            assert info.dpi == 96
            scale = monitor_dpi / 96
            assert info.client_size == (round(800 * scale), round(500 * scale))
        assert (info.hwnd, info.pid, info.title) == (game.hwnd, game.pid, title)
        assert info.class_name == "TkTopLevel" and info.visible and not info.minimized
        assert not info.cloaked and not info.fullscreen and info.process_created > 0
        left, top, right, bottom = info.frame_bounds
        assert left <= x and top <= y and right >= x + w and bottom >= y + h
        assert info.integrity is not None
        assert client_to_screen(game.hwnd, (10, 20)) == (x + 10, y + 20)


def test_minimized_detected(game: SampleGame) -> None:
    check_not_minimized(game.hwnd)
    user32.ShowWindow(game.hwnd, SW_MINIMIZE)
    try:
        wait_until(lambda: window_info(game.hwnd).minimized, timeout=5)
        err = refused(WINDOW_MINIMIZED, check_not_minimized, game.hwnd)
        assert game.ready["title"] in err.message
    finally:
        user32.ShowWindow(game.hwnd, SW_RESTORE)
    wait_until(lambda: not window_info(game.hwnd).minimized, timeout=5)


def test_set_client_size_exact(game: SampleGame) -> None:
    after = game.last_seq()
    assert set_client_size(game.hwnd, 900, 560)
    assert window_info(game.hwnd).client_size == (900, 560)
    # 게임도 그 크기를 받았다 (입력 수신 기록)
    game.wait_event("resize", after=after, client_size=[900, 560])
    assert set_client_size(game.hwnd, 1024, 640)
    assert window_info(game.hwnd).client_size == (1024, 640)
    assert not set_client_size(0x7FFF0000, 100, 100)  # 없는 창


def test_set_client_size_unaware_window(tmp_path: Path, title: str) -> None:
    # unaware 창: 창 DPI(96)로 계산한 테두리는 확대된 실제 테두리와 다르다 → 실측으로 고쳐 맞춘다
    with launch(tmp_path, title, "--dpi-awareness", "unaware") as game:
        scale = independent_monitor_dpi(game.hwnd) / 96
        after = game.last_seq()
        # 960x600은 100·125·150·200% 어느 배율에서도 논리 정수 크기다
        assert set_client_size(game.hwnd, 960, 600)
        assert window_info(game.hwnd).client_size == (960, 600)
        assert client_rect(game.hwnd)[2:] == (960, 600)
        # 게임(unaware)은 논리 크기로 받는다
        logical = [round(960 / scale), round(600 / scale)]
        game.wait_event("resize", after=after, client_size=logical)


def test_foreground_independent_second_window_refused(tmp_path: Path, title: str) -> None:
    with launch(tmp_path, title, "--second-window") as game:
        second = game.ready["windows"]["second"]
        bring_front(second)
        # 같은 프로세스의 독립 최상위 창이 포그라운드: 메인 창 대상 키보드 입력은 거부
        err = refused(WINDOW_NOT_FOREGROUND, check_foreground, game.hwnd)
        assert f"{title} Chat" in err.message
        check_foreground(second)
        bring_front(game.hwnd)
        check_foreground(game.hwnd)
        refused(WINDOW_NOT_FOREGROUND, check_foreground, second)


def test_foreground_owned_popup_allowed(tmp_path: Path, title: str) -> None:
    with launch(tmp_path, title, "--owned-popup") as game:
        popup = game.ready["windows"]["popup"]
        bring_front(popup)
        # 메인 창이 소유한 팝업이 포그라운드: 메인 창 대상 키보드는 통과, 팝업을 대상으로 해도 통과
        check_foreground(game.hwnd)
        check_foreground(popup)
        # 클릭 지점: 팝업이 덮은 메인 클라이언트 점은 거부, 팝업을 대상으로 하면 통과 (N1)
        x, y, w, h = client_rect(game.hwnd)
        under_popup = (x + 40 + 100, y + 40 + 80)
        err = refused(POINT_OBSCURED, check_point, game.hwnd, under_popup)
        assert f"{title} Notice" in err.message
        check_point(popup, under_popup)
        # 팝업 밖의 메인 클라이언트 점은 통과
        check_point(game.hwnd, (x + w - 30, y + h - 30))


def test_recreated_window_old_ref_gone(tmp_path: Path, title: str) -> None:
    tracker = WindowTracker()
    with tracker, launch(tmp_path, title, "--recreate-after", "1500") as game:
        old_hwnd = game.hwnd
        binding = tracker.resolve(old_hwnd)
        tracker.check(binding)
        generation = tracker.generation
        recreate = game.wait_event("recreate", old_hwnd=old_hwnd)
        game.wait_ready(after=recreate["seq"])
        assert game.ready["recreated"] and game.ready["title"] == title
        # 파괴 이벤트가 추적기 스레드에 와서 바인딩이 죽었다
        assert tracker.sync(1.0)
        wait_until(lambda: tracker.generation > generation, timeout=5)
        err = refused(WINDOW_GONE, tracker.check, binding)
        assert "파괴 이벤트" in err.message
        # 같은 제목의 새 창은 새 바인딩으로만 쓴다
        fresh = tracker.resolve(find_window(title=f"/^{title}$/") or 0)
        assert fresh.hwnd == game.hwnd and fresh.binding_id != binding.binding_id
        tracker.check(fresh)
    assert not tracker.running


def test_activate_best_effort_never_raises(game: SampleGame) -> None:
    assert activate(0) is False
    assert activate(0x7FFF0000) is False
    result = activate(game.hwnd)
    assert isinstance(result, bool)
    if result:
        fg = user32.GetForegroundWindow()
        assert user32.GetAncestor(fg, user32.GA_ROOT) == game.hwnd
    # 최소화된 창은 되살려 앞으로
    user32.ShowWindow(game.hwnd, SW_MINIMIZE)
    wait_until(lambda: bool(user32.IsIconic(game.hwnd)), timeout=5)
    activate(game.hwnd)
    wait_until(lambda: not user32.IsIconic(game.hwnd), timeout=5)
