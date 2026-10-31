"""그래프 문서 저장 계약 (M2 계획 2.6): 원문 바이트·revision·무쓰기 판정·충돌·원자적 쓰기."""

from __future__ import annotations

import copy
import difflib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from helpers.corpus import CORPUS_DIR, corpus_files, corpus_id

from kookabug_core import documents
from kookabug_core.canonical import canonical_dumps, loads_strict
from kookabug_core.documents import DocumentError
from kookabug_core.registry import default_registry
from kookabug_core.schema import check_shape
from kookabug_core.validate import check_graph
from kookabug_core.workspace import WORKSPACE_FILE, Workspace

OLD = 1_600_000_000  # 저장이 mtime을 건드렸는지 보려고 미리 옛 시각으로 둔다


def copy_file(src: Path, tmp_path: Path, name: str | None = None) -> Path:
    dst = tmp_path / (name or src.name)
    dst.write_bytes(src.read_bytes())
    os.utime(dst, (OLD, OLD))
    return dst


def snapshot(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), path.stat().st_mtime_ns


@pytest.mark.parametrize("src", corpus_files(), ids=corpus_id)
def test_unmodified_save_writes_nothing_for_every_corpus_file(src: Path, tmp_path: Path) -> None:
    path = copy_file(src, tmp_path)
    before = snapshot(path)
    doc = documents.open(path)
    assert doc.revision == documents.revision_of(before[0])
    # 같은 값을 JSON으로 한 번 왕복시킨 사본 (전송을 거친 값)
    value = json.loads(json.dumps(doc.value))
    result = documents.save(doc, value, doc.revision)
    assert (result.wrote, result.canonicalized, result.revision) == (False, False, doc.revision)
    assert snapshot(path) == before


def test_crlf_file_unmodified_save_keeps_bytes(tmp_path: Path) -> None:
    path = copy_file(CORPUS_DIR / "crlf.graph.json", tmp_path)
    before = snapshot(path)
    assert b"\r\n" in before[0]
    doc = documents.open(path)
    assert doc.original_bytes == before[0] and "\r\n" in doc.original_text
    assert not documents.save(doc, copy.deepcopy(doc.value), doc.revision).wrote
    assert snapshot(path) == before


def test_semantically_equal_value_keeps_original(tmp_path: Path) -> None:
    path = copy_file(CORPUS_DIR / "numbers.graph.json", tmp_path)
    before = snapshot(path)
    doc = documents.open(path)
    value = copy.deepcopy(doc.value)
    # 1.0 → 1, -0.0 → 0, 키 순서 뒤집기: 값으로는 같다
    sink = value["nodes"]["n_sink"]
    sink["in"]["one_float"] = 1
    sink["in"]["neg_zero_float"] = 0
    value["layout"]["nodes"]["n_entry"]["x"] = 1
    value["nodes"] = dict(reversed(list(value["nodes"].items())))
    result = documents.save(doc, value, doc.revision)
    assert not result.wrote
    assert snapshot(path) == before


def test_edit_noncanonical_file_rewrites_whole_canonical(tmp_path: Path) -> None:
    path = copy_file(CORPUS_DIR / "indent4.graph.json", tmp_path)
    doc = documents.open(path)
    assert not doc.canonical
    value = copy.deepcopy(doc.value)
    value["meta"]["title"] = "바뀐 제목"
    result = documents.save(doc, value, doc.revision)
    assert result.wrote and result.canonicalized
    assert path.read_text(encoding="utf-8") == canonical_dumps(value)
    assert doc.canonical and doc.revision == result.revision == documents.revision_of(
        path.read_bytes()
    )


def test_edit_canonical_file_minimal_diff(tmp_path: Path) -> None:
    path = copy_file(CORPUS_DIR / "canonical.graph.json", tmp_path)
    before = path.read_text(encoding="utf-8")
    doc = documents.open(path)
    assert doc.canonical
    value = copy.deepcopy(doc.value)
    value["nodes"]["n_log"]["in"]["text"] = "한 값만 바꿈"
    result = documents.save(doc, value, doc.revision)
    assert result.wrote and not result.canonicalized
    after = path.read_text(encoding="utf-8")
    changed = [
        line
        for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]
    assert changed == ['-        "text": "시작합니다"', '+        "text": "한 값만 바꿈"']


def edited(doc: documents.Document, title: str) -> dict[str, Any]:
    value = copy.deepcopy(doc.value)
    value.setdefault("meta", {})["title"] = title
    return value


def test_revision_conflict_when_disk_changed(tmp_path: Path) -> None:
    path = copy_file(CORPUS_DIR / "canonical.graph.json", tmp_path)
    doc = documents.open(path)
    other = canonical_dumps(edited(doc, "밖에서 바꿈")).encode("utf-8")
    path.write_bytes(other)
    with pytest.raises(DocumentError) as info:
        documents.save(doc, edited(doc, "내 편집"), doc.revision)
    assert info.value.code == "revision_conflict"
    assert info.value.revision == documents.revision_of(other)
    assert path.read_bytes() == other
    # 무수정 저장도 충돌이다 (디스크가 기준과 다름)
    with pytest.raises(DocumentError):
        documents.save(doc, doc.value, doc.revision)
    assert path.read_bytes() == other


def test_force_reverted_buffer_overwrites_external_change(tmp_path: Path) -> None:
    # 검수 M1: A를 연 뒤 디스크가 B로 바뀜 → 버퍼를 A로 되돌려 force 저장 → 디스크가 A 바이트
    path = copy_file(CORPUS_DIR / "indent4.graph.json", tmp_path)
    a = path.read_bytes()
    doc = documents.open(path)
    b = canonical_dumps(edited(doc, "B")).encode("utf-8")
    path.write_bytes(b)
    os.utime(path, (OLD, OLD))
    result = documents.save(doc, copy.deepcopy(doc.value), doc.revision, force=True)
    assert result.wrote and not result.canonicalized
    assert path.read_bytes() == a
    assert result.revision == documents.revision_of(a)


def test_force_edited_buffer_overwrites(tmp_path: Path) -> None:
    path = copy_file(CORPUS_DIR / "canonical.graph.json", tmp_path)
    doc = documents.open(path)
    path.write_bytes(canonical_dumps(edited(doc, "B")).encode("utf-8"))
    mine = edited(doc, "내 편집")
    result = documents.save(doc, mine, doc.revision, force=True)
    assert result.wrote
    assert path.read_text(encoding="utf-8") == canonical_dumps(mine)
    # 파일이 지워진 뒤 force 저장은 다시 만든다
    path.unlink()
    with pytest.raises(DocumentError) as info:
        documents.save(doc, edited(doc, "다시"), doc.revision)
    assert (info.value.code, info.value.revision) == ("revision_conflict", None)
    assert documents.save(doc, edited(doc, "다시"), doc.revision, force=True).wrote
    assert path.is_file()


def test_noop_judged_against_current_disk_bytes(tmp_path: Path) -> None:
    path = copy_file(CORPUS_DIR / "canonical.graph.json", tmp_path)
    doc = documents.open(path)
    # 디스크가 B(= canonical(B 값))로 바뀌고, 버퍼도 B 값이면 force여도 쓰지 않는다
    b_value = edited(doc, "B")
    path.write_bytes(canonical_dumps(b_value).encode("utf-8"))
    os.utime(path, (OLD, OLD))
    before = snapshot(path)
    result = documents.save(doc, b_value, doc.revision, force=True)
    assert not result.wrote
    assert snapshot(path) == before
    assert doc.revision == documents.revision_of(before[0]) and doc.value == b_value


@pytest.mark.parametrize(
    ("bad", "code"),
    [(2**53, "number_out_of_range"), (float("nan"), "number_not_finite")],
    ids=["2^53", "nan"],
)
def test_number_rules_block_save(bad: Any, code: str, tmp_path: Path) -> None:
    path = copy_file(CORPUS_DIR / "canonical.graph.json", tmp_path)
    before = snapshot(path)
    doc = documents.open(path)
    value = copy.deepcopy(doc.value)
    value["layout"]["nodes"]["n_log"]["x"] = bad
    with pytest.raises(DocumentError) as info:
        documents.save(doc, value, doc.revision, file="tests/a.graph.json")
    assert info.value.code == "validation_failed"
    assert [(d.code, d.pointer, d.file) for d in info.value.diagnostics] == [
        (code, "/layout/nodes/n_log/x", "tests/a.graph.json")
    ]
    assert snapshot(path) == before


def test_other_validation_errors_do_not_block_save(tmp_path: Path) -> None:
    path = copy_file(CORPUS_DIR / "canonical.graph.json", tmp_path)
    doc = documents.open(path)
    value = copy.deepcopy(doc.value)
    del value["plugins"]
    value["nodes"]["n_log"]["x_unknown"] = 1
    result = documents.save(doc, value, doc.revision)
    assert result.wrote
    assert {d.code for d in result.diagnostics} == {"missing_field", "unknown_field"}
    assert loads_strict(path.read_text(encoding="utf-8")) == value


def test_atomic_replace_leaves_no_temp_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = copy_file(CORPUS_DIR / "canonical.graph.json", tmp_path)
    before = snapshot(path)
    doc = documents.open(path)

    def fail(*args: Any) -> None:
        raise OSError(28, "디스크가 꽉 참")

    monkeypatch.setattr(documents.os, "replace", fail)
    with pytest.raises(DocumentError) as info:
        documents.save(doc, edited(doc, "못 씀"), doc.revision)
    assert info.value.code == "io_error"
    assert snapshot(path) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]
    # 문서는 그대로라 다시 저장할 수 있다
    monkeypatch.undo()
    assert documents.save(doc, edited(doc, "다시"), doc.revision).wrote


@pytest.mark.parametrize("stage", ["mkstemp", "fsync", "replace"])
def test_write_failure_at_every_stage_is_io_error(
    stage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 임시 파일을 만들기 전·쓴 뒤·바꿀 때 어디서 실패해도 DocumentError(io_error)이고 남는 것이 없다
    # (T2 검수 6: mkstemp 실패가 PermissionError 그대로 나왔다)
    path = copy_file(CORPUS_DIR / "canonical.graph.json", tmp_path)
    before = snapshot(path)
    doc = documents.open(path)
    revision = doc.revision

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError(13, "쓰기 권한 없음")

    target = {"mkstemp": documents.tempfile, "fsync": documents.os, "replace": documents.os}
    monkeypatch.setattr(target[stage], stage, fail)
    with pytest.raises(DocumentError) as info:
        documents.save(doc, edited(doc, "못 씀"), doc.revision)
    assert info.value.code == "io_error" and info.value.path == path
    assert snapshot(path) == before
    assert doc.revision == revision and doc.original_bytes == before[0]
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]


def test_bom_file_is_invalid_json(tmp_path: Path) -> None:
    ws_root = tmp_path
    (ws_root / WORKSPACE_FILE).write_text('{"format": "kookabug.workspace/0"}\n', encoding="utf-8")
    path = ws_root / "tests" / "bom.graph.json"
    path.parent.mkdir()
    path.write_bytes(b"\xef\xbb\xbf" + (CORPUS_DIR / "canonical.graph.json").read_bytes())
    with pytest.raises(DocumentError) as info:
        documents.open(path)
    assert (info.value.code, info.value.line, info.value.column) == ("invalid_json", 1, 1)
    # 로더(실행)도 읽지 못한다
    _, diags = check_graph(Workspace.open(ws_root), "tests/bom.graph.json")
    assert [d.code for d in diags] == ["json_invalid"]


def test_invalid_json_reports_position(tmp_path: Path) -> None:
    path = tmp_path / "bad.graph.json"
    path.write_bytes('{\n  "a": 1,\n  "한글": ,\n}\n'.encode())
    with pytest.raises(DocumentError) as info:
        documents.open(path)
    assert (info.value.code, info.value.line, info.value.column) == ("invalid_json", 3, 9)
    path.write_bytes(b'{"a": 1, "a": 2}')
    with pytest.raises(DocumentError) as info:
        documents.open(path)
    assert info.value.code == "invalid_json" and info.value.line is None
    path.write_bytes(b'{"a": NaN}')
    with pytest.raises(DocumentError) as info:
        documents.open(path)
    assert info.value.code == "invalid_json"
    with pytest.raises(DocumentError) as info:
        documents.open(tmp_path / "missing.graph.json")
    assert info.value.code == "not_found"


@pytest.mark.parametrize("kind", ["test", "subgraph"])
def test_create_template_is_canonical_and_valid(kind: str, tmp_path: Path) -> None:
    (tmp_path / WORKSPACE_FILE).write_text('{"format": "kookabug.workspace/0"}\n', encoding="utf-8")
    rel = f"{kind}s/new.graph.json"
    doc = documents.create(tmp_path / rel, kind, "새 그래프")  # type: ignore[arg-type]
    text = (tmp_path / rel).read_text(encoding="utf-8")
    assert doc.canonical and text == canonical_dumps(doc.value)
    assert doc.value["meta"] == {"title": "새 그래프"} and doc.value["kind"] == kind
    assert check_shape(doc.value) == []
    _, diags = check_graph(Workspace.open(tmp_path), rel, registry=default_registry())
    # 빈 테스트는 시작 노드 하나라 "검증 없이 끝나는 경로"만 나온다. 서브그래프 틀은 문제 없음
    assert [d.code for d in diags] == (["unconnected_ok_exit"] if kind == "test" else [])
    # 있으면 덮어쓰지 않는다
    before = snapshot(tmp_path / rel)
    with pytest.raises(DocumentError) as info:
        documents.create(tmp_path / rel, kind)  # type: ignore[arg-type]
    assert info.value.code == "exists" and info.value.revision == doc.revision
    assert snapshot(tmp_path / rel) == before
