"""조사 사건 `knowledge/cases/<사건 ID>.json` (M8 계획 3.2 사건·3.13, B4).

- **시그니처** = sha256(테스트 경로 + 그래프 스냅샷 해시(루트 그래프 sha와 스냅샷 폐포 digest) +
  주장 rev 목록 + 증상 종류 + 노드 + 프로필 + 게임 빌드 + 플랫폼 + 연결된 원본 해시). 같은
  시그니처로 열면 새 사건 없이 열린 사건의 `runs`에 붙이고 지난 가설을 돌려준다(같은 원인 확정은
  아님). 닫힌·해결된 사건에는 붙이지 않는다(재발은 새 사건)
- `original`은 열 때 채우고 그 뒤 바꾸지 않는다(원래 실패 보존). 원래 실패 증거 고정은 호출자
  (daemon)가 먼저 해서 그 묶음 ID를 넘긴다
- **`resolved`·`closed`는 Kookabug만**: Agent의 `update`가 그 상태를 주면
  `case_resolution_reserved`. 사람은 `close`(사람 전용 메서드)로, 자동 채택은 `adopt.publish_auto`가
  넣는다
- `update`는 허용 목록의 키만 바꾼다(`UPDATABLE`). `original`·`runs`·`signature`·`symptom`·
  `resolution`·`links.adoption`은 Agent가 바꾸지 못한다
- 쓰기는 지식 잠금 + `filetx` 한 거래 + 감사 이력(`log.jsonl`). 글자는 쓰기 전에 비밀값 검사
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, cast

from kookabug_core import filetx
from kookabug_core.adopt import case_rel, load_case, path_key
from kookabug_core.canonical import canonical_dumps
from kookabug_core.knowledge import store
from kookabug_core.knowledge.formats import (
    Actor,
    KnowledgeError,
    SecretCheck,
    new_id,
    now,
    shape_problem,
    strings_of,
)
from kookabug_core.knowledge.ops import log_into

__all__ = [
    "AGENT_STATES",
    "CASES_DIR",
    "OPEN_STATES",
    "UPDATABLE",
    "Facts",
    "close_case",
    "get_case",
    "list_cases",
    "open_case",
    "symptom_kind",
    "update_case",
]

CASES_DIR: Final = "knowledge/cases"
OPEN_STATES: Final = frozenset({"open", "needs_info", "watching"})
"""같은 시그니처 실패가 붙는 사건 상태."""
AGENT_STATES: Final = OPEN_STATES
"""`update`로 넣을 수 있는 상태 (`resolved`·`closed`는 Kookabug·사람만)."""
UPDATABLE: Final = frozenset(
    {"title", "state", "hypotheses", "actions", "needs", "recheck", "links"}
)
"""`update`가 바꾸는 키 (허용 목록 — 나머지는 `format`)."""
LINK_KEYS: Final = frozenset({"claims", "working", "reports"})
"""`update`가 바꾸는 `links` 키 (`adoption`은 채택만 넣는다)."""

_SYMPTOM_BY_CODE: Final[Mapping[str, str]] = {
    "target_not_found": "target_missing",
    "not_found": "target_missing",
    "launch_failed": "launch_failed",
    "window_not_found": "launch_failed",
    "stalled_repeat": "stalled",
    "screen_mismatch": "unexpected_screen",
    "unexpected_screen": "unexpected_screen",
}


LOCATOR_NODES: Final = frozenset(
    {
        "core.image.click",
        "core.image.wait",
        "core.image.wait_any",
        "core.image.wait_gone",
        "core.ocr.click_text",
        "core.ocr.wait_text",
    }
)
"""찾지 못하면 `target_missing`인 조작·찾기 노드 (판정 노드의 fail은 값 불일치)."""


def symptom_kind(verdict: str | None, code: str | None, node_type: str | None = None) -> str:
    """실행 판정·코드·실패 노드 종류 → 증상 종류 (KB문서 6장). 찾기·조작 노드의 fail은 대상 없음,
    그 밖 fail은 값 불일치, 오류는 노드 오류다."""
    if code is not None and code in _SYMPTOM_BY_CODE:
        return _SYMPTOM_BY_CODE[code]
    if verdict == "fail":
        return "target_missing" if node_type in LOCATOR_NODES else "value_mismatch"
    return "node_error"


@dataclass(frozen=True, slots=True)
class Facts:
    """실패 실행에서 읽은 시그니처 재료 (daemon이 실행 기록에서 채운다)."""

    run: str
    test: str | None
    graph_sha: str | None
    verdict: str | None
    code: str | None
    node: str | None
    profile: str | None = None
    game_build: str | None = None
    platform: str | None = None
    claims: tuple[tuple[str, int], ...] = ()
    sources: Mapping[str, str | None] = field(default_factory=dict[str, str | None])
    basis: str = "team"
    node_type: str | None = None
    snapshot: str | None = None
    """실행 스냅샷 폐포(그래프·서브그래프·target·PNG·화면 전부) 바이트의 digest — 루트 그래프만 같고
    서브그래프·target이 바뀐 재실행을 "같은 테스트"로 보지 않게 (시그니처·정체 감지)."""

    @property
    def kind(self) -> str:
        return symptom_kind(self.verdict, self.code, self.node_type)

    def signature(self) -> str:
        parts = {
            "test": None if self.test is None else path_key(self.test),
            "graph_sha": self.graph_sha,
            "snapshot": self.snapshot,
            "claims": sorted([list(c) for c in self.claims]),
            "kind": self.kind,
            "node": self.node,
            "profile": self.profile,
            "game_build": self.game_build,
            "platform": self.platform,
            "sources": dict(sorted(self.sources.items())),
        }
        digest = hashlib.sha256(canonical_dumps(parts).encode("utf-8")).hexdigest()
        return f"sha256:{digest}"


# ---------------------------------------------------------------- 읽기


def _case_files(root: Path) -> list[str]:
    folder = root / CASES_DIR
    if not folder.is_dir() or folder.is_symlink() or folder.is_junction():
        return []
    pattern = re.compile(r"^c-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
    return sorted(
        p.stem
        for p in folder.glob("c-*.json")
        if pattern.fullmatch(p.stem) and p.is_file() and not p.is_symlink()
    )


def _all(root: Path) -> list[tuple[dict[str, Any], str]]:
    out: list[tuple[dict[str, Any], str]] = []
    for case_id in _case_files(root):
        try:
            out.append(load_case(root, case_id))
        except KnowledgeError:
            continue  # 깨진 사건 파일은 목록에서 뺀다 (get은 그대로 거부)
    return out


def summary(doc: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": doc["id"],
        "revision": doc["revision"],
        "title": doc["title"],
        "state": doc["state"],
        "symptom": dict(cast(Mapping[str, Any], doc["symptom"])),
        "runs": 1 + len(cast(list[Any], doc.get("runs") or [])),
        "signature": doc["signature"],
    }


def list_cases(root: Path, state: str | None = None) -> list[dict[str, Any]]:
    return [summary(doc) for doc, _ in _all(root) if state is None or doc["state"] == state]


def get_case(root: Path, case_id: str) -> tuple[dict[str, Any], str]:
    return load_case(root, case_id)


# ---------------------------------------------------------------- 쓰기


def _encode(doc: Mapping[str, Any]) -> bytes:
    problem = shape_problem(doc, "case")
    if problem is not None:
        raise KnowledgeError("format", f"사건 형식이 틀렸다 ({problem})")
    return store.encode(dict(doc))


def _commit(
    root: Path,
    rel: str,
    data: bytes,
    expect: str | None,
    *,
    actor: Actor,
    op: str,
    case_id: str,
    base: int | None,
    new: int,
    fields: Sequence[str],
) -> None:
    tx = filetx.Tx(root)
    tx.write(rel, data, expect_sha=expect)
    log_into(
        root,
        tx,
        [
            {
                "op": op,
                "file": rel,
                "id": case_id,
                "base_rev": base,
                "new_rev": new,
                "fields": sorted(fields),
                "result": "applied",
            }
        ],
        actor,
    )
    tx.commit()


def _locked(fn: Any) -> Any:
    try:
        return fn()
    except filetx.TxError as exc:
        raise KnowledgeError(exc.code, exc.message) from exc


def open_case(
    root: Path,
    facts: Facts,
    *,
    title: str | None,
    evidence: str | None,
    actor: Actor,
    check_secrets: SecretCheck,
) -> dict[str, Any]:
    """실패 실행으로 사건을 연다. 같은 시그니처의 열린 사건이 있으면 그 `runs`에 붙인다."""
    if facts.verdict in (None, "pass", "skip"):
        raise KnowledgeError("format", "사건은 실패·오류로 끝난 실행으로만 연다")
    label = title or f"{facts.test or '실행'} 실패 ({facts.kind})"
    check_secrets([("title", label), *actor.texts()])
    signature = facts.signature()

    def work() -> dict[str, Any]:
        with filetx.locked(root):
            store.ensure_layout(root)
            for doc, sha in _all(root):
                if doc["signature"] != signature or doc["state"] not in OPEN_STATES:
                    continue
                runs = [dict(r) for r in cast(list[Any], doc.get("runs") or [])]
                known = {str(doc["original"]["run"]), *(str(r["run"]) for r in runs)}
                hypotheses = [dict(h) for h in cast(list[Any], doc.get("hypotheses") or [])]
                if facts.run in known:
                    return _opened(doc, True, signature, hypotheses)
                runs.append({"run": facts.run, "evidence": None, "at": now()})
                new = {**doc, "runs": runs, "revision": int(doc["revision"]) + 1}
                _commit(
                    root,
                    case_rel(str(doc["id"])),
                    _encode(new),
                    sha,
                    actor=actor,
                    op="case_attach",
                    case_id=str(doc["id"]),
                    base=int(doc["revision"]),
                    new=int(new["revision"]),
                    fields=["runs"],
                )
                return _opened(new, True, signature, hypotheses)
            case_id = new_id("c")
            while (root / case_rel(case_id)).exists():
                case_id = new_id("c")
            doc = {
                "format": "kookabug.case/0",
                "id": case_id,
                "revision": 1,
                "title": label,
                "state": "open",
                "symptom": {
                    "kind": facts.kind,
                    "test": facts.test,
                    "node": facts.node,
                    "code": facts.code,
                },
                "signature": signature,
                "original": {
                    "run": facts.run,
                    "evidence": evidence,
                    "graph_sha": facts.graph_sha,
                    "claims": [{"id": c, "rev": r} for c, r in facts.claims],
                    "basis": {"kind": facts.basis},
                },
                "runs": [],
                "hypotheses": [],
                "actions": [],
                "needs": [],
                "links": {"claims": [], "working": [], "adoption": None, "reports": []},
                "resolution": None,
            }
            _commit(
                root,
                case_rel(case_id),
                _encode(doc),
                None,
                actor=actor,
                op="case_open",
                case_id=case_id,
                base=None,
                new=1,
                fields=["original", "symptom", "signature"],
            )
            return _opened(doc, False, signature, [])

    return cast(dict[str, Any], _locked(work))


def _opened(
    doc: Mapping[str, Any], attached: bool, signature: str, hypotheses: list[dict[str, Any]]
) -> dict[str, Any]:
    original = cast(Mapping[str, Any], doc["original"])
    return {
        "case": doc["id"],
        "revision": doc["revision"],
        "attached": attached,
        "signature": signature,
        "evidence": original.get("evidence"),
        "hypotheses": hypotheses,
    }


def update_case(
    root: Path,
    case_id: str,
    base_revision: int,
    changes: Mapping[str, Any],
    *,
    actor: Actor,
    check_secrets: SecretCheck,
) -> dict[str, Any]:
    """제목·상태·가설·조치·필요 정보·재확인·연결만 바꾼다 (Agent·사람 공통 — 닫기는
    `close_case`)."""
    unknown = sorted(set(changes) - UPDATABLE)
    if unknown:
        raise KnowledgeError("format", f"사건에서 바꿀 수 없는 키다: {', '.join(unknown)}")
    state = changes.get("state")
    if state is not None and state not in AGENT_STATES:
        raise KnowledgeError(
            "case_resolution_reserved",
            "사건 resolved·closed는 자동 채택이나 사람만 넣는다 (가설·필요 정보로 남긴다)",
        )
    links = changes.get("links")
    if links is not None:
        if not isinstance(links, Mapping):
            raise KnowledgeError("format", "links는 객체다")
        extra = sorted(set(cast(Mapping[str, Any], links)) - LINK_KEYS)
        if extra:
            raise KnowledgeError("format", f"links에서 바꿀 수 없는 키다: {', '.join(extra)}")
    check_secrets([*strings_of(dict(changes), "changes"), *actor.texts()])

    def work() -> dict[str, Any]:
        with filetx.locked(root):
            doc, sha = load_case(root, case_id)
            if int(doc["revision"]) != int(base_revision):
                raise KnowledgeError(
                    "revision_conflict", "사건이 그사이 바뀌었다 — 다시 읽고 고친다"
                )
            if doc["state"] not in OPEN_STATES:
                raise KnowledgeError("case_closed", "닫히거나 해결된 사건은 고치지 않는다")
            new = dict(doc)
            for key, value in changes.items():
                if key == "links":
                    merged = dict(cast(Mapping[str, Any], doc.get("links") or {}))
                    merged.update(cast(Mapping[str, Any], value))
                    new["links"] = merged
                else:
                    new[key] = value
            new["revision"] = int(doc["revision"]) + 1
            _commit(
                root,
                case_rel(case_id),
                _encode(new),
                sha,
                actor=actor,
                op="case_update",
                case_id=case_id,
                base=int(doc["revision"]),
                new=int(new["revision"]),
                fields=list(changes),
            )
            return {"case": case_id, "revision": new["revision"]}

    return cast(dict[str, Any], _locked(work))


def close_case(
    root: Path,
    case_id: str,
    base_revision: int,
    *,
    state: str,
    note: str | None,
    actor: Actor,
    check_secrets: SecretCheck,
) -> dict[str, Any]:
    """사람 전용 닫기 (`cases.close`): `resolved`·`closed` + `resolution{by: human}`."""
    if actor.is_agent:
        raise KnowledgeError("case_resolution_reserved", "사건 닫기는 사람만 한다")
    if state not in ("resolved", "closed"):
        raise KnowledgeError("format", "닫기 상태는 resolved·closed다")
    check_secrets([("note", note or ""), *actor.texts()])

    def work() -> dict[str, Any]:
        with filetx.locked(root):
            doc, sha = load_case(root, case_id)
            if int(doc["revision"]) != int(base_revision):
                raise KnowledgeError("revision_conflict", "사건이 그사이 바뀌었다")
            resolution: dict[str, Any] = {"by": "human", "at": now()}
            if note:
                resolution["note"] = note
            new = {
                **doc,
                "state": state,
                "resolution": resolution,
                "revision": int(doc["revision"]) + 1,
            }
            _commit(
                root,
                case_rel(case_id),
                _encode(new),
                sha,
                actor=actor,
                op="case_close",
                case_id=case_id,
                base=int(doc["revision"]),
                new=int(new["revision"]),
                fields=["state", "resolution"],
            )
            return {"case": case_id, "revision": new["revision"]}

    return cast(dict[str, Any], _locked(work))
