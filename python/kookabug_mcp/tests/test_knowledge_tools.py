"""M8 knowledge·cases MCP 도구 (계획 3.14, B4) — 실제 `kookabug mcp` 하위 프로세스 → daemon.

- 툴셋을 켜야 도구가 보인다 (`knowledge` 4개, `cases` 8개)
- `--job-token-env`로 붙으면 주체가 그 작업에 묶인다 (토큰은 인자·로그에 없다)
- `qa_runner`: control·그래프·target·지식 쓰기·채택 요청이 없고, 작업 기준 실행을 못 한다
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon, daemon_env
from kb_testing.mcp_client import McpClient
from kb_testing.proc import Spawned
from kb_testing.sample_game import copy_example_workspace

pytestmark = [pytest.mark.process, pytest.mark.timeout(600)]

KNOWLEDGE = {"kb_knowledge_search", "kb_knowledge_get", "kb_knowledge_apply", "kb_wiki_write"}
CASES = {
    "kb_case_list", "kb_case_get", "kb_triage_signals", "kb_case_open", "kb_case_update",
    "kb_evidence_pin", "kb_adopt_request", "kb_report_note",
}  # fmt: skip
PASS_GRAPH = "tests/shop/qa_pass.graph.json"


def workspace(tmp_path: Path, preset: str) -> Path:
    root = copy_example_workspace(tmp_path)
    local = root / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["permissions"] = {"preset": preset}
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    graph = {
        "format": "kookabug.graph/0",
        "kind": "test",
        "plugins": {"core": "0.1.0"},
        "nodes": {
            "n_entry": {"type": "core.graph.entry", "version": 1, "next": {"start": "n_pass"}},
            "n_pass": {"type": "core.test.pass", "version": 1},
        },
    }
    (root / PASS_GRAPH).write_text(json.dumps(graph), encoding="utf-8")
    return root


def test_tools_listed_by_toolset(tmp_path: Path, spawned: Spawned) -> None:
    ws = workspace(tmp_path, "curator")
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")}
    with ThreadDaemon(ws, environ=environ, agent_toolsets=("core",)) as d:
        job = d.begin_job({"playbook": "triage"})
        env = {**daemon_env(tmp_path), "KB_TEST_JOB_TOKEN": job["token"]}
        args = (
            "--unattended",
            "--agent-id",
            job["agent_id"],
            "--job-token-env",
            "KB_TEST_JOB_TOKEN",
        )
        mcp = McpClient.start(spawned, ws, tmp_path / "mcp", *args, env=env)
        try:
            mcp.initialize()
            names = set(mcp.tool_names())
            assert not (KNOWLEDGE | CASES) & names
            mcp.data("kb_toolset_enable", {"toolsets": ["knowledge"]})
            assert set(mcp.tool_names()) >= KNOWLEDGE and not CASES & set(mcp.tool_names())
            mcp.data("kb_toolset_enable", {"toolsets": ["cases"]})
            assert set(mcp.tool_names()) >= (KNOWLEDGE | CASES)
            info = mcp.data("kb_project_info")
            assert info["principal"]["job"] == job["job"]
            listed = {t["name"]: t["tools"] for t in info["toolsets"]}
            assert set(listed["knowledge"]) == KNOWLEDGE and set(listed["cases"]) == CASES
            assert info["permissions"]["kb_adopt_request"] == "allow"
            assert info["permissions"]["kb_input_click"] == "allow"  # 작업 안 curator (R0)
            # 지식 연산: 추측 주장은 팀 파일, human 근거는 사람만
            added = mcp.data(
                "kb_knowledge_apply",
                {
                    "request_id": "r1",
                    "ops": [
                        {
                            "op": "add",
                            "file": "unknowns",
                            "base_revision": 0,
                            "item": {"question": "물약 가격이 바뀔 예정인가?", "human_only": True},
                        }
                    ],
                },
            )
            assert added is not None
            assert (ws / "knowledge" / "unknowns.json").exists()
            human = mcp.error(
                "kb_knowledge_apply",
                {
                    "request_id": "r2",
                    "ops": [
                        {
                            "op": "add",
                            "file": "lessons",
                            "base_revision": 0,
                            "item": {
                                "id": "shop.buttons_move",
                                "advice": "상점 단추는 자주 옮겨진다",
                                "basis": [{"type": "human", "ref": "u-20261110-000000-abcd"}],
                            },
                        }
                    ],
                },
            )
            assert human["code"] == "human_basis_reserved"
            # 정책 경로는 위키 도구로도 못 쓴다
            for path in ("AGENTS.md", "wiki/index.md", "knowledge/evidence/x.md"):
                error = mcp.error("kb_wiki_write", {"path": path, "text": "x", "base_sha256": None})
                assert error["code"] == "policy_path", path
            # 작업 토큰 원문이 든 메모는 거부한다 (R9 — 보고에 남지 않게)
            leaked = mcp.error("kb_report_note", {"text": f"토큰 {job['token']}"})
            assert leaked["code"] == "secret_in_text"
            note = mcp.data("kb_report_note", {"text": "요약"})  # 양성 대조
            assert note["job"] == job["job"]
            assert mcp.close() == 0
        finally:
            mcp.__exit__(None, None, None)
        stderr = (tmp_path / "mcp" / "stderr.log").read_text("utf-8", errors="replace")
        assert job["token"] not in stderr


def test_job_token_env_missing_or_invalid(tmp_path: Path, spawned: Spawned) -> None:
    ws = workspace(tmp_path, "curator")
    with ThreadDaemon(ws, environ={"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")}):
        env = {**daemon_env(tmp_path), "KB_TEST_JOB_TOKEN": "x" * 43}
        for name in ("KB_TEST_JOB_TOKEN", "KB_TEST_NOT_SET"):
            mcp = McpClient.start(
                spawned, ws, tmp_path / f"mcp-{name}", "--job-token-env", name, env=env
            )
            try:
                assert mcp.proc.wait(60) == 6  # 붙지 못함 (토큰 없음·틀림)
            finally:
                mcp.__exit__(None, None, None)
        # 작업 안(토큰 환경·job: 주체)인데 토큰 연결 없이 붙으면 종료 3 (작업 감독 우회 금지, R8)
        inside = [
            ({**daemon_env(tmp_path), "KOOKABUG_JOB_TOKEN": "x" * 43}, ()),
            (daemon_env(tmp_path), ("--agent-id", "job:j-20261110-010203-abcd")),
            ({**daemon_env(tmp_path), "KOOKABUG_AGENT": "job:j-20261110-010203-abcd"}, ()),
        ]
        for n, (env_in, args_in) in enumerate(inside):
            mcp = McpClient.start(spawned, ws, tmp_path / f"mcp-inside-{n}", *args_in, env=env_in)
            try:
                assert mcp.proc.wait(60) == 3, n
            finally:
                mcp.__exit__(None, None, None)


def call(mcp: McpClient, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    result = mcp.call_tool(tool, args, timeout=120)
    return result


def test_qa_runner_no_control_no_working(tmp_path: Path, spawned: Spawned) -> None:
    ws = workspace(tmp_path, "qa_runner")
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")}
    with ThreadDaemon(ws, environ=environ, platform_fake=ws / "fake-platform-shop.json") as d:
        job = d.begin_job({"playbook": "triage"})
        env = {**daemon_env(tmp_path), "KB_TEST_JOB_TOKEN": job["token"]}
        args = (
            "--unattended",
            "--agent-id",
            job["agent_id"],
            "--job-token-env",
            "KB_TEST_JOB_TOKEN",
        )
        mcp = McpClient.start(spawned, ws, tmp_path / "mcp", *args, env=env)
        try:
            mcp.initialize()
            mcp.data(
                "kb_toolset_enable",
                {"toolsets": ["graph_edit", "run", "control", "knowledge", "cases"]},
            )
            denied = {
                "kb_input_click": {"window": "SampleRPG 상점", "point": [1, 1]},
                "kb_input_key": {"window": "SampleRPG 상점", "keys": "`"},
                "kb_input_type": {"window": "SampleRPG 상점", "text": "give_gold 1"},
                "kb_graph_create": {"path": "tests/shop/x.graph.json", "kind": "test"},
                "kb_knowledge_apply": {"request_id": "r", "ops": [{"op": "add"}]},
                "kb_adopt_request": {
                    "case": "c-20261110-000000-abcd",
                    "change": "w-20261110-000000-abcd",
                },
            }
            for tool, tool_args in denied.items():
                assert mcp.error(tool, tool_args)["code"] == "permission_denied", tool
            error = mcp.error(
                "kb_run_start", {"path": PASS_GRAPH, "idempotency_key": "w", "basis": "working"}
            )
            assert error["code"] == "basis_denied"
            started = mcp.data("kb_run_start", {"path": PASS_GRAPH, "idempotency_key": "t"})
            status = mcp.data("kb_run_status", {"run": started["run"], "wait_ms": 30000})
            assert status["state"] == "ended", status
            assert mcp.data("kb_case_list", {}) == {"cases": []}
            assert mcp.close() == 0
        finally:
            mcp.__exit__(None, None, None)
    folder = next((ws / "runs").glob(f"*_{started['run']}"))
    record = json.loads((folder / "run.json").read_text("utf-8"))
    assert record["basis"]["kind"] == "team" and record["job"] == job["job"]
    assert not (ws / "tests/shop/x.graph.json").exists()
