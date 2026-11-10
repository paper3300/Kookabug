"""M8 사람 전용 메서드 전수 (계획 3.13, B4) — 엄격: Agent 권한.

검사는 표 하나(`HUMAN_ONLY_M8`)에서 만든다. M8 이름공간의 `ui_only` 메서드가 빠짐없이 그 표에
있는지, 그 표의 모든 메서드를 가장 넓은 Agent(사람 있는 `full`, 작업 토큰 연결 `full`)가 불러도
판정 전에 `permission_denied`이고 워크스페이스가 바뀌지 않는지 실제 daemon으로 본다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import copy_example_workspace
from kookabug_daemon.client import DaemonError
from kookabug_daemon.methods.tools import AGENT_DENIED, HUMAN_ONLY_M8, METHOD_TOOLS
from kookabug_daemon.protocol import UI_ONLY, methods

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

M8_SPACES = {
    "adopt", "adoptions", "working", "cases", "evidence", "knowledge", "wiki", "job", "jobs",
    "report", "reports", "unknowns", "cheats", "project", "sources", "wizard",
}  # fmt: skip
SHA = "0" * 64
CASE = "c-20261110-000000-abcd"
JOB = "j-20261110-000000-abcd"

# 메서드마다 형식 검사를 지나는 인자 (형식에서 막히면 판정 전 거부를 보지 못한다)
PARAMS: dict[str, dict[str, Any]] = {
    "cheats.list": {},
    "cheats.adopt": {"id": "give_gold", "rev": 1, "category": "dev_safe"},
    "cheats.unadopt": {"id": "give_gold", "rev": 1},
    "cheats.categories.set": {"base_sha256": SHA, "categories": [], "enabled": True},
    "adopt.revert": {"adoption": "a-20261110-000000-abcd"},
    "adoptions.list": {},
    "working.list": {},
    "working.accept": {"changes": ["w-20261110-000000-abcd"]},
    "working.reject": {"changes": ["w-20261110-000000-abcd"]},
    "cases.close": {"id": CASE, "base_revision": 1, "state": "resolved"},
    "unknowns.answer": {"id": "u-20261110-000000-abcd", "base_rev": 1, "text": "답"},
    "project.automation.set": {"base_sha256": SHA, "value": {"forbidden": []}},
    "project.sources.set": {"base_sha256": SHA, "value": []},
    "sources.check": {},
    "job.begin": {"playbook": "triage"},
    "job.end": {"job": JOB, "reason": "cancelled"},
    "job.finish": {"job": JOB},
    "job.heartbeat": {"job": JOB},
    "jobs.list": {},
    "reports.list": {},
    "reports.get": {"job": JOB},
    "report.decide": {"job": JOB, "group": "g", "decision": "accept"},
    "wizard.get": {},
    "wizard.set": {"wizard": {}},
}


def tree_digest(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and not rel.startswith((".kookabug/", "runs/")):
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = copy_example_workspace(tmp_path)
    local = root / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["permissions"] = {"preset": "full"}
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return root


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws) as d:
        yield d


def test_table_covers_every_m8_ui_only_method() -> None:
    contract = methods()
    m8_ui_only = {
        name
        for name, info in contract.items()
        if info.tool == UI_ONLY and name.split(".")[0] in M8_SPACES
    }
    assert m8_ui_only == HUMAN_ONLY_M8
    assert HUMAN_ONLY_M8 <= AGENT_DENIED
    assert all(METHOD_TOOLS[m] == UI_ONLY for m in HUMAN_ONLY_M8)
    assert set(PARAMS) == HUMAN_ONLY_M8


def test_all_human_methods_denied_for_agent(ws: Path, daemon: ThreadDaemon) -> None:
    before = tree_digest(ws)
    # 소유 연결을 열어 둔다 (R8: 끊기면 작업이 끝나 토큰이 무효)
    begun = daemon.begin_job({"playbook": "triage"})
    clients = [
        {"kind": "agent", "name": "mcp", "version": "0", "id": "panel", "attended": True},
        {
            "kind": "agent",
            "name": "mcp",
            "version": "0",
            "id": begun["agent_id"],
            "attended": False,
            "job_token": begun["token"],
        },
    ]
    for info in clients:
        with daemon.client(info) as agent:
            for method in sorted(HUMAN_ONLY_M8):
                with pytest.raises(DaemonError) as caught:
                    agent.call(method, PARAMS[method], timeout=60)
                assert caught.value.kind == "permission_denied", (info["id"], method)
    assert tree_digest(ws) == before
    # 사람 연결은 판정 전 거부가 없다 (처리기가 없는 B5·B7 메서드는 method_not_found)
    with daemon.client() as ui:
        for method in ("cases.close", "unknowns.answer", "job.finish", "wizard.get"):
            with pytest.raises(DaemonError) as caught:
                ui.call(method, PARAMS[method], timeout=60)
            assert caught.value.kind != "permission_denied", method


def test_human_policy_writes(ws: Path, daemon: ThreadDaemon) -> None:
    """사람 연결의 정책·원본 쓰기는 `kookabug.json`의 그 블록만, sha 대조 (Agent 경로 없음)."""
    config = ws / "kookabug.json"
    with daemon.client() as ui:
        base = hashlib.sha256(config.read_bytes()).hexdigest()
        with pytest.raises(DaemonError) as caught:
            ui.call("project.automation.set", {"base_sha256": SHA, "value": {}})
        assert caught.value.kind == "revision_conflict"
        value = {
            "format": "kookabug.automation/0",
            "forbidden": [{"kind": "text", "value": "결제"}, {"kind": "screen", "id": "x"}],
        }
        done = ui.call("project.automation.set", {"base_sha256": base, "value": value})
        written = json.loads(config.read_text("utf-8"))
        assert written["automation"] == value
        assert done["sha256"] == hashlib.sha256(config.read_bytes()).hexdigest()
        sources = [{"id": "item_table", "kind": "data", "title": "아이템", "path": "items.csv"}]
        ui.call("project.sources.set", {"base_sha256": done["sha256"], "value": sources})
        checked = ui.call("sources.check", {})
        assert [(s["id"], s["state"]) for s in checked["sources"]] == [("item_table", "missing")]
