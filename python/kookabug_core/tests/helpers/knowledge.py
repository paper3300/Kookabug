"""지식 저장소 검사 도우미 (M8 B1)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from kookabug_core.canonical import canonical_dumps
from kookabug_core.knowledge import ops
from kookabug_core.knowledge.formats import Actor, secret_checker
from kookabug_core.workspace import MemorySecrets
from kookabug_core.workspace_new import create_workspace

AGENT = Actor("agent", id="job:j-20261109-100000-abcd", client="fake", job="j-20261109-100000-abcd")
HUMAN = Actor("human", id="ui")
SECRET = "Hunter2-Pass!"
CHECK = secret_checker(["accounts.qa"], MemorySecrets({"accounts.qa": SECRET}))
ITEM_CSV = "id,price\npotion_hp_s,100\n"


def make_ws(tmp_path: Path) -> Path:
    """새 워크스페이스 + 원본 3개(데이터 파일·없는 파일·URL)."""
    root = tmp_path / "ws"
    create_workspace(root, "예제")
    data = tmp_path / "data"
    data.mkdir()
    (data / "item.csv").write_bytes(ITEM_CSV.encode("utf-8"))
    config = json.loads((root / "kookabug.json").read_text(encoding="utf-8"))
    config["sources"] = [
        {
            "id": "item_table",
            "kind": "data",
            "title": "아이템 테이블",
            "path": str(data / "item.csv"),
        },
        {"id": "gone", "kind": "data", "title": "없는 원본", "path": str(data / "none.csv")},
        {"id": "design_doc", "kind": "design_doc", "title": "기획", "url": "https://example.com/d"},
    ]
    (root / "kookabug.json").write_text(canonical_dumps(config), encoding="utf-8")
    return root


def item_hash() -> str:
    return "sha256:" + hashlib.sha256(ITEM_CSV.encode()).hexdigest()


def source_basis(**extra: Any) -> dict[str, Any]:
    return {"type": "source", "ref": "sources:item_table#potion_hp_s", **extra}


def price_claim(**extra: Any) -> dict[str, Any]:
    return {
        "id": "shop.potion.price",
        "kind": "expected",
        "statement": "체력 물약 1개 가격은 100골드다",
        "subject": "item:potion_hp_s",
        "property": "price",
        "value": 100,
        "unit": "gold",
        "basis": [source_basis()],
        "status": "supported",
        **extra,
    }


def apply(root: Path, ops_: list[dict[str, Any]], *, actor: Actor = AGENT, rid: str = "r1") -> Any:
    return ops.apply(root, {"request_id": rid, "ops": ops_}, actor=actor, check_secrets=CHECK)


def add(file: str, item: dict[str, Any], base: int = 0) -> dict[str, Any]:
    return {"op": "add", "file": file, "base_revision": base, "item": item}


def read(root: Path, rel: str) -> Any:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def tree(root: Path) -> dict[str, bytes]:
    """워크스페이스 파일 바이트 (`.kookabug/` 잠금·요청 기록 제외)."""
    out: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and not rel.startswith(".kookabug/"):
            out[rel] = path.read_bytes()
    return out
