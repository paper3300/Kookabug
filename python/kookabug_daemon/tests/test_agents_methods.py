"""`agents.get/detect/set`·`agent.connections` (M5 계획 3.5·3.12, B5).

에이전트 목록은 사용자 설정 파일에 있고 쓰기는 사람(ui) 연결만 한다. 쓰기 규칙은 `permissions.set`과
같다: revision이 다르면 `revision_conflict`, 다른 키·순서 보존, 형식이 틀린 파일은 바이트 그대로.
"""

from __future__ import annotations

import hashlib
import json
import queue
import time
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon, copy_sample_workspace
from kookabug_core.agents import detect
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(120)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-7", "attended": True}
FAKE = {"id": "fake", "name": "가짜 에이전트", "command": "python", "args": ["fake.py"]}


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return copy_sample_workspace(tmp_path / "ws")


@pytest.fixture
def user_dir(tmp_path: Path) -> Path:
    return tmp_path / "user"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def refused(client: DaemonClient, method: str, params: dict[str, Any] | None = None) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params or {})
    return caught.value


def notification(client: DaemonClient, method: str, timeout: float = 15) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise AssertionError(f"{timeout}초 안에 {method} 알림이 오지 않았다")
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            continue
        if message.get("method") == method:
            return message["params"]


def test_agent_cannot_set_agents(ws: Path, user_dir: Path) -> None:
    """에이전트 연결은 목록 읽기·감지·쓰기·연결 목록 모두 판정 전에 거부 — 자기가 띄워질 명령을
    바꾸지 못한다. 파일은 생기지 않는다."""
    settings = user_dir / "settings.json"
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(user_dir)}
    with ThreadDaemon(ws, environ=environ) as d, d.client(AGENT) as agent:
        for method, params in (
            ("agents.set", {"agents": [FAKE], "default_agent": None, "base_revision": None}),
            ("agents.get", {}),
            ("agents.detect", {}),
            ("agent.connections", {}),
        ):
            assert refused(agent, method, params).kind == "permission_denied", method
    assert not settings.exists()


def test_set_revision_conflict_preserves_file(ws: Path, user_dir: Path) -> None:
    """새 파일 → 지금 기준으로 고치기 → 옛 기준은 거부(바이트 그대로). 다른 키·순서 보존."""
    settings = user_dir / "settings.json"
    user_dir.mkdir()
    original = {
        "format": "kookabug.user-settings/0",
        "permissions": {"preset": "runner"},
        "agents": [],
    }
    settings.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8-sig")
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(user_dir)}
    with ThreadDaemon(ws, environ=environ) as d, d.client() as ui:
        got = ui.call("agents.get")
        assert got["agents"] == [] and got["default_agent"] is None and got["problem"] is None
        assert got["revision"] == sha(settings.read_bytes())
        assert got["source"] == str(settings)
        first = ui.call(
            "agents.set",
            {"agents": [FAKE], "default_agent": "fake", "base_revision": got["revision"]},
        )
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert list(data) == ["format", "permissions", "agents", "default_agent"]
        assert data["permissions"] == {"preset": "runner"}
        assert data["agents"] == [FAKE] and data["default_agent"] == "fake"
        assert first["revision"] == sha(settings.read_bytes()) == ui.call("agents.get")["revision"]
        # 늦은 쪽: 옛 기준으로 쓰면 거부, 바이트 그대로
        before = settings.read_bytes()
        error = refused(
            ui,
            "agents.set",
            {"agents": [], "default_agent": None, "base_revision": got["revision"]},
        )
        assert error.kind == "revision_conflict"
        assert error.data["revision"] == first["revision"]
        assert settings.read_bytes() == before
        # default_agent null이면 키를 지운다
        cleared = {"agents": [FAKE], "default_agent": None, "base_revision": sha(before)}
        ui.call("agents.set", cleared)
        assert "default_agent" not in json.loads(settings.read_text(encoding="utf-8"))
        # 형식이 틀린 항목은 쓰지 않는다 (daemon의 계약 검사 — 클라이언트 검사는 끈다)
        now = settings.read_bytes()
        bad = {**FAKE, "command": ""}
        ui.check = False
        with pytest.raises(DaemonError) as caught:
            ui.call(
                "agents.set", {"agents": [bad], "default_agent": None, "base_revision": sha(now)}
            )
        assert caught.value.code == -32602
        assert settings.read_bytes() == now


def test_invalid_file_not_overwritten(ws: Path, user_dir: Path) -> None:
    """형식이 틀린 사용자 설정: 읽기는 problem, 쓰기는 settings_invalid(바이트 그대로)."""
    settings = user_dir / "settings.json"
    user_dir.mkdir()
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(user_dir)}
    for raw in (b"{nope", json.dumps({"format": "kookabug.user-settings/0", "agents": 3}).encode()):
        settings.write_bytes(raw)
        with ThreadDaemon(ws, environ=environ) as d, d.client() as ui:
            got = ui.call("agents.get")
            assert got["problem"] is not None and got["agents"] == []
            error = refused(
                ui,
                "agents.set",
                {"agents": [FAKE], "default_agent": None, "base_revision": sha(raw)},
            )
            assert error.kind == "settings_invalid"
        assert settings.read_bytes() == raw


def test_detect_lists_table_without_installing(
    ws: Path, user_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """감지는 표의 제품마다 한 줄: 경로에서 찾으면 installed·path, 아니면 첫 후보 명령."""
    found = {"codex-acp": "C:/tools/codex-acp.exe"}
    monkeypatch.setattr(detect.shutil, "which", lambda name: found.get(name))
    rows = detect.detect()
    assert [r["id"] for r in rows] == [c.id for c in detect.DETECT_TABLE]
    codex = next(r for r in rows if r["id"] == "codex")
    assert codex["installed"] is True and codex["path"] == found["codex-acp"]
    assert codex["via"] == "path"
    assert all(r["installed"] is False and r["path"] is None for r in rows if r["id"] != "codex")
    assert all(r["via"] is None for r in rows if r["id"] != "codex")
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(user_dir)}
    with ThreadDaemon(ws, environ=environ) as d, d.client() as ui:
        candidates = ui.call("agents.detect")["candidates"]
        assert [c["id"] for c in candidates] == [c.id for c in detect.DETECT_TABLE]


def test_detect_bare_cli_uses_pinned_npx_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """본체 CLI(claude·codex)만 있으면 고정 판 ACP 어댑터를 npx로. npx가 없으면 본체 위치만."""
    found = {
        "claude": "C:/u/.local/bin/claude.exe",
        "codex": "C:/p/codex.exe",
        "npx": "C:/node/npx.cmd",
    }
    monkeypatch.setattr(detect.shutil, "which", lambda name: found.get(name))
    rows = {r["id"]: r for r in detect.detect()}
    for key in ("claude-code", "codex"):
        row = rows[key]
        package = next(c.package for c in detect.DETECT_TABLE if c.id == key)
        assert package is not None and "@" in package.lstrip("@")  # 판 고정
        assert row["installed"] is True and row["via"] == "npx"
        assert (row["command"], row["args"], row["path"]) == ("npx", ["-y", package], found["npx"])
        assert row["cli_path"] == found[row["cli"]]
    assert rows["gemini"]["installed"] is False and rows["gemini"]["cli_path"] is None

    del found["npx"]
    rows = {r["id"]: r for r in detect.detect()}
    claude = rows["claude-code"]
    assert claude["installed"] is False and claude["via"] is None and claude["path"] is None
    assert claude["cli_path"] == found["claude"] and claude["command"] == "claude-agent-acp"

    # 어댑터가 PATH에 있으면 npx보다 먼저
    found |= {"npx": "C:/node/npx.cmd", "claude-code-acp": "C:/g/claude-code-acp.cmd"}
    claude = next(r for r in detect.detect() if r["id"] == "claude-code")
    assert (claude["via"], claude["command"], claude["args"]) == ("path", "claude-code-acp", [])


def test_agent_connections_listed_and_notified(ws: Path, user_dir: Path) -> None:
    """ui 연결은 agent 연결 목록을 보고, 붙기·툴셋 켜기·끊기마다 agent.connections.changed."""
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(user_dir)}
    with ThreadDaemon(ws, environ=environ, agent_toolsets=["core"]) as d, d.client() as ui:
        assert ui.call("agent.connections")["connections"] == []
        with d.client(AGENT) as agent:
            notification(ui, "agent.connections.changed")
            [row] = ui.call("agent.connections")["connections"]
            assert (row["id"], row["name"], row["attended"]) == ("agent-7", "mcp", True)
            assert row["toolsets"] == ["core"] and row["since"].endswith("Z")
            agent.call("agent.toolsets.enable", {"toolsets": ["graph_edit"]})
            notification(ui, "agent.connections.changed")
            [row] = ui.call("agent.connections")["connections"]
            assert row["toolsets"] == ["core", "graph_edit"]
        notification(ui, "agent.connections.changed")
        assert ui.call("agent.connections")["connections"] == []
