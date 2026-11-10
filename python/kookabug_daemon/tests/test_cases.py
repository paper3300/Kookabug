"""사건 메서드 (M8 계획 3.2 사건·3.13, B4) — 엄격: 원래 실패 보존·Agent 권한.

실제 daemon·runner·예제 상점 가짜 게임(`shop_moved` 프로필 — 구매 단추가 옮겨져 `buy_potion`이
실패한다)으로 사건을 연다.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import copy_example_workspace
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(900)]

TEST = "tests/shop/buy_potion.graph.json"
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "panel", "attended": True}


@pytest.fixture
def ws(tmp_path: Path, ocr_models: Path) -> Path:
    os.environ.setdefault("KOOKABUG_OCR_MODELS", str(ocr_models))
    root = copy_example_workspace(tmp_path)
    local = root / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))  # 게임 실행 설정은 그대로 두고 권한만 더한다
    body["permissions"] = {"preset": "full"}
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return root


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws, platform_fake=ws / "fake-platform-shop.json") as d:
        yield d


def wait_ended(conn: DaemonClient, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 300
    while True:
        status = conn.call("run.status", {"run_id": run_id})
        if status["state"] == "ended":
            return status
        assert time.monotonic() < deadline, status
        time.sleep(0.3)


def run(conn: DaemonClient, profile: str | None = "shop_moved", **extra: Any) -> str:
    params: dict[str, Any] = {"path": TEST, **extra}
    if profile is not None:
        params["profile"] = profile
    run_id = str(conn.call("run.start", params)["run_id"])
    wait_ended(conn, run_id)
    return run_id


def error_of(conn: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        conn.call(method, params, timeout=120)
    return caught.value


def log_ops(ws: Path) -> list[str]:
    path = ws / "knowledge" / "log.jsonl"
    lines = path.read_text("utf-8").splitlines() if path.exists() else []
    return [json.loads(line)["op"] for line in lines if line.strip()]


def test_open_pins_original_and_signature_attaches(ws: Path, daemon: ThreadDaemon) -> None:
    graph_sha = hashlib.sha256((ws / TEST).read_bytes()).hexdigest()
    with daemon.client() as ui:
        first = run(ui)
        second = run(ui)
        passed = run(ui, profile=None)
    with daemon.client(AGENT) as agent:
        opened = agent.call("cases.open", {"run": first})
        assert opened["attached"] is False and opened["hypotheses"] == []
        case_id = opened["case"]
        evidence = opened["evidence"]
        assert isinstance(evidence, str) and evidence.startswith("e-")
        manifest = json.loads(
            (ws / "knowledge" / "evidence" / evidence / "manifest.json").read_text("utf-8")
        )
        assert manifest["run"] == first and manifest["verdict"] == "fail"
        doc = agent.call("cases.get", {"id": case_id})["case"]
        assert doc["original"] == {
            "run": first,
            "evidence": evidence,
            "graph_sha": graph_sha,
            "claims": [{"id": "shop.potion.price", "rev": 1}],
            "basis": {"kind": "team"},
        }
        assert doc["symptom"]["test"] == TEST and doc["symptom"]["node"] == "n_click_buy"
        assert doc["symptom"]["kind"] == "target_missing", doc["symptom"]
        assert doc["state"] == "open" and doc["signature"] == opened["signature"]
        # 가설을 남긴 뒤 같은 시그니처 실패는 새 사건 없이 붙고 지난 가설을 받는다
        hypothesis = {"cause": "ui_change", "state": "supported", "note": "단추가 옮겨졌다"}
        agent.call(
            "cases.update",
            {"id": case_id, "base_revision": 1, "changes": {"hypotheses": [hypothesis]}},
        )
        again = agent.call("cases.open", {"run": second})
        assert (again["case"], again["attached"]) == (case_id, True)
        assert again["hypotheses"] == [hypothesis] and again["evidence"] == evidence
        # 이미 붙은 실행은 두 번 붙지 않는다
        assert agent.call("cases.open", {"run": first})["attached"] is True
        doc = agent.call("cases.get", {"id": case_id})["case"]
        assert [r["run"] for r in doc["runs"]] == [second]
        assert doc["original"]["run"] == first  # 원래 실패는 그대로
        # 통과한 실행으로는 열지 않는다
        assert error_of(agent, "cases.open", {"run": passed}).kind == "validation_failed"
        listed = agent.call("cases.list", {"state": "open"})["cases"]
        assert [(c["id"], c["runs"]) for c in listed] == [(case_id, 2)]
    ops = log_ops(ws)
    assert ops.count("case_open") == 1 and ops.count("case_attach") == 1
    assert "evidence_pin" in ops


def test_resolved_reserved_for_agent(ws: Path, daemon: ThreadDaemon) -> None:
    with daemon.client() as ui:
        first = run(ui)
    with daemon.client(AGENT) as agent:
        case_id = agent.call("cases.open", {"run": first})["case"]
        for state in ("resolved", "closed"):
            error = error_of(
                agent,
                "cases.update",
                {"id": case_id, "base_revision": 1, "changes": {"state": state}},
            )
            assert error.kind == "case_resolution_reserved", state
        for changes in (
            {"original": {"run": "x"}},
            {"resolution": {"by": "human"}},
            {"signature": "sha256:" + "0" * 64},
            {"links": {"adoption": "a-20261110-000000-abcd"}},
        ):
            error = error_of(
                agent, "cases.update", {"id": case_id, "base_revision": 1, "changes": changes}
            )
            assert error.kind == "validation_failed", changes
        done = agent.call(
            "cases.update",
            {"id": case_id, "base_revision": 1, "changes": {"state": "needs_info"}},
        )
        assert done == {"case": case_id, "revision": 2}
        stale = error_of(
            agent, "cases.update", {"id": case_id, "base_revision": 1, "changes": {"title": "t"}}
        )
        assert stale.kind == "revision_conflict"
        closing = {"id": case_id, "base_revision": 2, "state": "resolved"}
        assert error_of(agent, "cases.close", closing).kind == "permission_denied"
    with daemon.client() as ui:
        assert ui.call("cases.close", {**closing, "note": "사람이 확인"})["revision"] == 3
    doc = json.loads((ws / "knowledge" / "cases" / f"{case_id}.json").read_text("utf-8"))
    assert doc["state"] == "resolved" and doc["resolution"]["by"] == "human"
    with daemon.client(AGENT) as agent:
        error = error_of(
            agent, "cases.update", {"id": case_id, "base_revision": 3, "changes": {"title": "t"}}
        )
        assert error.kind == "case_closed"


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_signals_no_cause_verdict(ws: Path, daemon: ThreadDaemon) -> None:
    with daemon.client() as ui:
        first = run(ui)
        run(ui, profile=None)  # 지난 성공 (비교 기준)
        second = run(ui)
    with daemon.client(AGENT) as agent:
        case_id = agent.call("cases.open", {"run": first})["case"]
        agent.call("cases.open", {"run": second})
        signals = agent.call("cases.signals", {"id": case_id})
    assert set(signals) == {
        "case", "diff", "screen", "reruns", "sources", "claims", "not_comparable",
    }  # fmt: skip
    # 판단 재료만: 원인·판정·가설 키가 없다
    assert not {"cause", "hypotheses", "hypothesis", "verdict_cause"} & _keys(signals)
    assert signals["reruns"]["unchanged"] == 1
    assert [r["run"] for r in signals["reruns"]["results"]] == [second]
    [claim] = signals["claims"]
    assert (claim["id"], claim["kind"], claim["found"]) == ("shop.potion.price", "expected", True)
    assert signals["diff"] is not None and signals["diff"]["run_id"] == first
    assert signals["screen"]["state"] in ("identified", "unmatched", "unknown")
    assert isinstance(signals["not_comparable"], list)


def test_stalled_repeat(ws: Path, daemon: ThreadDaemon) -> None:
    job = daemon.begin_job({"playbook": "triage"})
    info = {**AGENT, "id": job["agent_id"], "attended": False, "job_token": job["token"]}
    with daemon.client(info) as agent:
        for n in range(3):
            run(agent, idempotency_key=f"k{n}")
        error = error_of(
            agent, "run.start", {"path": TEST, "profile": "shop_moved", "idempotency_key": "k3"}
        )
        assert error.kind == "stalled_repeat"
        # 같은 키를 다시 보내면 지난 결과 (정체 감지는 새 시작에만)
        assert agent.call(
            "run.start", {"path": TEST, "profile": "shop_moved", "idempotency_key": "k2"}
        )["run_id"]
    # 다른 연결(사람)은 그대로 돌린다 — 정체는 그 작업 안에서만
    with daemon.client() as ui:
        run(ui)


def stalled_agent(daemon: ThreadDaemon) -> dict[str, Any]:
    """작업 토큰 Agent 연결 정보 (그 작업 안에서 정체 감지)."""
    job = daemon.begin_job({"playbook": "triage"})
    return {**AGENT, "id": job["agent_id"], "attended": False, "job_token": job["token"]}


def fail_three_times(agent: DaemonClient) -> None:
    for n in range(3):
        run(agent, idempotency_key=f"s{n}")
    # 바뀐 것이 없으면 여전히 거부 (각 검사의 음성 대조)
    error = error_of(
        agent, "run.start", {"path": TEST, "profile": "shop_moved", "idempotency_key": "s3"}
    )
    assert error.kind == "stalled_repeat"


def reformat(path: Path) -> None:
    """같은 값을 다른 바이트로 (들여쓰기) — 실행이 보는 바이트가 바뀐다."""
    value = json.loads(path.read_text("utf-8"))
    path.write_text(json.dumps(value, ensure_ascii=False, indent=3), encoding="utf-8")


def test_stall_cleared_after_graph_changed(ws: Path, daemon: ThreadDaemon) -> None:
    with daemon.client(stalled_agent(daemon)) as agent:
        fail_three_times(agent)
        reformat(ws / TEST)  # 사람이 팀 그래프를 고쳤다
        assert run(agent, idempotency_key="after-graph")


def test_stall_cleared_after_target_changed(ws: Path, daemon: ThreadDaemon) -> None:
    with daemon.client(stalled_agent(daemon)) as agent:
        fail_three_times(agent)
        reformat(ws / "targets" / "shop" / "buy.target.json")  # 그래프는 그대로, target만
        assert run(agent, idempotency_key="after-target")


def test_stall_cleared_after_working_copy_changed(ws: Path, daemon: ThreadDaemon) -> None:
    team = (ws / TEST).read_bytes()
    with daemon.client(stalled_agent(daemon)) as agent:
        fail_three_times(agent)
        # 이 작업의 작업 사본을 고쳤다 (팀 파일은 그대로 — 작업 기준 실행이 보는 바이트만 바뀜)
        opened = agent.call("graph.open", {"path": TEST})
        patched = agent.call(
            "graph.patch",
            {
                "path": TEST,
                "base_revision": opened["revision"],
                "ops": [{"op": "set_meta", "title": "물약 구매 (수리 중)"}],
            },
        )
        assert patched["basis"] == "working"
        assert (ws / TEST).read_bytes() == team
        assert run(agent, idempotency_key="after-working")


def test_stall_cleared_after_profile_changed(ws: Path, daemon: ThreadDaemon) -> None:
    """프로필이 다르면 다른 요청이다 — 거부하지 않는다."""
    with daemon.client(stalled_agent(daemon)) as agent:
        fail_three_times(agent)
        assert run(agent, profile=None, idempotency_key="other-profile")


SETTING_TEST = "tests/stall_settings.graph.json"
SETTING_GRAPH = {
    "format": "kookabug.graph/0",
    "kind": "test",
    "plugins": {"core": "0.1.0"},
    "nodes": {
        "n_entry": {"type": "core.graph.entry", "version": 1, "next": {"start": "n_branch"}},
        "n_branch": {
            "type": "core.flow.branch",
            "version": 1,
            "in": {"condition": {"$setting": "stall.ok"}},
            "next": {"true": "n_pass", "false": "n_fail"},
        },
        "n_pass": {"type": "core.test.pass", "version": 1},
        "n_fail": {"type": "core.test.fail", "version": 1, "in": {"reason": "stall false"}},
    },
}


def set_local_setting(ws: Path, value: bool) -> None:
    local = ws / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body.setdefault("settings", {})["stall.ok"] = value
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("where", ["request", "local"])
def test_stall_cleared_after_settings_changed(ws: Path, daemon: ThreadDaemon, where: str) -> None:
    """`$setting` 값은 그래프·스냅샷 바이트에 없다 — 실효 설정(요청·`local.json`)이 바뀌면 같은
    파일이어도 다른 요청이다. 바뀌지 않았으면 여전히 거부한다."""
    (ws / SETTING_TEST).write_text(json.dumps(SETTING_GRAPH, ensure_ascii=False), "utf-8")

    def params(value: bool, key: str) -> dict[str, Any]:
        out: dict[str, Any] = {"path": SETTING_TEST, "idempotency_key": key}
        if where == "request":
            out["settings"] = {"stall.ok": value}
        return out

    if where == "local":
        set_local_setting(ws, False)
    with daemon.client(stalled_agent(daemon)) as agent:
        for n in range(3):
            run_id = str(agent.call("run.start", params(False, f"f{n}"))["run_id"])
            assert wait_ended(agent, run_id)["outcome"]["verdict"] == "fail"
        # 바뀐 것이 없으면 여전히 거부 (음성 대조)
        assert error_of(agent, "run.start", params(False, "f3")).kind == "stalled_repeat"
        if where == "local":
            set_local_setting(ws, True)
        run_id = str(agent.call("run.start", params(True, "after-settings"))["run_id"])
        assert wait_ended(agent, run_id)["outcome"]["verdict"] == "pass"


def test_stall_cleared_after_deadline_changed(ws: Path, daemon: ThreadDaemon) -> None:
    """요청 기한도 실행 전에 아는 재료다 — 바뀌면 거부하지 않는다(설정이 같아 여전히 실패)."""
    (ws / SETTING_TEST).write_text(json.dumps(SETTING_GRAPH, ensure_ascii=False), "utf-8")
    base = {"path": SETTING_TEST, "settings": {"stall.ok": False}}
    with daemon.client(stalled_agent(daemon)) as agent:
        for n in range(3):
            run_id = str(agent.call("run.start", {**base, "idempotency_key": f"d{n}"})["run_id"])
            assert wait_ended(agent, run_id)["outcome"]["verdict"] == "fail"
        assert error_of(agent, "run.start", {**base, "idempotency_key": "d3"}).kind == (
            "stalled_repeat"
        )
        params = {**base, "idempotency_key": "d4", "deadline_ms": 120_000}
        run_id = str(agent.call("run.start", params)["run_id"])
        assert wait_ended(agent, run_id)["outcome"]["verdict"] == "fail"
