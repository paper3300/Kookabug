"""MCP `kb_target_create` (M5 계획 3.3·3.7, B1).

정지 화면 출처. 실행 기록 출처(`{run, file}`)는 B2."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.mcp_client import McpClient

pytestmark = pytest.mark.process

type Start = Callable[..., McpClient]

IMAGE = "targets/common/loading.png"
NEW = "targets/agent/loading_part.target.json"
EXISTING = "targets/common/loading.target.json"


def write_full(root: Path) -> None:
    path = root / ".kookabug" / "local.json"
    path.parent.mkdir(exist_ok=True)
    body = {"format": "kookabug.local/0", "permissions": {"preset": "full"}}
    path.write_text(json.dumps(body), encoding="utf-8")


def frame(daemon: ThreadDaemon) -> tuple[str, list[int]]:
    """UI 연결이 PNG를 정지 화면으로 연다 → (frame_id, 왼쪽 위 절반 사각형)."""
    with daemon.client() as ui:
        loaded = ui.call("target.load_image", {"path": IMAGE})
    return loaded["frame_id"], [0, 0, max(1, loaded["width"] // 2), max(1, loaded["height"] // 2)]


def test_target_create_from_frame(ws: Path, daemon: ThreadDaemon, start_mcp: Start) -> None:
    write_full(ws)
    frame_id, rect = frame(daemon)
    mcp = start_mcp()
    mcp.initialize()
    mcp.data("kb_toolset_enable", {"toolsets": ["graph_edit"]})
    saved = mcp.data(
        "kb_target_create", {"path": NEW, "source": {"frame_id": frame_id}, "rect": rect}
    )
    assert saved["path"] == NEW
    assert (ws / NEW).is_file()
    assert (ws / saved["image"]).is_file()
    # 실행 기록 출처는 아직 없다 (B2)
    error = mcp.error(
        "kb_target_create",
        {"path": "targets/agent/x.target.json", "source": {"run": "r", "file": "a.png"},
         "rect": rect},
    )  # fmt: skip
    assert error["code"] == "not_available"
    assert not (ws / "targets/agent/x.target.json").exists()
    assert mcp.close() == 0


def test_existing_target_needs_revision(ws: Path, daemon: ThreadDaemon, start_mcp: Start) -> None:
    write_full(ws)
    frame_id, rect = frame(daemon)
    before = (ws / EXISTING).read_bytes()
    mcp = start_mcp()
    mcp.initialize()
    mcp.data("kb_toolset_enable", {"toolsets": ["graph_edit"]})
    args = {"path": EXISTING, "source": {"frame_id": frame_id}, "rect": rect}
    # 기준 없이 있는 파일에 쓰면 exists (지금 revision을 알려 준다)
    error = mcp.error("kb_target_create", args)
    assert error["code"] == "exists"
    current = error["revision"]
    assert isinstance(current, str)
    # 틀린 기준은 revision_conflict
    stale = current.replace(current[0], "0" if current[0] != "0" else "1", 1)
    error = mcp.error("kb_target_create", {**args, "base_revision": stale})
    assert error["code"] == "revision_conflict"
    assert (ws / EXISTING).read_bytes() == before
    # 맞는 기준이면 고친다
    saved = mcp.data("kb_target_create", {**args, "base_revision": current})
    assert saved["revision"] != current
    assert (ws / EXISTING).read_bytes() != before
    assert mcp.close() == 0
