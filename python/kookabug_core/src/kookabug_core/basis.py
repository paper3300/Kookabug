"""두 기준: 팀 기준·작업 기준 덧씌움 (M8 계획 3.6·E3·E4·9장 R4) — 엄격: 사용자 파일 손상·Agent 권한.

- **작업 기준 변경** `knowledge/working/<w>/change.json`(`kookabug.working/0`) + 바뀐 파일 전체 사본
  `files/<루트 기준 경로>`. 경로는 `tests/`·`subgraphs/`·`targets/`만. 항목마다 바탕이 된 팀 파일
  sha(`base_sha256`, 새 파일이면 null)와 사본 sha(`after_sha256`)
- **실효 상태**: `active` 변경이라도 팀 파일 sha가 `base_sha256`와 다르거나 사본 바이트가
  `after_sha256`와 다르면 `stale` — 덧씌움에서 빠진다(조용히 가리지 않고 실행 기록·목록에 남김)
- **고정** `freeze`: 실행 시작 때 덧씌움(경로 → 사본 바이트)을 메모리로 읽어 감독자에 넘긴다.
  감독자가 실행 폴더 `overlay/`에 쓰고 스냅샷이 그 바이트로 복사하므로 실행 도중 작업 변경이
  바뀌어도 영향이 없다. `run.json basis`에 변경 ID·경로별 sha·빠진 변경·지식 revision을 남긴다
- **쓰기** `write`: 작업 기준 쓰기(E3·R4 대상 Agent의 그래프·target 쓰기)는 팀 파일을 건드리지 않고
  사본·`change.json`·감사 이력을 `filetx` 한 거래로 쓴다. 같은 주인(작업, 없으면 Agent)·같은
  사건이면 같은 변경을 갱신한다
- 팀 반영은 자동 채택(`adopt`)과 사람의 묶음 수락(`working.accept`)뿐이다
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, cast

from kookabug_core import filetx
from kookabug_core.adopt import path_key
from kookabug_core.canonical import loads_strict
from kookabug_core.knowledge import store
from kookabug_core.knowledge.formats import (
    FILE_FORMATS,
    Actor,
    KnowledgeError,
    file_rel,
    new_id,
    now,
    shape_problem,
)

__all__ = [
    "CHANGE_ID",
    "WORKING_DIR",
    "WORKING_PRESETS",
    "BasisKind",
    "Change",
    "Frozen",
    "change_rel",
    "copy_bytes",
    "copy_rel",
    "effective_state",
    "freeze",
    "knowledge_revisions",
    "load_change",
    "load_changes",
    "put_state",
    "team_sha",
    "view",
    "working_rel",
    "write",
    "writes_working",
]

log = logging.getLogger(__name__)

WORKING_DIR: Final = "knowledge/working"
CHANGE_FILE: Final = "change.json"
WORKING_ROOTS: Final = ("tests", "subgraphs", "targets")
WORKING_PRESETS: Final = frozenset({"curator", "qa_runner"})
"""작업 밖에서도 그래프·target 쓰기가 작업 기준으로 가는 프리셋 (E3·C7). 프리셋 등록은 B4."""
CHANGE_ID: Final = re.compile(r"^w-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
_UNSAFE: Final = "unsafe"
"""팀 파일을 경계 밖(링크·정션)이라 읽지 못함 — 어떤 sha와도 같지 않다."""

BasisKind = Literal["team", "working"]


def writes_working(kind: str, job: str | None, preset: str | None) -> bool:
    """E3·R4: Agent 연결 중 작업 토큰이 붙은 것(프리셋 무관, `full` 포함)과 `curator`·`qa_runner`
    프리셋은 `tests/`·`subgraphs/`·`targets/` 쓰기가 작업 기준으로 간다. 사람·그 밖 Agent는
    그대로."""
    return kind == "agent" and (job is not None or preset in WORKING_PRESETS)


def working_rel(rel: str) -> str:
    """작업 기준 경로 확인 (`tests/`·`subgraphs/`·`targets/` 아래, `.`·`..`·드라이브 없음). 아니면
    `policy_path`."""
    parts = rel.split("/")
    if (
        not rel
        or "\\" in rel
        or ":" in rel
        or rel.startswith("/")
        or any(p in ("", ".", "..") for p in parts)
        or len(parts) < 2
        or parts[0] not in WORKING_ROOTS
    ):
        raise KnowledgeError(
            "policy_path", "작업 기준은 tests/·subgraphs/·targets/ 아래 파일만 담는다"
        )
    return rel


def change_rel(change_id: str) -> str:
    return f"{WORKING_DIR}/{change_id}/{CHANGE_FILE}"


def copy_rel(change_id: str, rel: str) -> str:
    return f"{WORKING_DIR}/{change_id}/files/{rel}"


def _key(rel: str) -> str:
    """같은 파일 판별 키 (`adopt.path_key` — 구분자·빈 조각·대소문자 정규화)."""
    return path_key(rel)


@dataclass(slots=True)
class Change:
    """읽은 작업 기준 변경 (`doc`은 `kookabug.working/0`, `sha`는 `change.json` 바이트 sha)."""

    doc: dict[str, Any]
    sha: str | None

    @property
    def id(self) -> str:
        return str(self.doc["id"])

    @property
    def state(self) -> str:
        return str(self.doc["state"])

    @property
    def files(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.doc["files"])

    @property
    def job(self) -> str | None:
        return cast(dict[str, Any], self.doc.get("created") or {}).get("job")

    @property
    def agent(self) -> str | None:
        return cast(dict[str, Any], self.doc.get("created") or {}).get("agent")

    def file(self, rel: str) -> dict[str, Any] | None:
        return next((f for f in self.files if _key(f["path"]) == _key(rel)), None)

    def paths(self) -> list[str]:
        return [str(f["path"]) for f in self.files]


def _parse_change(data: bytes, rel: str) -> dict[str, Any]:
    try:
        doc = loads_strict(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise KnowledgeError("format", f"'{rel}'을(를) 읽을 수 없다", file=rel) from exc
    problem = shape_problem(doc, "working")
    if problem is not None:
        raise KnowledgeError("format", f"'{rel}'의 형식이 틀렸다 ({problem})", file=rel)
    return cast(dict[str, Any], doc)


def load_change(root: Path, change_id: str) -> Change | None:
    if not CHANGE_ID.fullmatch(change_id):
        return None
    rel = change_rel(change_id)
    data = filetx.read(root, rel)
    if data is None:
        return None
    doc = _parse_change(data, rel)
    if doc["id"] != change_id:
        raise KnowledgeError("format", f"'{rel}'의 id가 폴더 이름과 다르다", file=rel)
    return Change(doc, filetx.sha256_of(data))


def load_changes(root: Path) -> list[Change]:
    """작업 기준 변경 전부 (만든 시각·ID 순). 깨진 변경은 건너뛰고 로그 (덧씌움에 넣지 않는다)."""
    folder = root / WORKING_DIR
    if not folder.is_dir() or folder.is_symlink() or folder.is_junction():
        return []
    out: list[Change] = []
    for child in sorted(folder.iterdir()):
        if not CHANGE_ID.fullmatch(child.name) or child.is_symlink() or child.is_junction():
            continue
        try:
            change = load_change(root, child.name)
        except (KnowledgeError, filetx.TxError) as exc:
            log.warning("작업 기준 변경 %s을(를) 읽지 못해 건너뛴다: %s", child.name, exc)
            continue
        if change is not None:
            out.append(change)
    out.sort(key=lambda c: (str(cast(dict[str, Any], c.doc["created"]).get("at", "")), c.id))
    return out


def team_sha(root: Path, rel: str) -> str | None:
    """팀 파일 sha (없으면 None, 경계 밖이면 어떤 sha와도 다른 값)."""
    try:
        data = filetx.read(root, rel)
    except filetx.TxError:
        return _UNSAFE
    return None if data is None else filetx.sha256_of(data)


def copy_bytes(root: Path, change: Change, entry: Mapping[str, Any]) -> bytes | None:
    """사본 바이트. 없거나 `after_sha256`와 다르면(밖에서 고침) None."""
    try:
        data = filetx.read(root, copy_rel(change.id, str(entry["path"])))
    except filetx.TxError:
        return None
    if data is None or filetx.sha256_of(data) != entry["after_sha256"]:
        return None
    return data


def effective_state(root: Path, change: Change) -> str:
    """기록 상태가 `active`면 팀 파일·사본을 지금 확인해 `active`/`stale`, 아니면 기록 상태
    그대로."""
    if change.state != "active":
        return change.state
    for entry in change.files:
        if team_sha(root, str(entry["path"])) != entry["base_sha256"]:
            return "stale"
        if copy_bytes(root, change, entry) is None:
            return "stale"
    return "active"


def knowledge_revisions(root: Path) -> dict[str, int]:
    """실행 기록용 지식 파일 revision (`features/<기능>`·`lessons`·`cheats`·`unknowns`)."""
    out: dict[str, int] = {}
    for feature in store.feature_files(root):
        try:
            out[f"features/{feature}"] = int(
                store.load(root, file_rel(f"features/{feature}"), "claims", feature).doc["revision"]
            )
        except KnowledgeError, filetx.TxError, ValueError:
            continue
    for kind in ("lessons", "cheats", "unknowns"):
        try:
            loaded = store.load(root, file_rel(kind), kind)  # type: ignore[arg-type]
        except KnowledgeError, filetx.TxError:
            continue
        if loaded.sha is not None and loaded.doc.get("format") == FILE_FORMATS[kind]:  # type: ignore[index]
            out[kind] = int(loaded.doc["revision"])
    return out


@dataclass(frozen=True, slots=True)
class Frozen:
    """실행 시작 때 고정한 기준. `overlay`는 워크스페이스 기준 경로 → 바이트."""

    kind: BasisKind
    overlay: dict[str, bytes]
    record: dict[str, Any]


def _owned(change: Change, job: str | None, agent: str | None) -> bool:
    if job is not None:
        return change.job == job
    return change.job is None and agent is not None and change.agent == agent


def freeze(
    root: Path,
    kind: BasisKind,
    *,
    job: str | None = None,
    agent: str | None = None,
    changes: Sequence[str] | None = None,
) -> Frozen:
    """실행 기준 고정. `team`이면 덧씌움 없음. `working`이면 active이고 팀 파일·사본이 맞는 변경의
    사본(`changes`를 주면 그 변경만). 같은 경로를 여러 변경이 담으면 이 작업(없으면 이 Agent)의
    변경, 그다음 나중에 만든 변경이 이긴다."""
    record: dict[str, Any] = {
        "kind": kind,
        "working": [],
        "stale": [],
        "knowledge": knowledge_revisions(root),
    }
    if kind == "team":
        return Frozen(kind, {}, record)
    picked: list[tuple[Change, dict[str, bytes]]] = []
    for change in load_changes(root):
        if changes is not None and change.id not in changes:
            continue
        state = effective_state(root, change)
        if state == "stale":
            record["stale"].append(change.id)
            continue
        if state != "active":
            continue
        files: dict[str, bytes] = {}
        for entry in change.files:
            data = copy_bytes(root, change, entry)
            if data is None:  # 확인과 읽기 사이에 바뀜
                break
            files[str(entry["path"])] = data
        else:
            picked.append((change, files))
            continue
        record["stale"].append(change.id)
    picked.sort(key=lambda p: (_owned(p[0], job, agent),))  # 안정 정렬: 만든 순서 유지
    # 같은 파일(철자만 다른 키 포함)은 정규화 키 하나로 — 뒤 변경이 이기고 그 철자를 쓴다
    chosen: dict[str, tuple[str, bytes, str]] = {}
    for change, files in picked:
        for rel, data in files.items():
            chosen.pop(_key(rel), None)
            chosen[_key(rel)] = (rel, data, change.id)
    overlay = {rel: data for rel, data, _ in chosen.values()}
    for change, files in picked:
        used = {
            rel: filetx.sha256_of(d)
            for rel, d in files.items()
            if chosen[_key(rel)][2] == change.id and chosen[_key(rel)][0] == rel
        }
        if used:
            record["working"].append({"id": change.id, "files": dict(sorted(used.items()))})
    return Frozen(kind, overlay, record)


def view(
    root: Path, rel: str, *, job: str | None, agent: str | None
) -> tuple[bytes | None, Change | None]:
    """작업 연결이 보는 파일: 이 작업(없으면 이 Agent)의 실효 active 변경에 사본이 있으면 그
    바이트와
    변경, 아니면 팀 파일(변경 None)."""
    found: tuple[bytes, Change] | None = None
    for change in load_changes(root):
        if not _owned(change, job, agent) or change.file(rel) is None:
            continue
        if effective_state(root, change) != "active":
            continue
        entry = change.file(rel)
        assert entry is not None
        data = copy_bytes(root, change, entry)
        if data is not None:
            found = (data, change)
    if found is not None:
        return found
    return filetx.read(root, rel), None


def put_state(tx: filetx.Tx, change: Change, state: str) -> None:
    """변경 상태를 거래에 더한다 (채택·수락·거절·되돌리기)."""
    doc = dict(change.doc)
    doc["state"] = state
    problem = shape_problem(doc, "working")
    if problem is not None:
        raise KnowledgeError("format", f"작업 기준 변경 형식이 틀렸다 ({problem})")
    assert change.sha is not None
    tx.write(change_rel(change.id), store.encode(doc), expect_sha=change.sha)


def _pick(
    changes: Iterable[Change], rels: Sequence[str], actor: Actor, case: str | None
) -> Change | None:
    """갱신할 변경: 같은 주인·같은 사건이면 그 변경(사건이 없으면 같은 파일을 담은 것)."""
    for change in reversed(list(changes)):
        if change.state not in ("active",) or not _owned(change, actor.job, actor.id):
            continue
        if change.doc.get("case") != case:
            continue
        if case is not None or any(change.file(r) is not None for r in rels):
            return change
    return None


def write(
    root: Path,
    files: Mapping[str, bytes],
    *,
    actor: Actor,
    case: str | None = None,
    kind: str = "other",
    expect: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    """작업 기준 쓰기 (E3·R4). 팀 파일은 읽기만 한다. 사본·`change.json`·감사 이력을 한 거래로 쓰고
    변경 문서를 돌려준다. 바탕 sha는 처음 담을 때의 팀 파일 sha이고, 팀 파일이 그 뒤 바뀐 경로를
    다시
    쓰면(작업 연결은 그때 팀 파일을 보고 있었다) 지금 팀 sha로 옮긴다.

    `expect`(경로 → 쓰는 쪽이 읽은 바이트 sha, 없던 파일이면 None)를 주면 잠금 안에서 이 주체의
    지금 보기(`view`)와 비교해 다르면 `revision_conflict`(동시 쓰기가 앞 쓰기를 덮지 않게)."""
    rels = {working_rel(rel): data for rel, data in files.items()}
    if not rels:
        raise KnowledgeError("format", "쓸 파일이 없다")
    if len({_key(rel) for rel in rels}) != len(rels):
        raise KnowledgeError("path_alias", "같은 파일을 가리키는 경로가 둘 이상이다")
    from kookabug_core.knowledge.ops import log_into

    try:
        with filetx.locked(root):
            for rel, sha_before in (expect or {}).items():
                now_data, _ = view(root, rel, job=actor.job, agent=actor.id)
                now_sha = None if now_data is None else filetx.sha256_of(now_data)
                if now_sha != sha_before:
                    raise KnowledgeError(
                        "revision_conflict", f"'{rel}'이(가) 그 사이 바뀌었다 — 다시 읽는다"
                    )
            store.ensure_layout(root)
            existing = _pick(load_changes(root), list(rels), actor, case)
            if existing is None:
                doc: dict[str, Any] = {
                    "format": "kookabug.working/0",
                    "id": new_id("w"),
                    "kind": kind,
                    "case": case,
                    "group": None,
                    "files": [],
                    "state": "active",
                    "created": {"at": now(), "job": actor.job}
                    | ({"agent": actor.id} if actor.id else {}),
                }
                sha: str | None = None
            else:
                doc = dict(existing.doc)
                doc["files"] = [dict(f) for f in existing.files]
                sha = existing.sha
            entries = cast(list[dict[str, Any]], doc["files"])
            tx = filetx.Tx(root)
            for rel, data in sorted(rels.items()):
                team = team_sha(root, rel)
                if team == _UNSAFE:
                    raise KnowledgeError("policy_path", "링크·정션이 있는 경로는 담지 않는다")
                after = filetx.sha256_of(data)
                entry = next((f for f in entries if _key(f["path"]) == _key(rel)), None)
                # 이미 담은 파일이면 처음 철자의 사본 경로를 그대로 쓴다 (키 하나에 사본 하나)
                copy = copy_rel(str(doc["id"]), rel if entry is None else str(entry["path"]))
                old = filetx.read(root, copy)
                if entry is None:
                    entry = {"path": rel, "base_sha256": team, "after_sha256": after, "copy": copy}
                    entries.append(entry)
                else:
                    entry["base_sha256"] = team
                    entry["after_sha256"] = after
                tx.write(copy, data, expect_sha=None if old is None else filetx.sha256_of(old))
            entries.sort(key=lambda f: str(f["path"]))
            problem = shape_problem(doc, "working")
            if problem is not None:
                raise KnowledgeError("format", f"작업 기준 변경 형식이 틀렸다 ({problem})")
            tx.write(change_rel(str(doc["id"])), store.encode(doc), expect_sha=sha)
            log_into(
                root,
                tx,
                [
                    {
                        "op": "working_write",
                        "file": change_rel(str(doc["id"])),
                        "id": doc["id"],
                        "fields": sorted(rels),
                        "result": "applied",
                    }
                ],
                actor,
            )
            tx.commit()
    except filetx.TxError as exc:
        if exc.code == "path_outside_workspace":
            raise KnowledgeError("policy_path", "링크·정션이 있는 경로에는 쓰지 않는다") from exc
        raise KnowledgeError(exc.code, exc.message, **exc.fields) from exc
    return doc
