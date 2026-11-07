"""에이전트 제어 실행의 기록 강제 (M7 계획 3.4a·10장 R2): 워크스페이스가 비밀값을 가리지 않아도(D3
기본) 에이전트 제어 실행은 실행 사양으로 스크린샷·영상을 끄고 비밀값을 가린다. 그래프로 시작한
일반 실행은 D3 그대로.

실제 `kookabug mcp` → daemon → runner(가짜 예제 게임)로, 비밀값 입력 실행과 같은 창의 다음 실행(없는
target 클릭 실패 — 실패 증거·썸네일이 생기는 경로)을 잇는다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env

from kb_testing.daemon import daemon_env
from kb_testing.fake_game import PASSWORD_FIELD, START_BUTTON, WINDOW, FakeGame, make_fake_game
from kb_testing.mcp_client import McpClient
from kb_testing.proc import Spawned, wait_until
from kookabug_core.record import read_run_json

pytestmark = [pytest.mark.process, pytest.mark.timeout(600)]

SECRET = "PWQ4417ZX"
"""검사 전용 가짜 비밀값."""
PASSWORD_BOX = [400, 285, 320, 50]
OVERRIDE = {"by": "agent_control", "redact_secrets": True, "screenshots": "off", "video": "off"}
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".mp4", ".webm")


def game_env(tmp_path: Path) -> dict[str, str]:
    env = cli_env(tmp_path, None, KOOKABUG_SECRET_ACC_PW=SECRET)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp_path / "user")
    return env


@pytest.fixture
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path) -> FakeGame:
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", SECRET)
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    game = make_fake_game(tmp_path)
    record = json.loads((game.root / "kookabug.json").read_text("utf-8"))["record"]
    assert "redact_secrets" not in record and record["screenshots"] == "on"  # D3 기본 워크스페이스
    return game


def files(folder: Path) -> list[Path]:
    return [p for p in folder.rglob("*") if p.is_file()]


def test_agent_control_run_events_redacted_default_workspace(
    game: FakeGame, tmp_path: Path, spawned: Spawned
) -> None:
    with game.daemon(game_env(tmp_path)) as d:
        mcp = McpClient.start(spawned, game.root, tmp_path / "mcp", env=daemon_env(tmp_path))
        try:
            mcp.initialize()
            mcp.data("kb_toolset_enable", {"toolsets": ["observe", "control", "run"]})
            for point in (START_BUTTON, PASSWORD_FIELD):
                mcp.data("kb_input_click", {"window": WINDOW, "point": list(point)})
            typed = mcp.data("kb_input_type", {"window": WINDOW, "secret": "acc.pw"})
            # 양성 대조군: 게임에 값이 갔고(상태·입력 기록) 원본 캡처에 값이 보인다
            assert game.state()["forms"]["login"]["values"]["password"] == SECRET
            assert sum(x["op"] == "text" for x in game.inputs()) == len(SECRET)
            with d.client() as ui:
                (window,) = ui.call("windows.list", {})["windows"]
                frame = ui.call("target.capture", {"window": window["handle"]})
                read = ui.call(
                    "target.read_text", {"frame_id": frame["frame_id"], "rect": PASSWORD_BOX}
                )
                assert SECRET in read["text"].replace(" ", "").upper(), read
            # 같은 창의 다음 실행: 지금 화면에 없는 일반 target 클릭 → 실패(실패 증거 경로)
            missed = mcp.call_tool(
                "kb_input_click",
                {"window": WINDOW, "target": "targets/world/minimap.target.json"},
                timeout=180,
            )
            assert missed["isError"] or missed["structuredContent"]["verdict"] != "pass", missed
            raw = b"\n".join(mcp.lines).decode("utf-8", "replace")
            assert SECRET not in raw
            run_ids = [typed["run_id"]]
        finally:
            mcp.close()
        with d.client() as ui:
            wait_until(lambda: all(r["state"] == "ended" for r in ui.call("run.list", {})["runs"]))
    folders = game.run_folders()
    assert len(folders) == 4  # 클릭 2 + 비밀값 입력 + 실패한 target 클릭
    for folder in folders:
        run_json = read_run_json(folder / "run.json")
        assert run_json is not None and run_json["source"] == "agent_control"
        assert run_json["record_override"] == OVERRIDE
        # 이미지 기록 없음 (스크린샷·실패 증거·썸네일·영상). 스냅샷의 target 템플릿 PNG는
        # 워크스페이스 파일 사본이라 화면 기록이 아니다
        recorded = [p for p in files(folder) if "snapshot" not in p.relative_to(folder).parts]
        assert [p for p in recorded if p.suffix.casefold() in IMAGE_SUFFIXES] == []
        # 이벤트·run.json·로그·스냅샷 어디에도 값이 없다
        for path in files(folder):
            assert SECRET.encode() not in path.read_bytes(), path
    assert any(f.name.endswith(run_ids[0]) for f in folders)
    failed = [f for f in folders if (read_run_json(f / "run.json") or {}).get("verdict") != "pass"]
    assert len(failed) == 1  # 실패 실행에도 이미지 증거가 없다 (위에서 확인)
    # 워크스페이스·사용자 설정 파일은 바꾸지 않았다
    record = json.loads((game.root / "kookabug.json").read_text("utf-8"))["record"]
    assert "redact_secrets" not in record and record["screenshots"] == "on"


def secret_graph() -> dict[str, Any]:
    """사람이 그래프로 시작하는 실행: 창 붙기 → 비밀값 입력 → 통과."""
    from kookabug_core.documents import template

    value = template("test", "비밀값 입력 (일반 실행)")
    value.pop("layout", None)
    value["nodes"] = {
        "n_entry": {"type": "core.graph.entry", "version": 1, "next": {"start": "n_attach"}},
        "n_attach": {
            "type": "core.window.attach",
            "version": 1,
            "in": {"title": f"/^{WINDOW}$/"},
            "next": {"found": "n_type"},
        },
        "n_type": {
            "type": "core.input.type_text",
            "version": 1,
            "in": {"text": {"$secret": "acc.pw"}},
            "next": {"done": "n_miss"},
        },
        # 제어 실행 검사와 같은 실패 증거 경로: 지금 화면에 없는 target 클릭
        "n_miss": {
            "type": "core.image.click",
            "version": 1,
            "in": {"target": {"$target": "targets/world/minimap.target.json"}, "timeout_ms": 1500},
            "next": {"done": "n_pass"},
        },
        "n_pass": {"type": "core.test.pass", "version": 1},
    }
    return value


def test_graph_runs_keep_d3_policy(game: FakeGame, tmp_path: Path) -> None:
    path = game.root / "tests" / "secret_type.graph.json"
    path.write_text(json.dumps(secret_graph()), encoding="utf-8")
    with game.daemon(game_env(tmp_path)) as d, d.client() as ui:
        started = ui.call("run.start", {"path": "tests/secret_type.graph.json"})
        wait_until(
            lambda: ui.call("run.status", {"run_id": started["run_id"]})["state"] == "ended",
            timeout=120,
        )
    (folder,) = game.run_folders()
    run_json = read_run_json(folder / "run.json")
    assert run_json is not None and run_json["verdict"] != "pass", run_json
    # 일반 실행은 실행별 기록 강제가 없고, 워크스페이스 정책(D3 — 가리지 않음)대로 남긴다
    assert "record_override" not in run_json and "source" not in run_json
    shots = [
        p
        for p in files(folder)
        if p.suffix.casefold() == ".png" and "snapshot" not in p.relative_to(folder).parts
    ]
    assert shots  # 스크린샷 on·가림 없음(D3): 비밀값 입력 스텝 화면도 남는다
