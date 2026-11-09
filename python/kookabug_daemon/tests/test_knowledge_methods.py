"""지식 메서드 (M8 계획 3.3·3.13, 9장 R4의 B4 부분) — 실제 연결 주체로 쓰기 경계가 걸리는가.

`knowledge.apply`·`wiki.write`는 연결의 실제 주체(`Actor` — 작업 토큰이면 작업 ID까지)와 보호 기록의
글자 검사기로 코어 연산을 부른다. Agent의 `expected` 주장 고치기는 팀 파일이 아니라 작업 기준 주장
덧씌움으로 가고, 사람은 팀 파일에 쓴다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import copy_example_workspace
from kookabug_daemon.client import DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

SHOP = "knowledge/features/shop.json"
WORKING = "knowledge/working/claims/shop.json"
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "panel", "attended": True}


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = copy_example_workspace(tmp_path)
    local = root / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["permissions"] = {"preset": "curator"}
    local.write_text(json.dumps(body), encoding="utf-8")
    return root


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws) as d:
        yield d


def revise(value: int, base_rev: int) -> dict[str, Any]:
    return {
        "op": "revise",
        "file": "features/shop",
        "id": "shop.potion.price",
        "base_rev": base_rev,
        "changes": {"value": value},
    }


def log(ws: Path) -> list[dict[str, Any]]:
    lines = (ws / "knowledge" / "log.jsonl").read_text("utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_expected_revise_via_daemon_stays_working(ws: Path, daemon: ThreadDaemon) -> None:
    team = (ws / SHOP).read_bytes()
    with daemon.client() as ui:
        job = ui.call("job.begin", {"playbook": "repair"})
    info = {**AGENT, "id": job["agent_id"], "attended": False, "job_token": job["token"]}
    with daemon.client(info) as agent:
        done = agent.call("knowledge.apply", {"request_id": "r1", "ops": [revise(120, 1)]})
        assert done["results"][0]["basis"] == "working"
        # 같은 request_id는 같은 작업 안에서 지난 결과
        assert agent.call("knowledge.apply", {"request_id": "r1", "ops": [revise(120, 1)]})[
            "replayed"
        ]
        got = agent.call("knowledge.get", {"file": "features/shop", "id": "shop.potion.price"})
        assert got["item"]["value"] == 100 and got["working"][0]["claim"]["value"] == 120
        found = agent.call("knowledge.search", {"query": "체력 물약"})
        assert [m["id"] for m in found["matches"]] == ["shop.potion.price"]
    assert (ws / SHOP).read_bytes() == team
    over = json.loads((ws / WORKING).read_text("utf-8"))
    assert over["claims"][0]["claim"]["value"] == 120
    entry = next(e for e in log(ws) if e.get("request_id") == "r1")
    assert entry["job"] == job["job"] and entry["agent"]["kind"] == "agent"
    # 사람은 팀 파일에 쓴다
    with daemon.client() as ui:
        ui.call("knowledge.apply", {"request_id": "h1", "ops": [revise(130, 1)]})
    assert json.loads((ws / SHOP).read_text("utf-8"))["claims"][0]["value"] == 130


def test_agent_wiki_and_policy_paths(ws: Path, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        done = agent.call(
            "wiki.write", {"path": "wiki/features/shop.md", "text": "# 상점\n", "base_sha256": None}
        )
        assert done["rendered_claims"] is True
        for path in ("AGENTS.md", "wiki/index.md", "wiki/reports/x.md", "kookabug.json"):
            with pytest.raises(DaemonError) as caught:
                agent.call("wiki.write", {"path": path, "text": "x", "base_sha256": None})
            assert caught.value.kind == "policy_path", path
        with pytest.raises(DaemonError) as caught:
            agent.call(
                "knowledge.apply",
                {
                    "request_id": "c1",
                    "ops": [
                        {
                            "op": "revise",
                            "file": "cheats",
                            "id": "give_gold",
                            "base_rev": 1,
                            "changes": {"adoption": {"category": "dev_safe"}},
                        }
                    ],
                },
            )
        assert caught.value.kind == "adoption_reserved"
    shown = (ws / "wiki" / "features" / "shop.md").read_text("utf-8")
    assert "shop.potion.price" in shown  # 주장 표는 Kookabug가 다시 넣는다
