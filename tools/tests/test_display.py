"""검사 창 모니터 고르기 (`kb_testing.display`, `KOOKABUG_TEST_DISPLAY`). 창을 띄우지 않는다."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from kb_testing import display
from kb_testing.display import DISPLAY_ENV, TK_HOME, Monitor, pick, place, place_in, target, tk_env
from kb_testing.proc import isolated_env
from kb_testing.sample_game import game_env

# 이 레포를 만든 PC와 같은 모양: 왼쪽 세로, 가운데 주, 오른쪽 세로
LEFT = Monitor("L", (-1080, -404, 0, 1516), (-1080, -404, 0, 1468), False)
MAIN = Monitor("M", (0, 0, 1920, 1080), (0, 0, 1920, 1032), True)
RIGHT = Monitor("R", (1920, -401, 3000, 1519), (1920, -401, 3000, 1471), False)
ALL = [MAIN, LEFT, RIGHT]


def test_pick_by_name_and_point() -> None:
    assert pick("left", ALL) is LEFT
    assert pick(" Right ", ALL) is RIGHT
    assert pick("primary", ALL) is MAIN
    assert pick("-500,300", ALL) is LEFT
    assert pick("2000, -100", ALL) is RIGHT
    with pytest.raises(ValueError):
        pick("middle", ALL)
    with pytest.raises(ValueError):
        pick("5000,5000", ALL)
    # 모니터가 하나면 left·right·primary 모두 그 모니터
    assert pick("left", [MAIN]) is MAIN and pick("right", [MAIN]) is MAIN


def test_place_inside_work_area_and_overflow_away_from_primary() -> None:
    # 예제 게임 1024x640은 1080 폭 안에 들어간다
    x, y = place_in(LEFT, ALL, 1024, 640)
    assert x >= -1080 and x + 1024 <= 0 and y >= -404 and y + 640 <= 1468
    # 1440 폭은 넘친다: 왼쪽 모니터는 오른쪽 끝을 맞춰 왼쪽으로(주 모니터를 가리지 않게)
    x, _ = place_in(LEFT, ALL, 1440, 900)
    assert x + 1440 == 0
    # 오른쪽 모니터는 왼쪽 끝을 맞춰 오른쪽으로
    x, _ = place_in(RIGHT, ALL, 1440, 900)
    assert x == 1920
    # 작업 영역보다 높으면 위에 붙인다
    _, y = place_in(LEFT, ALL, 800, 4000)
    assert y == -404


def test_unset_or_blank_keeps_current_behavior() -> None:
    def never() -> list[Monitor]:
        raise AssertionError("값이 없으면 모니터를 찾지 않는다")

    assert target({}, never) is None
    assert target({DISPLAY_ENV: "  "}, never) is None
    assert place(100, 100, {}) is None
    assert target({DISPLAY_ENV: "left"}, lambda: ALL) == (LEFT, ALL)


def test_tk_env_and_test_environments(tmp_path: Path) -> None:
    assert "HOME" not in tk_env({"PATH": "x"})
    assert tk_env({DISPLAY_ENV: "left"})["HOME"] == str(TK_HOME)
    # 격리 환경은 KOOKABUG_*를 지우지만 검사 창 모니터는 남기고 tkinter 프로필을 건다
    outer = {"PATH": "x", "KOOKABUG_AGENT": "a", DISPLAY_ENV: "left"}
    env = isolated_env(tmp_path, outer)
    assert env[DISPLAY_ENV] == "left" and env["HOME"] == str(TK_HOME)
    assert "KOOKABUG_AGENT" not in env
    plain = isolated_env(tmp_path, {"PATH": "x"})
    assert DISPLAY_ENV not in plain and "HOME" not in plain
    assert game_env({DISPLAY_ENV: "right"})["HOME"] == str(TK_HOME)
    assert "HOME" not in game_env({"PATH": "x"})


def test_tk_profile_is_ascii_and_points_at_display_module() -> None:
    profile = TK_HOME / ".Tk.py"
    text = profile.read_bytes()
    text.decode("ascii")  # readprofile은 지역 인코딩으로 연다
    assert (TK_HOME / ".." / "display.py").resolve() == Path(display.__file__).resolve()


class FakeWindow:
    def __init__(self, req: tuple[int, int] = (300, 200)) -> None:
        self.req = req

    def winfo_reqwidth(self) -> int:
        return self.req[0]

    def winfo_reqheight(self) -> int:
        return self.req[1]


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # 크기만 주면(게임 메인 창) 그 모니터 가운데 위치를 붙인다 (창 틀 여유 16x40 포함)
        ("1024x640", "1024x640+-1060+192"),
        # 위치를 준 창(게임 보조 창이 메인 오른쪽 40)은 작업 영역 안으로 옮긴다
        ("360x240+12+94", "360x240+-376+94"),
        ("320x160+-1000+-500", "320x160+-1000+-404"),
        ("+5000+20", "+-316+20"),
        # 이미 안에 있으면 그대로, 모양이 다르면 손대지 않는다
        ("200x100+-900+0", "200x100+-900+0"),
        ("=200x100", "=200x100"),
    ],
)
def test_tk_geometry_adjusted_into_chosen_monitor(given: str, expected: str) -> None:
    adjust: Any = display._adjust  # pyright: ignore[reportPrivateUsage]
    assert adjust(FakeWindow(), given, LEFT, ALL) == expected


# ---------------------------------------------------------------- 검수 1차 회귀 (display_review_1)

LEFT_ENV = {DISPLAY_ENV: "left"}
GAME = (-1060, 192, -20, 871)
"""왼쪽 모니터에 놓인 기본 예제 게임 창 (1024x640 클라이언트, 실측)."""


@pytest.fixture
def fake_monitors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(display, "monitors", lambda: ALL)


def test_shift_within_keeps_moved_window_inside_chosen_monitor(fake_monitors: None) -> None:
    # 값이 없으면 원래 이동량
    assert display.shift_within(GAME, 40, 30, {}) == (40, 30)
    # 캡처 검사의 (40, 30): 가로 자리가 양쪽 20px뿐 → 20px만, 세로 30은 그대로 (주 모니터 침범 없음)
    dx, dy = display.shift_within(GAME, 40, 30, LEFT_ENV)
    moved = (GAME[0] + dx, GAME[1] + dy, GAME[2] + dx, GAME[3] + dy)
    assert (dx, dy) != (0, 0) and display._fits(moved, LEFT.work)  # pyright: ignore[reportPrivateUsage]
    assert (dx, dy) == (20, 30)
    # 그 방향에 자리가 없으면 반대로 (거리 같음)
    near_bottom = (-1060, 700, -20, 1379)
    assert display.shift_within(near_bottom, 0, 100, LEFT_ENV) == (0, -100)
    # 이미 밖에 있는 축은 손대지 않는다
    assert display.shift_within((10, 0, 50, 40), 5, 5, LEFT_ENV) == (5, 5)


def test_pair_layout_stacks_two_games_on_narrow_monitor(fake_monitors: None) -> None:
    assert display.pair_layout(GAME, GAME, 20, {}) is None
    first, other = display.pair_layout(GAME, GAME, 20, LEFT_ENV) or ((0, 0), (0, 0))
    w, h = GAME[2] - GAME[0], GAME[3] - GAME[1]
    a = (first[0], first[1], first[0] + w, first[1] + h)
    b = (other[0], other[1], other[0] + w, other[1] + h)
    fits: Any = display._fits  # pyright: ignore[reportPrivateUsage]
    assert fits(a, LEFT.work) and fits(b, LEFT.work)
    assert a[3] + 20 <= b[1]  # 겹치지 않게 세로로
    # 넓은 주 모니터에서는 가로로 나란히
    small = (0, 0, 600, 400)
    assert display.pair_layout(small, small, 20, {DISPLAY_ENV: "primary"}) == ((0, 0), (620, 0))
    with pytest.raises(ValueError):
        display.pair_layout((0, 0, 1100, 1000), (0, 0, 1100, 1000), 20, LEFT_ENV)


def test_offscreen_position_uses_edge_away_from_primary(fake_monitors: None) -> None:
    client = (-1052, 223, 1024, 640)
    bounds = [m.bounds for m in ALL]
    # 기본: 가장 오른쪽 모니터의 오른쪽 경계 (검사 원래 배치)
    x, _ = display.offscreen_position(client, GAME, bounds, 8, {})
    assert x + (client[0] - GAME[0]) + client[2] == 3000 + 8
    # 왼쪽 모니터: 그 왼쪽 경계에 클라이언트 왼쪽 8열 — 창 오른쪽 끝도 왼쪽 모니터 안
    x, y = display.offscreen_position(client, GAME, bounds, 8, LEFT_ENV)
    assert x + (client[0] - GAME[0]) == -1080 - 8
    assert x + (GAME[2] - GAME[0]) <= 0 and y == -404 + 50
    # 오른쪽 모니터는 오른쪽 경계, 양옆에 모니터가 있는 주 모니터면 가장 오른쪽 경계
    for spec in ("right", "primary"):
        x, _ = display.offscreen_position(client, GAME, bounds, 8, {DISPLAY_ENV: spec})
        assert x + (client[0] - GAME[0]) + client[2] == 3000 + 8


def test_in_process_tk_window_hooked(fake_monitors: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # 검사 프로세스 안에서 직접 만드는 tkinter 창(doctor 점검 창)도 세션 훅이 그 모니터에 둔다
    import tkinter

    from kookabug_platform.doctor import _ProbeWindow  # pyright: ignore[reportPrivateUsage]

    # 세션 훅(이 pytest가 KOOKABUG_TEST_DISPLAY=left·right로 돌면 이미 걸려 있음)을 걷어 내고 감싸기
    # 전 원래 메서드에서 시작한다 — 표시만 지우면 바깥 훅이 안쪽에 남아 좌표를 다시 옮긴다
    wm: Any = tkinter.Wm
    pristine = getattr(wm, "_kb_original_wm_geometry", wm.wm_geometry)
    for name in ("wm_geometry", "geometry"):
        monkeypatch.setattr(wm, name, pristine)
    monkeypatch.setattr(wm, "_kb_test_display", False, raising=False)
    monkeypatch.setattr(wm, "_kb_original_wm_geometry", pristine, raising=False)
    calls: list[tuple[Any, ...]] = []

    class FakeTcl:
        def call(self, *args: Any) -> Any:
            calls.append(args)
            return "0x1"

    class FakeRoot(tkinter.Wm):
        _w = "."

        def __init__(self) -> None:
            self.tk: Any = FakeTcl()

        def update(self) -> None:
            pass

        def destroy(self) -> None:
            pass

    class FakeCanvas:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __getattr__(self, name: str) -> Any:
            return lambda *args, **kwargs: None

    assert display.install_tk_hook(LEFT_ENV) == (LEFT, ALL)
    monkeypatch.setattr(tkinter, "Tk", FakeRoot)
    monkeypatch.setattr(tkinter, "Canvas", FakeCanvas)
    probe = _ProbeWindow()
    probe._stop.set()  # pyright: ignore[reportPrivateUsage]
    probe._run()  # pyright: ignore[reportPrivateUsage]
    assert probe.error is None
    geometry = [c[3] for c in calls if c[:2] == ("wm", "geometry")]
    # 원래 360x200+120+120(주 모니터) → 왼쪽 작업 영역 안 (창 틀 여유 포함)
    assert geometry == ["360x200+-376+120"]


def test_session_plugin_installs_hook_in_test_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 플러그인이 세션 시작 때 검사 프로세스 자신에 훅을 건다 (값이 있을 때만)
    from kb_testing.proc import inner_pytest

    test_file = tmp_path / "test_hooked.py"
    test_file.write_text(
        "import tkinter\n"
        "def test_hooked():\n"
        "    assert getattr(tkinter.Wm, '_kb_test_display', False)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(DISPLAY_ENV, "primary")
    result = inner_pytest(test_file)
    assert result.returncode == 0, result.stdout + result.stderr
    monkeypatch.delenv(DISPLAY_ENV)
    unhooked = inner_pytest(test_file)
    assert unhooked.returncode == 1, unhooked.stdout + unhooked.stderr


# ---------------------------------------------------------------- 검수 2차 회귀 (display_review_2)


def test_reserve_env_only_with_display() -> None:
    assert display.reserve_env(1280, 800, {}) == {}
    assert display.reserve_env(1280, 800, LEFT_ENV) == {display.RESERVE_ENV: "1280x800"}


def grown_outer(geometry: str, client: tuple[int, int]) -> tuple[int, int, int, int]:
    """Tk geometry로 놓인 창을 제품 `set_client_size`로 키운 뒤의 외곽 (실제 크기 계산, 96 DPI).

    검수 재현과 같은 길: 창 조회·변경 API만 대역이고 `AdjustWindowRectExForDpi`는 실제 함수다.
    `SWP_NOMOVE`라 왼쪽 위는 Tk가 놓은 자리 그대로다."""
    from unittest.mock import patch

    from kookabug_platform import windows
    from kookabug_platform.win32 import user32

    pos = re.fullmatch(r"\d+x\d+\+(-?\d+)\+(-?\d+)", geometry)
    assert pos is not None, geometry
    x, y = int(pos[1]), int(pos[2])
    sized: list[tuple[int, int]] = []

    def resized(_hwnd: Any, _after: Any, _x: int, _y: int, w: int, h: int, flags: int) -> bool:
        assert flags & user32.SWP_NOMOVE
        sized.append((w, h))
        return True

    style = lambda _hwnd, index: 0x00CF0000 if index == user32.GWL_STYLE else 0  # noqa: E731
    with (
        patch.object(user32, "IsWindow", return_value=True),
        patch.object(user32, "IsIconic", return_value=False),
        patch.object(user32, "GetWindowLongPtrW", side_effect=style),
        patch.object(user32, "GetMenu", return_value=0),
        patch.object(user32, "GetDpiForWindow", return_value=96),
        # 창 DPI 인식은 PMv2(가짜 창), 모니터는 못 읽음 → 96: 이 PC 배율과 무관하게 96 DPI 계산
        patch.object(
            user32,
            "GetWindowDpiAwarenessContext",
            return_value=user32.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
        ),
        patch.object(user32, "MonitorFromWindow", return_value=0),
        patch.object(user32, "SetWindowPos", side_effect=resized),
        patch.object(windows, "_client_size", return_value=client),
    ):
        assert windows.set_client_size(1, *client)
    w, h = sized[-1]
    return x, y, x + w, y + h


@pytest.mark.parametrize("spec", ["left", "right"])
def test_resize_after_reserved_placement_stays_off_primary(spec: str) -> None:
    # M1 재검증 그래프: 1024x640 게임을 1280x800으로 키운다 (네이티브 SetWindowPos, Tk 훅을 거치지
    # 않음). 예약 없이 놓으면 키운 창이 주 모니터를 침범하고(검수 반례), 예약하면 처음부터 키울
    # 자리에 놓여 주 모니터를 가리지 않는다
    chosen = display.pick(spec, ALL)
    adjust: Any = display._adjust  # pyright: ignore[reportPrivateUsage]
    plain = grown_outer(adjust(FakeWindow(), "1024x640", chosen, ALL, {}), (1280, 800))
    reserved_env = {DISPLAY_ENV: spec, **display.reserve_env(1280, 800, {DISPLAY_ENV: spec})}
    geometry = adjust(FakeWindow(), "1024x640", chosen, ALL, reserved_env)
    grown = grown_outer(geometry, (1280, 800))
    if spec == "left":
        assert plain[2] > MAIN.bounds[0]  # 반례: 예약 없으면 주 모니터 침범
        assert grown[2] <= MAIN.bounds[0]  # 왼쪽 위를 그대로 두고 키워도 주 모니터 밖
    else:
        assert grown[0] >= MAIN.bounds[2]
    # 키우기 전(1024x640) 창도 주 모니터를 가리지 않는다
    before = grown_outer(geometry, (1024, 640))
    assert before[2] <= MAIN.bounds[0] or before[0] >= MAIN.bounds[2]
    # 세로는 고른 모니터 작업 영역 안
    assert chosen.work[1] <= grown[1] and grown[3] <= chosen.work[3]
