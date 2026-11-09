"""지식 저장소 읽기·배치 (M8 계획 3.1).

쓰기는 모두 `filetx`(잠금 `.kookabug/knowledge.lock`) 안에서 `ops.apply`·`ops.wiki_write`가 한다.
여기는 경로·읽기·빈 폴더 만들기·요청 기록(`request_id` 멱등)·감사 이력 읽기만 둔다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from kookabug_core import filetx
from kookabug_core.canonical import canonical_dumps, loads_strict
from kookabug_core.knowledge.formats import (
    FILE_FORMATS,
    LAYOUT,
    LOG_FILE,
    WORKING_CLAIMS_DIR,
    Kind,
    KnowledgeError,
    empty_doc,
    shape_problem,
)

__all__ = [
    "REQUESTS_DIR",
    "Loaded",
    "encode",
    "ensure_layout",
    "load",
    "load_working_claims",
    "log_lines",
    "request_key",
    "request_record",
    "working_claims_rel",
]

REQUESTS_DIR: Final = ".kookabug/knowledge-requests"
"""`request_id` 결과 기록 (Git 제외 — 같은 PC의 재시작 중복 방지용)."""


class Loaded:
    """읽은 지식 파일: 문서(없으면 빈 문서)와 원래 바이트 sha(없으면 None)."""

    __slots__ = ("doc", "rel", "sha")

    def __init__(self, rel: str, doc: dict[str, Any], sha: str | None) -> None:
        self.rel = rel
        self.doc = doc
        self.sha = sha


def encode(doc: Any) -> bytes:
    return canonical_dumps(doc).encode("utf-8")


def ensure_layout(root: Path) -> list[str]:
    """`knowledge/`·`wiki/` 빈 폴더를 만든다 (기존 워크스페이스는 처음 지식 연산 때). 만든 것."""
    made: list[str] = []
    for rel in LAYOUT:
        path = filetx.plain(root, rel)
        if not path.is_dir():
            path.mkdir(parents=True, exist_ok=True)
            filetx.plain(root, rel)
            made.append(rel)
    return made


def _read_doc(root: Path, rel: str, kind: str) -> tuple[dict[str, Any] | None, str | None]:
    data = filetx.read(root, rel)
    if data is None:
        return None, None
    try:
        doc = loads_strict(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise KnowledgeError(
            "format", f"'{rel}'을(를) 읽을 수 없다 (손대지 않는다)", file=rel
        ) from exc
    problem = shape_problem(doc, kind)
    if problem is not None:
        raise KnowledgeError("format", f"'{rel}'의 형식이 틀려 손대지 않는다 ({problem})", file=rel)
    return doc, filetx.sha256_of(data)


def load(root: Path, rel: str, kind: Kind, feature: str | None = None) -> Loaded:
    """팀 지식 파일 하나. 깨진 파일은 고치지 않고 `format`으로 거부한다."""
    doc, sha = _read_doc(root, rel, kind)
    if doc is None:
        return Loaded(rel, empty_doc(kind, feature), None)
    if kind == "claims" and doc.get("feature") != feature:
        raise KnowledgeError("format", f"'{rel}'의 feature가 파일 이름과 다르다", file=rel)
    assert doc.get("format") == FILE_FORMATS[kind]
    return Loaded(rel, doc, sha)


def working_claims_rel(feature: str) -> str:
    return f"{WORKING_CLAIMS_DIR}/{feature}.json"


def load_working_claims(root: Path, feature: str) -> Loaded:
    """작업 기준 주장 덧씌움 (계획 9장 R4). 없으면 빈 문서."""
    rel = working_claims_rel(feature)
    doc, sha = _read_doc(root, rel, "working-claims")
    if doc is None:
        doc = {
            "format": "kookabug.working-claims/0",
            "feature": feature,
            "revision": 0,
            "claims": [],
        }
    return Loaded(rel, doc, sha)


def feature_files(root: Path) -> list[str]:
    """`knowledge/features/*.json`의 기능 이름 (정렬)."""
    folder = root / "knowledge" / "features"
    if not folder.is_dir() or folder.is_symlink() or folder.is_junction():
        return []
    return sorted(p.stem for p in folder.glob("*.json") if p.is_file() and not p.is_symlink())


# ---------------------------------------------------------------- 요청 기록


def request_key(job: str | None, request_id: str) -> str:
    return hashlib.sha256(f"{job or '-'}\n{request_id}".encode()).hexdigest()[:32]


def request_record(root: Path, job: str | None, request_id: str) -> dict[str, Any] | None:
    """지난 같은 요청의 기록 `{digest, result | error}` (없으면 None)."""
    rel = f"{REQUESTS_DIR}/{request_key(job, request_id)}.json"
    data = filetx.read(root, rel)
    if data is None:
        return None
    try:
        record = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        return None
    return record if isinstance(record, dict) else None


# ---------------------------------------------------------------- 감사 이력


def log_lines(root: Path) -> Iterator[dict[str, Any]]:
    """`knowledge/log.jsonl`의 줄 (깨진 줄은 건너뛴다)."""
    data = filetx.read(root, LOG_FILE)
    if not data:
        return
    for line in data.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            yield value
