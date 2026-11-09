"""원본 상태 (M8 계획 3.4)와 `source` 근거 검증 (계획 9장 R5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers.knowledge import add, apply, item_hash, make_ws, price_claim, source_basis

from kookabug_core.canonical import canonical_dumps
from kookabug_core.knowledge.formats import KnowledgeError
from kookabug_core.knowledge.sources import check_sources, read_cache
from kookabug_core.workspace import Workspace


def make_junction(link: Path, target: Path) -> None:
    import _winapi

    _winapi.CreateJunction(str(target), str(link))


def set_sources(root: Path, sources: list[dict]) -> None:
    config = json.loads((root / "kookabug.json").read_text("utf-8"))
    config["sources"] = [*config.get("sources", []), *sources]
    (root / "kookabug.json").write_text(canonical_dumps(config), "utf-8")


def code_of(root: Path, claim: dict, rid: str) -> str:
    with pytest.raises(KnowledgeError) as info:
        apply(root, [add("features/shop", claim)], rid=rid)
    return info.value.code


def test_check_states_and_local_path(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    folder = tmp_path / "code"
    (folder / "src").mkdir(parents=True)
    (folder / "src" / "a.py").write_text("x = 1\n", "utf-8")
    set_sources(
        root,
        [
            {"id": "game_code", "kind": "code", "title": "게임 코드", "local": True},
            {"id": "strings", "kind": "strings", "title": "문자열", "local": True},
        ],
    )
    (root / ".kookabug").mkdir(exist_ok=True)
    local = {"format": "kookabug.local/0", "sources": {"game_code": {"path": str(folder)}}}
    (root / ".kookabug/local.json").write_text(json.dumps(local), "utf-8")
    ws = Workspace.open(root)
    assert ws.diagnostics == []
    states = {s["id"]: s for s in check_sources(ws)}
    assert states["item_table"]["state"] == "ok" and states["item_table"]["hash"] == item_hash()
    assert states["gone"]["state"] == "missing"
    assert states["design_doc"]["state"] == "unchecked_url" and states["design_doc"]["hash"] is None
    assert states["game_code"]["state"] == "ok" and states["game_code"]["hash"].startswith(
        "sha256:"
    )
    assert states["strings"]["state"] == "missing"  # 이 PC에 경로가 없다
    assert {s["id"] for s in read_cache(ws)} == set(states)
    # 폴더 내용이 바뀌면 목록 해시가 바뀐다
    (folder / "src" / "b.py").write_text("y = 2\n", "utf-8")
    assert check_sources(ws)[3]["hash"] != states["game_code"]["hash"]


def test_source_basis_filled_by_service(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    apply(root, [add("features/shop", price_claim())], rid="r1")
    basis = json.loads((root / "knowledge/features/shop.json").read_text("utf-8"))["claims"][0][
        "basis"
    ][0]
    assert basis["hash"] == item_hash() and basis["verified"] is True and basis["seen_at"]
    for rid, ref in (("r2", "sources:nope"), ("r3", "sources:gone")):
        claim = price_claim(id="shop.b", basis=[source_basis(ref=ref)])
        with pytest.raises(KnowledgeError) as info:
            apply(root, [add("features/shop", claim, base=1)], rid=rid)
        assert info.value.code == "basis_unknown", ref


def test_source_basis_hash_mismatch(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    wrong = price_claim(basis=[source_basis(hash="sha256:" + "0" * 64)])
    assert code_of(root, wrong, "r1") == "basis_hash_mismatch"
    right = price_claim(basis=[source_basis(hash=item_hash())])
    assert apply(root, [add("features/shop", right)], rid="r2")["applied"]


def test_source_basis_self_citation_via_registered_folder(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    (root / "wiki" / "overview.md").write_text("가격은 100골드\n", "utf-8")
    (root / "knowledge" / "evidence" / "neg").mkdir(parents=True)
    (root / "knowledge" / "evidence" / "neg" / "a.txt").write_text("x", "utf-8")
    # 워크스페이스(또는 그 위 폴더)를 원본으로 등록하고 위키·지식을 근거로 대기
    set_sources(
        root,
        [
            {"id": "everything", "kind": "other", "title": "전부", "path": str(root)},
            {"id": "parent", "kind": "other", "title": "위", "path": str(root.parent)},
            {"id": "wikidir", "kind": "other", "title": "위키", "path": "wiki"},
        ],
    )
    cases = [
        "sources:everything#wiki/overview.md",
        "sources:everything#WIKI/overview.md",
        "sources:everything#knowledge/evidence/neg/a.txt",
        "sources:parent#ws/wiki/overview.md",
        "sources:wikidir#overview.md",
        "sources:wikidir",
    ]
    for i, ref in enumerate(cases):
        claim = price_claim(id=f"shop.c{i}", basis=[{"type": "source", "ref": ref}])
        assert code_of(root, claim, f"r{i}") == "basis_derived", ref
    escape = price_claim(
        id="shop.esc", basis=[{"type": "source", "ref": "sources:wikidir#../kookabug.json"}]
    )
    assert code_of(root, escape, "re") == "basis_unknown"


def test_source_basis_junction_alias(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    (root / "wiki" / "overview.md").write_text("가격은 100골드\n", "utf-8")
    alias = tmp_path / "docs_alias"
    make_junction(alias, root / "wiki")
    outer = tmp_path / "outer"
    outer.mkdir()
    make_junction(outer / "inner", root / "knowledge")
    set_sources(
        root,
        [
            {"id": "alias", "kind": "design_doc", "title": "별칭", "path": str(alias)},
            {"id": "outer", "kind": "design_doc", "title": "바깥", "path": str(outer)},
        ],
    )
    for i, ref in enumerate(
        ["sources:alias#overview.md", "sources:alias", "sources:outer#inner/x"]
    ):
        if ref.endswith("inner/x"):
            (root / "knowledge" / "x").write_text("1", "utf-8")
        claim = price_claim(id=f"shop.j{i}", basis=[{"type": "source", "ref": ref}])
        assert code_of(root, claim, f"r{i}") == "basis_derived", ref


def short_name(path: Path) -> str | None:
    """8.3 짧은 이름 (볼륨에서 꺼져 있으면 None)."""
    import ctypes

    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, len(buf))
    name = Path(buf.value).name if n else ""
    return name if name and name.casefold() != path.name.casefold() else None


def test_outward_derived_junction_is_not_source(tmp_path: Path) -> None:
    """파생 폴더 안에서 바깥을 가리키는 정션(안→밖)·그런 정션을 다시 가리키는 바깥 별칭(밖→안→밖)·
    중간 조각·대소문자·8.3 짧은 이름·심볼릭 링크 — 모두 basis_derived."""
    root = make_ws(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    (external / "note.md").write_text("가격은 120골드\n", "utf-8")
    make_junction(root / "wiki" / "alias", external)
    make_junction(root / "knowledge" / "ext", external)
    hop = tmp_path / "hop"
    make_junction(hop, root / "wiki" / "alias")  # 바깥 → (파생 안 정션) → 바깥
    sources = [
        {"id": "rel", "kind": "other", "title": "a", "path": "wiki/alias"},
        {"id": "abs", "kind": "other", "title": "b", "path": str(root / "wiki" / "alias")},
        {"id": "upper", "kind": "other", "title": "c", "path": "WIKI/alias"},
        {"id": "everything", "kind": "other", "title": "d", "path": str(root)},
        {"id": "hop", "kind": "other", "title": "e", "path": str(hop)},
        {"id": "kn", "kind": "other", "title": "f", "path": "knowledge/ext"},
    ]
    refs = [
        "sources:rel#note.md",
        "sources:rel",
        "sources:abs#note.md",
        "sources:upper#note.md",
        "sources:everything#wiki/alias/note.md",
        "sources:everything#Wiki/alias/note.md",
        "sources:hop#note.md",
        "sources:hop",
        "sources:kn#note.md",
    ]
    short = short_name(root / "knowledge")
    if short is not None:
        sources.append({"id": "short", "kind": "other", "title": "g", "path": f"{short}/ext"})
        refs.append("sources:short#note.md")
    link = tmp_path / "sym"
    try:
        link.symlink_to(root / "wiki" / "alias", target_is_directory=True)
    except OSError:
        pass  # 심볼릭 링크 권한이 없는 PC (정션으로 같은 규칙을 이미 본다)
    else:
        sources.append({"id": "sym", "kind": "other", "title": "h", "path": str(link)})
        refs.append("sources:sym#note.md")
    set_sources(root, sources)
    for i, ref in enumerate(refs):
        claim = price_claim(id=f"shop.o{i}", basis=[{"type": "source", "ref": ref}])
        assert code_of(root, claim, f"r{i}") == "basis_derived", ref
    # 같은 바깥 폴더를 직접 등록하면 정상 원본이다
    set_sources(root, [{"id": "direct", "kind": "other", "title": "i", "path": str(external)}])
    ok = price_claim(id="shop.ok", basis=[{"type": "source", "ref": "sources:direct#note.md"}])
    assert apply(root, [add("features/shop", ok)], rid="ok")["applied"]


def test_unverified_url_basis_cannot_support(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    url = [{"type": "source", "ref": "sources:design_doc#가격", "verified": True}]
    assert code_of(root, price_claim(basis=url), "r1") == "basis_required"
    # 가설로는 쓸 수 있고 verified: false로 남는다 (Agent가 준 true는 무시)
    result = apply(
        root, [add("features/shop", price_claim(basis=url, status="hypothesis"))], rid="r2"
    )
    assert result["applied"]
    claim = json.loads((root / "knowledge/features/shop.json").read_text("utf-8"))["claims"][0]
    assert claim["basis"][0]["verified"] is False
    # revise로 verified를 바꾸지 못하고, set_status supported도 막힌다 (사람이 해도 같다)
    from helpers.knowledge import HUMAN

    revise = {
        "op": "revise",
        "file": "features/shop",
        "id": "shop.potion.price",
        "base_rev": 1,
        "changes": {"basis": [{**claim["basis"][0], "verified": True}], "status": "supported"},
    }
    with pytest.raises(KnowledgeError) as info:
        apply(root, [revise], actor=HUMAN, rid="r3")
    assert info.value.code == "basis_required"
    # 확인된 원본을 더하면 올릴 수 있다
    att = {
        "op": "attach_evidence",
        "file": "features/shop",
        "id": "shop.potion.price",
        "base_rev": 1,
        "basis": source_basis(),
    }
    apply(root, [att], actor=HUMAN, rid="r4")
    st = {
        "op": "set_status",
        "file": "features/shop",
        "id": "shop.potion.price",
        "base_rev": 2,
        "status": "supported",
    }
    apply(root, [st], actor=HUMAN, rid="r5")
    assert (
        json.loads((root / "knowledge/features/shop.json").read_text("utf-8"))["claims"][0][
            "status"
        ]
        == "supported"
    )
