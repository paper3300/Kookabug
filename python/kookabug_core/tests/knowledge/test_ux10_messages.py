"""UX10 A·C: 형식 오류 안내를 한 번에 (빠진 필드 전부·허용 값 목록, 요청자 키·값은 싣지 않음),
init·entry 플레이북의 최소 예가 실제 검증기(지식 연산·사건 고치기)를 통과한다."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from kb_testing.sample_game import copy_example_workspace
from kookabug_core import cases, playbooks
from kookabug_core.knowledge import ops
from kookabug_core.knowledge.formats import Actor, KnowledgeError, shape_problem
from kookabug_core.schema.shape import metaschema

JOB = "j-20261116-090000-aaaa"
AGENT = Actor("agent", f"job:{JOB}", client="fake", job=JOB)
WORD = "hunter2secretkey"


def no_secret(_: Any) -> None:
    return None


def apply(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    return ops.apply(root, request, actor=AGENT, check_secrets=no_secret)


def open_case(root: Path) -> tuple[str, int]:
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
        root, facts, title=None, evidence=None, actor=AGENT, check_secrets=no_secret
    )
    doc, _ = cases.get_case(root, str(opened["case"]))
    return str(opened["case"]), int(doc["revision"])


# ---------------------------------------------------------------- A. 한 번에 안내


def test_claim_add_lists_all_missing_fields_at_once(tmp_path: Path) -> None:
    root = copy_example_workspace(tmp_path)
    request = {
        "request_id": "ux10-a1",
        "ops": [{"op": "add", "file": "features/title", "base_revision": 0, "item": {}}],
    }
    request["ops"][0]["item"] = {"id": "title.x", "statement": "s"}
    with pytest.raises(KnowledgeError) as caught:
        apply(root, request)
    message = caught.value.message
    assert caught.value.code == "format"
    # Kookabug가 채우는 rev·status 말고 빠진 필드가 한 메시지에 모두
    assert "missing_fields 'basis', 'kind'" in message, message


def test_claim_kind_invalid_lists_allowed_values(tmp_path: Path) -> None:
    root = copy_example_workspace(tmp_path)
    item = {"id": "title.x", "kind": WORD, "statement": "s", "basis": []}
    request = {
        "request_id": "ux10-a2",
        "ops": [{"op": "add", "file": "features/title", "base_revision": 0, "item": item}],
    }
    with pytest.raises(KnowledgeError) as caught:
        apply(root, request)
    message = caught.value.message
    assert "/kind: invalid_value" in message
    assert '"expected", "guess", "observed"' in message
    assert WORD not in message  # 요청 값은 싣지 않는다


def test_case_hypothesis_missing_then_invalid(tmp_path: Path) -> None:
    root = copy_example_workspace(tmp_path)
    case_id, revision = open_case(root)

    def update(hypothesis: dict[str, Any]) -> str:
        with pytest.raises(KnowledgeError) as caught:
            cases.update_case(
                root,
                case_id,
                revision,
                {"hypotheses": [hypothesis]},
                actor=AGENT,
                check_secrets=no_secret,
            )
        return caught.value.message

    message = update({"note": "n"})
    assert "/hypotheses/0: missing_fields 'cause', 'state'" in message, message
    message = update({"cause": WORD, "state": "nope", WORD: 1})
    assert "/hypotheses/0/cause: invalid_value (허용 값: " in message
    for value in metaschema("case")["properties"]["hypotheses"]["items"]["properties"]["cause"][
        "enum"
    ]:
        assert f'"{value}"' in message
    assert "/hypotheses/0/state: invalid_value" in message and '"supported"' in message
    assert "unknown_field" in message
    assert WORD not in message and "nope" not in message


def test_allowed_values_are_capped() -> None:
    from kookabug_core.schema.shape import listing

    many = [str(i) for i in range(25)]
    assert listing(many).endswith("19 외 5개")
    assert listing(many[:3]) == "0, 1, 2"


def test_pattern_hint_is_schema_rule_not_value() -> None:
    problem = shape_problem({"id": WORD.upper(), "rev": 1}, "claims", ref="#/$defs/ClaimRef")
    assert problem is not None
    assert "/id: pattern_mismatch (형식: 정규식 ^[a-z][a-z0-9_.]{0,127}$)" in problem
    assert WORD.upper() not in problem


def test_many_problems_are_cut() -> None:
    hypotheses = [{} for _ in range(8)]
    problem = shape_problem({"format": "kookabug.case/0", "hypotheses": hypotheses}, "case")
    assert problem is not None and problem.count("; ") == 4 and problem.endswith("곳")


# ---------------------------------------------------------------- C. 플레이북 최소 예


def examples(name: str) -> list[dict[str, Any]]:
    body = playbooks.load(name).body
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", body, re.S)]


@pytest.mark.parametrize("name", ["init", "entry"])
def test_playbook_examples_pass_real_validators(name: str, tmp_path: Path) -> None:
    found = examples(name)
    claim = next(e for e in found if "ops" in e)
    hypothesis = next(e for e in found if "changes" in e)
    root = copy_example_workspace(tmp_path)

    applied = apply(root, claim)
    assert applied["applied"] is True

    case_id, revision = open_case(root)
    assert hypothesis["base_revision"] == revision  # 새로 연 사건의 revision
    result = cases.update_case(
        root,
        case_id,
        revision,
        hypothesis["changes"],
        actor=AGENT,
        check_secrets=no_secret,
    )
    assert result["revision"] == revision + 1


@pytest.mark.parametrize("name", ["init", "entry"])
def test_playbook_lists_schema_values(name: str) -> None:
    body = playbooks.load(name).body
    claim = metaschema("claims")["$defs"]["Claim"]["properties"]
    hyp = metaschema("case")["properties"]["hypotheses"]["items"]["properties"]
    for value in [*claim["kind"]["enum"], *hyp["cause"]["enum"], *hyp["state"]["enum"]]:
        assert f"`{value}`" in body, value
    # 게임 실행 서브그래프는 경로 대신 게임 설정
    assert "`path`" in body and "game.executable" in body
