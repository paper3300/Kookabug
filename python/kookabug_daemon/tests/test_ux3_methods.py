"""UX3 (Agent 읽기 허용 폴더) daemon 쪽 — 실제 daemon(ThreadDaemon)으로.

- 저장: 사람 전용 `local.settings.set`(`agent.read_roots`)이 허용하지 않는 폴더를 `policy_path`
  (`reason`·`index`)로 거부하고, 받은 목록은 `local.json`에만 쓴다. `wizard.get`은 목록과 자동 포함
  줄(실효 게임 실행 파일 폴더)을 준다
- Agent 연결(패널·작업)은 `local.settings.set`으로 직접 설정하지 못한다
- 읽기: 작업 Agent가 `kb_source_list`·`kb_source_read`로 워크스페이스 밖 읽기 허용 폴더와 자동
  포함 게임 폴더를 읽는다(가림·활동 목록 대상 `read:<…>:경로`)
- 제안: `agent.read_roots.add`(값은 이 PC `proposals.json`에만) → 사람 수락이 6단계와 같은 검사·
  저장으로 반영, 허용하지 않는 폴더는 제안 단계에서 거부
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.proc import wait_until
from kb_testing.sample_game import copy_example_workspace
from kookabug_core.agent_job import jobdir
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

KEY = "agent.read_roots"


def agent(agent_id: str, token: str | None = None) -> dict[str, Any]:
    hello: dict[str, Any] = {"kind": "agent", "name": "mcp", "version": "0", "id": agent_id}
    if token is not None:
        hello["job_token"] = token
    return hello


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8-sig"))


@pytest.fixture
def game(tmp_path: Path) -> Path:
    folder = tmp_path / "game"
    folder.mkdir()
    (folder / "Game.exe").write_bytes(b"MZ\0\0")
    (folder / "servers.json").write_text('{"servers": ["dev"]}', "utf-8")
    return folder


@pytest.fixture
def tools(tmp_path: Path) -> Path:
    folder = tmp_path / "launch_tools"
    folder.mkdir()
    (folder / "launch.bat").write_bytes(b"@echo off\nGame.exe -server=dev\n")
    (folder / ".env").write_bytes(b"TOKEN=x\n")
    return folder


@pytest.fixture
def ws(tmp_path: Path, game: Path) -> Path:
    local = {"game.executable": str(game / "Game.exe"), "game.cwd": str(game)}
    root = copy_example_workspace(tmp_path, local)
    path = root / ".kookabug" / "local.json"
    body = read_json(path)
    body["permissions"] = {"preset": "curator"}
    path.write_text(json.dumps(body, ensure_ascii=False), "utf-8")
    return root


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws) as d:
        yield d


def refused(conn: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        conn.call(method, params, timeout=60)
    return caught.value


def test_save_read_roots_checks_and_wizard_view(
    daemon: ThreadDaemon, ws: Path, tools: Path, game: Path
) -> None:
    local = ws / ".kookabug" / "local.json"
    with daemon.client() as ui:
        view = ui.call("wizard.get", {})["read_roots"]
        assert view["paths"] == []
        assert view["auto"] == [
            {
                "id": "read:game",
                "path": str(game),
                "title": "게임 실행 파일 폴더(자동)",
                "state": "ok",
                "reason": None,
                "message": None,
            }
        ]
        revision = ui.call("wizard.get", {})["local_revision"]
        # 허용하지 않는 폴더: 저장하지 않고 이유·몇째 줄 (6단계가 그대로 보인다)
        before = local.read_bytes()
        for bad, why in ((ws.parent, "contains_workspace"), (Path(ws.anchor), "drive_root")):
            err = refused(
                ui,
                "local.settings.set",
                {"base_revision": revision, "settings": {KEY: [str(tools), str(bad)]}},
            )
            assert err.kind == "policy_path"
            assert err.data["reason"] == why and err.data["index"] == 1
            assert str(bad) not in err.message
        assert local.read_bytes() == before
        saved = ui.call(
            "local.settings.set",
            {"base_revision": revision, "settings": {KEY: [str(tools), " ", str(tools)]}},
        )
        assert read_json(local)["settings"][KEY] == [str(tools)]
        assert ui.call("wizard.get", {})["read_roots"]["paths"] == [str(tools)]
        # 빈 목록은 키를 지운다 (자동 포함만 남는다)
        ui.call("local.settings.set", {"base_revision": saved["revision"], "settings": {KEY: []}})
        assert KEY not in read_json(local)["settings"]
        # 자동 포함이 허용하지 않는 폴더면 빼고 경고 (워크스페이스 안 파생 폴더를 작업 폴더로)
        body = read_json(local)
        body["settings"]["game.cwd"] = str(ws / "knowledge")
        local.write_text(json.dumps(body, ensure_ascii=False), "utf-8")
        auto = {a["id"]: a for a in ui.call("wizard.get", {})["read_roots"]["auto"]}
        assert auto["read:game_cwd"]["state"] == "refused"
        assert auto["read:game_cwd"]["reason"] == "workspace_derived"
        assert auto["read:game_cwd"]["message"]


def test_agent_cannot_set_read_roots_directly(daemon: ThreadDaemon, ws: Path, tools: Path) -> None:
    local = ws / ".kookabug" / "local.json"
    before = local.read_bytes()
    job = daemon.begin_job({"playbook": "followup"})
    for hello in (agent("panel"), agent(job["agent_id"], job["token"])):
        with daemon.client(hello) as conn:
            err = refused(conn, "local.settings.set", {"settings": {KEY: [str(tools)]}})
            assert err.kind == "permission_denied"
    assert local.read_bytes() == before


def test_job_agent_reads_read_roots(
    daemon: ThreadDaemon, ws: Path, tools: Path, game: Path
) -> None:
    with daemon.client() as ui:
        revision = ui.call("wizard.get", {})["local_revision"]
        ui.call("local.settings.set", {"base_revision": revision, "settings": {KEY: [str(tools)]}})
    job = daemon.begin_job({"playbook": "init"})
    (ws / jobdir.JOBS_DIR / job["job"]).mkdir(parents=True)  # runner가 만드는 작업 폴더
    (tools / "token.txt").write_bytes(f"token={job['token']}".encode())
    with daemon.client(agent(job["agent_id"], job["token"])) as conn:
        listed = {s["id"]: s for s in conn.call("sources.list", {})["sources"]}
        assert listed["read:1"] == {
            "id": "read:1",
            "kind": "read_root",
            "title": str(tools),
            "state": "ok",
            "type": "dir",
        }
        assert listed["read:game"]["state"] == "ok"
        names = [e["name"] for e in conn.call("sources.list", {"source": "read:1"})["entries"]]
        assert names == ["launch.bat", "token.txt"]  # .env는 목록에서 뺀다
        got = conn.call("sources.read", {"source": "read:1", "path": "launch.bat"})
        assert "Game.exe -server=dev" in got["text"] and got["ref"] == "read:1#launch.bat"
        masked = conn.call("sources.read", {"source": "read:1", "path": "token.txt"})["text"]
        assert masked == "token=***"
        servers = conn.call("sources.read", {"source": "read:game", "path": "servers.json"})
        assert '"dev"' in servers["text"]
        assert refused(conn, "sources.read", {"source": "read:1", "path": ".env"}).kind == (
            "policy_path"
        )
        assert refused(conn, "sources.read", {"source": "read:1", "path": "../x"}).kind == (
            "policy_path"
        )
        assert refused(conn, "sources.read", {"source": "read:7", "path": "a"}).kind == (
            "not_found"
        )
    with daemon.client() as ui:
        wait_until(
            lambda: any(
                e["target"] == "read:1:launch.bat"
                for e in ui.call("jobs.activity", {"job": job["job"]})["entries"]
            ),
            timeout=15,
            message=lambda: str(ui.call("jobs.activity", {"job": job["job"]})["entries"]),
        )


def test_read_root_proposal_accept(daemon: ThreadDaemon, ws: Path, tools: Path) -> None:
    job = daemon.begin_job({"playbook": "followup"})
    with daemon.client(agent(job["agent_id"], job["token"])) as conn:
        conn.call("agent.toolsets.enable", {"toolsets": ["cases"]})

        def propose(value: str) -> dict[str, Any]:
            return conn.call(
                "setting.propose",
                {"key": "agent.read_roots.add", "value": value, "reason": "실행 bat 읽기"},
            )

        propose(str(tools))
        # 허용하지 않는 폴더는 제안 단계에서 거부
        err = refused(
            conn,
            "setting.propose",
            {"key": "agent.read_roots.add", "value": str(ws.parent), "reason": "r"},
        )
        assert err.kind == "policy_path" and err.data["reason"] == "contains_workspace"
    # 제안만으로는 바뀌지 않는다
    assert KEY not in read_json(ws / ".kookabug" / "local.json").get("settings", {})
    with daemon.client() as ui:
        ui.call("job.end", {"job": job["job"], "reason": "cancelled"}, timeout=300)
        report = ui.call("reports.get", {"job": job["job"]})["report"]
        group = next(
            g for g in report["groups"]
            if g["items"][0]["kind"] == "setting_change"
            and g["items"][0]["setting"]["key"] == "agent.read_roots.add"
        )  # fmt: skip
        assert group["items"][0]["setting"]["local"]["value"] == str(tools)
        # 값(이 PC 경로)은 팀 보고 파일에 없다
        team = (ws / "knowledge" / "reports" / f"{job['job']}.json").read_text("utf-8")
        assert json.dumps(str(tools))[1:-1] not in team
        ui.call("report.decide", {"job": job["job"], "group": group["key"], "decision": "accept"})
        assert read_json(ws / ".kookabug" / "local.json")["settings"][KEY] == [str(tools)]
        assert ui.call("sources.read", {"source": "read:1", "path": "launch.bat"})["text"]
