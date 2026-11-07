"""비밀값 보호 검사의 양성 대조군 (M7 계획 3.12): 검사 전용 `draw_fields`로 가짜 게임 캡처에 칸 값이
평문으로 그려진다 — 에이전트가 입력한 테스트 비밀값이 **원본 프레임에 실제로 보인다**(같은 OCR로
읽힌다). 보호 검사(`test_frame_guard.py`)는 이것을 먼저 확인한 뒤 출구에 값이 없음을 본다."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers.cli import cli_env

from kb_testing.fake_game import PASSWORD_FIELD, START_BUTTON, WINDOW, make_fake_game

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

SECRET = "PWQ4417ZX"
"""검사 전용 가짜 비밀값."""
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-d", "attended": False}
PASSWORD_BOX = [400, 285, 320, 50]


def game_env(tmp_path: Path) -> dict[str, str]:
    env = cli_env(tmp_path, None, KOOKABUG_SECRET_ACC_PW=SECRET)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp_path / "user")
    return env


def test_typed_secret_visible_in_raw_frame(
    tmp_path: Path, ocr_models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", SECRET)  # daemon 사전 검증 (이 프로세스)
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    game = make_fake_game(tmp_path)
    with game.daemon(game_env(tmp_path)) as d, d.client(AGENT) as agent, d.client() as ui:
        for point in (START_BUTTON, PASSWORD_FIELD):
            done = agent.call(
                "control.click", {"window": WINDOW, "point": list(point)}, timeout=120
            )
            assert done["verdict"] == "pass", done
        typed = agent.call("control.type", {"window": WINDOW, "secret": "acc.pw"}, timeout=120)
        assert typed["verdict"] == "pass", typed
        # 게임 쪽에는 값이 갔다 (가짜 입력 기록은 글자 수만, 게임 상태 파일에 값)
        assert sum(x["op"] == "text" for x in game.inputs()) == len(SECRET)
        assert game.state()["forms"]["login"]["values"]["password"] == SECRET
        # 사람 연결의 원본 캡처: 그 칸에 값이 평문으로 그려져 OCR로 읽힌다
        (window,) = ui.call("windows.list", {})["windows"]
        frame = ui.call("target.capture", {"window": window["handle"]})
        read = ui.call("target.read_text", {"frame_id": frame["frame_id"], "rect": PASSWORD_BOX})
        assert SECRET in read["text"].replace(" ", "").upper(), read
