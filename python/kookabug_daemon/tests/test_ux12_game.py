"""UX12 2a — 사람(앱 마법사)이 띄운 게임을 기억: Agent가 `@game`으로 쓰고, `kb_app_launch`는 같은
게임을 또 띄우지 않는다. 사람이 다시 띄우면 사람이 전에 띄운 게임을 끝낸다(UX8 B와 같은 규칙).
실제 daemon + 장면 가짜 게임(`launch_fake` — 띄운 가짜 게임 창이 생긴다)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.packaging import REPO_ROOT
from kb_testing.sample_game import copy_example_workspace

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-ux12g", "attended": False}


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    root = copy_example_workspace(tmp_path)
    frames = tmp_path / "frames"
    shutil.copytree(REPO_ROOT / "fixtures" / "sample-game" / "frames", frames)
    spec = tmp_path / "platform.json"
    spec.write_text(
        json.dumps({"scenario": str(frames / "scenario.json"), "launch_fake": True}),
        encoding="utf-8",
    )
    local = root / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8")) if local.exists() else {}
    body.setdefault("format", "kookabug.local/0")
    body["settings"] = {"game.executable": "C:/Games/Sample/Game.exe"}
    body["permissions"] = {"preset": "full", "rules": []}
    local.parent.mkdir(exist_ok=True)
    local.write_text(json.dumps(body), encoding="utf-8")
    return root, spec


def test_agent_uses_human_launched_game(tmp_path: Path) -> None:
    root, spec = _workspace(tmp_path)
    with (
        ThreadDaemon(root, platform_fake=spec) as d,
        d.client() as ui,
        d.client(AGENT) as agent,
    ):
        human = ui.call("app.launch", {})
        # 자기 기억이 없어도 @game은 사람이 띄운 게임이다
        step = agent.call("explore.step", {"window": "@game"}, timeout=120)
        assert step["window"] == "@game" and step["frame"]["width"] > 0
        # kb_app_launch는 새로 띄우지 않고 그 게임을 쓴다 (사람 게임은 그대로)
        again = agent.call("app.launch", {})
        assert again == {"pid": human["pid"], "reused": True}
        assert [w["pid"] for w in ui.call("windows.list")["windows"]] == [human["pid"]]
        # 사람이 다시 띄우면 사람이 전에 띄운 게임을 끝낸다 — 게임은 계속 하나
        second = ui.call("app.launch", {})
        assert second["replaced_pid"] == human["pid"]
        assert [w["pid"] for w in ui.call("windows.list")["windows"]] == [second["pid"]]
        # Agent의 다음 띄우기도 새 사람 게임을 쓴다
        third = agent.call("app.launch", {})
        assert third == {"pid": second["pid"], "reused": True}


def test_human_reuse_goes_through_launch_checks(tmp_path: Path) -> None:
    """검수 1 High 4: 사람 게임 재사용도 시작 잠금 안의 검사(검증 중 거부)를 지나고, 자기 이전
    게임을 끝내면 입력 세대를 올린다."""
    from kookabug_daemon.client import DaemonError

    root, spec = _workspace(tmp_path)
    with (
        ThreadDaemon(root, platform_fake=spec) as d,
        d.client() as ui,
        d.client(AGENT) as agent,
    ):
        manager = d.daemon.run_manager
        previous = agent.call("app.launch", {})["pid"]
        human = ui.call("app.launch", {})["pid"]
        manager.begin_verification()
        try:
            with pytest.raises(DaemonError) as caught:
                agent.call("app.launch", {})
            assert caught.value.kind == "verification_active"
            pids = [w["pid"] for w in ui.call("windows.list")["windows"]]
            assert previous in pids and human in pids  # 아무것도 끄지 않았다
        finally:
            manager.end_verification()
        before = manager.input_epoch()
        reused = agent.call("app.launch", {})
        assert reused == {"pid": human, "reused": True, "replaced_pid": previous}
        assert manager.input_epoch() == before + 1  # 이전 게임을 끝냈다
        assert [w["pid"] for w in ui.call("windows.list")["windows"]] == [human]
