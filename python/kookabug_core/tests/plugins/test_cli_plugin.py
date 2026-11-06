"""`kookabug plugin …` 명령 (M6 계획 3.7·3.9): 에이전트 거부·확인 필요·동시 작업."""

from __future__ import annotations

import json

import pytest
from helpers.plugins import Rig, plugin_cli

from kookabug_core.plugins import Layout

pytestmark = [pytest.mark.packaging, pytest.mark.process, pytest.mark.timeout(600)]


def test_agent_env_refused_exit5(rig: Rig) -> None:
    wheel = rig.world.wheel("sample")
    for args in (
        ("add", wheel, "--yes", "--json"),
        ("remove", "sample", "--yes", "--json"),
        ("upgrade", "sample", "--yes", "--json"),
        ("sync", "--yes", "--json"),
        ("relock", "--yes", "--json"),
        ("gc", "--yes", "--json"),
    ):
        proc = plugin_cli(rig, *args, KOOKABUG_AGENT="agent-1")
        assert proc.returncode == 5, proc.stdout + proc.stderr
        assert json.loads(proc.stdout)["error"]["code"] == "permission_denied"
    assert rig.lock_bytes() is None
    assert not (rig.root / ".kookabug" / "plugins").exists()
    # 목록은 에이전트도 본다
    listed = plugin_cli(rig, "list", "--json", KOOKABUG_AGENT="agent-1")
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout)["plugins"] == []


def test_non_interactive_needs_yes_exit6(rig: Rig) -> None:
    proc = plugin_cli(rig, "add", rig.world.wheel("sample"), "--json")
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["error"]["code"] == "confirm_required"
    assert rig.lock_bytes() is None
    staging = rig.root / ".kookabug" / "plugins" / "staging"
    assert not staging.exists() or not any(staging.iterdir())
    # --yes면 설치된다
    done = plugin_cli(rig, "add", rig.world.wheel("sample"), "--yes", "--json")
    assert done.returncode == 0, done.stdout + done.stderr
    body = json.loads(done.stdout)
    assert body["ok"] is True and body["plugin"]["id"] == "sample"
    listed = json.loads(plugin_cli(rig, "list", "--json").stdout)
    assert [(p["id"], p["env_status"]) for p in listed["plugins"]] == [("sample", "ready")]


def test_concurrent_ops_busy(rig: Rig) -> None:
    with Layout(rig.root).busy():
        proc = plugin_cli(rig, "add", rig.world.wheel("sample"), "--yes", "--json")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["error"]["code"] == "plugin_busy"
    assert rig.lock_bytes() is None
