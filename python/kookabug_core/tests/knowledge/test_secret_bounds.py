"""비밀값 경계 — 분기 스키마의 키 가림, 숫자 표현, 요청 digest (M8 B1 4라운드 검수 재현)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from helpers.knowledge import AGENT, add, make_ws

from kookabug_core.canonical import canonical_dumps
from kookabug_core.knowledge import formats, ops
from kookabug_core.knowledge.formats import KnowledgeError, mask_pointer, secret_checker
from kookabug_core.workspace import MemorySecrets


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return make_ws(tmp_path)


def guess(cid: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": cid,
        "kind": "guess",
        "statement": "추측",
        "basis": [],
        "status": "hypothesis",
        **extra,
    }


def refuse(root: Path, secret: str, ops_: list[dict[str, Any]], rid: str = "r1") -> KnowledgeError:
    check = secret_checker(["accounts.x"], MemorySecrets({"accounts.x": secret}))
    with pytest.raises(KnowledgeError) as info:
        ops.apply(root, {"request_id": rid, "ops": ops_}, actor=AGENT, check_secrets=check)
    return info.value


def dumped(exc: KnowledgeError) -> str:
    return json.dumps(exc.to_dict(), ensure_ascii=False) + str(exc)


def no_trace(root: Path, value: str) -> None:
    for path in root.rglob("*"):
        if path.is_file() and path != root / "kookabug.json":
            assert value not in path.read_bytes().decode("utf-8", "replace"), path


# ---------------------------------------------------------------- 분기 커서 (High 1)


def test_branch_only_key_not_exposed(ws: Path) -> None:
    """`impl`이 plugin 분기(판별자 kind)면 console 분기에만 있는 `template`는 요청자 키로 가린다."""
    cheat = {
        "id": "give_gold",
        "title": "골드",
        "effect": "골드를 준다",
        "args": {},
        "impl": {"kind": "plugin", "node": "review.node", "template": "x"},
    }
    exc = refuse(ws, "template", [add("cheats", cheat)])
    assert exc.code == "secret_in_text"
    assert "template" not in dumped(exc) and "ops/0/item/impl/<key#2>" in dumped(exc)
    # console 분기로 확정되면 `template`는 고정 이름이다 (값만 걸린다)
    console = {**cheat, "impl": {"kind": "console", "graph": "g.graph.json", "template": "pw x"}}
    exc = refuse(ws, "pw", [add("cheats", console)], rid="r2")
    assert "ops/0/item/impl/template" in dumped(exc)


@pytest.mark.parametrize("combinator", ["oneOf", "anyOf"])
def test_union_cursor_preserves_dynamic_branch(combinator: str) -> None:
    """값으로 고를 수 없는 분기에서 한 후보라도 자유 JSON이면 그 키와 그 아래를 가린다."""
    doc: dict[str, Any] = {
        "$defs": {
            "Payload": {
                combinator: [
                    {"type": "object"},  # 자유 JSON
                    {"type": "object", "properties": {"answer": {"type": "integer"}}},
                ]
            }
        },
        "type": "object",
        "properties": {
            "payload": {"$ref": "#/$defs/Payload"},
            "list": {"items": {"$ref": "#/$defs/Payload"}},
        },
    }
    cursor = formats._cursor(doc, doc)  # pyright: ignore[reportPrivateUsage]
    data = {"payload": {"answer": {"deep": 1}}, "list": [{"answer": 1}]}
    assert mask_pointer(data, "/payload/answer", cursor) == "/payload/<key#0>"
    assert mask_pointer(data, "/payload/answer/deep", cursor) == "/payload/<key#0>/<key#0>"
    assert mask_pointer(data, "/list/0/answer", cursor) == "/list/0/<key#0>"
    # 판별자로 고를 수 있으면 확정 분기만 쓴다
    tagged: dict[str, Any] = {
        combinator: [
            {"properties": {"kind": {"const": "a"}, "answer": {}}},
            {"properties": {"kind": {"const": "b"}}},
        ]
    }
    cur = formats._cursor(tagged, tagged)  # pyright: ignore[reportPrivateUsage]
    assert mask_pointer({"kind": "a", "answer": 1}, "/answer", cur) == "/answer"
    assert mask_pointer({"kind": "b", "answer": 1}, "/answer", cur) == "/<key#1>"
    assert mask_pointer({"answer": 1}, "/answer", cur) == "/<key#0>"  # 고를 수 없으면 가림


# ---------------------------------------------------------------- 숫자 표현·digest (High 2)


def test_canonical_number_secret_not_persisted(ws: Path) -> None:
    """저장 표현(canonical `0.000001`)과 렌더 표현(`1e-06`) 둘 다 글자 검사한다."""
    exc = refuse(ws, "0.000001", [add("features/shop", guess("shop.a", value=0.000001))])
    assert exc.code == "secret_in_text"
    assert not (ws / "knowledge/features/shop.json").exists()
    no_trace(ws, "0.000001")
    exc = refuse(ws, "1e-06", [add("features/shop", guess("shop.a", value=0.000001))], rid="r2")
    assert exc.code == "secret_in_text"


def test_rejected_numeric_digest_not_recoverable(ws: Path) -> None:
    """비밀값이 든 요청은 정책·형식 거부보다 먼저 글자 검사에 걸려 원문 digest를 남기지 않는다."""
    bad = [{"op": "add", "file": "forbidden", "item": {"value": 0.000001}}]
    exc = refuse(ws, "0.000001", bad)
    assert exc.code == "secret_in_text"
    requests = ws / ".kookabug/knowledge-requests"
    assert not requests.exists() or list(requests.iterdir()) == []
    blob = "".join(p.read_bytes().decode("utf-8", "replace") for p in ws.rglob("*") if p.is_file())
    for n in range(1, 10):
        candidate = [{"op": "add", "file": "forbidden", "item": {"value": n / 1_000_000}}]
        digest = hashlib.sha256(canonical_dumps({"ops": candidate}).encode()).hexdigest()
        assert digest not in blob


def test_invalid_number_exception_hides_secret(ws: Path) -> None:
    """저장할 수 없는 수(±2^53 밖)는 원문 없는 형식 거부 — 예외 글에 값이 없고 요청 기록도 없다."""
    big = 938476259384762593847625
    exc = refuse(ws, "938476259384762593847625", [add("features/shop", guess("shop.a", value=big))])
    assert exc.code == "secret_in_text" and str(big) not in dumped(exc)
    exc = refuse(ws, "unrelated-secret", [add("features/shop", guess("shop.a", value=big))], "r2")
    assert exc.code == "format" and str(big) not in dumped(exc)
    assert exc.__cause__ is None and exc.__suppress_context__
    requests = ws / ".kookabug/knowledge-requests"
    assert not requests.exists() or list(requests.iterdir()) == []
    no_trace(ws, str(big))
