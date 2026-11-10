"""`qa_runner` 보장 범위 (M8 9장 R3) — 엄격: Agent 권한.

"`qa_runner`는 그래프·target을 쓰지 못하고 직접 입력(`kb_input_*`·control 도구)을 못 하며, 팀 기준
revision 그대로의 테스트만 실행한다(작업 기준·덧씌움 실행 거부). 실행 중 치트 노드는 채택·`qa` 허용
범위만 통과한다(중첩 서브그래프 포함)." 작업 토큰 연결이어도 같다.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import copy_example_workspace
from kookabug_core import basis
from kookabug_core.knowledge.formats import Actor
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(900)]

PASS_GRAPH = "tests/shop/qa_pass.graph.json"
CHEAT_GRAPH = "tests/shop/qa_cheat.graph.json"
NESTED_GRAPH = "tests/shop/qa_nested.graph.json"
SUB = "subgraphs/cheats/wrap.graph.json"
CHEAT_NODE = {
    "config": {"args": {"amount": 1000}, "cheat": "give_gold"},
    "next": {"done": "n_pass"},
    "type": "core.qa.cheat",
    "version": 1,
}
ALLOW = {"cheats": {"allow": [{"id": "give_gold", "max_calls": 5}]}, "format": "kookabug.qa/0"}


def graph(nodes: dict[str, Any], *, kind: str = "test", qa: Any = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "format": "kookabug.graph/0",
        "kind": kind,
        "plugins": {"core": "0.1.0"},
        "nodes": nodes,
    }
    if qa is not None:
        value["qa"] = qa
    return value


def entry(to: str) -> dict[str, Any]:
    return {"type": "core.graph.entry", "version": 1, "next": {"start": to}}


PASS = {"type": "core.test.pass", "version": 1}


@pytest.fixture
def ws(tmp_path: Path, ocr_models: Path) -> Path:
    os.environ.setdefault("KOOKABUG_OCR_MODELS", str(ocr_models))
    root = copy_example_workspace(tmp_path)
    local = root / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["permissions"] = {"preset": "qa_runner"}
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    files = {
        PASS_GRAPH: graph({"n_entry": entry("n_pass"), "n_pass": PASS}),
        CHEAT_GRAPH: graph(
            {"n_entry": entry("n_cheat"), "n_cheat": CHEAT_NODE, "n_pass": PASS}, qa=ALLOW
        ),
        SUB: graph(
            {
                "n_entry": entry("n_cheat"),
                "n_cheat": {**CHEAT_NODE, "next": {"done": "n_exit"}},
                "n_exit": {"config": {"exit": "done"}, "type": "core.graph.exit", "version": 1},
            },
            kind="subgraph",
            qa=ALLOW,
        )
        | {"interface": {"exits": {"done": {"kind": "ok"}}}},
        NESTED_GRAPH: graph(
            {
                "n_entry": entry("n_call"),
                "n_call": {
                    "config": {"graph": SUB},
                    "next": {"done": "n_pass"},
                    "type": "core.graph.call",
                    "version": 1,
                },
                "n_pass": PASS,
            },
            qa=ALLOW,
        ),
    }
    for rel, value in files.items():
        (root / rel).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    # 예제 치트는 채택 전으로 둔다 (사람이 채택한 경우만 통과)
    cheats_file = root / "knowledge" / "cheats.json"
    doc = json.loads(cheats_file.read_text("utf-8"))
    for cheat in doc["cheats"]:
        cheat["adoption"] = None
    cheats_file.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return root


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws, platform_fake=ws / "fake-platform-shop.json") as d:
        yield d


def job_agent(d: ThreadDaemon) -> dict[str, Any]:
    # 워크스페이스당 끝나지 않은 작업은 하나다 (M8 R8) — 앞 작업을 끝내고 새로 만든다
    for live in d.daemon.jobs.all():
        if not live.ended.is_set():
            with d.client() as ui:
                ui.call("job.end", {"job": live.id, "reason": "done"}, timeout=300)
    job = d.begin_job({"playbook": "triage"})
    return {
        "kind": "agent",
        "name": "mcp",
        "version": "0",
        "id": job["agent_id"],
        "attended": False,
        "job_token": job["token"],
    }


PLAIN = {"kind": "agent", "name": "mcp", "version": "0", "id": "qa-1", "attended": False}


def agents(d: ThreadDaemon) -> Iterator[dict[str, Any]]:
    """작업 밖 Agent를 먼저(작업이 없을 때 — 작업 중이면 실행·입력이 `job_active`), 그다음 작업
    Agent."""
    yield PLAIN
    yield job_agent(d)


def ended(conn: DaemonClient, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 300
    while True:
        status = conn.call("run.status", {"run_id": run_id})
        if status["state"] == "ended":
            return status
        assert time.monotonic() < deadline, status
        time.sleep(0.3)


def run_json(ws: Path, run_id: str) -> dict[str, Any]:
    folder = next((ws / "runs").glob(f"*_{run_id}"))
    return json.loads((folder / "run.json").read_text("utf-8"))


def refused(conn: DaemonClient, method: str, params: dict[str, Any]) -> str:
    with pytest.raises(DaemonError) as caught:
        conn.call(method, params, timeout=120)
    return str(caught.value.kind)


def test_qa_runner_refuses_working_basis(ws: Path, daemon: ThreadDaemon) -> None:
    # 작업 기준 변경이 있어도 qa_runner 실행은 팀 기준만 (덧씌움 없음)
    pass_bytes = (ws / PASS_GRAPH).read_bytes()
    changed = pass_bytes.replace(b"core.test.pass", b"core.test.fail")
    basis.write(ws, {PASS_GRAPH: changed}, actor=Actor("agent", "other"), kind="graph")
    for info in agents(daemon):
        with daemon.client(info) as conn:
            kind = refused(
                conn, "run.start", {"path": PASS_GRAPH, "basis": "working", "idempotency_key": "w"}
            )
            assert kind == "basis_denied", info["id"]
            # 기본값은 작업 연결이어도 팀 기준
            started = conn.call("run.start", {"path": PASS_GRAPH, "idempotency_key": "t"})
            assert ended(conn, started["run_id"])["outcome"]["verdict"] == "pass"
            record = run_json(ws, started["run_id"])
            assert record["basis"]["kind"] == "team" and record["basis"]["working"] == []
    assert (ws / PASS_GRAPH).read_bytes() == pass_bytes


def test_qa_runner_no_direct_input(ws: Path, daemon: ThreadDaemon) -> None:
    before = (ws / PASS_GRAPH).read_bytes()
    for info in agents(daemon):
        with daemon.client(info) as conn:
            for method, params in (
                ("control.click", {"window": "SampleRPG 상점", "point": [1, 1]}),
                ("control.key", {"window": "SampleRPG 상점", "keys": "`"}),
                ("control.type", {"window": "SampleRPG 상점", "text": "give_gold 1"}),
                ("app.launch", {}),
                ("graph.create", {"path": "tests/shop/new.graph.json", "kind": "test"}),
                (
                    "graph.patch",
                    {
                        "path": PASS_GRAPH,
                        "base_revision": "0" * 64,
                        "ops": [{"op": "remove_node", "id": "n_pass"}],
                    },
                ),
                ("knowledge.apply", {"request_id": "r", "ops": [{"op": "add"}]}),
                ("wiki.write", {"path": "wiki/x.md", "text": "x", "base_sha256": None}),
                (
                    "adopt.request",
                    {"case": "c-20261110-000000-abcd", "change": "w-20261110-000000-abcd"},
                ),
            ):
                assert refused(conn, method, params) == "permission_denied", (info["id"], method)
            # 사건 조회·기록은 된다
            assert conn.call("cases.list", {}) == {"cases": []}
    assert (ws / PASS_GRAPH).read_bytes() == before
    assert not (ws / "tests/shop/new.graph.json").exists()


def test_qa_runner_refuses_unadopted_cheat_node(ws: Path, daemon: ThreadDaemon) -> None:
    with daemon.client(job_agent(daemon)) as conn:
        started = conn.call("run.start", {"path": CHEAT_GRAPH, "idempotency_key": "c1"})
        ended(conn, started["run_id"])
        assert run_json(ws, started["run_id"])["code"] == "cheat_not_adopted"
    with daemon.client() as ui:
        ui.call("cheats.adopt", {"id": "give_gold", "rev": 1, "category": "dev_safe"})
    with daemon.client(job_agent(daemon)) as conn:
        started = conn.call("run.start", {"path": CHEAT_GRAPH, "idempotency_key": "c2"})
        ended(conn, started["run_id"])
        # 채택된 치트는 허용 검사를 지난다 (그 뒤 콘솔 입력은 창 상황에 따라 끝난다)
        record = run_json(ws, started["run_id"])
        assert record["code"] not in ("cheat_not_adopted", "cheat_denied"), record


def test_qa_runner_nested_subgraph_cheat_checked(ws: Path, daemon: ThreadDaemon) -> None:
    with daemon.client(job_agent(daemon)) as conn:
        started = conn.call("run.start", {"path": NESTED_GRAPH, "idempotency_key": "n1"})
        ended(conn, started["run_id"])
        assert run_json(ws, started["run_id"])["code"] == "cheat_not_adopted"
    # 루트 테스트가 허용하지 않으면 서브그래프의 qa가 허용해도 거부 (넓히지 못함)
    nested = json.loads((ws / NESTED_GRAPH).read_text("utf-8"))
    nested["qa"] = {"format": "kookabug.qa/0"}
    (ws / NESTED_GRAPH).write_text(json.dumps(nested, ensure_ascii=False), encoding="utf-8")
    with daemon.client() as ui:
        ui.call("cheats.adopt", {"id": "give_gold", "rev": 1, "category": "dev_safe"})
    with daemon.client(job_agent(daemon)) as conn:
        started = conn.call("run.start", {"path": NESTED_GRAPH, "idempotency_key": "n2"})
        ended(conn, started["run_id"])
        assert run_json(ws, started["run_id"])["code"] == "cheat_denied"
