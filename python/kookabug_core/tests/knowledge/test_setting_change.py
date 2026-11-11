"""설정 바꾸기 제안 (UX2 C) — 코어: 허용 목록·모양·비밀값·저장, 보고 항목·결정.

설정 파일 적용(마법사 저장과 같은 경로)은 daemon 검사(`test_ux2_methods`)가 본다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from helpers.knowledge import CHECK, SECRET, add, apply, make_ws

from kookabug_core.agent_job import report as reports
from kookabug_core.knowledge import setting_change
from kookabug_core.knowledge.formats import KnowledgeError

JOB = "j-20261111-120000-abcd"
META = {
    "id": JOB,
    "playbook": "followup",
    "trigger": "manual",
    "agent": {"profile": "x"},
    "started_at": "2026-11-11T12:00:00Z",
    "budget": {"minutes": 60, "runs": 30},
}


def unknown(root: Path, question: str = "창 제목은?") -> str:
    done = apply(
        root,
        [
            add(
                "unknowns",
                {
                    "question": question,
                    "human_only": True,
                    "blocks": [],
                    "how": "답",
                    "source": None,
                },
            )
        ],
        rid="ux2-unknown",
    )
    return str(done["results"][0]["id"])


def propose(root: Path, key: str, value: Any, *, reason: str = "사람 답", ids: Any = ()) -> Any:
    return setting_change.propose(root, JOB, key, value, reason, list(ids), check_secrets=CHECK)


def code(fn: Any, *args: Any, **kwargs: Any) -> str:
    with pytest.raises(KnowledgeError) as info:
        fn(*args, **kwargs)
    return info.value.code


def test_allow_list_and_shapes(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    for key in ("game.client_size", "agents.default", "secrets.qa", "permissions.preset", "x"):
        assert code(propose, root, key, "v") == "setting_not_allowed"
    bad: list[tuple[str, Any]] = [
        ("game.title", ""),
        ("game.title", 3),
        ("game.title", "a\nb"),
        ("game.args", "-windowed"),
        ("game.args", [1]),
        ("sources.add", {"kind": "secret", "location": "D:/x"}),
        ("sources.add", {"kind": "code"}),
        ("cheats.categories.add", {"id": "Bad", "title": "t", "unattended": False}),
        ("cheats.categories.add", {"id": "ok", "title": "t"}),
        ("automation.forbidden.add", {"kind": "text"}),
        ("automation.forbidden.add", {"kind": "target", "path": "C:/x.target.json"}),
    ]
    for key, value in bad:
        assert code(propose, root, key, value) == "format", (key, value)
    assert code(propose, root, "game.title", "Sample", reason="") == "format"
    assert code(propose, root, "game.title", "Sample", ids=["u-20261111-000000-ffff"]) == (
        "unknown_id"
    )
    # 작업 ID 없는 제안 없음 (작업 연결 전용)
    with pytest.raises(KnowledgeError) as info:
        setting_change.propose(root, "", "game.title", "x", "r", [], check_secrets=CHECK)
    assert info.value.code == "job_only"
    assert setting_change.load_proposals(root, JOB) == []


def test_secret_in_value_or_reason_refused(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    assert code(propose, root, "game.args", ["-pw", SECRET]) == "secret_in_text"
    assert code(propose, root, "game.title", "Sample", reason=f"비번 {SECRET}") == "secret_in_text"
    assert code(
        propose, root, "sources.add", {"kind": "design_doc", "location": f"https://x/{SECRET}"}
    ) == ("secret_in_text")
    assert setting_change.load_proposals(root, JOB) == []


def test_propose_stores_in_job_folder_and_report_item(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    before = (root / "kookabug.json").read_bytes()
    uid = unknown(root)
    first = propose(root, "game.title", "Sample RPG", ids=[uid])
    second = propose(root, "sources.add", {"kind": "design_doc", "location": "D:/plans"})
    third = propose(
        root, "cheats.categories.add", {"id": "dev_safe", "title": "개발용", "unattended": True}
    )
    # 설정 파일은 바뀌지 않는다
    assert (root / "kookabug.json").read_bytes() == before
    assert first["current"] is None and first["unknowns"] == [uid]
    assert second["current"] == ["item_table", "gone", "design_doc"]
    stored = setting_change.load_proposals(root, JOB)
    assert [p["id"] for p in stored] == [first["id"], second["id"], third["id"]]
    file = root / ".kookabug" / "jobs" / JOB / "proposals.json"
    assert json.loads(file.read_text("utf-8"))["format"] == setting_change.FORMAT
    meta = {
        "id": JOB,
        "playbook": "followup",
        "trigger": "manual",
        "agent": {"profile": "x"},
        "started_at": "2026-11-11T12:00:00Z",
        "budget": {"minutes": 60, "runs": 30},
    }
    built = reports.build(root, meta, state="done", used={}, notes=None, check_secrets=CHECK)
    groups = [g for g in built["groups"] if g["items"][0]["kind"] == "setting_change"]
    assert sorted(g["title"] for g in groups) == [
        "설정 바꾸기 제안 · cheats.categories.add",
        "설정 바꾸기 제안 · game.title",
        "설정 바꾸기 제안 · sources.add",
    ]
    title = next(g for g in groups if g["title"].endswith("game.title"))
    item = title["items"][0]
    # 팀 보고에는 ID·키·이유·근거 질문만 — 값·현재 값은 이 PC 제안 파일에만 (검수 1 H1)
    assert item["setting"] == {"id": first["id"], "key": "game.title", "reason": "사람 답"}
    assert item["unknowns"] == [uid]
    assert setting_change.local_view(root, JOB, first["id"]) == {
        "value": "Sample RPG",
        "current": None,
        "current_hidden": False,
        "reason": "사람 답",
    }
    # followup도 Init 요약을 단다
    assert any(g["items"][0]["kind"] == "init_summary" for g in built["groups"])
    written = reports.write(root, built)  # 보고 형식 검사를 지난다
    assert reports.list_reports(root)[0]["undecided"] == 3
    team = (root / "knowledge" / "reports" / f"{JOB}.json").read_text("utf-8")
    assert "Sample RPG" not in team and "D:/plans" not in team and "item_table" not in team
    md = (root / written["rendered"]).read_text("utf-8")
    assert "키 `game.title`" in md and "Sample RPG" not in md  # 값은 위키에도 쓰지 않는다

    applied: list[dict[str, Any]] = []
    done = reports.decide_setting(
        root, JOB, title["key"], "accept", apply=lambda s: applied.append(dict(s)) or {"ok": 1}
    )
    assert done["decision"] == "accept" and applied[0]["key"] == "game.title"
    again = reports.read_report(root, JOB)
    assert again is not None
    assert next(g for g in again["groups"] if g["key"] == title["key"])["decision"]["by"] == "human"
    # 두 번 결정하지 않는다
    assert code(
        reports.decide_setting, root, JOB, title["key"], "reject", apply=lambda s: None
    ) == ("revision_conflict")
    # 거절은 적용 함수를 부르지 않는다
    other = next(g for g in groups if g["title"].endswith("sources.add"))
    reports.decide_setting(
        root, JOB, other["key"], "reject", apply=lambda s: applied.append(dict(s))
    )
    assert len(applied) == 1
    log = [
        json.loads(line)
        for line in (root / "knowledge" / "log.jsonl").read_text("utf-8").splitlines()
    ]
    ops = [(line["op"], line.get("fields")) for line in log if line["op"].startswith("setting_")]
    assert ops == [("setting_accept", ["game.title"]), ("setting_reject", ["sources.add"])]
    # 적용이 실패하면 결정을 남기지 않는다
    third_key = next(g for g in groups if g["title"].endswith("cheats.categories.add"))["key"]

    def conflict(_: Any) -> None:
        raise KnowledgeError("revision_conflict", "바뀜")

    assert code(reports.decide_setting, root, JOB, third_key, "accept", apply=conflict) == (
        "revision_conflict"
    )
    final = reports.read_report(root, JOB)
    assert final is not None
    assert next(g for g in final["groups"] if g["key"] == third_key)["decision"] is None


def test_local_secret_never_reaches_team_report(tmp_path: Path) -> None:
    """검수 1 H1 재현: 이 PC `game.args`에 비밀값 → 무해한 제안(`game.args=[]`) → 팀 보고에 원문이
    없다. 현재 값 스냅샷도 이 PC 파일에 원문을 쓰지 않고 해시만 남긴다."""
    root = make_ws(tmp_path)
    (root / ".kookabug").mkdir(exist_ok=True)
    local = {"format": "kookabug.local/0", "settings": {"game.args": ["--password", SECRET]}}
    (root / ".kookabug" / "local.json").write_text(json.dumps(local), "utf-8")
    got = propose(root, "game.args", [], reason="인자를 비운다")
    assert got["current"] is None and got["current_hidden"] is True
    assert got["current_hash"] == setting_change.value_hash(["--password", SECRET])
    proposals = (root / ".kookabug" / "jobs" / JOB / "proposals.json").read_text("utf-8")
    assert SECRET not in proposals
    meta = META
    reports.write(
        root, reports.build(root, meta, state="done", used={}, notes=None, check_secrets=CHECK)
    )
    team = (root / "knowledge" / "reports" / f"{JOB}.json").read_text("utf-8")
    assert SECRET not in team and "--password" not in team
    assert "인자를 비운다" in team  # 이유는 검사를 지나 실린다 (양성 대조)
    view = setting_change.local_view(root, JOB, got["id"])
    assert view is not None and view["current"] is None and view["current_hidden"] is True


def test_reason_rechecked_before_team_report(tmp_path: Path) -> None:
    """이유는 보고에 쓰기 직전 다시 검사한다: 검사기가 없거나 걸리면 자리 글로 바꾼다."""
    root = make_ws(tmp_path)
    got = propose(root, "game.title", "Sample", reason="C:/Users/someone/game 경로")
    meta = META

    def refuse(_: Any) -> None:
        raise KnowledgeError("secret_in_text", "걸림")

    for checker in (None, refuse):
        built = reports.build(root, meta, state="done", used={}, notes=None, check_secrets=checker)
        item = next(g for g in built["groups"] if g["items"][0]["kind"] == "setting_change")
        assert item["items"][0]["setting"] == {
            "id": got["id"],
            "key": "game.title",
            "reason": setting_change.REASON_HIDDEN,
        }


def test_existing_items_refused(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    config = json.loads((root / "kookabug.json").read_text("utf-8"))
    config["cheats"] = {"enabled": True, "categories": [{"id": "dev_safe", "title": "개발"}]}
    config["automation"] = {
        "format": "kookabug.automation/0",
        "forbidden": [{"kind": "text", "value": "결제"}],
    }
    (root / "kookabug.json").write_text(json.dumps(config), "utf-8")
    assert (
        code(
            propose,
            root,
            "cheats.categories.add",
            {"id": "dev_safe", "title": "t", "unattended": True},
        )
        == "exists"
    )
    assert code(propose, root, "automation.forbidden.add", {"kind": "text", "value": "결제"}) == (
        "exists"
    )
    got = propose(root, "automation.forbidden.add", {"kind": "text", "value": "캐릭터 삭제"})
    assert got["current"] == [{"kind": "text", "value": "결제"}]


def test_source_entry_like_wizard_step6() -> None:
    existing = [{"id": "design_doc"}]
    url, local = setting_change.source_entry(
        {"kind": "design_doc", "location": "https://wiki/x"}, existing, tag="abc123"
    )
    assert url == {"id": "design_doc_abc123", "kind": "design_doc", "title": "기획 문서",
                   "url": "https://wiki/x"} and local is None  # fmt: skip
    entry, local = setting_change.source_entry({"kind": "code", "location": "D:\\src"}, existing)
    assert entry == {"id": "game_code", "kind": "code", "title": "게임 코드", "local": True}
    assert local == "D:\\src"
    rel, local = setting_change.source_entry(
        {"kind": "data", "location": "data\\tables", "title": "테이블"}, []
    )
    assert rel == {"id": "data_table", "kind": "data", "title": "테이블", "path": "data/tables"}
