"""MCP `kb_target_create` (M5 계획 3.3·3.7, B1·B2).

정지 화면 출처(에이전트는 자기 연결이 만든 정지 화면만 — `kb_screen_capture`, B2 검수 H2).
실행 기록 출처(`{run, file}`)의 분류 검사는 daemon `test_agent_view`."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.mcp_client import McpClient

pytestmark = pytest.mark.process

type Start = Callable[..., McpClient]

IMAGE = "targets/common/loading.png"
NEW = "targets/agent/loading_part.target.json"
EXISTING = "targets/common/loading.target.json"
TITLE = "Fake Game"


def write_full(root: Path) -> None:
    path = root / ".kookabug" / "local.json"
    path.parent.mkdir(exist_ok=True)
    body = {"format": "kookabug.local/0", "permissions": {"preset": "full"}}
    path.write_text(json.dumps(body), encoding="utf-8")


def fake_window(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 프로세스 daemon의 창 목록·캡처를 가짜로 (화면 = `IMAGE`)."""
    import kookabug_daemon.methods.target as target_methods
    import kookabug_daemon.methods.windows as window_methods

    data = (ws / IMAGE).read_bytes()
    pixels = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert pixels is not None
    height, width = int(pixels.shape[0]), int(pixels.shape[1])
    window = {"handle": 9, "title": TITLE, "process": "game.exe", "pid": 1,
              "client_size": [width, height], "dpi": 96}  # fmt: skip
    monkeypatch.setattr(window_methods, "_windows", lambda: [window])
    monkeypatch.setattr(
        target_methods,
        "capture_window",
        lambda hwnd: SimpleNamespace(
            pixels=pixels.copy(), info=SimpleNamespace(client_size=(width, height), dpi=96)
        ),
    )


def frame(mcp: McpClient) -> tuple[str, list[int]]:
    """MCP로 창을 캡처한다 → (frame_id, 왼쪽 위 절반 사각형)."""
    mcp.data("kb_toolset_enable", {"toolsets": ["observe", "graph_edit"]})
    shot = mcp.data("kb_screen_capture", {"window": TITLE})
    return shot["frame_id"], [0, 0, max(1, shot["width"] // 2), max(1, shot["height"] // 2)]


def test_target_create_from_frame(
    ws: Path, daemon: ThreadDaemon, start_mcp: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_full(ws)
    fake_window(ws, monkeypatch)
    mcp = start_mcp()
    mcp.initialize()
    frame_id, rect = frame(mcp)
    # UI가 연 정지 화면은 에이전트가 쓰지 못한다 (자기 연결이 만든 것만)
    with daemon.client() as ui:
        ui_frame = ui.call("target.load_image", {"path": IMAGE})["frame_id"]
    error = mcp.error(
        "kb_target_create", {"path": NEW, "source": {"frame_id": ui_frame}, "rect": rect}
    )
    assert error["code"] == "frame_not_owned" and not (ws / NEW).exists()
    saved = mcp.data(
        "kb_target_create", {"path": NEW, "source": {"frame_id": frame_id}, "rect": rect}
    )
    assert saved["path"] == NEW
    assert (ws / NEW).is_file()
    assert (ws / saved["image"]).is_file()
    # 실행 기록 출처 (B2): 없는 실행이면 저장하지 않는다 (분류 검사는 daemon test_agent_view)
    error = mcp.error(
        "kb_target_create",
        {"path": "targets/agent/x.target.json", "source": {"run": "nope0000", "file": "a.png"},
         "rect": rect},
    )  # fmt: skip
    assert error["code"] == "run_not_found"
    assert not (ws / "targets/agent/x.target.json").exists()
    assert mcp.close() == 0


def test_existing_target_needs_revision(
    ws: Path, daemon: ThreadDaemon, start_mcp: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_full(ws)
    fake_window(ws, monkeypatch)
    before = (ws / EXISTING).read_bytes()
    mcp = start_mcp()
    mcp.initialize()
    frame_id, rect = frame(mcp)
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
