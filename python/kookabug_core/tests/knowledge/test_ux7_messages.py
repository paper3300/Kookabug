"""UX7 F: 형식 오류 문구 — 빠진 필드 이름과 허용 필드 목록 (요청자가 정한 키 이름은 싣지
않는다), 보고함 목록 줄의 한 줄 결과(headline), 위키 쓰기 충돌의 지금 sha256, 붙여 실행 기록은
근거가 아니다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kookabug_core.agent_job.report import headline_of
from kookabug_core.knowledge import ops
from kookabug_core.knowledge.formats import Actor, KnowledgeError, shape_problem

AGENT = Actor("agent", id="agent-x")


def no_check(_: object) -> None:
    return None


def test_missing_field_named_with_allowed_list() -> None:
    request = {"request_id": "r1", "ops": [{"file": "lessons", "base_revision": 0, "item": {}}]}
    problem = shape_problem(request, "knowledge-ops")
    assert problem is not None
    assert problem.startswith("/ops/0: missing_field 'op'")
    allowed = problem.split("허용:", 1)[1]
    for name in ("op", "file", "item", "base_revision"):
        assert name in allowed


def test_unknown_field_hides_requester_key_but_lists_allowed() -> None:
    word = "hunter2secretkey"
    case = {"format": "kookabug.case/0", word: 1}
    problem = shape_problem(case, "case")
    assert problem is not None and word not in problem
    if "unknown_field" in problem:
        assert "허용:" in problem


def test_headline_falls_back_to_first_line() -> None:
    assert headline_of("로그인 팝업까지 — 계정 필요", "요약") == "로그인 팝업까지 — 계정 필요"
    assert headline_of(None, "## 로비까지 갔다\n둘째 줄") == "로비까지 갔다"
    long = "가" * 80
    cut = headline_of(None, long)
    assert cut is not None and len(cut) == 60 and cut.endswith("…")
    assert headline_of(None, None) is None and headline_of("  ", "") is None


def test_wiki_conflict_carries_current_sha(tmp_path: Path) -> None:
    (tmp_path / "kookabug.json").write_text('{"format": "kookabug.workspace/0"}', "utf-8")
    wrote = ops.wiki_write(
        tmp_path, "wiki/notes.md", "a\n", None, actor=AGENT, check_secrets=no_check
    )
    got = ops.wiki_read(tmp_path, "wiki/notes.md")
    assert got["sha256"] == wrote["sha256"]
    with pytest.raises(KnowledgeError) as caught:
        ops.wiki_write(
            tmp_path, "wiki/notes.md", "b\n", "0" * 64, actor=AGENT, check_secrets=no_check
        )
    assert caught.value.code == "revision_conflict"
    assert caught.value.fields.get("sha256") == got["sha256"]
    with pytest.raises(KnowledgeError) as caught:
        ops.wiki_read(tmp_path, "notes.md")
    assert caught.value.code == "policy_path" and "wiki/environment.md" in caught.value.message


def test_run_source_reads_run_json(tmp_path: Path) -> None:
    folder = tmp_path / "runs" / "2026-11-15T00-00-00_x_abcd1234"
    folder.mkdir(parents=True)
    (folder / "run.json").write_text(json.dumps({"source": "agent_attach"}), "utf-8")
    assert ops.run_source(folder) == "agent_attach"
    assert ops.run_source(tmp_path / "none") is None
