"""위키 렌더 (M8 계획 3.1·E8) — 결정적, 값 대신 필드 이름."""

from __future__ import annotations

import json
from pathlib import Path

from helpers.knowledge import AGENT, CHECK, add, apply, make_ws, price_claim

from kookabug_core.knowledge import ops, render


def test_index_log_feature_tables_deterministic(tmp_path: Path) -> None:
    roots = [make_ws(tmp_path / n) for n in ("a", "b")]
    outputs = []
    for root in roots:
        ops.wiki_write(
            root,
            "wiki/features/shop.md",
            "# 상점\n\n설명 글\n",
            None,
            actor=AGENT,
            check_secrets=CHECK,
        )
        apply(root, [add("features/shop", price_claim())], rid="r1")
        page = (root / "wiki/features/shop.md").read_text("utf-8")
        index = (root / "wiki/index.md").read_text("utf-8")
        log = (root / "wiki/log.md").read_text("utf-8")
        outputs.append((page, index))
        # Agent 글은 남고 주장 표가 표시 사이에 들어간다
        assert page.startswith("# 상점\n\n설명 글\n")
        assert page.count(render.CLAIMS_BEGIN) == 1
        assert "| shop.potion.price | 1 | expected | supported |" in page
        assert "- [shop](features/shop.md) — 주장 1개 (supported 1)" in index
        assert "**add** features/shop · shop.potion.price" in log and "wiki_write" in log
        # 같은 입력이면 다시 렌더해도 바이트가 같다
        doc = json.loads((root / "knowledge/features/shop.json").read_text("utf-8"))
        assert render.render_feature_page(page, doc) == page
    assert outputs[0] == outputs[1]
    # Agent가 표 구간을 고쳐 써도 Kookabug가 다시 쓴다
    root = roots[0]
    sha = __import__("hashlib").sha256((root / "wiki/features/shop.md").read_bytes()).hexdigest()
    forged = f"# 상점\n\n{render.CLAIMS_BEGIN}\n| 가짜 |\n{render.CLAIMS_END}\n"
    ops.wiki_write(root, "wiki/features/shop.md", forged, sha, actor=AGENT, check_secrets=CHECK)
    page = (root / "wiki/features/shop.md").read_text("utf-8")
    assert "가짜" not in page and "shop.potion.price" in page


def test_log_has_field_names_not_values(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    apply(root, [add("features/shop", price_claim())], rid="r1")
    revise = {
        "op": "revise",
        "file": "features/shop",
        "id": "shop.potion.price",
        "base_rev": 1,
        "changes": {"statement": "아주 특별한 문장"},
    }
    apply(root, [revise], rid="r2")
    text = (root / "knowledge/log.jsonl").read_text("utf-8") + (root / "wiki/log.md").read_text(
        "utf-8"
    )
    assert "아주 특별한 문장" not in text and "statement" in text


def test_report_render_pins_revisions() -> None:
    report = {
        "format": "kookabug.report/0",
        "job": "j-20261109-100000-abcd",
        "playbook": "repair",
        "trigger": "manual",
        "agent": "claude",
        "started_at": "2026-11-09T10:00:00Z",
        "ended_at": "2026-11-09T10:12:00Z",
        "state": "done",
        "budget": {"minutes": [12, 60], "runs": [9, 30]},
        "groups": [
            {
                "key": "auto_adopted|ui_change|targets/shop/buy.target.json",
                "cause": "ui_change",
                "title": "상점 구매 버튼 위치가 바뀜",
                "items": [
                    {
                        "kind": "auto_adopted",
                        "case": "c-20261109-100100-abcd",
                        "adoption": "a-20261109-101000-abcd",
                        "checks": ["oracle", "negative", "affected:3"],
                        "claims": [{"id": "shop.potion.price", "rev": 3}],
                    }
                ],
                "decision": None,
            }
        ],
        "unknowns": [],
        "notes": "요약",
        "rendered": None,
    }
    text = render.render_report(report, {"shop.potion.price": 3})
    assert text == render.render_report(report, {"shop.potion.price": 3})
    assert "a-20261109-101000-abcd" in text and "주장 shop.potion.price rev 3" in text
