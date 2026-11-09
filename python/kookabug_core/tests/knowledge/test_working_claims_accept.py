"""작업 주장 덧씌움의 이력·수락·거절 (M8 계획 9장 R4, B1 인계 → B3) — 엄격: Agent 권한.

- 덧씌움은 지난 작업 rev를 지우지 않는다(보고 항목이 가리킨 rev를 찾을 때)
- 수락 대상은 `{id, rev}`(보고가 가리킨 작업 rev). 지금 작업 rev와 다르거나 팀 주장 rev가 덧씌움의
  바탕(`base_rev`)과 다르면 `revision_conflict`로 아무것도 바꾸지 않는다
- 수락한 주장이 낀 의미 충돌은 수락 때 다시 찾아 둘 다 `conflicted`로 둔다(조용히 고르지 않음)
- 파일형 작업 변경과 한 거래로 수락·거절한다(`adopt.decide`)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers.knowledge import HUMAN, add, apply, make_ws, price_claim, read

from kookabug_core import adopt as rules
from kookabug_core.knowledge.formats import KnowledgeError

SHOP = "knowledge/features/shop.json"
OVER = "knowledge/working/claims/shop.json"
CID = "shop.potion.price"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = make_ws(tmp_path)
    apply(root, [add("features/shop", price_claim())], rid="r0")
    return root


def revise(value: int, base_rev: int) -> dict[str, object]:
    return {
        "op": "revise",
        "file": "features/shop",
        "id": CID,
        "base_rev": base_rev,
        "changes": {"value": value, "statement": f"물약 가격은 {value}골드다"},
    }


def test_working_claim_history_kept(ws: Path) -> None:
    apply(ws, [revise(120, 1)], rid="r1")
    apply(ws, [revise(130, 2)], rid="r2")
    entry = read(ws, OVER)["claims"][0]
    assert entry["claim"]["rev"] == 3 and entry["claim"]["value"] == 130
    assert [h["rev"] for h in entry["history"]] == [2]
    assert entry["history"][0]["value"] == 120
    assert entry["base_rev"] == 1


def test_accept_pinned_rev_and_team_base(ws: Path) -> None:
    apply(ws, [revise(120, 1)], rid="r1")
    team = (ws / SHOP).read_bytes()
    over = (ws / OVER).read_bytes()
    # 보고가 가리킨 rev(2)가 아니면 거부
    with pytest.raises(KnowledgeError) as caught:
        rules.decide(ws, changes=[], claims=[{"id": CID, "rev": 1}], accept=True, by="ui")
    assert caught.value.code == "revision_conflict"
    # 팀 주장이 그 사이 바뀌었으면 거부 (덧씌움의 바탕 rev와 다름)
    apply(
        ws,
        [{**revise(100, 1), "changes": {"statement": "사람이 고친 문장"}}],
        actor=HUMAN,
        rid="h1",
    )
    team = (ws / SHOP).read_bytes()
    with pytest.raises(KnowledgeError) as caught:
        rules.decide(ws, changes=[], claims=[{"id": CID, "rev": 2}], accept=True, by="ui")
    assert caught.value.code == "revision_conflict"
    assert (ws / SHOP).read_bytes() == team and (ws / OVER).read_bytes() == over
    # 거절은 덧씌움에서만 뺀다
    out = rules.decide(ws, changes=[], claims=[{"id": CID, "rev": 2}], accept=False, by="ui")
    assert out["claims"] == [{"id": CID, "rev": 2, "file": None}]
    assert read(ws, OVER)["claims"] == [] and (ws / SHOP).read_bytes() == team


def test_accept_rechecks_semantic_conflict(ws: Path) -> None:
    other = price_claim(id="shop.potion.price_table", statement="표의 물약 가격 100골드")
    apply(ws, [add("features/shop", other, base=1)], actor=HUMAN, rid="h0")
    apply(ws, [revise(120, 1)], rid="r1")  # 작업 기준에서만 120 — 팀은 아직 충돌 없음
    assert all(c["status"] == "supported" for c in read(ws, SHOP)["claims"])
    out = rules.decide(ws, changes=[], claims=[{"id": CID, "rev": 2}], accept=True, by="ui")
    assert out["claims"] == [{"id": CID, "rev": 2, "file": "features/shop"}]
    assert len(out["conflicts"]) == 1
    claims = {c["id"]: c for c in read(ws, SHOP)["claims"]}
    assert claims[CID]["value"] == 120
    assert claims[CID]["status"] == "conflicted"
    assert claims["shop.potion.price_table"]["status"] == "conflicted"
    log = (ws / "knowledge" / "log.jsonl").read_text("utf-8")
    assert "accept_working_claim" in log
