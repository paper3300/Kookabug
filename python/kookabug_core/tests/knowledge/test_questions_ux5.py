"""UX5 사람 질문 규칙·테스트 계정 질문·막힘 보고 (코어).

- Init·이어 하기는 사람 질문(`human_only` 미지수)을 하나도 못 만든다 (`question_limit`, 안내 글)
- 접속 경로(`entry`)는 credential 종류만, 상한 3개. 다른 작업·작업 밖은 지금 그대로
- credential 답은 사람이 준 글이 아니라 키 이름만 담은 고정 글 (값이 지식에 남지 않는다)
- Init 작업의 막힘 사건(needs_info)은 보고에서 "막힘" 묶음, 시도한 것과 결과가 보인다
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kb_testing.sample_game import copy_example_workspace
from kookabug_core import cases, playbooks
from kookabug_core.agent_job import report as reports
from kookabug_core.knowledge import human, ops
from kookabug_core.knowledge.formats import Actor, KnowledgeError

JOB = "j-20261113-090000-aaaa"
SECRET = "hunter22-very-secret"


def no_secret(_: Any) -> None:
    return None


def agent(job: str | None = JOB) -> Actor:
    return Actor("agent", f"job:{job}" if job else "panel", client="fake", job=job)


def question(
    text: str, *, kind: str | None = None, keys: list[str] | None = None
) -> dict[str, Any]:
    item: dict[str, Any] = {"question": text, "human_only": True, "blocks": [], "how": "확인"}
    if kind is not None:
        item["kind"] = kind
    if keys is not None:
        item["secret_keys"] = keys
    return item


def add(
    root: Path,
    rid: str,
    items: list[dict[str, Any]],
    playbook: str | None,
    *,
    job: str | None = JOB,
) -> dict[str, Any]:
    base = _revision(root)
    return ops.apply(
        root,
        {
            "request_id": rid,
            "ops": [
                {"op": "add", "file": "unknowns", "base_revision": base, "item": i} for i in items
            ],
        },
        actor=agent(job),
        check_secrets=no_secret,
        questions=playbooks.question_rule(playbook),
    )


def _revision(root: Path) -> int:
    path = root / "knowledge" / "unknowns.json"
    if not path.exists():
        return 0
    return int(json.loads(path.read_text("utf-8"))["revision"])


def unknowns(root: Path) -> list[dict[str, Any]]:
    return list(json.loads((root / "knowledge" / "unknowns.json").read_text("utf-8"))["unknowns"])


def test_rules_per_playbook() -> None:
    assert playbooks.question_rule("init") == playbooks.QuestionRule(0)
    assert playbooks.question_rule("followup") == playbooks.QuestionRule(0)
    entry = playbooks.question_rule("entry")
    assert entry is not None and entry.limit == 3 and entry.kinds == {"credential"}
    for other in ("triage", "repair", "explore", "author", "lint", None):
        assert playbooks.question_rule(other) is None


@pytest.mark.parametrize("playbook", ["init", "followup"])
def test_init_refuses_first_human_question(tmp_path: Path, playbook: str) -> None:
    root = copy_example_workspace(tmp_path)
    with pytest.raises(KnowledgeError) as caught:
        add(root, "q1", [question("게임 창 제목은 무엇인가요")], playbook)
    assert caught.value.code == "question_limit"
    assert "모르는 것" in caught.value.message and "막힘" in caught.value.message
    assert not (root / "knowledge" / "unknowns.json").exists() or unknowns(root) == []
    # 사람 질문이 아닌 미지수(위키에 남길 궁금증 기록)는 된다 — 양성 대조
    item = {"question": "상점 세금이 있나", "human_only": False, "blocks": [], "how": "탐색"}
    assert add(root, "q2", [item], playbook)["applied"] is True
    # 있던 미지수를 사람 질문으로 바꿔 넘을 수도 없다
    uid = unknowns(root)[0]["id"]
    with pytest.raises(KnowledgeError) as caught:
        ops.apply(
            root,
            {
                "request_id": "q3",
                "ops": [
                    {
                        "op": "revise",
                        "file": "unknowns",
                        "id": uid,
                        "base_rev": 1,
                        "changes": {"human_only": True},
                    }
                ],
            },
            actor=agent(),
            check_secrets=no_secret,
            questions=playbooks.question_rule(playbook),
        )
    assert caught.value.code == "question_limit"


def test_entry_allows_only_credential_up_to_three(tmp_path: Path) -> None:
    root = copy_example_workspace(tmp_path)
    with pytest.raises(KnowledgeError) as caught:
        add(root, "e1", [question("서버는 어느 것인가요")], "entry")
    assert caught.value.code == "question_limit" and "credential" in caught.value.message
    # 키 이름 제안이 없는 credential은 형식 거부
    with pytest.raises(KnowledgeError) as caught:
        add(root, "e2", [question("계정이 필요해요", kind="credential")], "entry")
    assert caught.value.code == "format"
    login = question(
        "로그인 화면이에요. 테스트 계정을 등록해 주세요",
        kind="credential",
        keys=["login.id", "login.password"],
    )
    assert add(root, "e3", [login], "entry")["applied"] is True
    # 같은 요청 둘 + 앞 요청 하나 = 3 (상한), 넷째는 거부
    two = [
        question("두 번째 계정", kind="credential", keys=["alt.id"]),
        question("세 번째 계정", kind="credential", keys=["alt2.id"]),
    ]
    assert add(root, "e4", two, "entry")["applied"] is True
    with pytest.raises(KnowledgeError) as caught:
        add(root, "e5", [question("네 번째", kind="credential", keys=["x.id"])], "entry")
    assert caught.value.code == "question_limit" and "상한(3개)" in caught.value.message
    # 다른 작업의 질문은 이 작업 상한에 세지 않는다
    other = "j-20261113-090000-bbbb"
    assert add(
        root, "e6", [question("다른 작업", kind="credential", keys=["y.id"])], "entry", job=other
    )["applied"]


def test_other_playbooks_and_non_job_unchanged(tmp_path: Path) -> None:
    root = copy_example_workspace(tmp_path)
    many = [question(f"질문 {i}") for i in range(5)]
    assert add(root, "t1", many, "triage")["applied"] is True
    assert add(root, "t2", [question("패널 질문")], None, job=None)["applied"] is True
    assert sum(1 for u in unknowns(root) if u["human_only"]) == 6


def test_credential_answer_keeps_no_value(tmp_path: Path) -> None:
    root = copy_example_workspace(tmp_path)
    login = question("로그인 화면", kind="credential", keys=["login.id", "login.password"])
    add(root, "c1", [login], "entry")
    item = unknowns(root)[0]
    registered: set[str] = set()
    person = Actor("human", "ui:1")

    def answer() -> dict[str, Any]:
        return human.answer_unknown(
            root,
            item["id"],
            item["rev"],
            SECRET,  # 렌더러가 실수로 값을 보내도 남지 않는다
            actor=person,
            check_secrets=no_secret,
            secret_exists=lambda key: key in registered,
        )

    with pytest.raises(KnowledgeError) as caught:
        answer()
    assert caught.value.code == "secret_missing" and SECRET not in caught.value.message
    registered.add("login.id")
    with pytest.raises(KnowledgeError):
        answer()  # 둘 다 있어야 한다
    registered.add("login.password")
    answer()
    after = unknowns(root)[0]
    assert after["state"] == "answered"
    assert "login.id" in after["answer"]["text"] and "login.password" in after["answer"]["text"]
    for rel in ("knowledge/unknowns.json", "knowledge/log.jsonl"):
        assert SECRET not in (root / rel).read_text("utf-8")
    # 일반 질문 답은 그대로 사람 글이다 (양성 대조)
    add(root, "c2", [question("일반 질문")], "triage")
    plain = next(u for u in unknowns(root) if u["question"] == "일반 질문")
    human.answer_unknown(
        root, plain["id"], plain["rev"], "사람 답", actor=person, check_secrets=no_secret
    )
    assert next(u for u in unknowns(root) if u["id"] == plain["id"])["answer"]["text"] == "사람 답"


def _meta(playbook: str) -> dict[str, Any]:
    return {
        "id": JOB,
        "playbook": playbook,
        "trigger": "manual",
        "agent": {"profile": "custom"},
        "started_at": "2026-11-13T09:00:00Z",
        "budget": {"minutes": 60, "runs": 3},
    }


def test_blocked_case_shown_as_blocked_in_setup_reports(tmp_path: Path) -> None:
    root = copy_example_workspace(tmp_path)
    facts = cases.Facts(
        run="r-0001",
        test="subgraphs/common/game_launch.graph.json",
        graph_sha="0" * 64,
        verdict="fail",
        code="window_not_found",
        node="n_launch",
        node_type="core.app.launch",
        claims=(),
    )
    opened = cases.open_case(
        root, facts, title=None, evidence=None, actor=agent(), check_secrets=no_secret
    )
    case_id = str(opened["case"])
    doc, _ = cases.get_case(root, case_id)
    tried = "실행하면 '서버에 연결할 수 없음'이 떠요. 설정 파일 두 개를 봤지만 주소가 없었어요."
    cases.update_case(
        root,
        case_id,
        int(doc["revision"]),
        {"state": "needs_info", "needs": [{"unknown": tried, "how": "사람이 설정을 고친다"}]},
        actor=agent(),
        check_secrets=no_secret,
    )
    used = {"runs": 1, "tool_calls": 3, "minutes": 1}
    built = reports.build(root, _meta("init"), state="done", used=used, notes=None)
    group = next(g for g in built["groups"] if any(i.get("case") == case_id for i in g["items"]))
    assert group["title"].startswith("막힘")
    assert tried in group["items"][0]["detail"]
    # 양성 대조: 준비 플레이북이 아니면 그대로 "판단 불가"
    other = reports.build(root, _meta("triage"), state="done", used=used, notes=None)
    group = next(g for g in other["groups"] if any(i.get("case") == case_id for i in g["items"]))
    assert group["title"].startswith("판단 불가")
