"""daemon 가짜 캡처 (M7 계획 3.12): 숨은 `--platform-fake` 사양에 장면 표가 있으면 `windows.list`·
`target.capture`가 제어 실행(runner)과 같은 가짜 게임 상태로 답한다. 검사 전용 키(`state_file`·
`draw_fields`)는 제품 경로에 새지 않는다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers.cli import cli_env

from kb_testing.fake_game import START_BUTTON, WINDOW, make_fake_game
from kookabug_core.record import read_run_json
from kookabug_core.runner.spec import PlatformSpec, SpecError
from kookabug_core.schema import check_shape
from kookabug_platform.frames import decode_image

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-f", "attended": False}
FRAMES = Path(__file__).resolve().parents[3] / "fixtures" / "sample-game" / "frames"
TEST_KEYS = ("state_file", "draw_fields")


def env_of(tmp_path: Path) -> dict[str, str]:
    env = cli_env(tmp_path, None)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp_path / "user")
    return env


def same_scene(pixels: object, scene: str) -> bool:
    import numpy as np

    expected = decode_image((FRAMES / f"{scene}.png").read_bytes())
    return bool(np.array_equal(np.asarray(pixels), expected))


def test_daemon_fake_capture_follows_state(tmp_path: Path) -> None:
    game = make_fake_game(tmp_path, draw=False)
    with game.daemon(env_of(tmp_path)) as d, d.client(AGENT) as agent, d.client() as ui:
        (window,) = ui.call("windows.list", {})["windows"]
        assert (window["title"], window["pid"], window["client_size"]) == (
            WINDOW,
            4001,
            [1024, 640],
        )
        first = ui.call("target.capture", {"window": window["handle"]})
        assert same_scene(d.daemon.frames.get(first["frame_id"]).pixels, "title")
        # 제어 실행(별도 runner 프로세스)이 바꾼 장면을 daemon 캡처가 그대로 본다
        done = agent.call(
            "control.click", {"window": WINDOW, "point": list(START_BUTTON)}, timeout=120
        )
        assert done["verdict"] == "pass", done
        assert game.state()["scene"] == "login"
        after = ui.call("target.capture", {"window": window["handle"]})
        assert same_scene(d.daemon.frames.get(after["frame_id"]).pixels, "login")
        # 캡처 한 번 = 한 프레임 (runner와 같은 소비 규칙)
        captures = game.state()["captures"]
        ui.call("target.capture", {"window": window["handle"]})
        assert game.state()["captures"] == captures + 1
        # 창이 닫히면 목록에서 빠진다
        game.set_window(open=False)
        assert ui.call("windows.list", {})["windows"] == []


def test_state_file_not_in_product_paths(tmp_path: Path) -> None:
    # 실제 플랫폼·장면 없는 가짜에는 상태 파일을 쓸 수 없다
    with pytest.raises(SpecError):
        PlatformSpec("windows", state_file="x.json")
    with pytest.raises(SpecError):
        PlatformSpec("fake", state_file="x.json")
    # 제품 설정 파일 형식에는 그 키가 없다
    for key in TEST_KEYS:
        workspace = {"format": "kookabug.workspace/0", key: "x"}
        assert check_shape(workspace), key
        settings = {"format": "kookabug.user-settings/0", key: "x"}
        assert check_shape(settings), key
    # 실제로 돌린 실행의 run.json 조건·스냅샷 kookabug.json에도 없다
    game = make_fake_game(tmp_path)
    with game.daemon(env_of(tmp_path)) as d, d.client(AGENT) as agent:
        agent.call("control.key", {"window": WINDOW, "keys": "enter"}, timeout=120)
    (folder,) = game.run_folders()
    run_json = read_run_json(folder / "run.json")
    assert run_json is not None and run_json["conditions"]["platform"] == "fake"
    texts = [
        (folder / "run.json").read_text("utf-8"),
        (folder / "snapshot" / "kookabug.json").read_text("utf-8"),
        (game.root / "kookabug.json").read_text("utf-8"),
    ]
    for text in texts:
        for key in TEST_KEYS:
            assert key not in text
    # 사용자 설정 폴더에도 쓰지 않는다
    user = tmp_path / "user"
    if user.exists():
        assert not any(
            key in p.read_text("utf-8", "replace")
            for p in user.rglob("*")
            if p.is_file()
            for key in TEST_KEYS
        )
    assert json.loads(game.platform.read_text("utf-8"))["state_file"]  # 숨은 사양에만 있다
