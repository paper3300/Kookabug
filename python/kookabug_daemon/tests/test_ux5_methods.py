"""UX5 daemon 쪽 — 실제 daemon(ThreadDaemon)으로.

- 작업 연결의 `knowledge.apply`가 그 작업 플레이북의 사람 질문 규칙을 받는다: init은 첫 사람
  질문부터 `question_limit`, entry는 credential만, triage는 그대로
- `unknowns.answer`(사람)의 credential 답: 키가 등록되기 전에는 `secret_missing`, 등록 뒤에는 키
  이름만 담은 고정 글 (보낸 글·값이 지식에 남지 않는다)
- `entry` 플레이북: job.begin 허용·`agent-job playbooks` 목록·도구 범위
- `kookabug secret set`: 표준 입력 값 → 자격 증명 관리자 (Windows), 에이전트 환경은 거부
"""

from __future__ import annotations

import io
import json
import sys
from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.proc import wait_until
from kb_testing.sample_game import copy_example_workspace
from kookabug_cli import secret_cmd
from kookabug_core import playbooks
from kookabug_core.agent_job import jobdir
from kookabug_core.workspace import Workspace, secret_env_name, workspace_id
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

VALUE = "ux5-pass-Zq81"


def agent(agent_id: str, token: str) -> dict[str, Any]:
    return {"kind": "agent", "name": "mcp", "version": "0", "id": agent_id, "job_token": token}


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = copy_example_workspace(tmp_path)
    local = root / ".kookabug" / "local.json"
    local.parent.mkdir(exist_ok=True)
    local.write_text(
        json.dumps({"format": "kookabug.local/0", "permissions": {"preset": "curator"}}), "utf-8"
    )
    return root


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws) as d:
        yield d


def unknowns_revision(conn: DaemonClient) -> int:
    doc = conn.call("knowledge.get", {"file": "unknowns"}).get("doc") or {}
    return int(doc.get("revision", 0))


def add_unknown(conn: DaemonClient, rid: str, item: dict[str, Any]) -> dict[str, Any]:
    op = {"op": "add", "file": "unknowns", "base_revision": unknowns_revision(conn), "item": item}
    return dict(conn.call("knowledge.apply", {"request_id": rid, "ops": [op]}, timeout=60))


def refused(fn: Any) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        fn()
    return caught.value


QUESTION = {
    "question": "게임 창 제목은 무엇인가요",
    "human_only": True,
    "blocks": [],
    "how": "확인",
}
LOGIN = {
    "question": "로그인 화면이에요. 첫 단추를 눌러 봤지만 계정 칸이 비어 있어요",
    "human_only": True,
    "blocks": [],
    "how": "사람이 테스트 계정을 등록한다",
    "kind": "credential",
    "secret_keys": ["login.id", "login.password"],
}


def begin(daemon: ThreadDaemon, ws: Path, playbook: str) -> dict[str, Any]:
    job = daemon.begin_job({"playbook": playbook})
    (ws / jobdir.JOBS_DIR / job["job"]).mkdir(parents=True, exist_ok=True)
    return job


def test_question_rule_follows_job_playbook(daemon: ThreadDaemon, ws: Path) -> None:
    init = begin(daemon, ws, "init")
    with daemon.client(agent(init["agent_id"], init["token"])) as conn:
        err = refused(lambda: add_unknown(conn, "i1", QUESTION))
        assert err.kind == "question_limit" and "모르는 것" in str(err)
        # 사람 질문이 아닌 미지수는 된다 (양성 대조)
        assert add_unknown(conn, "i2", {**QUESTION, "human_only": False})["applied"] is True
    with daemon.client() as ui:
        ui.call("job.end", {"job": init["job"], "reason": "cancelled"}, timeout=60)

    entry = begin(daemon, ws, "entry")
    with daemon.client(agent(entry["agent_id"], entry["token"])) as conn:
        assert refused(lambda: add_unknown(conn, "e1", QUESTION)).kind == "question_limit"
        assert add_unknown(conn, "e2", LOGIN)["applied"] is True
    with daemon.client() as ui:
        ui.call("job.end", {"job": entry["job"], "reason": "cancelled"}, timeout=60)

    triage = begin(daemon, ws, "triage")
    with daemon.client(agent(triage["agent_id"], triage["token"])) as conn:
        assert add_unknown(conn, "t1", QUESTION)["applied"] is True


def bare(agent_id: str) -> dict[str, Any]:
    """작업 토큰 없는 Agent 연결."""
    return {"kind": "agent", "name": "mcp", "version": "0", "id": agent_id}


def hello_refused(daemon: ThreadDaemon, info: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        DaemonClient.connect(daemon.port, daemon.session.token, client=info)
    return caught.value


@pytest.mark.parametrize("playbook", ["init", "followup", "entry"])
def test_job_agent_without_token_refused(daemon: ThreadDaemon, ws: Path, playbook: str) -> None:
    """검수 1 High: 작업에 예약된 Agent ID로 토큰을 빼고 붙어 질문 규칙을 피하지 못한다."""
    job = begin(daemon, ws, playbook)
    aid = job["agent_id"]
    # 검수 2 High: 대소문자·공백·서식 문자 변형도 작업 이름공간으로 본다
    # 검수 3 High: 닮은 콜론(RATIO 등)·전각 글자 — 토큰 없는 ID는 공백 없는 ASCII만
    rest = aid.removeprefix("job:")
    homoglyphs = [f"job{chr(c)}{rest}" for c in (0x2236, 0xA789, 0x02D0, 0xFF1A)]
    zwsp = chr(0x200B)
    for variant in (aid, aid.upper(), f" {aid}", f"{aid} ", f"{zwsp}{aid}", "JOB:x", *homoglyphs):
        assert hello_refused(daemon, bare(variant)).kind == "job_token_invalid", variant
    wide_mcp = "".join(chr(ord(ch) + 0xFEE0) for ch in "mcp") + ":7"
    assert hello_refused(daemon, bare(wide_mcp)).kind == "job_token_invalid"
    # 다른 작업의 토큰도 거부 (기존 bind 검사 — 확인만)
    other = "job:j-20261113-000000-ffff"
    assert hello_refused(daemon, agent(other, job["token"])).kind == "job_token_invalid"
    # 양성: 정상 토큰 연결은 붙고 그 작업 규칙이 걸린다
    with daemon.client(agent(job["agent_id"], job["token"])) as conn:
        assert refused(lambda: add_unknown(conn, f"{playbook}-q", QUESTION)).kind == (
            "question_limit"
        )
    # 양성: 패널 Agent·작업과 무관한 Agent ID는 지금처럼 붙는다 (작업 밖 연결)
    for other_id in ("panel:s-1", "mcp:7"):
        with daemon.client(bare(other_id)) as conn:
            assert conn.call("knowledge.get", {"file": "unknowns"}) is not None
    # 작업이 끝나도 job: 이름공간은 토큰 전용이다 (검수 2 결정)
    with daemon.client() as ui:
        ui.call("job.end", {"job": job["job"], "reason": "cancelled"}, timeout=300)
    wait_until(lambda: not daemon.daemon.jobs.reserved(job["agent_id"]), message="작업 끝")
    assert hello_refused(daemon, bare(job["agent_id"])).kind == "job_token_invalid"


def test_credential_answer_needs_registered_keys_and_keeps_no_value(
    daemon: ThreadDaemon, ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = begin(daemon, ws, "entry")
    with daemon.client(agent(entry["agent_id"], entry["token"])) as conn:
        add_unknown(conn, "c1", LOGIN)
    with daemon.client() as ui:
        item = ui.call("knowledge.get", {"file": "unknowns"})["doc"]["unknowns"][0]
        assert item["kind"] == "credential" and item["secret_keys"] == [
            "login.id",
            "login.password",
        ]
        params = {"id": item["id"], "base_rev": item["rev"], "text": VALUE}
        assert refused(lambda: ui.call("unknowns.answer", params)).kind == "secret_missing"
        # 환경 변수 비밀값도 등록으로 본다 (자격 증명 관리자를 쓰지 않는 검사)
        monkeypatch.setenv(secret_env_name("login.id"), "qa")
        monkeypatch.setenv(secret_env_name("login.password"), VALUE)
        ui.call("unknowns.answer", params)
        after = ui.call("knowledge.get", {"file": "unknowns"})["doc"]["unknowns"][0]
    assert after["state"] == "answered" and "login.password" in after["answer"]["text"]
    for path in (ws / "knowledge").rglob("*"):
        if path.is_file():
            assert VALUE.encode() not in path.read_bytes(), path


def test_entry_playbook_registered(daemon: ThreadDaemon, ws: Path) -> None:
    assert "entry" in playbooks.NAMES
    book = playbooks.load("entry")
    assert {"graph_edit", "knowledge", "cases", "control", "screens", "run"} <= set(book.tools)
    job = begin(daemon, ws, "entry")
    with daemon.client() as ui:
        listed = ui.call("jobs.list", {})["jobs"]
        assert any(j.get("job") == job["job"] and j.get("playbook") == "entry" for j in listed)
    # "이어서 진행"이 entry를 다시 이어 갈 때도 같은 agent-job run 경로 (CLI가 entry를 받는다)
    from kookabug_cli.main import build_parser

    args = build_parser().parse_args(
        ["agent-job", "run", "--workspace", str(ws), "--playbook", "entry", "--agent", "custom"]
    )
    assert args.playbook == "entry"


def _args(action: str, key: str, ws: Path, **extra: Any) -> Namespace:
    return Namespace(action=action, key=key, workspace=str(ws), json=True, replace=False, **extra)


def test_secret_cli_refuses_agent_and_bad_input(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setenv("KOOKABUG_AGENT", "job:x")
    assert secret_cmd.run(_args("set", "login.id", ws), out, err, io.StringIO("v\n")) == 5
    monkeypatch.delenv("KOOKABUG_AGENT")
    assert secret_cmd.run(_args("set", "../bad", ws), out, err, io.StringIO("v\n")) == 1
    for bad in ("", "\n", "a\nb\n", "x" * 2000):
        assert secret_cmd.run(_args("set", "login.id", ws), out, err, io.StringIO(bad)) == 1
    assert "value_invalid" in out.getvalue()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 자격 증명 관리자")
def test_secret_cli_writes_credential_only(ws: Path) -> None:
    from kookabug_core.win.credentials import CredentialStore

    out, err = io.StringIO(), io.StringIO()
    try:
        code = secret_cmd.run(
            _args("set", "login.password", ws), out, err, io.StringIO(VALUE + "\n")
        )
        assert code == 0, out.getvalue()
        wid = workspace_id(Workspace.open(ws))
        assert wid is not None and CredentialStore().read(wid, "login.password") == VALUE
        # 이미 있으면 거부 (바꾸기는 --replace)
        assert secret_cmd.run(_args("set", "login.password", ws), out, err, io.StringIO("x\n")) == 1
        assert VALUE not in out.getvalue() and VALUE not in err.getvalue()
        # 값은 워크스페이스 파일 어디에도 없다 (ID만 kookabug.json에)
        for path in ws.rglob("*"):
            if path.is_file():
                assert VALUE.encode() not in path.read_bytes(), path
    finally:
        wid = workspace_id(Workspace.open(ws))
        if wid is not None:
            store = CredentialStore()
            for key in store.keys(wid):
                store.delete(wid, key)
