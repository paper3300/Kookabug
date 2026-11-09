"""제한 지식 변경 연산 (M8 계획 3.3·9장 R4) — 엄격: 지식 쓰기 경계·비밀값."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from helpers.knowledge import (
    AGENT,
    HUMAN,
    SECRET,
    add,
    apply,
    make_ws,
    price_claim,
    read,
    source_basis,
    tree,
)

from kookabug_core.knowledge import ops
from kookabug_core.knowledge.formats import Actor, KnowledgeError, cheat_digest, secret_checker
from kookabug_core.workspace import MemorySecrets

SHOP = "knowledge/features/shop.json"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return make_ws(tmp_path)


def code_of(root: Path, ops_: list[dict], **kw: object) -> str:
    with pytest.raises(KnowledgeError) as info:
        apply(root, ops_, **kw)  # type: ignore[arg-type]
    return info.value.code


def guess(cid: str, **extra: object) -> dict:
    return {
        "id": cid,
        "kind": "guess",
        "statement": "추측",
        "basis": [],
        "status": "hypothesis",
        **extra,
    }


def test_add_writes_claim_log_and_wiki(ws: Path) -> None:
    result = apply(ws, [add("features/shop", price_claim())])
    assert result["applied"] and result["revisions"] == {"features/shop": 1}
    doc = read(ws, SHOP)
    claim = doc["claims"][0]
    assert claim["rev"] == 1 and claim["basis"][0]["verified"] is True
    assert claim["basis"][0]["hash"].startswith("sha256:")
    log = [json.loads(x) for x in (ws / "knowledge/log.jsonl").read_text("utf-8").splitlines()]
    assert log[-1]["op"] == "add" and log[-1]["result"] == "applied"
    assert log[-1]["job"] == AGENT.job and "value" not in log[-1]
    assert "shop.potion.price" in (ws / "wiki/features/shop.md").read_text("utf-8")
    assert "features/shop.md" in (ws / "wiki/index.md").read_text("utf-8")


def test_apply_atomic_all_or_nothing(ws: Path) -> None:
    apply(ws, [add("features/shop", price_claim())], rid="r0")
    before = tree(ws)
    # 둘째 연산(없는 ID)이 틀리면 첫째(다른 파일 추가)도 쓰지 않는다
    bad = [
        add(
            "lessons", {"id": "notice.wait", "advice": "공지를 기다린다", "basis": [source_basis()]}
        ),
        {
            "op": "set_status",
            "file": "features/shop",
            "id": "shop.nope",
            "base_rev": 1,
            "status": "supported",
        },
    ]
    assert code_of(ws, bad) == "unknown_id"
    after = tree(ws)
    assert not (ws / "knowledge/lessons.json").exists()
    assert {k: v for k, v in after.items() if k not in ("knowledge/log.jsonl", "wiki/log.md")} == {
        k: v for k, v in before.items() if k not in ("knowledge/log.jsonl", "wiki/log.md")
    }
    last = (ws / "knowledge/log.jsonl").read_text("utf-8").splitlines()[-1]
    assert json.loads(last)["result"] == "refused"


REFUSAL_RECORDS = ("knowledge/log.jsonl", "wiki/log.md")
"""거부도 남기는 감사 기록 (의도한 예외 — 그 밖의 파일은 바이트 그대로)."""


def full_tree(root: Path) -> dict[str, bytes]:
    """워크스페이스 전체 파일 (거부 기록·잠금·요청 기록 폴더 제외)."""
    out: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or rel in REFUSAL_RECORDS:
            continue
        if rel == ".kookabug/knowledge.lock" or rel.startswith(
            (".kookabug/knowledge-requests/", ".kookabug/filetx/trash/")
        ):
            continue  # 요청 기록·거부 기록 거래가 옮겨 둔 이전 기록 사본
        out[rel] = path.read_bytes()
    return out


def test_revision_conflict_writes_nothing(ws: Path) -> None:
    apply(ws, [add("features/shop", price_claim())], rid="r0")
    shop = (ws / SHOP).read_bytes()
    before = full_tree(ws)
    assert code_of(ws, [add("features/shop", guess("shop.a"), base=0)]) == "revision_conflict"
    assert (
        code_of(
            ws,
            [
                {
                    "op": "attach_evidence",
                    "file": "features/shop",
                    "id": "shop.potion.price",
                    "base_rev": 9,
                    "basis": source_basis(),
                }
            ],
            rid="r2",
        )
        == "revision_conflict"
    )
    assert (ws / SHOP).read_bytes() == shop
    # 거부 기록(감사 이력·일지·요청 기록) 말고는 워크스페이스 어느 파일도 바뀌지 않았다
    assert full_tree(ws) == before
    lines = (ws / "knowledge/log.jsonl").read_text("utf-8").splitlines()
    assert [json.loads(x)["result"] for x in lines[-2:]] == ["refused", "refused"]


def test_request_id_idempotent(ws: Path) -> None:
    first = apply(ws, [add("features/shop", guess("shop.a"))], rid="same")
    again = apply(ws, [add("features/shop", guess("shop.a"))], rid="same")
    assert again["replayed"] is True and again["results"] == first["results"]
    assert read(ws, SHOP)["revision"] == 1 and len(read(ws, SHOP)["claims"]) == 1
    # 같은 ID로 다른 연산은 거부
    assert (
        code_of(ws, [add("features/shop", guess("shop.b"))], rid="same") == "idempotency_conflict"
    )
    # 거부도 같은 결과를 돌려준다
    assert (
        code_of(ws, [add("features/shop", guess("shop.a"), base=0)], rid="dup")
        == "revision_conflict"
    )
    assert (
        code_of(ws, [add("features/shop", guess("shop.a"), base=0)], rid="dup")
        == "revision_conflict"
    )


def test_semantic_conflict_marks_both(ws: Path) -> None:
    """사람(서비스) 요청: 같은 subject+property, 겹치는 범위의 expected 값이 다르면 팀 파일에서
    둘 다 conflicted (Agent 요청은 아래 간접 충돌 검사)."""
    apply(ws, [add("features/shop", price_claim())], actor=HUMAN, rid="r0")
    other = price_claim(id="shop.potion.price_event", value=120, statement="물약 가격 120골드")
    result = apply(ws, [add("features/shop", other, base=1)], actor=HUMAN, rid="r1")
    assert len(result["conflicts"]) == 1
    assert {(c["id"], c["rev"], c["basis"]) for c in result["conflicts"][0]["claims"]} == {
        ("shop.potion.price", 2, "team"),
        ("shop.potion.price_event", 1, "team"),
    }
    claims = {c["id"]: c for c in read(ws, SHOP)["claims"]}
    assert claims["shop.potion.price"]["status"] == "conflicted"
    assert claims["shop.potion.price_event"]["status"] == "conflicted"
    assert claims["shop.potion.price"]["rev"] == 2  # 이전 rev는 history로
    assert read(ws, SHOP)["history"][0]["rev"] == 1
    # 범위가 안 겹치면 충돌이 아니다
    apart = price_claim(id="shop.potion.price_live", value=150, scope={"profiles": ["live"]})
    ws2 = make_ws(ws.parent / "b")
    apply(ws2, [add("features/shop", price_claim(scope={"profiles": ["dev"]}))], rid="a")
    result = apply(ws2, [add("features/shop", apart, base=1)], rid="b")
    assert result["conflicts"] == []


def test_indirect_conflict_does_not_change_existing_team_claim(ws: Path) -> None:
    """Agent가 새 expected를 더해 기존 팀 expected와 의미 충돌을 일으켜도 기존 팀 주장은 그대로이고,
    충돌 표시는 작업 주장 덧씌움으로 간다 (R4 — 간접 변경도 막는다)."""
    item = "knowledge/features/item.json"
    apply(ws, [add("features/shop", price_claim())], actor=HUMAN, rid="h0")
    item_claim = price_claim(id="item.potion.price", statement="아이템 표: 물약 100골드")
    apply(ws, [add("features/item", item_claim)], actor=HUMAN, rid="h1")
    shop_before = read(ws, SHOP)
    item_bytes = (ws / item).read_bytes()
    other = price_claim(id="shop.potion.price_event", value=120, statement="물약 가격 120골드")
    result = apply(ws, [add("features/shop", other, base=1)], rid="r1")

    shop = read(ws, SHOP)
    existing = next(c for c in shop["claims"] if c["id"] == "shop.potion.price")
    assert existing == shop_before["claims"][0]  # 상태·rev·conflicts_with 그대로
    assert shop.get("history", []) == shop_before.get("history", [])
    assert (ws / item).read_bytes() == item_bytes  # 다른 기능 파일 바이트 그대로
    added = next(c for c in shop["claims"] if c["id"] == "shop.potion.price_event")
    assert added["status"] == "conflicted" and added["rev"] == 1
    assert {r["id"] for r in added["conflicts_with"]} == {"shop.potion.price", "item.potion.price"}

    over = {
        f: {e["claim"]["id"]: e for e in read(ws, f"knowledge/working/claims/{f}.json")["claims"]}
        for f in ("shop", "item")
    }
    shop_entry = over["shop"]["shop.potion.price"]
    item_entry = over["item"]["item.potion.price"]
    for entry in (shop_entry, item_entry):
        assert entry["base_rev"] == 1 and entry["ops"] == ["mark_conflicted"]
        assert entry["claim"]["status"] == "conflicted" and entry["claim"]["rev"] == 2

    # 응답·감사 이력의 rev·위치가 실제 저장한 곳과 같다
    saved = {
        (c["id"], c["rev"], c["basis"])
        for conflict in result["conflicts"]
        for c in conflict["claims"]
    }
    assert saved == {
        ("shop.potion.price", 2, "working"),
        ("item.potion.price", 2, "working"),
        ("shop.potion.price_event", 1, "team"),
    }
    log = [json.loads(x) for x in (ws / "knowledge/log.jsonl").read_text("utf-8").splitlines()]
    marks = {
        (e["file"], e["id"], e.get("base_rev"), e["new_rev"])
        for e in log
        if e["seq"] > 2 and e["op"] == "mark_conflicted"
    }
    assert ("knowledge/working/claims/shop.json", "shop.potion.price", 1, 2) in marks
    assert ("knowledge/working/claims/item.json", "item.potion.price", 1, 2) in marks
    assert not any(f == "features/item" for f, *_ in marks)
    assert result["revisions"] == {"features/shop": 2}
    assert result["working"] == {"item": 1, "shop": 1}  # 기능 → 작업 주장 파일 revision


def test_expected_requires_source_basis(ws: Path) -> None:
    assert code_of(ws, [add("features/shop", price_claim(basis=[]))]) == "basis_required"
    run_only = price_claim(basis=[{"type": "run", "ref": "abcdefgh"}])
    assert code_of(ws, [add("features/shop", run_only)], rid="r2") in (
        "basis_unknown",
        "basis_required",
    )
    # 은폐 ⑧: expected 값을 관찰 근거로 바꾸기
    apply(ws, [add("features/shop", price_claim())], rid="r3")
    (ws / "knowledge/evidence/e-20261109-100000-abcd").mkdir(parents=True)
    (ws / "knowledge/evidence/e-20261109-100000-abcd/manifest.json").write_text("{}", "utf-8")
    hide = {
        "op": "revise",
        "file": "features/shop",
        "id": "shop.potion.price",
        "base_rev": 1,
        "changes": {"value": 120, "basis": [{"type": "evidence", "ref": "e-20261109-100000-abcd"}]},
    }
    assert code_of(ws, [hide], rid="r4") == "basis_required"


def test_agent_cannot_write_human_basis(ws: Path) -> None:
    human = price_claim(basis=[{"type": "human", "ref": "u-20261109-100000-abcd"}])
    assert code_of(ws, [add("features/shop", human)]) == "human_basis_reserved"
    assert apply(ws, [add("features/shop", human)], actor=HUMAN, rid="h")["applied"]


def test_no_wiki_or_claim_basis_type(ws: Path) -> None:
    for kind, ref in (("wiki", "wiki/features/shop.md"), ("claim", "shop.other")):
        item = guess("shop.a", basis=[{"type": kind, "ref": ref}])
        assert code_of(ws, [add("features/shop", item)], rid=f"r-{kind}") == "format"
    assert not (ws / SHOP).exists()


def cheat(**extra: object) -> dict:
    return {
        "id": "give_gold",
        "title": "골드 지급",
        "effect": "골드를 amount만큼 늘린다",
        "args": {"amount": {"type": "integer", "min": 1, "max": 100000}},
        "impl": {
            "kind": "console",
            "graph": "subgraphs/cheats/console.graph.json",
            "template": "give_gold {amount}",
        },
        "env": {"profiles": ["dev"]},
        **extra,
    }


def test_cheat_adoption_field_reserved(ws: Path) -> None:
    adopted = cheat(
        adoption={
            "category": "dev_safe",
            "digest": "0" * 64,
            "by": "human",
            "at": "2026-11-09T00:00:00Z",
        }
    )
    assert code_of(ws, [add("cheats", adopted)], rid="r0") == "adoption_reserved"
    apply(ws, [add("cheats", cheat())], rid="r1")
    grab = {
        "op": "revise",
        "file": "cheats",
        "id": "give_gold",
        "base_rev": 1,
        "changes": {"adoption": {"category": "x", "digest": "0" * 64, "by": "human", "at": "t"}},
    }
    assert code_of(ws, [grab], rid="r2") == "adoption_reserved"
    # 템플릿 규칙: 정의되지 않은 자리·자리 밖 중괄호
    bad = cheat(
        id="bad_one",
        impl={"kind": "console", "graph": "subgraphs/c.graph.json", "template": "x {who}"},
    )
    assert code_of(ws, [add("cheats", bad, base=1)], rid="r3") == "format"


def test_cheat_revise_clears_adoption(ws: Path) -> None:
    apply(ws, [add("cheats", cheat())], rid="r1")
    # 사람이 채택했다고 치고 파일을 고친다 (cheats.adopt는 B2)
    doc = read(ws, "knowledge/cheats.json")
    doc["cheats"][0]["adoption"] = {
        "category": "dev_safe",
        "digest": cheat_digest(doc["cheats"][0], closure=None, nodes=None),
        "by": "human",
        "at": "2026-11-09T00:00:00Z",
    }
    (ws / "knowledge/cheats.json").write_text(json.dumps(doc, ensure_ascii=False), "utf-8")
    revise = {
        "op": "revise",
        "file": "cheats",
        "id": "give_gold",
        "base_rev": 1,
        "changes": {"args": {"amount": {"type": "integer", "min": 1, "max": 999999}}},
    }
    apply(ws, [revise], rid="r2")
    after = read(ws, "knowledge/cheats.json")["cheats"][0]
    assert after["adoption"] is None and after["rev"] == 2


def test_cheat_digest_covers_closure_and_nodes() -> None:
    base = cheat(rev=1)
    one = cheat_digest(base, closure="a" * 64, nodes={"core.input.type": "1"})
    assert one != cheat_digest(base, closure="b" * 64, nodes={"core.input.type": "1"})
    assert one != cheat_digest(base, closure="a" * 64, nodes={"core.input.type": "2"})
    assert one == cheat_digest(dict(base), closure="a" * 64, nodes={"core.input.type": "1"})


def test_secret_in_text_refused(ws: Path) -> None:
    leak = guess("shop.a", statement=f"로그인 비밀번호는 {SECRET.lower()} 이다")
    assert code_of(ws, [add("features/shop", leak)]) == "secret_in_text"
    assert not (ws / SHOP).exists()
    for path in ws.rglob("*"):
        if path.is_file():
            assert SECRET.casefold() not in path.read_bytes().decode("utf-8", "replace").casefold()
    # 위키도 같다
    from helpers.knowledge import CHECK

    from kookabug_core.knowledge import ops

    with pytest.raises(KnowledgeError) as info:
        ops.wiki_write(
            ws, "wiki/overview.md", f"pw: {SECRET}", None, actor=AGENT, check_secrets=CHECK
        )
    assert info.value.code == "secret_in_text"
    assert not (ws / "wiki/overview.md").exists()


def test_expected_revise_with_existing_source_stays_working(ws: Path) -> None:
    apply(ws, [add("features/shop", price_claim())], rid="r0")
    team = (ws / SHOP).read_bytes()
    revise = {
        "op": "revise",
        "file": "features/shop",
        "id": "shop.potion.price",
        "base_rev": 1,
        "changes": {"value": 120, "statement": "물약 가격은 120골드다"},
    }
    result = apply(ws, [revise], rid="r1")
    assert result["results"][0]["basis"] == "working"
    assert (ws / SHOP).read_bytes() == team  # 팀 파일 그대로
    over = read(ws, "knowledge/working/claims/shop.json")
    entry = over["claims"][0]
    assert entry["base_rev"] == 1 and entry["claim"]["value"] == 120 and entry["claim"]["rev"] == 2
    # 다음 연산은 작업 revision 기준
    again = {**revise, "base_rev": 2, "changes": {"value": 130}}
    apply(ws, [again], rid="r2")
    assert read(ws, "knowledge/working/claims/shop.json")["claims"][0]["claim"]["rev"] == 3
    # 사람은 팀 파일에 바로 쓴다
    apply(ws, [revise], actor=HUMAN, rid="h1")
    assert read(ws, SHOP)["claims"][0]["value"] == 120


def test_expected_supersede_requires_acceptance(ws: Path) -> None:
    apply(ws, [add("features/shop", price_claim())], rid="r0")
    new = price_claim(id="shop.potion.price_v2", value=100, statement="물약 가격 100골드 (새 표)")
    apply(ws, [add("features/shop", new, base=1)], rid="r1")
    team = (ws / SHOP).read_bytes()
    sup = {
        "op": "supersede",
        "file": "features/shop",
        "id": "shop.potion.price",
        "base_rev": 1,
        "by": {"id": "shop.potion.price_v2", "rev": 1},
    }
    result = apply(ws, [sup], rid="r2")
    assert result["results"][0]["basis"] == "working"
    assert (ws / SHOP).read_bytes() == team
    entry = read(ws, "knowledge/working/claims/shop.json")["claims"][0]
    assert entry["claim"]["status"] == "superseded" and entry["ops"] == ["supersede"]
    # set_status도 작업 기준, guess·attach_evidence는 팀 그대로
    st = {
        "op": "set_status",
        "file": "features/shop",
        "id": "shop.potion.price_v2",
        "base_rev": 1,
        "status": "unverifiable",
    }
    assert apply(ws, [st], rid="r3")["results"][0]["basis"] == "working"
    apply(ws, [add("features/shop", guess("shop.note"), base=2)], rid="r4")
    assert read(ws, SHOP)["revision"] == 3


# ---------------------------------------------------------------- 비밀값 경계 (검수 B1-1 High 1~3)

WORD = "ReviewSecret123"
NUMBER = "93847625"
STRICT = secret_checker(
    ["accounts.word", "accounts.pin"],
    MemorySecrets({"accounts.word": WORD, "accounts.pin": NUMBER}),
)


def strict(root: Path, ops_: list[dict], rid: str, actor: Actor = AGENT) -> dict:
    return ops.apply(root, {"request_id": rid, "ops": ops_}, actor=actor, check_secrets=STRICT)


def strict_error(root: Path, ops_: list[dict], rid: str, actor: Actor = AGENT) -> KnowledgeError:
    with pytest.raises(KnowledgeError) as info:
        strict(root, ops_, rid, actor)
    return info.value


def no_trace(root: Path, *values: str) -> None:
    """워크스페이스 파일 어디에도 값이 없다 (검사 준비 설정 `kookabug.json`은 임시 폴더 경로를 담아
    빼고 본다)."""
    for path in root.rglob("*"):
        if path.is_file() and path != root / "kookabug.json":
            text = path.read_bytes().decode("utf-8", "replace").casefold()
            for value in values:
                assert value.casefold() not in text, (path, value)


def test_request_id_secret_not_written(ws: Path) -> None:
    good = [add("features/shop", guess("shop.a"))]
    bad_shape = [{"op": "add", "file": "features/shop", "base_revision": "x", "item": {}}]
    secret_ops = [add("features/shop", guess("shop.b", statement=f"pw {WORD}"))]
    for i, ops_ in enumerate((good, bad_shape, secret_ops)):
        exc = strict_error(ws, ops_, f"job-{WORD}-{i}")
        assert exc.code == "secret_in_text"
        assert WORD.casefold() not in json.dumps(exc.to_dict(), ensure_ascii=False).casefold()
    # 주체 필드(클라이언트 이름·모델·작업)도 같다
    for i, actor in enumerate(
        (
            Actor("agent", id="job:x", client=f"cli-{WORD}"),
            Actor("agent", id="job:x", model=WORD),
            Actor("agent", id=f"job:{WORD}", job=f"j-{WORD}"),
        )
    ):
        exc = strict_error(ws, good, f"a{i}", actor)
        assert exc.code == "secret_in_text"
        assert WORD.casefold() not in json.dumps(exc.to_dict(), ensure_ascii=False).casefold()
    assert not (ws / SHOP).exists()
    no_trace(ws, WORD)
    # 거부는 값과 무관한 임의 식별자로 감사 이력에 남는다
    log = [json.loads(x) for x in (ws / "knowledge/log.jsonl").read_text("utf-8").splitlines()]
    assert len(log) == 6 and all(e["result"] == "refused" for e in log)
    assert all(e["code"] == "secret_in_text" for e in log)
    assert log[0]["request_id"].startswith("x-")
    # 깨끗한 요청 ID·주체는 원문 그대로 성공
    assert strict(ws, good, "clean-1")["request_id"] == "clean-1"
    no_trace(ws, WORD)


def test_secret_key_absent_from_error(ws: Path) -> None:
    keyed = guess("shop.a", value={WORD: "x"})
    exc = strict_error(ws, [add("features/shop", keyed)], "r1")
    assert exc.code == "secret_in_text"
    dumped = json.dumps(exc.to_dict(), ensure_ascii=False)
    assert WORD.casefold() not in dumped.casefold() and "<key#0>" in dumped
    # 형식 거부(글자 검사 전)의 위치에도 요청자 키를 넣지 않는다
    unknown = guess("shop.b")
    unknown[WORD] = 1
    exc = strict_error(ws, [add("features/shop", unknown)], "r2")
    assert exc.code in ("format", "secret_in_text")
    assert WORD.casefold() not in json.dumps(exc.to_dict(), ensure_ascii=False).casefold()
    plain_exc = strict_error(ws, [add("features/shop", {**guess("shop.c"), "bogus_key": 1})], "r3")
    assert plain_exc.code == "format" and "bogus_key" not in plain_exc.message
    # 치트 인자 이름(요청자 키)도
    bad_cheat = cheat(args={"amount": {"type": "integer", "min": 9, "max": 1}})
    exc = strict_error(ws, [add("cheats", bad_cheat)], "r4")
    assert exc.code == "format" and "amount" not in exc.message
    no_trace(ws, WORD)


def test_numeric_secret_not_saved_or_rendered(ws: Path) -> None:
    claim = price_claim(value=int(NUMBER))
    exc = strict_error(ws, [add("features/shop", claim)], "r1")
    assert exc.code == "secret_in_text"
    nested = guess("shop.a", value={"pin": [1, float(NUMBER)]})
    assert strict_error(ws, [add("features/shop", nested)], "r2").code == "secret_in_text"
    assert not (ws / SHOP).exists() and not (ws / "wiki/features/shop.md").exists()
    no_trace(ws, NUMBER)
    # 비밀값이 아닌 숫자는 그대로 저장·렌더
    strict(ws, [add("features/shop", price_claim())], "r3")
    assert "100" in (ws / "wiki/features/shop.md").read_text("utf-8")


@pytest.mark.parametrize("name", ["answer", "question", "advice", "template"])
def test_dynamic_key_error(ws: Path, name: str) -> None:
    """다른 형식에서는 고정 필드 이름인 글자라도, 자유 JSON(`value`) 안의 키면 오류 위치에서
    가린다 (스키마 위치 기준)."""
    check = secret_checker(["accounts.word"], MemorySecrets({"accounts.word": name}))

    def error(ops_: list[dict], rid: str) -> KnowledgeError:
        with pytest.raises(KnowledgeError) as info:
            ops.apply(ws, {"request_id": rid, "ops": ops_}, actor=AGENT, check_secrets=check)
        return info.value

    exc = error([add("features/shop", guess("shop.a", value={name: "x"}))], "r1")
    assert exc.code == "secret_in_text"
    dumped = json.dumps(exc.to_dict(), ensure_ascii=False)
    assert name not in dumped and "ops/0/item/value/<key#0>" in dumped
    nested = guess("shop.b", value=[{"ok": {name: 1}}])
    exc = error([add("features/shop", nested)], "r2")
    assert name not in json.dumps(exc.to_dict(), ensure_ascii=False)
    no_trace(ws, name)


def test_short_secret_cannot_be_recovered_from_audit(ws: Path) -> None:
    """글자 검사에 걸린 요청 ID·주체는 값과 무관한 임의 식별자로만 남는다 — 짧은 비밀값(PIN)을 후보
    대입으로 되찾을 해시가 감사 이력·요청 기록 어디에도 없다."""
    pin = "4937"
    check = secret_checker(["accounts.pin"], MemorySecrets({"accounts.pin": pin}))

    def refuse(rid: str, ops_: list[dict], actor: Actor = AGENT) -> None:
        with pytest.raises(KnowledgeError) as info:
            ops.apply(ws, {"request_id": rid, "ops": ops_}, actor=actor, check_secrets=check)
        assert info.value.code == "secret_in_text"

    good = [add("features/shop", guess("shop.a"))]
    refuse(pin, good)
    refuse(pin, good)
    refuse("r-ok", good, Actor("agent", id=f"job:{pin}", client="c"))
    refuse("r-ops", [add("features/shop", guess("shop.b", statement=f"pin {pin}"))])
    log = [json.loads(x) for x in (ws / "knowledge/log.jsonl").read_text("utf-8").splitlines()]
    assert len(log) == 4
    # 같은 값이 두 번 걸려도 식별자가 다르다 = 값에서 계산하지 않았다
    assert log[0]["request_id"] != log[1]["request_id"]
    assert log[2]["agent"]["id"] != log[2]["request_id"]
    # 0000~9999 후보의 sha256(앞 8자리 이상)이 어떤 기록에도 없다
    blob = b"".join(p.read_bytes() for p in ws.rglob("*") if p.is_file()).decode("utf-8", "replace")
    hits = [
        c
        for c in (f"{n:04d}" for n in range(10000))
        if hashlib.sha256(c.encode()).hexdigest()[:8] in blob
    ]
    assert hits == []
    # 비밀값 거부는 요청 기록(원문 digest)을 남기지 않는다
    requests = ws / ".kookabug/knowledge-requests"
    assert not requests.exists() or list(requests.iterdir()) == []


def test_working_noop_reports_stored_basis(ws: Path) -> None:
    """무변경 연산의 응답 rev·basis도 실제 저장한 곳 기준이다."""
    apply(ws, [add("features/shop", price_claim())], actor=HUMAN, rid="h0")
    other = price_claim(id="shop.potion.price_event", value=120, statement="물약 가격 120골드")
    apply(ws, [add("features/shop", other, base=1)], rid="r1")  # 기존 주장 → 작업 rev 2 conflicted
    noop = {
        "op": "set_status",
        "file": "features/shop",
        "id": "shop.potion.price",
        "base_rev": 2,
        "status": "conflicted",
    }
    result = apply(ws, [noop], rid="r2")
    assert result["results"] == [
        {
            "op": "set_status",
            "file": "features/shop",
            "id": "shop.potion.price",
            "rev": 2,
            "basis": "working",
        }
    ]
    # 덧씌움이 없는 팀 항목의 무변경은 팀 기준
    apply(ws, [add("features/shop", guess("shop.g"), base=2)], rid="r3")
    same = {
        "op": "set_status",
        "file": "features/shop",
        "id": "shop.g",
        "base_rev": 1,
        "status": "hypothesis",
    }
    assert apply(ws, [same], rid="r4")["results"][0] | {} == {
        "op": "set_status",
        "file": "features/shop",
        "id": "shop.g",
        "rev": 1,
        "basis": "team",
    }
