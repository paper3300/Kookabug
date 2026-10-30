"""포그라운드·점 아래 창 판정식 (구현 계획 M1 2.2, 계획 검수 5·2차 N1). Win32 호출은 가짜 표.

창 배치 (모두 PID 10):
- 0x100 대상 메인 창 A, 0x101 A의 자식 컨트롤(부모 A)
- 0x200 A가 소유한 팝업 B, 0x300 B가 소유한 팝업 C (소유 사슬 C → B → A)
- 0x400 같은 프로세스의 독립 최상위 창 S (소유자 없음)
- 0x500 다른 프로세스(PID 20)의 창 X
"""

from __future__ import annotations

import pytest

from kb_testing.fake_win32 import FakeWindowApi
from kookabug_platform.errors import POINT_OBSCURED, WINDOW_NOT_FOREGROUND, PlatformError
from kookabug_platform.windows import check_foreground, check_point, is_owned_by

A, A_CHILD, B, C, S, X = 0x100, 0x101, 0x200, 0x300, 0x400, 0x500
PT = (300, 200)


@pytest.fixture
def api() -> FakeWindowApi:
    fake = FakeWindowApi(names={10: "game.exe", 20: "other.exe"})
    fake.add(A, 10, title="Game")
    fake.add(A_CHILD, 10, title="", parent=A)
    fake.add(B, 10, title="Game Notice", owner=A)
    fake.add(C, 10, title="Game Notice Detail", owner=B)
    fake.add(S, 10, title="Game Chat")
    fake.add(X, 20, title="Editor")
    return fake


def refused(code: str, fn: object, *args: object) -> PlatformError:
    with pytest.raises(PlatformError) as info:
        fn(*args)  # type: ignore[operator]
    assert info.value.code == code
    return info.value


def test_target_itself_passes(api: FakeWindowApi) -> None:
    api.foreground = A
    check_foreground(A, api)
    api.under_point[PT] = A_CHILD  # 자식 컨트롤은 GA_ROOT로 대상 창이 된다
    check_point(A, PT, api)


def test_owned_popup_root_owner_passes(api: FakeWindowApi) -> None:
    # A가 대상이면 A가 (사슬로) 소유한 팝업 B·C가 포그라운드여도 키보드는 통과
    for fg in (B, C):
        api.foreground = fg
        check_foreground(A, api)
    # 팝업 B 자체를 attach해 대상으로 삼으면, B가 포그라운드일 때 통과 (N1: A != B로 거부하지 않음)
    api.foreground = B
    check_foreground(B, api)
    api.under_point[PT] = B
    check_point(B, PT, api)
    # B가 대상일 때 B 소유 팝업 C도 통과, 소유자 A는 B의 팝업이 아니므로 거부
    api.foreground = C
    check_foreground(B, api)
    api.foreground = A
    refused(WINDOW_NOT_FOREGROUND, check_foreground, B, api)


def test_independent_window_same_pid_refused(api: FakeWindowApi) -> None:
    api.foreground = S
    err = refused(WINDOW_NOT_FOREGROUND, check_foreground, A, api)
    # 메시지에 대상과 지금 포그라운드 창
    assert "'Game'" in err.message and "'Game Chat'" in err.message and "game.exe" in err.message
    api.foreground = X
    refused(WINDOW_NOT_FOREGROUND, check_foreground, A, api)
    api.foreground = 0  # 포그라운드 없음 (잠금 직후 등)
    refused(WINDOW_NOT_FOREGROUND, check_foreground, A, api)


def test_point_under_other_window_obscured(api: FakeWindowApi) -> None:
    api.under_point[PT] = X
    err = refused(POINT_OBSCURED, check_point, A, PT, api)
    assert "'Editor'" in err.message and "other.exe" in err.message
    api.under_point[PT] = S  # 같은 프로세스의 독립 창도 거부
    refused(POINT_OBSCURED, check_point, A, PT, api)
    del api.under_point[PT]  # 화면 밖·아무 창 없음
    refused(POINT_OBSCURED, check_point, A, PT, api)


def test_point_under_owned_popup_obscured(api: FakeWindowApi) -> None:
    # WGC 창 캡처에는 소유 팝업이 찍히지 않는다: A의 관측 좌표로 팝업 위를 누르지 않는다
    for popup in (B, C):
        api.under_point[PT] = popup
        refused(POINT_OBSCURED, check_point, A, PT, api)


def test_owner_chain_walk(api: FakeWindowApi) -> None:
    assert is_owned_by(C, A, api) and is_owned_by(C, B, api) and is_owned_by(A, A, api)
    assert not is_owned_by(A, B, api) and not is_owned_by(S, A, api) and not is_owned_by(0, A, api)
    # 소유 순환(비정상)에서도 끝난다
    api.windows[A].owner = C
    assert not is_owned_by(C, S, api)
