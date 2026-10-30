"""권한 수준·입력 데스크톱·전체화면 추정·제목 일치·오류 코드 (구현 계획 M1 2.2).

판정식은 가짜 창 표로, 무결성·프로세스 이름은 실제 호출로 본다.
"""

from __future__ import annotations

import re

import pytest

from kb_testing.fake_win32 import FakeWindowApi
from kookabug_core.engine.errors import EngineError
from kookabug_platform.errors import (
    CODES,
    INPUT_DESKTOP_UNAVAILABLE,
    TARGET_ELEVATED,
    PlatformError,
)
from kookabug_platform.win32.api import INTEGRITY_MEDIUM, Win32Api
from kookabug_platform.windows import (
    check_input_desktop,
    check_integrity,
    find_windows,
    integrity_exceeds,
    is_fullscreen,
    title_matches,
)

GAME = 0x100
MEDIUM, HIGH, LOW, SYSTEM = 0x2000, 0x3000, 0x1000, 0x4000


def test_integrity_compare_elevated_target() -> None:
    assert integrity_exceeds(HIGH, MEDIUM) and integrity_exceeds(SYSTEM, HIGH)
    assert not integrity_exceeds(MEDIUM, MEDIUM) and not integrity_exceeds(LOW, MEDIUM)
    assert not integrity_exceeds(HIGH, HIGH)  # runner도 관리자 권한이면 통과
    # 대상 토큰을 읽을 수 없음(접근 거부) = 상승된 프로세스로 본다. runner 쪽을 모르면 막지 않는다
    assert integrity_exceeds(None, MEDIUM) and not integrity_exceeds(HIGH, None)

    api = FakeWindowApi(names={10: "game.exe"})
    api.add(GAME, 10, title="Game")
    api.integrity = {None: MEDIUM, 10: HIGH}
    with pytest.raises(PlatformError) as info:
        check_integrity(GAME, api)
    assert info.value.code == TARGET_ELEVATED
    assert "'Game'" in info.value.message and "0x3000" in info.value.message
    api.integrity = {None: MEDIUM, 10: None}
    with pytest.raises(PlatformError) as info:
        check_integrity(GAME, api)
    assert "접근 거부" in info.value.message
    api.integrity = {None: HIGH, 10: HIGH}
    check_integrity(GAME, api)


def test_input_desktop_unavailable() -> None:
    api = FakeWindowApi()
    check_input_desktop(api)
    cases = [
        (("Default", ""), True, "잠겨"),  # Windows 10·11 잠금 화면은 Default 위에 뜬다
        ((None, "Win32 오류 5: 액세스 거부"), False, "열 수 없다"),
        (("Winlogon", ""), False, "Winlogon"),
    ]
    for desktop, locked, words in cases:
        api.desktop, api.locked = desktop, locked
        with pytest.raises(PlatformError) as info:
            check_input_desktop(api)
        assert info.value.code == INPUT_DESKTOP_UNAVAILABLE
        assert words in info.value.message
    api.desktop, api.locked = ("Default", ""), None  # 잠금 상태 모름: 막지 않는다
    check_input_desktop(api)


def test_fullscreen_heuristic() -> None:
    monitor = (0, 0, 1920, 1080)
    caption, popup = 0x00C00000 | 0x10000000, 0x80000000 | 0x10000000
    assert is_fullscreen((0, 0, 1920, 1080), monitor, popup)  # 테두리 없는 전체화면
    assert is_fullscreen((-8, -8, 1928, 1088), monitor, popup)  # 모니터보다 크게 덮음
    assert not is_fullscreen((0, 0, 1920, 1080), monitor, caption)  # 최대화된 창(캡션 있음)
    assert not is_fullscreen((0, 0, 1280, 720), monitor, popup)
    # 두 번째 모니터 (음수 좌표)
    assert is_fullscreen((-1920, 0, 0, 1080), (-1920, 0, 0, 1080), popup)
    assert not is_fullscreen((0, 0, 1920, 1080), (-1920, 0, 0, 1080), popup)


def test_title_matches_substring_and_regex() -> None:
    assert title_matches("samplerpg", "SampleRPG Notice")
    assert not title_matches("Chat", "SampleRPG Notice")
    assert title_matches("/^SampleRPG$/", "SampleRPG")
    assert not title_matches("/^SampleRPG$/", "SampleRPG Chat")
    assert not title_matches("/^samplerpg$/", "SampleRPG")  # 정규식은 대소문자를 구분 ((?i) 가능)
    assert title_matches("/(?i)^samplerpg$/", "SampleRPG")
    with pytest.raises(re.error):
        find_windows(title="/[/", api=FakeWindowApi())


def test_find_windows_filters_and_z_order() -> None:
    api = FakeWindowApi(names={10: "Game.EXE", 20: "other.exe"})
    api.add(0x10, 10, title="Game Notice", owner=0x20)  # 소유 팝업 (Z 순서 앞)
    api.add(0x20, 10, title="Game")
    api.add(0x30, 10, title="Game Hidden", visible=False)
    api.add(0x40, 10, title="Game Cloaked", cloaked=True)
    api.add(0x50, 20, title="Game Editor")
    assert find_windows(title="game", api=api) == [0x20, 0x50]
    assert find_windows(title="game", owned=True, api=api) == [0x10, 0x20, 0x50]
    assert find_windows(process_name="game.exe", api=api) == [0x20]
    assert find_windows(pids=[20], api=api) == [0x50]
    assert find_windows(title="Notice", api=api) == []


def test_platform_error_codes() -> None:
    err = PlatformError("window_gone", "닫혔다")
    assert isinstance(err, EngineError) and err.code == "window_gone"
    assert "stale_observation" not in CODES  # 처리되지 않은 fail은 error 코드가 아니다
    with pytest.raises(ValueError):
        PlatformError("no_such_code", "x")


def test_real_api_own_integrity_and_desktop_name() -> None:
    api = Win32Api()
    own = api.process_integrity(None)
    assert own is not None and own >= INTEGRITY_MEDIUM - 0x1000  # 보통 이상 (낮음은 샌드박스)
    import os

    assert api.process_integrity(os.getpid()) == own
    assert api.process_integrity(0x7FFFFFF0) is None  # 없는 PID
    assert api.process_name(os.getpid()).lower().startswith("python")
