"""MCP graph_edit·core 도구 (M5 계획 3.3·3.4, B1).

실제 `kookabug mcp` stdio + 같은 프로세스 daemon."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.mcp_client import McpClient

pytestmark = pytest.mark.process

type Start = Callable[..., McpClient]

GRAPH = "tests/inventory_open.graph.json"
NEW = "tests/agent_new.graph.json"
OLD_NS = 1_600_000_000 * 10**9


def write_local(root: Path, preset: str) -> None:
    path = root / ".kookabug" / "local.json"
    path.parent.mkdir(exist_ok=True)
    body = {"format": "kookabug.local/0", "permissions": {"preset": preset}}
    path.write_text(json.dumps(body), encoding="utf-8")


def test_create_patch_get_roundtrip_full_preset(
    ws: Path, daemon: ThreadDaemon, start_mcp: Start
) -> None:
    write_local(ws, "full")
    mcp = start_mcp()
    mcp.initialize()
    mcp.data("kb_toolset_enable", {"toolsets": ["graph_edit"]})

    created = mcp.data(
        "kb_graph_create",
        {
            "path": NEW,
            "kind": "test",
            "title": "에이전트가 만든 테스트",
            "ops": [
                {"op": "add_node", "ref": "key", "type": "core.input.key", "in": {"keys": "I"}},
                {"op": "add_node", "ref": "ok", "type": "core.test.pass"},
                {"op": "connect", "from": "n_entry", "exit": "start", "to": "key"},
                {"op": "connect", "from": "key", "exit": "done", "to": "ok"},
            ],
        },
    )
    key, ok = created["created"]["key"], created["created"]["ok"]
    got = mcp.data("kb_graph_get", {"path": NEW})
    assert got["revision"] == created["revision"]
    nodes = got["value"]["nodes"]
    assert nodes["n_entry"]["next"] == {"start": key}
    assert nodes[key] == {"in": {"keys": "I"}, "next": {"done": ok}, "type": "core.input.key",
                          "version": 1}  # fmt: skip
    assert got["value"]["meta"] == {"title": "에이전트가 만든 테스트"}
    assert json.loads((ws / NEW).read_text(encoding="utf-8")) == got["value"]

    patched = mcp.data(
        "kb_graph_patch",
        {
            "path": NEW,
            "base_revision": got["revision"],
            "ops": [{"op": "set_node", "id": key, "title": "I 키"}],
        },
    )
    assert patched["revision"] != got["revision"]
    again = mcp.data("kb_graph_get", {"path": NEW})
    assert again["revision"] == patched["revision"]
    assert again["value"]["nodes"][key]["title"] == "I 키"

    # 낡은 기준은 revision_conflict (isError) — 다시 읽으라는 지금 revision을 준다
    error = mcp.error(
        "kb_graph_patch",
        {"path": NEW, "base_revision": got["revision"], "ops": [{"op": "set_meta", "title": "x"}]},
    )
    assert error["code"] == "revision_conflict"
    assert error["revision"] == patched["revision"]
    # 틀린 연산은 patch_invalid + 순번
    error = mcp.error(
        "kb_graph_patch",
        {"path": NEW, "base_revision": patched["revision"],
         "ops": [{"op": "remove_node", "id": "n_nope"}]},
    )  # fmt: skip
    assert (error["code"], error["index"]) == ("patch_invalid", 0)

    # 조회 도구
    listed = {g["path"]: g for g in mcp.data("kb_graph_list", {"under": "tests"})["graphs"]}
    assert listed[NEW]["kind"] == "test"
    assert listed[NEW]["title"] == "에이전트가 만든 테스트"
    assert listed[GRAPH]["title"] == "인벤토리 열기"
    assert all(path.startswith("tests/") for path in listed)
    checked = mcp.data("kb_graph_validate", {"path": NEW})
    assert all(d["severity"] != "error" for d in checked["diagnostics"]), checked
    bad = dict(again["value"])
    bad["nodes"] = {**bad["nodes"], key: {**bad["nodes"][key], "next": {"done": "n_gone"}}}
    checked = mcp.data("kb_graph_validate", {"path": NEW, "value": bad})
    assert any(d["severity"] == "error" for d in checked["diagnostics"])
    assert json.loads((ws / NEW).read_text(encoding="utf-8")) == again["value"]  # 쓰지 않음
    found = mcp.data("kb_node_search", {"query": "input.key"})["nodes"]
    assert [n["type"] for n in found] == ["core.input.key"]
    assert "keys" in found[0]["inputs"] and found[0]["exits"] == ["done"]
    # 에이전트가 연 문서는 표에 남지 않는다
    assert len(daemon.daemon.documents) == 0
    assert mcp.close() == 0
    mcp.assert_protocol_only()


def test_graph_author_patch_needs_approval_unattended_denied(
    ws: Path, daemon: ThreadDaemon, start_mcp: Start
) -> None:
    # 기본 프리셋 graph_author: graph_edit 변경 도구는 ask
    os.utime(ws / GRAPH, ns=(OLD_NS, OLD_NS))
    before = (ws / GRAPH).read_bytes()
    for args, kind, reason in (
        ((), "approval_required", "preset"),
        (("--unattended",), "permission_denied", "unattended_ask"),
    ):
        mcp = start_mcp(*args)
        mcp.initialize()
        mcp.data("kb_toolset_enable", {"toolsets": ["graph_edit"]})
        base = mcp.data("kb_graph_get", {"path": GRAPH})["revision"]
        error = mcp.error(
            "kb_graph_patch",
            {"path": GRAPH, "base_revision": base, "ops": [{"op": "set_meta", "title": "x"}]},
        )
        assert error["code"] == kind
        assert error["decision"]["verdict"] == "ask"
        assert error["decision"]["reason"] == reason
        error = mcp.error("kb_graph_create", {"path": NEW, "kind": "test"})
        assert error["code"] == kind
        assert mcp.close() == 0
    assert (ws / GRAPH).read_bytes() == before
    assert (ws / GRAPH).stat().st_mtime_ns == OLD_NS
    assert not (ws / NEW).exists()
