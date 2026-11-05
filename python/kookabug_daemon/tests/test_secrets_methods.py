"""`secrets.list`·`secrets.create` (M4 계획 2.8, T7). 실제 자격 증명 관리자(제품 접두, 무작위
워크스페이스 ID — 끝에 지움). 녹화 세션(T8) 대신 `RecorderTexts` 위 단순 원천을 daemon에 둔다."""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from kb_testing.daemon import ThreadDaemon, make_workspace
from kookabug_core.recorder.fields import SecretText
from kookabug_core.recorder.secrets import RecorderTexts
from kookabug_core.win.credentials import CredentialStore
from kookabug_core.workspace import Workspace, ensure_workspace_id, workspace_id
from kookabug_daemon.client import DaemonError
from kookabug_daemon.methods.secrets import TextsSecretSource

pytestmark = [
    pytest.mark.process,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows 자격 증명 관리자"),
]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-7"}
RAW = "hunter22-pass"


@pytest.fixture
def root(tmp_path: Path) -> Iterator[Path]:
    root = make_workspace(tmp_path / "ws")
    yield root
    wid = workspace_id(Workspace.open(root))
    if wid is not None:
        store = CredentialStore()
        for key in store.keys(wid):
            store.delete(wid, key)


def texts_with_steps() -> RecorderTexts:
    texts = RecorderTexts()
    for span, box, raw in ((1, (400, 285, 320, 50), RAW), (2, (400, 205, 320, 50), "qa_tester")):
        texts.open_span(span, box)
        texts.put(span, SecretText(raw))
        texts.classifier.close(span, final=SecretText(raw))
    texts.classifier.label(1, "비밀번호")
    texts.classifier.label(2, "계정")
    texts.classifier.final(2, "qa_tester", SecretText("qa_tester"))
    return texts


def test_list_returns_keys_only(root: Path) -> None:
    before = (root / "kookabug.json").read_bytes()
    with ThreadDaemon(root) as d, d.client() as client:
        empty = client.call("secrets.list")
        assert empty["keys"] == [] and empty["env_note"]
        assert (root / "kookabug.json").read_bytes() == before  # 목록은 ID를 만들지 않는다
        wid = ensure_workspace_id(root)
        store = CredentialStore()
        store.write(wid, "accounts.qa", "value-one")
        store.write(wid, "accounts.admin", "value-two")
        other_ws = str(uuid.uuid4())
        store.write(other_ws, "other.ws", "value-three")  # 다른 워크스페이스
        try:
            result = client.call("secrets.list")
        finally:
            store.delete(other_ws, "other.ws")
    assert result["keys"] == [
        {"key": "accounts.admin", "source": "credential"},
        {"key": "accounts.qa", "source": "credential"},
    ]
    text = json.dumps(result, ensure_ascii=False)
    assert "value-one" not in text and "value-two" not in text and "other.ws" not in text


def test_create_only_from_recorder_memory(root: Path) -> None:
    texts = texts_with_steps()
    with ThreadDaemon(root) as d, d.client() as client, d.client() as other:
        params = {"key": "accounts.qa_password", "from_step": "rs1"}
        with pytest.raises(DaemonError) as caught:
            client.call("secrets.create", params)
        assert caught.value.kind == "recorder_state_invalid"  # 녹화 세션 없음
        owner = min(c.number for c in d.daemon.transport.connections)  # 먼저 연 client
        source = TextsSecretSource(texts, owner, {"rs1": 1, "rs2": 2})
        d.call_in_loop(setattr, d.daemon, "recorder_secrets", source)
        with pytest.raises(DaemonError) as caught:
            other.call("secrets.create", params)
        assert caught.value.kind == "not_owner"
        with pytest.raises(DaemonError) as caught:  # 일반 글자 스텝의 원문은 비밀값으로 못 만든다
            client.call("secrets.create", {"key": "accounts.qa", "from_step": "rs2"})
        assert caught.value.kind == "recorder_state_invalid"
        result = client.call("secrets.create", params)
        assert result == {"key": "accounts.qa_password", "source": "credential"}
        with pytest.raises(DaemonError) as caught:
            client.call("secrets.create", params)
        assert caught.value.kind == "exists"
        listed = client.call("secrets.list")
    wid = workspace_id(Workspace.open(root))
    assert wid is not None
    assert CredentialStore().read(wid, "accounts.qa_password") == RAW
    assert {"key": "accounts.qa_password", "source": "credential"} in listed["keys"]
    # 스텝은 그 키를 고른 비밀값이 됐다
    assert texts.view(1) == {
        "text_state": "secret",
        "text_len": len(RAW),
        "secret_key": "accounts.qa_password",
    }
    assert texts.commit_blocked([1, 2]) is None
    assert texts.graph_text(1) == {"$secret": "accounts.qa_password"}


def test_agent_denied(root: Path) -> None:
    with ThreadDaemon(root) as d, d.client(AGENT) as agent:
        for method, params in (
            ("secrets.list", {}),
            ("secrets.create", {"key": "a", "from_step": "rs1"}),
        ):
            with pytest.raises(DaemonError) as caught:
                agent.call(method, params)
            assert caught.value.kind == "permission_denied", method
