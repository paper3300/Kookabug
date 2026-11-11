"""등록된 원본 읽기 (UX2 A) — 경계·크기·형식·가림.

원본은 워크스페이스 **밖** 임시 폴더다(`make_ws`의 `data/`·`docs/`). 2026-11-11 사람 테스트에서
Init이 워크스페이스 밖 원본을 하나도 못 읽은 결함의 회귀 검사.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any

import pytest
from helpers.knowledge import add, apply, make_ws, price_claim

from kookabug_core.agent_job import activity
from kookabug_core.canonical import canonical_dumps
from kookabug_core.knowledge import source_read
from kookabug_core.knowledge.formats import KnowledgeError
from kookabug_core.knowledge.sources import verify_basis
from kookabug_core.workspace import Workspace

NO_SECRETS = lambda: []  # noqa: E731


def make_junction(link: Path, target: Path) -> None:
    import _winapi

    _winapi.CreateJunction(str(target), str(link))


def add_sources(root: Path, *sources: dict) -> None:
    config = json.loads((root / "kookabug.json").read_text("utf-8"))
    config["sources"] = [*config.get("sources", []), *sources]
    (root / "kookabug.json").write_text(canonical_dumps(config), "utf-8")


def set_local_source(root: Path, source_id: str, path: Path) -> None:
    (root / ".kookabug").mkdir(exist_ok=True)
    file = root / ".kookabug" / "local.json"
    doc: dict[str, Any] = (
        json.loads(file.read_text("utf-8")) if file.exists() else {"format": "kookabug.local/0"}
    )
    sources: dict[str, Any] = doc.setdefault("sources", {})
    sources[source_id] = {"path": str(path)}
    file.write_text(json.dumps(doc), "utf-8")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = make_ws(tmp_path)
    docs = tmp_path / "docs"
    (docs / "plan").mkdir(parents=True)
    (docs / "plan" / "shop.md").write_text("# 상점\n물약 100골드\n", "utf-8")
    (docs / "readme.txt").write_bytes("한글 cp949 문서".encode("cp949"))
    add_sources(root, {"id": "plans", "kind": "design_doc", "title": "기획", "local": True})
    set_local_source(root, "plans", docs)
    return root


def code(fn: Any, *args: Any, **kwargs: Any) -> str:
    with pytest.raises(KnowledgeError) as info:
        fn(*args, **kwargs)
    return info.value.code


def test_lists_and_reads_source_outside_workspace(ws: Path, tmp_path: Path) -> None:
    w = Workspace.open(ws)
    states = {s["id"]: s for s in source_read.list_sources(w)}
    assert states["plans"]["state"] == "ok" and states["plans"]["type"] == "dir"
    assert states["item_table"]["type"] == "file"  # 워크스페이스 밖 파일 원본
    assert states["gone"]["state"] == "missing"
    assert states["design_doc"]["state"] == "unchecked_url" and states["design_doc"]["type"] is None
    listed = source_read.list_source(w, "item_table")
    assert listed["type"] == "file" and listed["bytes"] > 0
    got = source_read.read_source(w, "item_table", secrets=NO_SECRETS)
    assert got["ref"] == "sources:item_table" and "potion_hp_s" in got["text"]
    # 같은 ID 원본이 둘이면 어느 것을 읽을지 모른다
    add_sources(ws, {"id": "plans", "kind": "other", "title": "또", "path": str(tmp_path)})
    with pytest.raises(KnowledgeError) as info:
        source_read.read_source(Workspace.open(ws), "plans", "plan/shop.md", secrets=NO_SECRETS)
    assert info.value.fields["reason"] == "duplicate_id"


def test_folder_listing_and_text_read(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    docs = tmp_path / "plan_docs"
    (docs / "plan").mkdir(parents=True)
    (docs / "plan" / "shop.md").write_bytes("# 상점\n물약 100골드\n".encode())
    (docs / "readme.txt").write_bytes("한글 cp949 문서".encode("cp949"))
    (docs / "bom.txt").write_bytes("﻿BOM 있는 글".encode())
    add_sources(root, {"id": "plans", "kind": "design_doc", "title": "기획", "local": True})
    set_local_source(root, "plans", docs)
    w = Workspace.open(root)
    top = source_read.list_source(w, "plans")
    assert [(e["name"], e["type"]) for e in top["entries"]] == [
        ("plan", "dir"),
        ("bom.txt", "file"),
        ("readme.txt", "file"),
    ]
    assert [e["name"] for e in source_read.list_source(w, "plans", "plan")["entries"]] == [
        "shop.md"
    ]
    got = source_read.read_source(w, "plans", "plan/shop.md", secrets=NO_SECRETS)
    assert got["text"] == "# 상점\n물약 100골드\n" and got["format"] == "text"
    assert got["ref"] == "sources:plans#plan/shop.md" and got["next_offset"] is None
    assert source_read.read_source(w, "plans", "readme.txt", secrets=NO_SECRETS)["text"] == (
        "한글 cp949 문서"
    )
    assert source_read.read_source(w, "plans", "bom.txt", secrets=NO_SECRETS)["text"] == (
        "BOM 있는 글"
    )
    # 읽은 결과의 ref·hash가 그대로 source 근거로 확인된다 (verify_basis와 맞물림)
    basis = verify_basis(w, {"type": "source", "ref": got["ref"], "hash": got["hash"]})
    assert basis["verified"] is True and basis["hash"] == got["hash"]
    claim = price_claim(basis=[{"type": "source", "ref": got["ref"], "hash": got["hash"]}])
    done = apply(root, [add("features/shop", claim)], rid="ux2-basis")
    assert done["applied"] is True


def test_boundaries(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("a", "utf-8")
    secret_dir = tmp_path / "private"
    secret_dir.mkdir()
    (secret_dir / "s.md").write_text("private", "utf-8")
    make_junction(docs / "jump", secret_dir)
    os.symlink(secret_dir / "s.md", docs / "link.md") if _can_symlink(tmp_path) else None
    add_sources(
        root,
        {"id": "docs", "kind": "design_doc", "title": "기획", "path": str(docs)},
        {"id": "self", "kind": "other", "title": "워크스페이스", "path": "."},
        {"id": "web", "kind": "other", "title": "웹", "url": "https://example.com/x"},
    )
    (root / "knowledge" / "secret.md").write_text("derived", "utf-8")
    (root / "notes.md").write_text("ok", "utf-8")
    w = Workspace.open(root)
    for bad in ("../private/s.md", "..\\private\\s.md", "C:/Windows/win.ini", "/a.md", "./a.md"):
        assert code(source_read.read_source, w, "docs", bad, secrets=NO_SECRETS) == "policy_path"
    # 원본 안 정션·링크는 따라가지 않는다 (읽기·목록 둘 다)
    assert code(source_read.read_source, w, "docs", "jump/s.md", secrets=NO_SECRETS) == (
        "policy_path"
    )
    assert code(source_read.list_source, w, "docs", "jump") == "policy_path"
    names = [e["name"] for e in source_read.list_source(w, "docs")["entries"]]
    assert names == ["a.md"]
    if (docs / "link.md").is_symlink():
        assert code(source_read.read_source, w, "docs", "link.md", secrets=NO_SECRETS) == (
            "policy_path"
        )
    # 등록되지 않은 원본
    assert code(source_read.read_source, w, "nope", "a.md", secrets=NO_SECRETS) == "unknown_id"
    # 워크스페이스 파생 폴더는 원본으로 읽지 않는다 (원본 루트가 워크스페이스여도)
    assert code(source_read.read_source, w, "self", "knowledge/secret.md", secrets=NO_SECRETS) == (
        "policy_path"
    )
    assert code(source_read.read_source, w, "self", "KNOWLEDGE/secret.md", secrets=NO_SECRETS) == (
        "policy_path"
    )
    assert "knowledge" not in [e["name"] for e in source_read.list_source(w, "self")["entries"]]
    assert source_read.read_source(w, "self", "notes.md", secrets=NO_SECRETS)["text"] == "ok"
    # URL 원본은 받지 않는다
    with pytest.raises(KnowledgeError) as info:
        source_read.read_source(w, "web", secrets=NO_SECRETS)
    assert info.value.code == "source_unavailable" and info.value.fields["reason"] == (
        "unchecked_url"
    )
    with pytest.raises(KnowledgeError) as info:
        source_read.read_source(w, "gone", secrets=NO_SECRETS)
    assert info.value.fields["reason"] == "missing"


def test_root_junction_follows_check_sources_rule(tmp_path: Path) -> None:
    """원본 루트 자체가 정션이면 그 대상이 루트다 (`check_sources`와 같은 규칙). 대상이 파생 폴더면
    거부."""
    root = make_ws(tmp_path)
    real = tmp_path / "real_docs"
    real.mkdir()
    (real / "a.md").write_text("real", "utf-8")
    make_junction(tmp_path / "docs_alias", real)
    make_junction(tmp_path / "wiki_alias", root / "wiki")
    add_sources(
        root,
        {
            "id": "alias",
            "kind": "design_doc",
            "title": "별칭",
            "path": str(tmp_path / "docs_alias"),
        },
        {"id": "wiki", "kind": "other", "title": "위키", "path": str(tmp_path / "wiki_alias")},
    )
    w = Workspace.open(root)
    assert source_read.read_source(w, "alias", "a.md", secrets=NO_SECRETS)["text"] == "real"
    assert code(source_read.list_source, w, "wiki") == "policy_path"


def test_size_limit_and_offset(ws: Path, tmp_path: Path) -> None:
    body = "".join(f"{i:05d} 가나다라\n" for i in range(30000))  # UTF-8 약 480 KB
    (tmp_path / "docs" / "big.txt").write_bytes(body.encode())
    w = Workspace.open(ws)
    parts: list[str] = []
    offset = 0
    rounds = 0
    while True:
        got = source_read.read_source(w, "plans", "big.txt", offset=offset, secrets=NO_SECRETS)
        # MCP 결과 상한(256 KiB)은 JSON 이스케이프 뒤 크기로 잰다 — 줄바꿈 많은 글도 한 번에 실린다
        assert len(json.dumps(got, ensure_ascii=False).encode()) < 256 * 1024 - 1024
        parts.append(got["text"])
        rounds += 1
        if got["next_offset"] is None:
            break
        offset = got["next_offset"]
    assert "".join(parts) == body and rounds == 3


def test_secrets_masked_before_slicing(ws: Path, tmp_path: Path) -> None:
    secret = "ux2-secret-value-9931"
    filler = "x" * (source_read.TEXT_LIMIT - 5)
    (tmp_path / "docs" / "s.txt").write_text(f"{filler}{secret} tail {secret}", "utf-8")
    w = Workspace.open(ws)
    first = source_read.read_source(w, "plans", "s.txt", secrets=lambda: [secret])
    second = source_read.read_source(
        w, "plans", "s.txt", offset=first["next_offset"], secrets=lambda: [secret]
    )
    joined = first["text"] + second["text"]
    assert secret not in joined and secret[:6] not in second["text"][:10]
    assert joined.endswith("*** tail ***")

    def broken() -> list[str]:
        raise OSError("자격 증명 관리자를 읽지 못함")

    assert code(source_read.read_source, w, "plans", "s.txt", secrets=broken) == (
        "secret_unchecked"
    )


def _zip(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
P = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def test_office_extraction() -> None:
    docx = _zip(
        {
            "word/document.xml": f"<w:document {W}><w:body>"
            "<w:p><w:r><w:t>상점 기획</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>물약</w:t><w:tab/><w:t>100골드</w:t></w:r></w:p>"
            "</w:body></w:document>"
        }
    )
    assert source_read.extract_text("a.docx", docx) == ("상점 기획\n물약\t100골드", "docx")
    xlsx = _zip(
        {
            "xl/workbook.xml": f'<workbook {S} {R}><sheets><sheet name="아이템" sheetId="1" '
            'r:id="rId1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" '
            'Type="x"/></Relationships>',
            "xl/sharedStrings.xml": f"<sst {S}><si><t>이름</t></si><si><t>물약</t></si>"
            "<si><r><t>가</t></r><r><t>격</t></r></si></sst>",
            "xl/worksheets/sheet1.xml": f"<worksheet {S}><sheetData>"
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>2</v></c></row>'
            '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="C2"><v>100</v></c>'
            '<c r="D2" t="inlineStr"><is><t>메모</t></is></c><c r="E2" t="b"><v>1</v></c></row>'
            "</sheetData></worksheet>",
        }
    )
    assert source_read.extract_text("a.xlsx", xlsx) == (
        "## 아이템\n이름\t\t가격\n물약\t\t100\t메모\tTRUE",
        "xlsx",
    )
    pptx = _zip(
        {
            "ppt/slides/slide2.xml": f"<p:sld {P} xmlns:p='p'><a:p><a:r><a:t>둘째</a:t></a:r></a:p>"
            "</p:sld>",
            "ppt/slides/slide10.xml": f"<p:sld {P} xmlns:p='p'><a:p><a:r><a:t>열째</a:t></a:r>"
            "</a:p></p:sld>",
            "ppt/slides/slide1.xml": f"<p:sld {P} xmlns:p='p'><a:p><a:r><a:t>첫</a:t></a:r>"
            "<a:r><a:t>째</a:t></a:r></a:p></p:sld>",
        }
    )
    assert source_read.extract_text("a.pptx", pptx) == (
        "## 슬라이드 1\n첫째\n\n## 슬라이드 2\n둘째\n\n## 슬라이드 10\n열째",
        "pptx",
    )


def test_office_bombs_and_bad_formats(monkeypatch: pytest.MonkeyPatch) -> None:
    def fails(name: str, data: bytes) -> str:
        with pytest.raises(KnowledgeError) as info:
            source_read.extract_text(name, data)
        assert info.value.code == "unsupported_format"
        return str(info.value.fields.get("reason"))

    # 압축 해제 상한: 작게 줄이고 헤더 크기와 무관하게 실제로 푼 바이트로 멈춘다
    monkeypatch.setattr(source_read, "UNZIP_LIMIT", 100_000)
    bomb = _zip({"word/document.xml": f"<w:document {W}>" + " " * 500_000 + "</w:document>"})
    assert len(bomb) < 10_000
    assert fails("bomb.docx", bomb) == "too_large"
    # DTD(엔티티 확장)는 인코딩과 상관없이 받지 않는다 (검수 1 M3: UTF-16은 바이트 검색을 지났다)
    body = (
        '<!DOCTYPE document [<!ENTITY injected "entity-expanded">]>'
        "<document><p><t>&injected;</t></p></document>"
    )
    for name, encoded in (
        ("utf8", ('<?xml version="1.0"?>' + body).encode("utf-8")),
        (
            "utf16le",
            b"\xff\xfe" + ('<?xml version="1.0" encoding="UTF-16"?>' + body).encode("utf-16-le"),
        ),
        (
            "utf16be",
            b"\xfe\xff" + ('<?xml version="1.0" encoding="UTF-16"?>' + body).encode("utf-16-be"),
        ),
    ):
        with pytest.raises(KnowledgeError) as info:
            source_read.extract_text("l.docx", _zip({"word/document.xml": encoded}))
        assert info.value.code == "unsupported_format" and info.value.fields["reason"] == "dtd", (
            name
        )
    # 양성 대조: DTD 없는 UTF-16 문서는 읽힌다
    plain = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        + f"<w:document {W}><w:p><w:r><w:t>본문</w:t></w:r></w:p></w:document>"
    )
    assert (
        source_read.extract_text(
            "u.docx", _zip({"word/document.xml": b"\xff\xfe" + plain.encode("utf-16-le")})
        )[0]
        == "본문"
    )
    assert fails("broken.docx", b"PK\x03\x04garbage") == "corrupt"
    assert fails("img.png", b"\x89PNG\r\n\x1a\n\0\0\0") == "binary"
    assert fails("old.doc", b"\xd0\xcf\x11\xe0\0\0\0\0") == "binary"
    assert fails("x.zip", _zip({"a.txt": "a"})) == "binary"


def _repeated_xlsx(text: str, refs: int) -> bytes:
    """공유 문자열 하나를 셀 `refs`개가 참조하는 xlsx (검수 1 M2 재현 구조를 작게)."""
    cells = "".join(f'<c r="A{i + 1}" t="s"><v>0</v></c>' for i in range(refs))
    return _zip(
        {
            "xl/workbook.xml": f'<workbook {S} {R}><sheets><sheet name="s" sheetId="1" '
            'r:id="rId1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" '
            'Type="x"/></Relationships>',
            "xl/sharedStrings.xml": f"<sst {S}><si><t>{text}</t></si></sst>",
            "xl/worksheets/sheet1.xml": f'<worksheet {S}><sheetData><row r="1">{cells}</row>'
            "</sheetData></worksheet>",
        }
    )


def test_output_limit_stops_shared_string_amplification(monkeypatch: pytest.MonkeyPatch) -> None:
    """XML은 작아도 공유 문자열을 반복 참조하면 출력이 커진다 — 뽑는 중에 세어 멈춘다."""
    monkeypatch.setattr(source_read, "OUTPUT_LIMIT", 100_000)
    small = _repeated_xlsx("x" * 1024, 50)  # 약 51 KB 출력 — 상한 안
    assert len(source_read.extract_text("ok.xlsx", small)[0]) > 50 * 1024
    big = _repeated_xlsx("x" * 1024, 128)  # 약 131 KB 출력 — XML은 수 KB
    assert len(big) < 10_000
    with pytest.raises(KnowledgeError) as info:
        source_read.extract_text("big.xlsx", big)
    assert info.value.code == "unsupported_format" and info.value.fields["reason"] == "too_large"
    # 먼 열 채움(빈 칸 탭)도 센다
    far = "".join(f'<row r="{i + 1}"><c r="XFC{i + 1}"><v>1</v></c></row>' for i in range(20))
    wide = _zip(
        {
            "xl/workbook.xml": f'<workbook {S} {R}><sheets><sheet name="s" sheetId="1" '
            'r:id="rId1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" '
            'Type="x"/></Relationships>',
            "xl/worksheets/sheet1.xml": f"<worksheet {S}><sheetData>{far}</sheetData></worksheet>",
        }
    )
    with pytest.raises(KnowledgeError) as info:
        source_read.extract_text("wide.xlsx", wide)
    assert info.value.fields["reason"] == "too_large"
    # docx 문단도 같은 카운터
    many = "".join("<w:p><w:r><w:t>" + "y" * 1000 + "</w:t></w:r></w:p>" for _ in range(150))
    with pytest.raises(KnowledgeError) as info:
        source_read.extract_text(
            "d.docx", _zip({"word/document.xml": f"<w:document {W}>{many}</w:document>"})
        )
    assert info.value.fields["reason"] == "too_large"


def test_activity_target_is_source_and_path() -> None:
    assert activity.short_target("sources.read", {"source": "design_doc", "path": "plan/a.md"}) == (
        "design_doc:plan/a.md"
    )
    assert activity.short_target("sources.list", {"source": "design_doc"}) == "design_doc:"
    assert activity.short_target("sources.list", {}) == ""
    assert activity.short_target("sources.read", {"source": "d", "path": "a\nb"}) == ""


def _can_symlink(tmp_path: Path) -> bool:
    probe = tmp_path / "probe_link"
    try:
        os.symlink(tmp_path, probe)
    except OSError:
        return False
    probe.unlink()
    return True
