"""개발 모듈 daemon의 에이전트 실행 거부 (M6 계획 3.7·D11, rev1 H3).

daemon이 `--plugin-module`(개발 모듈)로 떠 있으면 에이전트 연결의 `run.start`·`control.*`은
runner를 띄우기 전(사람 확인도 묻기 전) `permission_denied`(이유 `dev_modules_agent`)다. 사람(ui)
연결은 그대로 개발 모듈 실행을 쓴다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers.daemon_runs import TEST, RunRig
from helpers.graphs import GraphBuilder

from kb_testing.daemon import ThreadDaemon
from kookabug_daemon.client import DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(180)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-dev"}


def _allow_everything(rig: RunRig) -> None:
    path = rig.root / ".kookabug" / "local.json"
    path.parent.mkdir(exist_ok=True)
    body = {"format": "kookabug.local/0", "permissions": {"preset": "full"}}
    path.write_text(json.dumps(body), encoding="utf-8")


def _run_folders(rig: RunRig) -> list[Path]:
    runs = rig.root / "runs"
    return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() else []


def test_agent_run_start_refused_on_dev_daemon(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, GraphBuilder().entry("n").node("n", "core.test.pass"))
    _allow_everything(rig)
    with rig.daemon() as d, d.client(AGENT) as agent:
        with pytest.raises(DaemonError) as caught:
            agent.call("run.start", {"path": TEST})
        assert caught.value.kind == "permission_denied"
        assert caught.value.data["reason"] == "dev_modules_agent"
        with pytest.raises(DaemonError) as control:
            agent.call("control.click", {"window": "SampleRPG", "point": [1, 1]}, timeout=60)
        assert control.value.kind == "permission_denied"
        assert control.value.data["reason"] == "dev_modules_agent"
        # runner를 띄우지 않았다: 실행 폴더가 없다
        assert _run_folders(rig) == []


def test_human_still_runs_dev_modules(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, GraphBuilder().entry("n").node("n", "core.test.pass"))
    with rig.daemon() as d, d.client() as ui:
        started = ui.call("run.start", {"path": TEST})
        ended = ui.call("run.status", {"run_id": started["run_id"]})
        assert ended["run_id"] == started["run_id"]
        manager = d.daemon.run_manager
        outcome = manager.wait_outcome(started["run_id"], 60)
        assert outcome is not None
        assert outcome.run_end is not None and outcome.run_end["verdict"] == "pass"


def test_agent_runs_on_daemon_without_dev_modules(tmp_path: Path) -> None:
    """회귀: 개발 모듈 없는 daemon에서는 에이전트 실행이 기존 판정대로 된다."""
    rig = RunRig.make(tmp_path, GraphBuilder().entry("n").node("n", "core.test.pass"))
    _allow_everything(rig)
    plain = ThreadDaemon(rig.root, service=rig.service(), platform_fake=rig.platform)
    with plain as d, d.client(AGENT) as agent:
        started = agent.call("run.start", {"path": TEST})
        outcome = d.daemon.run_manager.wait_outcome(started["run_id"], 60)
        assert outcome is not None
        assert outcome.run_end is not None and outcome.run_end["verdict"] == "pass"
