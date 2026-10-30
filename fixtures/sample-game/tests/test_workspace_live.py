"""예제 워크스페이스를 실제 Windows 플랫폼(WGC 캡처·SendInput)으로 돌린다 (구현 계획 M1 T12,
2.14 #1).

제품 CLI(`kookabug run`)가 감독자이고, 게임은 그래프의 `core.app.launch`가 실행 Job 안에서 띄운다
(실행이 끝나면 Job이 정리한다). 게임이 실제로 받은 것은 입력 수신 기록(`--event-log`)으로 본다.
실제 입력 검사는 시작 전에 눌린 키가 없는지 보고, 끝에 눌린 것을 뗀다(`kb_testing.keys`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from helpers.cli import cli_env, run_cli

from kb_testing.keys import assert_no_keys_held, release_all_for_test
from kb_testing.sample_game import EXAMPLE_SECRET_ENV, EXAMPLE_SECRETS, copy_example_workspace

INVENTORY_OPEN = "tests/inventory_open.graph.json"


@pytest.fixture
def no_keys_left() -> Iterator[None]:
    assert_no_keys_held()
    try:
        yield
    finally:
        release_all_for_test()


@pytest.mark.desktop_input
@pytest.mark.usefixtures("no_keys_left")
def test_inventory_open_pass_real(tmp_path: Path, ocr_models: Path) -> None:
    ws = copy_example_workspace(tmp_path)
    event_log = tmp_path / "game.jsonl"
    args = ["-m", "sample_game", "--event-log", str(event_log)]
    env = cli_env(tmp_path, None, **EXAMPLE_SECRET_ENV, KOOKABUG_OCR_MODELS=str(ocr_models))
    done = run_cli(
        ["run", INVENTORY_OPEN, "--json", "--set", f"game.args={json.dumps(args)}"],
        cwd=ws,
        env=env,
        timeout=240,
    )
    lines = event_log.read_text(encoding="utf-8").splitlines() if event_log.exists() else []
    events = [json.loads(line) for line in lines if line.strip()]
    assert done.returncode == 0, (done.stdout, done.stderr, events)
    out = json.loads(done.stdout)
    assert (out["verdict"], out["code"]) == ("pass", "assertion_passed"), out
    # 게임이 실제로 지나간 화면: 타이틀 → 로그인 → 로비(Server 1 고름) → 로딩 → 월드 → 인벤토리
    scenes = [e["scene"] for e in events if e["event"] == "screen"]
    for scene in ("title", "login", "lobby", "lobby_server1", "loading", "world", "inventory"):
        assert scene in scenes, scenes
    assert scenes.index("login") < scenes.index("lobby_server1") < scenes.index("inventory")
    typed = "".join(e["text"] for e in events if e["event"] == "char")
    assert "qa_tester_01" in typed and EXAMPLE_SECRETS["accounts.qa_tester_01"] in typed
