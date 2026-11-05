"""부품 합성 가짜 프레임 원천·가짜 세계 (M4 계획 2.9 "가짜 원천", 검수 M10, T8).

가짜 사람이 각본 입력을 장면 상태에 적용하고, 원천이 입력 칸 상태(포커스 테두리·값·가림 글자)를
장면 그림 위에 그린다. 실제 게임 캡처와 같은지는 데스크톱 검사
(`fixtures/sample-game/tests/test_fake_frame_parts.py`)가 본다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from kb_testing.recorder_scripts import LOGIN_SCRIPTS, login_script
from kb_testing.sample_game import FRAMES_DIR, GAME_DIR
from kookabug_platform.recorder.fake_frames import (
    FIELD_EDGE,
    FIELD_FOCUS,
    FIELD_TEXT,
    FakeWorld,
)

SCENARIO = FRAMES_DIR / "scenario.json"
ACCOUNT = (400, 205, 320, 50)
PASSWORD = (400, 285, 320, 50)
MS = 1_000_000


def border(image: np.ndarray, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    x, y, _w, h = box
    b, g, r = (int(v) for v in image[y + h // 2, x])
    return b, g, r


def mask_dots(image: np.ndarray, box: tuple[int, int, int, int]) -> int:
    """칸 가운데 줄에서 글자 색 덩어리 수 (가림 글자 수)."""
    x, y, w, h = box
    row = image[y + h // 2, x + 4 : x + w - 4]
    lit = np.all(np.abs(row.astype(int) - np.array(FIELD_TEXT)) < 40, axis=1)
    return int(np.count_nonzero(lit[1:] & ~lit[:-1]) + (1 if lit[0] else 0))


def test_fake_frame_source_draws_focus_and_mask() -> None:
    world = FakeWorld(login_script(split=True), SCENARIO)
    assert world.state.scene == "title"
    world.advance_to(1000 * MS)
    assert world.state.scene == "login"  # 시작 단추 클릭 (뗄 때)
    login = world.client_pixels()
    assert border(login, ACCOUNT) == FIELD_FOCUS and border(login, PASSWORD) == FIELD_EDGE
    world.advance_to(3500 * MS)  # 계정 글자 다 친 뒤, Tab 전
    typed = world.client_pixels()
    assert world.state.forms["login"]["values"]["account"] == "qa_tester_01"
    x, y, w, h = ACCOUNT
    inside = typed[y + 4 : y + h - 4, x + 4 : x + w - 4]
    assert np.any(np.all(np.abs(inside.astype(int) - np.array(FIELD_TEXT)) < 40, axis=2))
    world.advance_to(4100 * MS)  # Tab 뒤: 포커스가 비밀번호 칸으로
    moved = world.client_pixels()
    assert border(moved, ACCOUNT) == FIELD_EDGE and border(moved, PASSWORD) == FIELD_FOCUS
    world.advance_to(5000 * MS)  # `sample-` 일곱 글자 (쉬는 중)
    assert mask_dots(world.client_pixels(), PASSWORD) == 7
    # 링에는 테두리 있는 버퍼가 시각 차례로 들어 있고, 마지막 프레임 = 지금 그림
    latest = world.ring.latest()
    assert latest is not None
    gen = world.geometry.frame_generation(latest.arrival_ns, latest.buffer_size)
    assert gen is not None
    assert np.array_equal(gen.geometry.crop_client(latest.buffer), world.client_pixels())
    world.advance_to(12_000 * MS)
    assert world.state.scene == "lobby"  # 고른 값이 맞아 `when.valid`로 로비
    world.close()


def test_recorder_scripts_fresh() -> None:
    """`fixtures/sample-game/recorder/*.script.jsonl` = 생성기 결과
    (`python tools/kb_testing/recorder_scripts.py`로 다시 만든다)."""
    import json

    folder = Path(GAME_DIR) / "recorder"
    for name, kwargs in LOGIN_SCRIPTS.items():
        lines = [
            json.loads(line)
            for line in (folder / f"{name}.script.jsonl").read_text("utf-8").splitlines()
        ]
        assert lines == json.loads(json.dumps(login_script(**kwargs))), name
