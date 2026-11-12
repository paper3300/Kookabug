"""UX2 (Init 질문 답 이후 흐름) daemon 쪽 — 실제 daemon(ThreadDaemon)으로.

- A `sources.list`·`sources.read`(`kb_source_list`·`kb_source_read`): 워크스페이스 **밖** 임시
  폴더를 원본으로 등록하고 작업 Agent가 읽는다. 경계 거부·작업 토큰 가림·활동 목록 대상
  (`원본id:상대경로`)
- C `setting.propose`(`kb_setting_propose`): 작업 연결 전용·허용 목록·비밀값 거부, 보고의
  `setting_change` 묶음 → 사람 `report.decide` 수락이 마법사와 같은 저장으로 반영, 그 사이
  바뀌었으면 `revision_conflict`, 거절, Agent 연결의 결정 거부
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.proc import wait_until
from kb_testing.sample_game import copy_example_workspace
from kookabug_core.agent_job import activity, jobdir
from kookabug_core.canonical import canonical_dumps
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]


def agent(agent_id: str, token: str | None = None) -> dict[str, Any]:
    hello: dict[str, Any] = {"kind": "agent", "name": "mcp", "version": "0", "id": agent_id}
    if token is not None:
        hello["job_token"] = token
    return hello


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8-sig"))


def set_local(ws: Path, **fields: Any) -> None:
    local = ws / ".kookabug" / "local.json"
    body = read_json(local) if local.exists() else {"format": "kookabug.local/0"}
    body.update(fields)
    local.parent.mkdir(exist_ok=True)
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    docs = tmp_path / "outside_plans"
    (docs / "plan").mkdir(parents=True)
    (docs / "plan" / "shop.md").write_bytes("# 상점\n물약 100골드\n".encode())
    return docs


@pytest.fixture
def ws(tmp_path: Path, outside: Path) -> Path:
    root = copy_example_workspace(tmp_path)
    config = read_json(root / "kookabug.json")
    config["sources"] = [{"id": "plans", "kind": "design_doc", "title": "기획", "local": True}]
    (root / "kookabug.json").write_text(canonical_dumps(config), "utf-8")
    set_local(root, permissions={"preset": "curator"}, sources={"plans": {"path": str(outside)}})
    return root


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws) as d:
        yield d


def refused(conn: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        conn.call(method, params, timeout=60)
    return caught.value


def test_job_agent_reads_source_outside_workspace(
    daemon: ThreadDaemon, ws: Path, outside: Path
) -> None:
    job = daemon.begin_job({"playbook": "init"})
    (ws / jobdir.JOBS_DIR / job["job"]).mkdir(parents=True)  # runner가 만드는 작업 폴더
    (outside / "token.txt").write_bytes(f"token={job['token']}".encode())
    with daemon.client(agent(job["agent_id"], job["token"])) as conn:
        listed = conn.call("sources.list", {})["sources"]
        # UX3: 읽기 허용 폴더(자동 포함 게임 폴더)도 같은 목록에 온다 — 원본만 본다
        listed = [s for s in listed if s["kind"] != "read_root"]
        assert listed == [
            {"id": "plans", "kind": "design_doc", "title": "기획", "state": "ok", "type": "dir"}
        ]
        top = conn.call("sources.list", {"source": "plans"})
        assert [e["name"] for e in top["entries"]] == ["plan", "token.txt"]
        got = conn.call("sources.read", {"source": "plans", "path": "plan/shop.md"})
        assert (
            got["text"] == "# 상점\n물약 100골드\n" and got["ref"] == "sources:plans#plan/shop.md"
        )
        assert (
            got["hash"]
            == "sha256:" + hashlib.sha256((outside / "plan/shop.md").read_bytes()).hexdigest()
        )
        # 작업 토큰 원문은 가린다 (agent.log와 같은 가림)
        masked = conn.call("sources.read", {"source": "plans", "path": "token.txt"})["text"]
        assert masked == "token=***" and job["token"] not in masked
        # 경계: .. 탈출·등록 안 된 원본
        assert refused(conn, "sources.read", {"source": "plans", "path": "../x"}).kind == (
            "policy_path"
        )
        assert refused(conn, "sources.read", {"source": "nope", "path": "a"}).kind == "not_found"
        assert refused(conn, "sources.read", {"source": "plans", "path": "plan"}).kind == (
            "policy_path"
        )
        # 쓰기 메서드는 없다 — 계약에도 없다
        with daemon.client() as ui:
            wait_until(
                lambda: any(
                    e["target"] == "plans:plan/shop.md"
                    for e in ui.call("jobs.activity", {"job": job["job"]})["entries"]
                ),
                timeout=15,
                message=lambda: str(ui.call("jobs.activity", {"job": job["job"]})["entries"]),
            )
            entries = ui.call("jobs.activity", {"job": job["job"]})["entries"]
    tools = {(e["tool"], e["target"]) for e in entries}
    assert ("kb_source_read", "plans:plan/shop.md") in tools
    assert ("kb_source_list", "plans:") in tools
    raw = (ws / jobdir.JOBS_DIR / job["job"] / activity.ACTIVITY_FILE).read_text("utf-8")
    assert job["token"] not in raw


def group_of(report: dict[str, Any], key: str) -> dict[str, Any]:
    return next(
        g for g in report["groups"]
        if g["items"][0]["kind"] == "setting_change" and g["items"][0]["setting"]["key"] == key
    )  # fmt: skip


def test_setting_propose_accept_conflict_reject(
    daemon: ThreadDaemon, ws: Path, tmp_path: Path
) -> None:
    job = daemon.begin_job({"playbook": "followup"})
    new_docs = tmp_path / "more_docs"
    new_docs.mkdir()
    (new_docs / "a.md").write_bytes(b"more")
    before = (ws / "kookabug.json").read_bytes()
    with daemon.client(agent(job["agent_id"], job["token"])) as conn:
        conn.call("agent.toolsets.enable", {"toolsets": ["cases"]})

        def propose(key: str, value: Any, reason: str = "사람 답") -> dict[str, Any]:
            return conn.call("setting.propose", {"key": key, "value": value, "reason": reason})

        propose("game.title", "SampleRPG 새 창")
        propose("game.executable", "C:/Games/Sample/Game.exe")
        propose("game.cwd", "C:/Games/Sample")
        propose("sources.add", {"kind": "design_doc", "location": str(new_docs)})
        propose("automation.forbidden.add", {"kind": "text", "value": "캐릭터 삭제"})
        propose("cheats.categories.add", {"id": "qa_only", "title": "QA 전용", "unattended": True})
        # 허용 목록 밖·비밀값
        for key in ("game.client_size", "agents.default", "permissions.preset"):
            assert refused(
                conn, "setting.propose", {"key": key, "value": "x", "reason": "r"}
            ).kind == ("setting_not_allowed")
        assert (
            refused(
                conn, "setting.propose", {"key": "game.title", "value": "x", "reason": job["token"]}
            ).kind
            == "secret_in_text"
        )
    # 제안만으로는 설정이 바뀌지 않는다
    assert (ws / "kookabug.json").read_bytes() == before
    # 작업 토큰이 없는 Agent 연결은 제안하지 못한다
    with daemon.client(agent("panel")) as plain:
        plain.call("agent.toolsets.enable", {"toolsets": ["cases"]})
        assert (
            refused(
                plain, "setting.propose", {"key": "game.title", "value": "x", "reason": "r"}
            ).kind
            == "job_only"
        )
    with daemon.client() as ui:
        ui.call("job.end", {"job": job["job"], "reason": "cancelled"}, timeout=300)
        report = ui.call("reports.get", {"job": job["job"]})["report"]
        assert report["playbook"] == "followup"
        title = group_of(report, "game.title")
        assert title["title"] == "설정 바꾸기 제안 · game.title"
        # 값·현재 값은 이 PC proposals.json에서 붙여 준다 — 팀 보고 파일에는 없다 (검수 1 H1)
        local_view = title["items"][0]["setting"]["local"]
        assert local_view["current"] == "SampleRPG" and local_view["value"] == "SampleRPG 새 창"
        team = (ws / "knowledge" / "reports" / f"{job['job']}.json").read_text("utf-8")
        for leaked in ("SampleRPG 새 창", "C:/Games/Sample", str(new_docs), "캐릭터 삭제"):
            assert leaked not in team and json.dumps(leaked)[1:-1] not in team
        # Agent 연결은 결정하지 못한다 (사람 전용)
        with daemon.client(agent("panel")) as plain:
            assert (
                refused(
                    plain,
                    "report.decide",
                    {"job": job["job"], "group": title["key"], "decision": "accept"},
                ).kind
                == "permission_denied"
            )

        def decide(key: str, decision: str = "accept") -> Any:
            group = group_of(ui.call("reports.get", {"job": job["job"]})["report"], key)
            return ui.call(
                "report.decide", {"job": job["job"], "group": group["key"], "decision": decision}
            )

        decide("game.title")
        assert read_json(ws / "kookabug.json")["settings"]["game.title"] == "SampleRPG 새 창"
        decide("game.executable")
        local = read_json(ws / ".kookabug" / "local.json")
        assert local["settings"]["game.executable"] == "C:/Games/Sample/Game.exe"
        # 제안 뒤 사람이 그 설정을 바꿨으면 충돌 (적용 안 함, 결정도 안 남음)
        wizard = ui.call("wizard.get", {})
        ui.call(
            "local.settings.set",
            {"base_revision": wizard["local_revision"], "settings": {"game.cwd": "D:/Other"}},
        )
        assert refused(ui, "report.decide", {
            "job": job["job"], "group": group_of(
                ui.call("reports.get", {"job": job["job"]})["report"], "game.cwd")["key"],
            "decision": "accept"}).kind == "revision_conflict"  # fmt: skip
        assert read_json(ws / ".kookabug" / "local.json")["settings"]["game.cwd"] == "D:/Other"
        assert (
            group_of(ui.call("reports.get", {"job": job["job"]})["report"], "game.cwd")["decision"]
            is None
        )
        # 원본 추가: 6단계와 같이 팀 정의(local) + 이 PC 경로 → 곧바로 읽힌다
        decide("sources.add")
        sources = read_json(ws / "kookabug.json")["sources"]
        assert {
            "id": "design_doc",
            "kind": "design_doc",
            "title": "기획 문서",
            "local": True,
        } in sources
        assert read_json(ws / ".kookabug" / "local.json")["sources"]["design_doc"]["path"] == str(
            new_docs
        )
        assert ui.call("sources.read", {"source": "design_doc", "path": "a.md"})["text"] == "more"
        # 다른 PC에서 만든 보고(이 PC에 proposals.json 없음): 값을 못 보이고 수락은 거부,
        # 거절은 된다
        proposals = ws / jobdir.JOBS_DIR / job["job"] / "proposals.json"
        saved = proposals.read_bytes()
        proposals.unlink()
        foreign = group_of(ui.call("reports.get", {"job": job["job"]})["report"], "game.cwd")
        assert foreign["items"][0]["setting"]["local"] is None
        accept = {"job": job["job"], "group": foreign["key"], "decision": "accept"}
        assert refused(ui, "report.decide", accept).kind == "not_found"
        decide("game.cwd", "reject")
        proposals.write_bytes(saved)
        decide("automation.forbidden.add")
        forbidden = read_json(ws / "kookabug.json")["automation"]["forbidden"]
        assert {"kind": "text", "value": "캐릭터 삭제"} in forbidden
        cheats_before = read_json(ws / "kookabug.json").get("cheats")
        decide("cheats.categories.add", "reject")
        assert read_json(ws / "kookabug.json").get("cheats") == cheats_before
        final = ui.call("reports.get", {"job": job["job"]})["report"]
        assert group_of(final, "cheats.categories.add")["decision"]["decision"] == "reject"
        assert group_of(final, "game.title")["decision"]["decision"] == "accept"
        # 이미 결정한 묶음은 다시 결정하지 않는다
        assert refused(ui, "report.decide", {
            "job": job["job"], "group": group_of(final, "game.title")["key"],
            "decision": "reject"}).kind == "revision_conflict"  # fmt: skip
    log = [
        json.loads(line)
        for line in (ws / "knowledge" / "log.jsonl").read_text("utf-8").splitlines()
    ]
    ops = [line["op"] for line in log if line["op"].startswith("setting_")]
    assert ops.count("setting_accept") == 4 and ops.count("setting_reject") == 2
