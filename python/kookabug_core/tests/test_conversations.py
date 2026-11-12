"""에이전트 패널 이전 대화 저장 (UX4): 가림·제목·상한·경계."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from kookabug_core import conversations as conv


def _conv(cid: str, text: str = "안녕", **extra: object) -> dict[str, object]:
    return {
        "id": cid,
        "agent_id": "fake",
        "agent_name": "가짜",
        "acp_session": "s1",
        "items": [
            {"kind": "user", "text": text, "chips": []},
            {"kind": "agent", "text": "답"},
            {
                "kind": "tools",
                "tools": [{"title": "kb_run_start", "status": "completed", "failed": False}],
                "hidden": 0,
                "seconds": 2,
            },
            {"kind": "permission", "title": "파일 쓰기", "outcome": "selected", "chosen": "허용"},
        ],
        **extra,
    }


def test_save_redacts_workspace_secrets(tmp_path: Path) -> None:
    secret = "hunter2-pw"
    data = _conv("c-20261112-101010-abcd", text=f"비번은 {secret} 야")
    data["items"].append({"kind": "agent", "text": f"받았다: {secret}{secret}"})  # type: ignore[union-attr]
    summary = conv.save(tmp_path, data, [secret, "x"])
    raw = (tmp_path / ".kookabug/conversations/c-20261112-101010-abcd.json").read_text("utf-8")
    assert secret not in raw
    stored = json.loads(raw)
    assert stored["format"] == conv.FORMAT
    assert stored["items"][0]["text"] == "비번은 *** 야"
    assert stored["items"][-1]["text"] == "받았다: ******"
    # 제목은 가린 뒤의 첫 사용자 메시지
    assert summary["title"] == "비번은 *** 야" and stored["title"] == summary["title"]
    assert summary["count"] == 5 and summary["agent_name"] == "가짜"


def test_save_refuses_when_secrets_unknown(tmp_path: Path) -> None:
    with pytest.raises(conv.ConversationError) as caught:
        conv.save(tmp_path, _conv("c-20261112-101010-abcd"), None)
    assert caught.value.code == "secret_unchecked"
    assert not (tmp_path / ".kookabug/conversations").exists()


def test_keeps_created_at_and_caps_count(tmp_path: Path) -> None:
    first = "c-20261112-000000-0000"
    conv.save(tmp_path, _conv(first), [], now="2026-11-12T00:00:00.000000Z")
    conv.save(tmp_path, _conv(first, "다시"), [], now="2026-11-12T00:00:05.000000Z")
    got = conv.get(tmp_path, first)
    assert got["created_at"] == "2026-11-12T00:00:00.000000Z"
    assert got["updated_at"] == "2026-11-12T00:00:05.000000Z" and got["title"] == "다시"
    for i in range(1, 5):
        conv.save(
            tmp_path,
            _conv(f"c-20261112-00000{i}-000{i}"),
            [],
            now=f"2026-11-12T00:01:0{i}.000000Z",
            keep=3,
        )
    ids = [s["id"] for s in conv.list_summaries(tmp_path)]
    assert ids == ["c-20261112-000004-0004", "c-20261112-000003-0003", "c-20261112-000002-0002"]
    assert conv.delete(tmp_path, "c-20261112-000003-0003") is True
    assert conv.delete(tmp_path, "c-20261112-000003-0003") is False
    with pytest.raises(conv.ConversationError):
        conv.get(tmp_path, first)


def test_bad_id_refused(tmp_path: Path) -> None:
    with pytest.raises(conv.ConversationError):
        conv.save(tmp_path, _conv("../escape"), [])
    with pytest.raises(conv.ConversationError):
        conv.get(tmp_path, "c-..")


def test_redact_before_clip_secret_on_boundary(tmp_path: Path) -> None:
    """검수 1 H1: 길이 상한(20000자) 경계에 걸친 비밀값도 앞부분이 남지 않는다. 제목 경계도 같다."""
    secret = "sample-secret-0123456789abcdef"
    cid = "c-20261112-101010-beef"
    data = _conv(cid, text="x" * 19980 + secret)
    items = cast(list[dict[str, object]], data["items"])
    items.append({"kind": "agent", "text": "y" * 19990 + secret + "끝"})
    items.append(
        {
            "kind": "tools",
            "tools": [{"title": "z" * 19995 + secret, "status": "completed", "failed": False}],
            "hidden": 0,
            "seconds": 0,
        }
    )
    conv.save(tmp_path, data, [secret])
    raw = (tmp_path / f".kookabug/conversations/{cid}.json").read_text("utf-8")
    for n in (6, 10, 20):
        assert secret[:n] not in raw, n
    got = conv.get(tmp_path, cid)
    assert got["items"][0]["text"] == "x" * 19980 + "***"
    # 제목 경계: 앞 40자 안에 비밀값이 걸쳐도 남지 않는다
    title_cid = "c-20261112-101010-cafe"
    conv.save(tmp_path, _conv(title_cid, text="a" * 30 + secret), [secret])
    title = conv.get(tmp_path, title_cid)["title"]
    assert secret[:6] not in title and title.startswith("a" * 30 + "***")
