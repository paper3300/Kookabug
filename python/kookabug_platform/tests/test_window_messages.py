"""UX7 검수 4: 플랫폼 오류 메시지에 창 제목을 넣지 않는다 — 창은 `HWND 0x…` + 프로세스 이름(못
읽으면 `?`). 로그인 뒤 제목에 계정 ID가 들어가는 게임이 있다 (보통 실행·붙여 실행 모두)."""

from __future__ import annotations

import pytest

from kb_testing.fake_win32 import FakeWindowApi
from kookabug_platform.errors import PlatformError
from kookabug_platform.windows import (
    check_foreground,
    check_integrity,
    check_not_minimized,
    check_point,
    describe,
)

ACCOUNT = "acct-r5-secret-77"
TITLE = f"Game [Account : {ACCOUNT}]"
OTHER_TITLE = f"Launcher {ACCOUNT}"
GAME, OTHER = 0x1A2B, 0x3C4D


def api() -> FakeWindowApi:
    fake = FakeWindowApi()
    fake.add(GAME, 100, title=TITLE)
    fake.add(OTHER, 200, title=OTHER_TITLE)
    fake.names = {100: "game.exe", 200: "launcher.exe"}
    return fake


def test_describe_has_hwnd_and_process_not_title() -> None:
    fake = api()
    assert describe(GAME, fake) == "HWND 0x1a2b (game.exe pid 100)"
    assert describe(0, fake) == "(창 없음)"
    fake.names = {100: ""}
    assert describe(GAME, fake) == "HWND 0x1a2b (? pid 100)"  # 프로세스 이름을 못 읽으면 ?
    fake.destroy(GAME)
    assert describe(GAME, fake) == "(닫힌 창 HWND 0x1a2b)"


def message(fn: object, *args: object) -> str:
    with pytest.raises(PlatformError) as caught:
        fn(*args)  # type: ignore[operator]
    return str(caught.value)


def test_check_messages_have_no_title() -> None:
    fake = api()
    fake.foreground = OTHER
    texts = [message(check_foreground, GAME, fake)]
    fake.under_point[(10, 10)] = OTHER
    texts.append(message(check_point, GAME, (10, 10), fake))
    fake.windows[GAME].minimized = True
    texts.append(message(check_not_minimized, GAME, fake))
    fake.integrity = {100: 0x3000, None: 0x2000}
    texts.append(message(check_integrity, GAME, fake))
    for text in texts:
        assert ACCOUNT not in text and "Game [" not in text and "Launcher" not in text, text
        assert "HWND 0x1a2b (game.exe pid 100)" in text
    # 양성 대조: 다른 창도 HWND·프로세스로
    assert "HWND 0x3c4d (launcher.exe pid 200)" in texts[0]
