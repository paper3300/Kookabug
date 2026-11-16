"""실측(2026-11-16 Init): 지식 연산 형식 오류는 내부 오류 없이 고칠 방법(필드·예)을 알려 준다."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers.knowledge import add, apply, make_ws

from kookabug_core.knowledge.formats import KnowledgeError


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return make_ws(tmp_path)


def claim(basis: object) -> dict[str, object]:
    return {
        "id": "shop.intro",
        "kind": "guess",
        "statement": "추측",
        "status": "hypothesis",
        "basis": basis,
    }


def error(ws: Path, ops_: list[dict[str, object]]) -> KnowledgeError:
    with pytest.raises(KnowledgeError) as info:
        apply(ws, ops_)  # type: ignore[arg-type]
    return info.value


def test_string_basis_entry_is_format_error_with_example(ws: Path) -> None:
    exc = error(ws, [add("features/shop", claim(["sources:design_doc#a.docx"]))])
    assert exc.code == "format"
    assert '"type"' in exc.message and "sources:" in exc.message


def test_unknown_basis_type_shows_example(ws: Path) -> None:
    exc = error(ws, [add("features/shop", claim([{"type": "doc", "ref": "x"}]))])
    assert exc.code == "format" and '"type"' in exc.message


def test_missing_file_names_the_field(ws: Path) -> None:
    op = add("features/shop", claim([]))
    op.pop("file")
    exc = error(ws, [op])
    assert exc.code == "policy_path" and "`file`" in exc.message
