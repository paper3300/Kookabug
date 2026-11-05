"""부품 합성 그림 = 같은 상태의 실제 게임 캡처 (M4 계획 2.9, 검수 M10, T8). **데스크톱 입력 검사**
(`desktop_input`) — 실제 예제 게임에 클릭·글자를 넣고 WGC로 찍는다. 조율자가 잠금 해제 데스크톱에서
돌린다.

같은 상태(로그인 장면, 계정 칸 값, 비밀번호 칸 포커스·가림 글자 수)를 가짜 원천의 `draw_forms`로
그린 그림과 비교한다. 글자 글리프는 OpenCV 글꼴이라 모양이 다르다 — 칸 테두리 색(포커스·아님),
가림 글자 수, 칸 밖 그림, 칸 안 글자가 시작하는 자리를 본다.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from kb_testing.keys import button_input, key_input, release_all_for_test, send_inputs
from kb_testing.recorder_scripts import ACCOUNT, ACCOUNT_POINT, START_POINT, char_vk
from kb_testing.sample_game import FRAMES_DIR, capture_client, launch_sample_game
from kookabug_core.engine.scenario import FakeScenario, ScenarioState
from kookabug_platform.dpi import per_monitor_v2_thread
from kookabug_platform.recorder.fake_frames import draw_forms
from kookabug_platform.recorder.scripted_frames import png_scenes
from kookabug_platform.windows import activate, window_info

pytestmark = [pytest.mark.desktop_input, pytest.mark.timeout(120)]

FIELDS = {"account": (400, 205, 320, 50), "password": (400, 285, 320, 50)}
MASKED = "sample"


def _click(hwnd: int, point: tuple[int, int]) -> None:
    import ctypes

    with per_monitor_v2_thread():
        origin = window_info(hwnd).client_origin
        ctypes.windll.user32.SetCursorPos(origin[0] + point[0], origin[1] + point[1])
    time.sleep(0.15)
    send_inputs(button_input("mouse:left"), button_input("mouse:left", up=True))
    time.sleep(0.4)


def _type(text: str) -> None:
    for ch in text:
        vk, shift = char_vk(ch)
        if shift:
            send_inputs(key_input(0xA0))
        send_inputs(key_input(vk), key_input(vk, up=True))
        if shift:
            send_inputs(key_input(0xA0, up=True))
        time.sleep(0.06)


def _dots(image: np.ndarray, box: tuple[int, int, int, int]) -> int:
    x, y, w, h = box
    row = image[y + h // 2, x + 4 : x + w - 4].astype(int)
    lit = row.mean(axis=1) > 160
    return int(np.count_nonzero(lit[1:] & ~lit[:-1]) + (1 if lit[0] else 0))


def test_composed_form_matches_real_capture(tmp_path: Path) -> None:
    game = launch_sample_game(workdir=tmp_path / "game")
    try:
        activate(game.hwnd)
        _click(game.hwnd, START_POINT)
        game.wait_screen("login")
        _click(game.hwnd, ACCOUNT_POINT)
        _type(ACCOUNT)
        send_inputs(key_input(0x09), key_input(0x09, up=True))
        time.sleep(0.2)
        _type(MASKED)
        time.sleep(0.5)
        real = capture_client(game.hwnd)
    finally:
        release_all_for_test()
        game.close()
    scenario = FakeScenario.load(FRAMES_DIR / "scenario.json")
    state = ScenarioState(scenario.spec)
    state.scene = "login"
    state.forms["login"] = {
        "values": {"account": ACCOUNT, "password": MASKED},
        "focus": "password",
        "selected": False,
    }
    base = png_scenes(FRAMES_DIR)("login", scenario.client_size)
    composed = draw_forms(base, scenario.spec, state, scenario.client_size)
    assert real.shape == composed.shape
    for name, (x, y, _w, h) in FIELDS.items():
        a = real[y + h // 2, x].astype(int)
        b = composed[y + h // 2, x].astype(int)
        assert np.abs(a - b).max() <= 16, (name, a, b)  # 테두리 색 (포커스·아님)
    assert _dots(real, FIELDS["password"]) == _dots(composed, FIELDS["password"]) == len(MASKED)
    # 칸 밖은 같은 그림
    outside = np.ones(real.shape[:2], dtype=bool)
    for x, y, w, h in FIELDS.values():
        outside[y - 4 : y + h + 4, x - 4 : x + w + 4] = False
    diff = np.abs(real.astype(int) - composed.astype(int)).max(axis=2)
    assert float(diff[outside].mean()) < 3.0
    # 계정 칸 글자는 같은 자리(왼쪽 14 px)에서 시작한다
    x, y, w, h = FIELDS["account"]
    for image in (real, composed):
        cols = np.nonzero(
            (image[y + 8 : y + h - 8, x + 4 : x + w - 4].mean(axis=2) > 160).any(axis=0)
        )[0]
        assert cols.size and 6 <= int(cols[0]) <= 18
