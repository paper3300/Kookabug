"""워크스페이스 ID와 자격 증명 관리자 비밀값의 실행 (M4 계획 2.8, C11·Q10, T7).

- 실행의 `$secret`은 기본 제공자(환경 변수 → 자격 증명 관리자 `kookabug:<ID>:<키>`)로 풀린다
- `kookabug.json`에 `id`가 없으면 처음 만들 때 넣되 나머지 원문은 그대로 둔다
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
from helpers.graphs import GraphBuilder, make_workspace, secret

from kookabug_core.engine import ExecOptions, Executor, FakeClock, FakePlatform, MemoryArtifacts
from kookabug_core.loader import load_program
from kookabug_core.registry import default_registry
from kookabug_core.win.credentials import CredentialStore
from kookabug_core.workspace import (
    Workspace,
    WorkspaceError,
    ensure_workspace_id,
    workspace_id,
)

windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows 자격 증명 관리자")


@windows
def test_credential_secret_resolves_in_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KOOKABUG_SECRET_ACCOUNTS_QA_PASSWORD", raising=False)
    ws = make_workspace(tmp_path / "ws")
    wid = ensure_workspace_id(ws.root)
    store = CredentialStore()  # 제품 접두 — 무작위 워크스페이스 ID라 다른 키와 겹치지 않는다
    store.write(wid, "accounts.qa_password", "cred-pass-01")
    try:
        ws = Workspace.open(ws.root)
        graph = (
            GraphBuilder()
            .entry("n_type")
            .node(
                "n_type",
                "core.input.type_text",
                inputs={"text": secret("accounts.qa_password"), "clear": True},
                next={"done": "n_pass"},
            )
            .node("n_pass", "core.test.pass")
        )
        graph.write(ws, "tests/t.graph.json")
        program = load_program(ws, "tests/t.graph.json")  # 기본 비밀값 제공자
        platform = FakePlatform([])
        result = Executor(
            default_registry(), platform=platform, clock=FakeClock(), artifacts=MemoryArtifacts()
        ).run(program, ExecOptions(run_id="r1"))
        assert result.verdict == "pass", result.events
        typed = [c for c in platform.input.calls if c.method == "type_text"]
        assert len(typed) == 1 and typed[0].args[0].reveal() == "cred-pass-01"
        assert "cred-pass-01" not in json.dumps(result.events, ensure_ascii=False, default=str)
    finally:
        store.delete(wid, "accounts.qa_password")


def test_ensure_workspace_id_adds_only_id(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    original = '{\n  "format": "kookabug.workspace/0",\n  "settings": {"game.title": "S"}\n}\n'
    (root / "kookabug.json").write_text(original, encoding="utf-8")
    assert workspace_id(Workspace.open(root)) is None
    wid = ensure_workspace_id(root)
    assert str(uuid.UUID(wid)) == wid
    data = json.loads((root / "kookabug.json").read_text(encoding="utf-8"))
    assert data == {"format": "kookabug.workspace/0", "settings": {"game.title": "S"}, "id": wid}
    assert workspace_id(Workspace.open(root)) == wid
    assert ensure_workspace_id(root) == wid  # 두 번째는 그대로
    assert Workspace.open(root).diagnostics == []


def test_ensure_workspace_id_refuses_broken_file(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "kookabug.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(WorkspaceError):
        ensure_workspace_id(root)
    assert (root / "kookabug.json").read_text(encoding="utf-8") == "{broken"
