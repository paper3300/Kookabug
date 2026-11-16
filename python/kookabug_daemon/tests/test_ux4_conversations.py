"""UX4 이전 대화 daemon 쪽 (실제 daemon): 사람 연결은 저장·목록·읽기·지우기. 워크스페이스(게임)
비밀값은 가리지 않는다(UX11 B — 작업 토큰만 가린다). Agent 연결은 판정 전 거부."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import copy_example_workspace
from kookabug_daemon.client import DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

CID = "c-20261112-120000-beef"
SECRET = "ux4-secret-value-123"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return copy_example_workspace(tmp_path)


@pytest.fixture
def daemon(ws: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ThreadDaemon]:
    monkeypatch.setenv("KOOKABUG_SECRET_UX4_TEST", SECRET)
    with ThreadDaemon(ws) as d:
        yield d


def test_save_list_get_delete_keeps_game_secret(ws: Path, daemon: ThreadDaemon) -> None:
    item = {"kind": "user", "text": f"토큰 {SECRET} 써", "chips": []}
    with daemon.client() as ui:
        saved = ui.call(
            "conversations.save",
            {
                "conversation": {
                    "id": CID,
                    "agent_id": "fake",
                    "agent_name": "가짜",
                    "acp_session": None,
                    "items": [item],
                }
            },
        )["conversation"]
        # 게임 비밀값(워크스페이스 비밀값)은 가리지 않는다 (UX11 B)
        assert saved["id"] == CID and SECRET in saved["title"]
        raw = (ws / ".kookabug/conversations" / f"{CID}.json").read_text("utf-8")
        assert SECRET in raw and "***" not in raw
        listed = ui.call("conversations.list", {})["conversations"]
        assert [c["id"] for c in listed] == [CID]
        got = ui.call("conversations.get", {"id": CID})["conversation"]
        assert got["items"][0]["text"] == f"토큰 {SECRET} 써" and got["acp_session"] is None
        assert ui.call("conversations.delete", {"id": CID}) == {"deleted": True}
        with pytest.raises(DaemonError) as caught:
            ui.call("conversations.get", {"id": CID})
        assert caught.value.kind == "not_found"


def test_agent_connection_denied(daemon: ThreadDaemon) -> None:
    hello = {"kind": "agent", "name": "mcp", "version": "0", "id": "panel", "attended": True}
    with daemon.client(hello) as agent:
        for method, params in (("conversations.list", {}), ("conversations.get", {"id": CID})):
            with pytest.raises(DaemonError) as caught:
                agent.call(method, params, timeout=60)
            assert caught.value.kind == "permission_denied", method
