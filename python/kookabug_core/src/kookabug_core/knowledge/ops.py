"""제한 지식 변경 연산 적용기 (M8 계획 3.3·9장 R4·R5) — 엄격: 지식 쓰기 경계·비밀값.

`apply`(= `kb_knowledge_apply`)와 `wiki_write`(= `kb_wiki_write`)만 지식·위키를 바꾼다. 둘 다
`.kookabug/knowledge.lock` + `filetx` 한 거래로 쓴다(전부 또는 없음). 쓰는 곳은
`knowledge/{features,lessons,cheats,unknowns}`·`knowledge/working/claims/`·`knowledge/log.jsonl`·
`wiki/**/*.md`(Agent는 `wiki/index.md`·`log.md`·`reports/` 제외)뿐이다 — 정책(`kookabug.json`·
`local.json`)·`AGENTS.md`·플레이북·증거 묶음으로 가는 경로가 없다(`policy_path`).

순서: 요청 ID 확인 → 지난 같은 요청이면 그 결과 → 경로 차단 → 형식 → 글자 검사 → 연산(메모리) →
근거 규칙·의미 충돌 → 한 거래로 게시(지식 파일·작업 덧씌움·감사 이력·위키 렌더·요청 기록).
거부도 감사 이력과 요청 기록에 남긴다(글자 검사 전 거부는 위치·ID 없이).

R4: Agent가 **기존 `expected` 주장**에 한 `revise`·`supersede`·`set_status`·`mark_conflicted`는 팀
파일 대신 `knowledge/working/claims/<기능>.json`(작업 revision)에 쌓인다. 팀 반영은 보고함 수락(B3).
R5: 새 `source` 근거는 서비스가 확인한다(`sources.verify_basis`).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final, cast

from kookabug_core import filetx
from kookabug_core.canonical import canonical_dumps
from kookabug_core.knowledge import render, sources, store
from kookabug_core.knowledge.formats import (
    CLAIM_ID,
    LOG_FILE,
    OPS_CURSOR,
    Actor,
    Kind,
    KnowledgeError,
    SecretCheck,
    check_cheat,
    file_kind,
    file_rel,
    new_id,
    now,
    opaque,
    shape_problem,
    strings_of,
)
from kookabug_core.workspace import Workspace, WorkspaceError

__all__ = ["MAX_WIKI_BYTES", "apply", "check_wiki_path", "refresh_wiki", "wiki_write"]

MAX_WIKI_BYTES: Final = 1 << 20
REQUEST_ID: Final = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
ITEM_DEF: Final[dict[str, str]] = {
    "claims": "#/$defs/Claim",
    "lessons": "#/$defs/Lesson",
    "cheats": "#/$defs/Cheat",
    "unknowns": "#/$defs/Unknown",
}
CLAIM_STATUSES: Final = ("hypothesis", "supported", "conflicted", "superseded", "unverifiable")
WORKING_OPS: Final = ("revise", "supersede", "set_status", "mark_conflicted")
TRANSIENT: Final = (
    "secret_unchecked",
    "knowledge_busy",
    "recovery_pending",
    "io_error",
    "tx_failed",
)
"""다시 하면 달라질 수 있는 거부 — 요청 기록에 남기지 않는다."""


def _items(doc: dict[str, Any], kind: Kind) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], doc[kind])


def _key(b: Mapping[str, Any]) -> tuple[str, str]:
    return str(b.get("type")), str(b.get("ref"))


def _same(a: Any, b: Any) -> bool:
    return canonical_dumps(a) == canonical_dumps(b)


def _tx_error(exc: filetx.TxError) -> KnowledgeError:
    if exc.code == "path_outside_workspace":
        return KnowledgeError("policy_path", "링크·정션이 있는 경로에는 쓰지 않는다")
    return KnowledgeError(exc.code, exc.message, **exc.fields)


# ---------------------------------------------------------------- 범위


def _range(builds: Any) -> tuple[str | None, str | None]:
    if not isinstance(builds, dict):
        return None, None
    b = cast(dict[str, Any], builds)
    return b.get("from"), b.get("to")


def _build_key(v: str) -> tuple[int, int | str]:
    return (0, int(v)) if v.isdigit() else (1, v)


def scopes_overlap(a: Mapping[str, Any] | None, b: Mapping[str, Any] | None) -> bool:
    """적용 범위가 겹치나 (빠짐·null은 제한 없음)."""
    a, b = a or {}, b or {}
    pa, pb = a.get("profiles"), b.get("profiles")
    if pa is not None and pb is not None and not set(pa) & set(pb):
        return False
    for key in ("locale", "data_rev"):
        if a.get(key) is not None and b.get(key) is not None and a[key] != b[key]:
            return False
    (af, at), (bf, bt) = _range(a.get("builds")), _range(b.get("builds"))
    if at is not None and bf is not None and _build_key(at) < _build_key(bf):
        return False
    return not (bt is not None and af is not None and _build_key(bt) < _build_key(af))


# ---------------------------------------------------------------- 적용기


class _Engine:
    def __init__(self, root: Path, workspace: Workspace, actor: Actor) -> None:
        self.root = root
        self.ws = workspace
        self.actor = actor
        self.team: dict[str, store.Loaded] = {}
        self.start: dict[str, int] = {}
        self.working: dict[str, store.Loaded] = {}
        self.touched: set[str] = set()
        self.touched_working: set[str] = set()
        self.working_ids: set[tuple[str, str]] = set()
        self.expected_at_start: set[tuple[str, str]] = set()
        """요청 시작 때 팀 파일에 있던 `expected` 주장 (R4: Agent가 직접·간접으로 못 바꾼다)."""
        self.bumped: set[tuple[str, str]] = set()
        self.changed: set[tuple[str, str]] = set()
        self.results: list[dict[str, Any]] = []
        self.entries: list[dict[str, Any]] = []
        self.conflicts: list[dict[str, Any]] = []

    # ------------------------------------------------------------ 읽기

    def doc(self, file: str) -> store.Loaded:
        if file not in self.team:
            parsed = file_kind(file)
            assert parsed is not None
            loaded = store.load(self.root, file_rel(file), parsed[0], parsed[1])
            self.team[file] = loaded
            self.start[file] = int(loaded.doc["revision"])
            if parsed[0] == "claims":
                self.expected_at_start.update(
                    (file, str(c.get("id")))
                    for c in loaded.doc["claims"]
                    if c.get("kind") == "expected"
                )
        return self.team[file]

    def overlay(self, feature: str) -> store.Loaded:
        if feature not in self.working:
            self.working[feature] = store.load_working_claims(self.root, feature)
        return self.working[feature]

    @staticmethod
    def find(items: list[dict[str, Any]], item_id: str) -> int | None:
        return next((i for i, it in enumerate(items) if it.get("id") == item_id), None)

    # ------------------------------------------------------------ 작업 주장 덧씌움 (R4)

    def _working_pos(self, feature: str, claim_id: str) -> tuple[list[dict[str, Any]], int | None]:
        entries = cast(list[dict[str, Any]], self.overlay(feature).doc["claims"])
        pos = next((i for i, e in enumerate(entries) if e["claim"].get("id") == claim_id), None)
        return entries, pos

    def working_current(self, feature: str, team_item: dict[str, Any]) -> dict[str, Any]:
        """덧씌움에 있으면 그 작업 rev, 없으면 팀 항목 (작업 기준 연산의 시작점)."""
        entries, pos = self._working_pos(feature, str(team_item["id"]))
        return entries[pos]["claim"] if pos is not None else team_item

    def put_working(
        self, feature: str, team_item: dict[str, Any], new: dict[str, Any], op: str
    ) -> None:
        """기존 팀 `expected`의 새 작업 rev를 덧씌움에 쓴다 (팀 파일은 그대로). `base_rev`는 처음
        덧씌울 때의 팀 rev를 유지한다."""
        entries, pos = self._working_pos(feature, str(team_item["id"]))
        entry = {
            "at": now(),
            "base_rev": int(team_item["rev"]) if pos is None else entries[pos]["base_rev"],
            "by": {"agent": self.actor.id, "job": self.actor.job},
            "claim": new,
            "ops": sorted({*(entries[pos]["ops"] if pos is not None else []), op}),
        }
        if pos is None:
            entries.append(entry)
        else:
            entries[pos] = entry
        self.touched_working.add(feature)
        self.working_ids.add((feature, str(team_item["id"])))

    # ------------------------------------------------------------ 근거

    def basis(
        self, new: list[dict[str, Any]] | None, old: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]]:
        """새 근거 목록: 이미 있던 근거(형식·ref가 같음)는 저장된 값 그대로(`verified`를 Agent가
        바꾸지 못함), 새 근거는 확인한다."""
        stored = {_key(b): b for b in old or []}
        out: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for entry in new or []:
            key = _key(entry)
            if key in seen:
                continue
            seen.add(key)
            if key in stored:
                out.append(stored[key])
                continue
            out.append(self.check_new_basis(entry))
        return out

    def check_new_basis(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        kind, ref = _key(entry)
        if kind == "human":
            if self.actor.is_agent:
                raise KnowledgeError(
                    "human_basis_reserved", "Agent는 사람(human) 근거를 새로 쓸 수 없다"
                )
            return dict(entry)
        if kind == "source":
            return sources.verify_basis(self.ws, entry)
        if kind == "evidence":
            if (
                not re.fullmatch(r"[a-z][a-z0-9-]{0,95}", ref)
                or filetx.read(self.root, f"knowledge/evidence/{ref}/manifest.json") is None
            ):
                raise KnowledgeError("basis_unknown", "없는 증거 묶음이다")
            return dict(entry)
        if kind == "run":
            runs = self.root / "runs"
            ok = re.fullmatch(r"[a-z0-9]{8,64}", ref) is not None and any(
                (p / "run.json").is_file() for p in runs.glob(f"*_{ref}") if p.is_dir()
            )
            if not ok:
                raise KnowledgeError("basis_unknown", "없는 실행이다")
            return dict(entry)
        raise KnowledgeError("format", "모르는 근거 형식이다")

    # ------------------------------------------------------------ 규칙

    def check_item(self, kind: Kind, item: dict[str, Any], where: str) -> None:
        problem = shape_problem(item, kind, ref=ITEM_DEF[kind])
        if problem is not None:
            raise KnowledgeError("format", f"{where}: 형식이 틀렸다 ({problem})")
        basis = item.get("basis") or []
        types = {b.get("type") for b in basis}
        if kind == "claims":
            if item.get("kind") == "expected" and not types & {"source", "human"}:
                raise KnowledgeError(
                    "basis_required", f"{where}: expected 주장은 원본(source)·사람 근거가 필요하다"
                )
            if item.get("status") == "supported":
                if not types:
                    raise KnowledgeError("basis_required", f"{where}: supported는 근거가 필요하다")
                if item.get("kind") == "expected" and not any(
                    b.get("type") == "human"
                    or (b.get("type") == "source" and b.get("verified") is not False)
                    for b in basis
                ):
                    raise KnowledgeError(
                        "basis_required",
                        f"{where}: 확인 안 된 원본만으로는 expected를 supported로 올릴 수 없다",
                    )
        elif kind == "lessons":
            if not basis:
                raise KnowledgeError("basis_required", f"{where}: 경험칙은 근거가 필요하다")
        elif kind == "cheats":
            problem = check_cheat(item)
            if problem is not None:
                raise KnowledgeError("format", f"{where}: {problem}")

    # ------------------------------------------------------------ 연산

    def run(self, ops: list[dict[str, Any]]) -> None:
        for index, op in enumerate(ops):
            try:
                self.one(index, op)
            except KnowledgeError as exc:
                exc.fields.setdefault("index", index)
                raise
        self.semantic_conflicts()

    def one(self, index: int, op: dict[str, Any]) -> None:
        file = str(op["file"])
        parsed = file_kind(file)
        assert parsed is not None
        kind, feature = parsed
        where = f"ops/{index}"
        name = str(op["op"])
        loaded = self.doc(file)
        items = _items(loaded.doc, kind)
        if name == "add":
            self.add(kind, feature, file, loaded, op, where)
            return
        item_id = str(op["id"])
        pos = self.find(items, item_id)
        if pos is None:
            raise KnowledgeError("unknown_id", f"{where}: 없는 항목 ID다", id=item_id)
        team_item = items[pos]
        if name in ("adopt", "unadopt"):
            self.adoption(kind, file, loaded, pos, op, where)
            return
        if name in ("supersede", "mark_conflicted") and kind != "claims":
            raise KnowledgeError("format", f"{where}: {name}은(는) 주장 파일에만 쓴다")
        if name == "attach_evidence" and kind not in ("claims", "lessons"):
            raise KnowledgeError("format", f"{where}: attach_evidence는 주장·경험칙에만 쓴다")
        # R4: Agent가 기존 expected 주장의 판정 뜻을 바꾸는 연산은 작업 기준으로 간다
        to_working = (
            self.actor.is_agent
            and kind == "claims"
            and name in WORKING_OPS
            and team_item.get("kind") == "expected"
        )
        if to_working:
            assert feature is not None
            current = self.working_current(feature, team_item)
        else:
            current = team_item
        if int(op["base_rev"]) != int(current["rev"]):
            raise KnowledgeError(
                "revision_conflict",
                f"{where}: 항목 rev가 다르다 (지금 {current['rev']})",
                id=item_id,
                rev=current["rev"],
            )
        new, fields = self.transform(kind, file, name, current, op, where)
        if new is None:
            # 바뀐 게 없다: 지금 저장된 곳(작업 덧씌움에 있으면 그 rev) 기준으로 알린다
            stored = "working" if to_working and current is not team_item else "team"
            self.results.append(
                {"op": name, "file": file, "id": item_id, "rev": current["rev"], "basis": stored}
            )
            return
        new["rev"] = int(current["rev"]) + 1
        self.check_item(kind, new, where)
        if to_working:
            assert feature is not None
            self.put_working(feature, team_item, new, name)
            basis_kind = "working"
        else:
            history = cast(list[dict[str, Any]], loaded.doc.setdefault("history", []))
            history.append(copy.deepcopy(current))
            items[pos] = new
            self.touched.add(file)
            self.bumped.add((file, item_id))
            self.changed.add((file, item_id))
            basis_kind = "team"
        self.results.append(
            {"op": name, "file": file, "id": item_id, "rev": new["rev"], "basis": basis_kind}
        )
        self.entries.append(
            {
                "op": name,
                "file": file if basis_kind == "team" else store.working_claims_rel(str(feature)),
                "id": item_id,
                "base_rev": current["rev"],
                "new_rev": new["rev"],
                "basis": [
                    {"type": b.get("type"), "ref": b.get("ref")} for b in new.get("basis", [])
                ],
                "fields": fields,
                "result": "applied",
            }
        )

    def adoption(
        self,
        kind: Kind,
        file: str,
        loaded: store.Loaded,
        pos: int,
        op: dict[str, Any],
        where: str,
    ) -> None:
        """치트 채택·풀기 (계획 3.2·R2, 사람 전용). 채택은 정의가 아니라 rev를 올리지 않는다
        (digest가 정의 rev를 담으므로). digest는 Kookabug가 지금 워크스페이스에서 계산하고,
        미해결·동적 의존성이 있으면 거부한다(`cheat_not_adoptable`)."""
        name = str(op["op"])
        if kind != "cheats":
            raise KnowledgeError("format", f"{where}: {name}은(는) 치트 파일에만 쓴다")
        if self.actor.kind != "human":
            raise KnowledgeError("adoption_reserved", f"{where}: 치트 채택은 사람만 한다")
        items = _items(loaded.doc, kind)
        current = items[pos]
        item_id = str(current.get("id"))
        if int(op["base_rev"]) != int(current["rev"]):
            raise KnowledgeError(
                "revision_conflict",
                f"{where}: 항목 rev가 다르다 (지금 {current['rev']})",
                id=item_id,
                rev=current["rev"],
            )
        new = copy.deepcopy(current)
        if name == "unadopt":
            if current.get("adoption") is None:
                self.results.append(
                    {
                        "op": name,
                        "file": file,
                        "id": item_id,
                        "rev": current["rev"],
                        "basis": "team",
                    }
                )
                return
            new["adoption"] = None
        else:
            category = str(op["category"])
            policy = self.ws.config.get("cheats")
            categories = policy.get("categories", ()) if isinstance(policy, Mapping) else ()
            if not any(isinstance(c, Mapping) and c.get("id") == category for c in categories):
                raise KnowledgeError(
                    "category_unknown", f"{where}: 분류 '{category}'이(가) kookabug.json에 없다"
                )
            from kookabug_core.knowledge.cheats import adoption_digest

            digest, problems = adoption_digest(self.ws, current)
            if digest is None:
                raise KnowledgeError(
                    "cheat_not_adoptable",
                    f"{where}: 치트 구현에 미해결·동적 의존성이 있다 ({', '.join(problems[:5])})",
                    id=item_id,
                )
            new["adoption"] = {"at": now(), "by": "human", "category": category, "digest": digest}
        items[pos] = new
        self.touched.add(file)
        self.results.append(
            {"op": name, "file": file, "id": item_id, "rev": current["rev"], "basis": "team"}
        )
        self.entries.append(
            {
                "op": name,
                "file": file,
                "id": item_id,
                "base_rev": current["rev"],
                "new_rev": current["rev"],
                "basis": [],
                "fields": ["adoption"],
                "result": "applied",
            }
        )

    def add(
        self,
        kind: Kind,
        feature: str | None,
        file: str,
        loaded: store.Loaded,
        op: dict[str, Any],
        where: str,
    ) -> None:
        if int(op["base_revision"]) != self.start[file]:
            raise KnowledgeError(
                "revision_conflict",
                f"{where}: 파일 revision이 다르다 (지금 {self.start[file]})",
                revision=self.start[file],
            )
        item = copy.deepcopy(cast(dict[str, Any], op["item"]))
        if kind == "claims":
            item_id = item.get("id")
            if (
                not isinstance(item_id, str)
                or not CLAIM_ID.fullmatch(item_id)
                or not item_id.startswith(f"{feature}.")
            ):
                raise KnowledgeError("format", f"{where}: 주장 ID는 '<기능>.<이름>' 꼴이다")
            item.setdefault("status", "hypothesis")
            for reserved in ("superseded_by",):
                item.pop(reserved, None)
        elif kind == "unknowns":
            if item.get("answer") not in (None,) or item.get("state") == "answered":
                raise KnowledgeError("answer_reserved", f"{where}: 미지수 답은 사람만 단다")
            item.setdefault("id", new_id("u"))
            item.setdefault("state", "open")
            item["answer"] = None
        elif kind == "cheats":
            if item.get("adoption") is not None:
                raise KnowledgeError("adoption_reserved", f"{where}: 치트 채택은 사람만 한다")
            item["adoption"] = None
            item.setdefault(
                "origin",
                {"kind": "agent" if self.actor.is_agent else "human"}
                | ({"job": self.actor.job} if self.actor.job else {}),
            )
            origin = cast(dict[str, Any], item["origin"])
            if isinstance(origin, dict) and "basis" in origin:
                origin["basis"] = self.basis(origin.get("basis"), None)
        elif kind == "lessons":
            item.setdefault("active", True)
        item["rev"] = 1
        items = _items(loaded.doc, kind)
        if self.find(items, str(item.get("id"))) is not None:
            raise KnowledgeError("duplicate_id", f"{where}: 이미 있는 ID다", id=item.get("id"))
        if "basis" in item:
            item["basis"] = self.basis(item.get("basis"), None)
        self.check_item(kind, item, where)
        items.append(item)
        self.touched.add(file)
        self.bumped.add((file, str(item["id"])))
        self.changed.add((file, str(item["id"])))
        self.results.append(
            {"op": "add", "file": file, "id": item["id"], "rev": 1, "basis": "team"}
        )
        self.entries.append(
            {
                "op": "add",
                "file": file,
                "id": item["id"],
                "base_rev": None,
                "new_rev": 1,
                "basis": [
                    {"type": b.get("type"), "ref": b.get("ref")} for b in item.get("basis", [])
                ],
                "fields": sorted(item),
                "result": "applied",
            }
        )

    def transform(
        self,
        kind: Kind,
        file: str,
        name: str,
        current: dict[str, Any],
        op: dict[str, Any],
        where: str,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        """연산 하나 → (새 항목 — rev는 부르는 쪽이, 바뀐 필드). 바뀐 게 없으면 (None, [])."""
        new = copy.deepcopy(current)
        if name == "revise":
            changes = cast(dict[str, Any], op["changes"])
            if "id" in changes or "rev" in changes:
                raise KnowledgeError("format", f"{where}: id·rev는 바꿀 수 없다")
            if kind == "cheats" and "adoption" in changes:
                raise KnowledgeError("adoption_reserved", f"{where}: 치트 채택은 사람만 한다")
            if kind == "unknowns" and ("answer" in changes or changes.get("state") == "answered"):
                raise KnowledgeError("answer_reserved", f"{where}: 미지수 답은 사람만 단다")
            if kind == "claims" and "superseded_by" in changes:
                raise KnowledgeError("format", f"{where}: superseded_by는 supersede 연산으로만")
            new.update(copy.deepcopy(changes))
            if "basis" in changes:
                new["basis"] = self.basis(changes.get("basis"), current.get("basis"))
            if kind == "cheats":
                origin = new.get("origin")
                if isinstance(origin, dict) and "basis" in origin:
                    old_origin = current.get("origin") or {}
                    origin["basis"] = self.basis(
                        cast(dict[str, Any], origin).get("basis"),
                        cast(dict[str, Any], old_origin).get("basis"),
                    )
                if current.get("adoption") is not None:
                    new["adoption"] = None  # 정의가 바뀌면 채택이 풀린다 (다시 사람이 채택)
        elif name == "supersede":
            by = cast(dict[str, Any], op["by"])
            if by.get("id") == current.get("id"):
                raise KnowledgeError("format", f"{where}: 자기 자신으로 대체할 수 없다")
            self.claim_exists(file, by, where)
            new["status"] = "superseded"
            new["superseded_by"] = {"id": by["id"], "rev": by["rev"]}
        elif name == "mark_conflicted":
            refs = cast(list[dict[str, Any]], op["with"])
            for r in refs:
                self.claim_exists(file, r, where)
            merged = list(current.get("conflicts_with", []))
            for r in refs:
                ref = {"id": r["id"], "rev": r["rev"]}
                if ref not in merged:
                    merged.append(ref)
            new["status"] = "conflicted"
            new["conflicts_with"] = merged
        elif name == "attach_evidence":
            entry = cast(dict[str, Any], op["basis"])
            if any(_key(b) == _key(entry) for b in current.get("basis", [])):
                return None, []
            new["basis"] = [*current.get("basis", []), self.check_new_basis(entry)]
        elif name == "set_status":
            status = str(op["status"])
            if kind == "claims":
                if status not in CLAIM_STATUSES:
                    raise KnowledgeError("format", f"{where}: 모르는 주장 상태다")
                new["status"] = status
            elif kind == "unknowns":
                if status == "answered":
                    raise KnowledgeError("answer_reserved", f"{where}: 미지수 답은 사람만 단다")
                if status not in ("open", "dropped"):
                    raise KnowledgeError("format", f"{where}: 미지수 상태는 open·dropped다")
                new["state"] = status
            elif kind == "lessons":
                if status not in ("active", "inactive"):
                    raise KnowledgeError("format", f"{where}: 경험칙 상태는 active·inactive다")
                new["active"] = status == "active"
            else:
                raise KnowledgeError("format", f"{where}: 치트에는 set_status가 없다")
        fields = sorted(
            k
            for k in set(new) | set(current)
            if k != "rev" and not _same(new.get(k), current.get(k))
        )
        if not fields:
            return None, []
        return new, fields

    def claim_exists(self, file: str, ref: Mapping[str, Any], where: str) -> None:
        """`{id, rev}` 주장이 팀 파일(지금 또는 옛 rev)에 있나. 기능은 ID 접두로 찾는다."""
        rid = str(ref.get("id"))
        feature = rid.split(".", 1)[0]
        target = f"features/{feature}"
        if file_kind(target) is None:
            raise KnowledgeError("unknown_id", f"{where}: 없는 주장이다", id=rid)
        doc = self.doc(target).doc
        for c in [*doc.get("claims", []), *doc.get("history", [])]:
            if c.get("id") == rid and c.get("rev") == ref.get("rev"):
                return
        raise KnowledgeError("unknown_id", f"{where}: 없는 주장 rev다", id=rid)

    # ------------------------------------------------------------ 의미 충돌

    def semantic_conflicts(self) -> None:
        """같은 subject+property, 겹치는 scope의 expected 주장 값이 다르면 둘 다 conflicted (3.3).
        이 요청이 바꾼 주장이 낀 짝만 본다. 조용히 하나를 고르지 않는다."""
        if not any(f.startswith("features/") for f, _ in self.changed):
            return
        for feature in store.feature_files(self.root):
            if file_kind(f"features/{feature}") is not None:
                self.doc(f"features/{feature}")
        pool: list[tuple[str, dict[str, Any]]] = []
        for file, loaded in self.team.items():
            if not file.startswith("features/"):
                continue
            for c in loaded.doc["claims"]:
                if (
                    c.get("kind") == "expected"
                    and c.get("status") != "superseded"
                    and "subject" in c
                    and "property" in c
                ):
                    pool.append((file, c))
        for i, (fa, a) in enumerate(pool):
            for fb, b in pool[i + 1 :]:
                if (fa, a["id"]) not in self.changed and (fb, b["id"]) not in self.changed:
                    continue
                if a["subject"] != b["subject"] or a["property"] != b["property"]:
                    continue
                if _same(a.get("value"), b.get("value")) or not scopes_overlap(
                    a.get("scope"), b.get("scope")
                ):
                    continue
                if any(r.get("id") == b["id"] for r in a.get("conflicts_with", [])) and any(
                    r.get("id") == a["id"] for r in b.get("conflicts_with", [])
                ):
                    continue
                ref_a, ref_b = {"id": a["id"], "rev": a["rev"]}, {"id": b["id"], "rev": b["rev"]}
                saved_a = self.mark(fa, a, ref_b)
                saved_b = self.mark(fb, b, ref_a)
                self.conflicts.append(
                    {
                        "subject": a["subject"],
                        "property": a["property"],
                        "claims": [saved_a, saved_b],
                    }
                )

    def mark(self, file: str, claim: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
        """의미 충돌 표시. 요청 시작 때 있던 팀 `expected`를 Agent 요청이 간접으로 바꾸는 것도
        R4대로 작업 주장 덧씌움으로 보낸다(팀 항목·history·rev 그대로). 돌려주는
        `{file, id, rev, basis}`는 실제 저장한 곳 기준이다."""
        loaded = self.team[file]
        items = loaded.doc["claims"]
        pos = self.find(items, claim["id"])
        assert pos is not None
        team_item = items[pos]
        feature = file.split("/", 1)[1]
        indirect = self.actor.is_agent and (file, str(claim["id"])) in self.expected_at_start
        current = self.working_current(feature, team_item) if indirect else team_item
        new = copy.deepcopy(current)
        new["status"] = "conflicted"
        refs = list(new.get("conflicts_with", []))
        if not any(r.get("id") == other["id"] for r in refs):
            refs.append(other)
        new["conflicts_with"] = refs
        saved_file = store.working_claims_rel(feature) if indirect else file
        basis_kind = "working" if indirect else "team"
        if _same(new, current):
            return {
                "file": saved_file,
                "id": claim["id"],
                "rev": current["rev"],
                "basis": basis_kind,
            }
        if indirect:
            if (feature, str(claim["id"])) not in self.working_ids:
                new["rev"] = int(current["rev"]) + 1
            self.put_working(feature, team_item, new, "mark_conflicted")
        else:
            if (file, claim["id"]) not in self.bumped:
                loaded.doc.setdefault("history", []).append(copy.deepcopy(current))
                new["rev"] = int(current["rev"]) + 1
                self.bumped.add((file, claim["id"]))
            items[pos] = new
            claim.update(new)
            self.touched.add(file)
        self.entries.append(
            {
                "op": "mark_conflicted",
                "file": saved_file,
                "id": claim["id"],
                "base_rev": current["rev"],
                "new_rev": new["rev"],
                "basis": [],
                "fields": ["conflicts_with", "status"],
                "result": "conflict",
            }
        )
        return {"file": saved_file, "id": claim["id"], "rev": new["rev"], "basis": basis_kind}


# ---------------------------------------------------------------- 게시


def _log_bytes(
    root: Path, entries: list[dict[str, Any]], actor: Actor, request_id: str | None
) -> tuple[bytes, str | None, list[dict[str, Any]]]:
    """기존 감사 이력 + 새 줄. (새 바이트, 기존 sha, 전체 줄)."""
    old = filetx.read(root, LOG_FILE)
    existing = list(store.log_lines(root))
    seq = max((int(e.get("seq", 0)) for e in existing), default=0)
    at = now()
    lines: list[dict[str, Any]] = []
    for entry in entries:
        seq += 1
        line = {
            "format": "kookabug.knowledge-log/0",
            "seq": seq,
            "at": at,
            "agent": actor.to_log(),
            "job": actor.job,
            "request_id": request_id,
            **entry,
        }
        lines.append({k: v for k, v in line.items() if v is not None or k in ("job", "request_id")})
    body = old or b""
    if body and not body.endswith(b"\n"):
        body += b"\n"
    body += b"".join(
        (json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        for line in lines
    )
    return body, None if old is None else filetx.sha256_of(old), [*existing, *lines]


def _wiki_pages(root: Path) -> tuple[list[str], list[str]]:
    """(`wiki/` 기준 페이지들 — 색인·일지·보고 제외, 보고 파일 이름들). 링크·정션은 따라가지
    않는다."""
    base = root / "wiki"
    pages: list[str] = []
    reports: list[str] = []
    if not base.is_dir() or base.is_symlink() or base.is_junction():
        return pages, reports
    for dirpath, dirnames, filenames in os.walk(base):
        here = Path(dirpath)
        dirnames[:] = sorted(
            d for d in dirnames if not (here / d).is_symlink() and not (here / d).is_junction()
        )
        for name in sorted(filenames):
            if not name.casefold().endswith(".md") or (here / name).is_symlink():
                continue
            rel = (here / name).relative_to(base).as_posix()
            if rel.casefold() in ("index.md", "log.md"):
                continue
            if rel.casefold().startswith("reports/"):
                reports.append(rel.split("/", 1)[1])
            else:
                pages.append(rel)
    return pages, reports


def refresh_wiki(
    root: Path,
    tx: filetx.Tx,
    *,
    features: Mapping[str, Mapping[str, Any]],
    changed_features: Iterable[str],
    log_entries: list[dict[str, Any]] | None,
    extra_pages: Iterable[str] = (),
    page_texts: Mapping[str, str] | None = None,
) -> None:
    """위키 렌더 파일을 거래에 더한다: 바뀐 기능 페이지의 주장 표, `index.md`, (주면) `log.md`.
    `page_texts`는 이 거래가 함께 쓰는 위키 페이지 글(기능 페이지면 그 글에 표를 넣는다)."""
    texts = dict(page_texts or {})
    for feature in sorted(set(changed_features)):
        rel = f"wiki/features/{feature}.md"
        if rel in texts:
            continue
        old = filetx.read(root, rel)
        new = render.render_feature_page(
            None if old is None else old.decode("utf-8", errors="replace"), features[feature]
        )
        tx.write(
            rel, new.encode("utf-8"), expect_sha=None if old is None else filetx.sha256_of(old)
        )
    pages, reports = _wiki_pages(root)
    added = [p.removeprefix("wiki/") for p in [*extra_pages, *texts]]
    added += [f"features/{f}.md" for f in changed_features]
    page_list = sorted(set(pages) | set(added))
    index = render.render_index(page_list, features, reports)
    old = filetx.read(root, "wiki/index.md")
    tx.write(
        "wiki/index.md",
        index.encode("utf-8"),
        expect_sha=None if old is None else filetx.sha256_of(old),
    )
    if log_entries is not None:
        old = filetx.read(root, "wiki/log.md")
        body = render.render_log(log_entries).encode("utf-8")
        tx.write("wiki/log.md", body, expect_sha=None if old is None else filetx.sha256_of(old))


def _all_features(root: Path, engine: _Engine | None = None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for feature in store.feature_files(root):
        file = f"features/{feature}"
        if file_kind(file) is None:
            continue
        if engine is not None and file in engine.team:
            out[feature] = engine.team[file].doc
        else:
            try:
                out[feature] = store.load(root, file_rel(file), "claims", feature).doc
            except KnowledgeError:
                continue  # 깨진 파일은 목차에서 뺀다 (고치지 않는다)
    if engine is not None:
        for file, loaded in engine.team.items():
            if file.startswith("features/"):
                out[file.split("/", 1)[1]] = loaded.doc
    return out


def _record_rel(actor: Actor, request_id: str) -> str:
    return f"{store.REQUESTS_DIR}/{store.request_key(actor.job, request_id)}.json"


def _record_bytes(digest: str, payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps({"digest": digest, **payload}, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode()


def _refuse(
    root: Path,
    actor: Actor,
    request_id: str,
    digest: str,
    exc: KnowledgeError,
    *,
    early: bool,
    entry: Mapping[str, Any] | None = None,
    record: bool = True,
) -> None:
    """거부를 감사 이력·요청 기록에 남긴다 (한 거래). `early`(글자 검사 전 거부)면 위치·ID 없이.
    `record=False`면 요청 기록은 쓰지 않는다. 글자 검사 거부(`secret_in_text`)는 늘 요청 기록 없이
    — 요청 기록의 `digest`는 원문에서 계산한 값이라 비밀값이 든 요청에서는 남기지 않는다(요청 ID·
    주체가 걸렸으면 부르는 쪽이 값과 무관한 임의 식별자로 바꿔 넘긴다)."""
    if exc.code in TRANSIENT:
        return
    if exc.code == "secret_in_text":
        record = False
    line: dict[str, Any] = {"op": "request", "file": "-", "result": "refused", "code": exc.code}
    if not early and entry is not None:
        line.update({k: entry[k] for k in ("op", "file", "id") if entry.get(k) is not None})
    error = {"code": exc.code, "message": exc.message if not early else exc.code}
    if not early:
        error.update(
            {k: v for k, v in exc.fields.items() if k in ("index", "id", "rev", "revision")}
        )
    try:
        tx = filetx.Tx(root)
        body, sha, all_lines = _log_bytes(root, [line], actor, request_id)
        tx.write(LOG_FILE, body, expect_sha=sha)
        old = filetx.read(root, "wiki/log.md")
        tx.write(
            "wiki/log.md",
            render.render_log(all_lines).encode("utf-8"),
            expect_sha=None if old is None else filetx.sha256_of(old),
        )
        if record:
            tx.create(_record_rel(actor, request_id), _record_bytes(digest, {"error": error}))
        tx.commit()
    except filetx.TxError:
        pass  # 거부 기록을 못 남겨도 거부는 그대로다


def apply(
    root: Path,
    request: Mapping[str, Any],
    *,
    actor: Actor,
    check_secrets: SecretCheck,
) -> dict[str, Any]:
    """`kb_knowledge_apply`. 전부 적용하고 결과를 주거나, 아무것도 바꾸지 않고 `KnowledgeError`."""
    request_id = request.get("request_id") if isinstance(request, Mapping) else None
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise KnowledgeError("format", "request_id가 없거나 형식이 틀렸다")
    try:
        workspace = Workspace.open(root)
    except WorkspaceError as exc:
        raise KnowledgeError("io_error", "워크스페이스를 열 수 없다") from exc
    ops_raw = request.get("ops")
    try:
        with filetx.locked(root):
            # 요청 ID·주체 글자도 감사 이력·요청 기록·응답에 들어가므로 무엇이든 쓰기 전에 검사한다.
            # 걸리면 원문 대신 값과 무관한 임의 식별자로만 거부를 남긴다
            try:
                check_secrets([("request_id", request_id), *actor.texts()])
            except KnowledgeError as exc:
                _refuse(
                    root, actor.opaque(), str(opaque(request_id)), "", exc, early=True, record=False
                )
                raise
            # 연산 글자 검사는 원문 digest 계산보다 먼저: 이 뒤의 거부·성공만 요청 기록에 digest를
            # 남기므로 비밀값이 없는 요청만 거기까지 간다 (모양이 틀린 요청도 글자는 다 본다)
            try:
                check_secrets(list(strings_of(ops_raw, "ops", OPS_CURSOR)))
            except KnowledgeError as exc:
                _refuse(root, actor, request_id, "", exc, early=True, record=False)
                raise
            try:
                digest = hashlib.sha256(
                    canonical_dumps({"ops": ops_raw}).encode("utf-8")
                ).hexdigest()
            except TypeError, ValueError, RecursionError:
                # 범위 밖 정수·NaN 등: 예외 글에 원문 값이 들어 있으므로 버리고 형식 거부
                exc = KnowledgeError("format", "요청에 저장할 수 없는 값(범위 밖 숫자 등)이 있다")
                _refuse(root, actor, request_id, "", exc, early=True, record=False)
                raise exc from None
            record = store.request_record(root, actor.job, request_id)
            if record is not None:
                if record.get("digest") != digest:
                    raise KnowledgeError(
                        "idempotency_conflict", "같은 request_id로 다른 연산을 보냈다"
                    )
                if "error" in record:
                    error = dict(record["error"])
                    raise KnowledgeError(str(error.pop("code")), str(error.pop("message")), **error)
                return {**record["result"], "replayed": True}
            return _apply_locked(root, workspace, request, request_id, digest, actor, check_secrets)
    except filetx.TxError as exc:
        raise _tx_error(exc) from exc


def _apply_locked(
    root: Path,
    workspace: Workspace,
    request: Mapping[str, Any],
    request_id: str,
    digest: str,
    actor: Actor,
    check_secrets: SecretCheck,
) -> dict[str, Any]:
    ops_raw = request.get("ops")
    # (글자 검사·digest는 `apply`가 이미 했다)
    # 경로 차단: 형식 검사보다 먼저 (어떤 모양이든 정책 경로로는 가지 않는다)
    if isinstance(ops_raw, list):
        for op in cast(list[Any], ops_raw):
            if isinstance(op, dict) and file_kind(cast(dict[str, Any], op).get("file")) is None:
                exc = KnowledgeError(
                    "policy_path",
                    "지식 연산은 features/<기능>·lessons·cheats·unknowns에만 쓴다",
                )
                _refuse(root, actor, request_id, digest, exc, early=True)
                raise exc
    problem = shape_problem(dict(request), "knowledge-ops")
    if problem is not None:
        exc = KnowledgeError("format", f"요청 형식이 틀렸다 ({problem})")
        _refuse(root, actor, request_id, digest, exc, early=True)
        raise exc
    ops = cast(list[dict[str, Any]], request["ops"])
    store.ensure_layout(root)
    engine = _Engine(root, workspace, actor)
    try:
        engine.run(ops)
        for file in engine.touched:
            loaded = engine.team[file]
            loaded.doc["revision"] = engine.start[file] + 1
            parsed = file_kind(file)
            assert parsed is not None
            problem = shape_problem(loaded.doc, parsed[0])
            if problem is not None:
                raise KnowledgeError("format", f"{file}: 결과 형식이 틀렸다 ({problem})")
        for feature in engine.touched_working:
            over = engine.working[feature]
            over.doc["revision"] = int(over.doc["revision"]) + 1
            problem = shape_problem(over.doc, "working-claims")
            if problem is not None:
                raise KnowledgeError("format", f"작업 주장 {feature}: 형식이 틀렸다 ({problem})")
    except KnowledgeError as exc:
        index = exc.fields.get("index")
        entry = ops[index] if isinstance(index, int) and index < len(ops) else None
        _refuse(root, actor, request_id, digest, exc, early=False, entry=entry)
        raise
    result: dict[str, Any] = {
        "request_id": request_id,
        "applied": True,
        "results": engine.results,
        "revisions": {f: engine.team[f].doc["revision"] for f in sorted(engine.touched)},
        "working": {f: engine.working[f].doc["revision"] for f in sorted(engine.touched_working)},
        "conflicts": engine.conflicts,
        "replayed": False,
    }
    tx = filetx.Tx(root)
    for file in sorted(engine.touched):
        loaded = engine.team[file]
        tx.write(loaded.rel, store.encode(loaded.doc), expect_sha=loaded.sha)
    for feature in sorted(engine.touched_working):
        over = engine.working[feature]
        tx.write(over.rel, store.encode(over.doc), expect_sha=over.sha)
    body, sha, all_lines = _log_bytes(root, engine.entries, actor, request_id)
    tx.write(LOG_FILE, body, expect_sha=sha)
    changed_features = [f.split("/", 1)[1] for f in engine.touched if f.startswith("features/")]
    refresh_wiki(
        root,
        tx,
        features=_all_features(root, engine),
        changed_features=changed_features,
        log_entries=all_lines,
    )
    tx.create(_record_rel(actor, request_id), _record_bytes(digest, {"result": result}))
    commit = tx.commit()
    result["warnings"] = commit["warnings"]
    return result


# ---------------------------------------------------------------- 위키 쓰기

_BAD_CHARS: Final = re.compile(r'[<>:"\\|?*~\x00-\x1f]')
_RESERVED: Final = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)


def _wiki_reserved(parts: list[str]) -> bool:
    folded = [p.casefold() for p in parts]
    if folded[:1] != ["wiki"]:
        return True
    if folded in (["wiki", "index.md"], ["wiki", "log.md"]):
        return True
    return len(folded) > 2 and folded[1] == "reports"


def check_wiki_path(root: Path, path: object) -> str:
    """Agent 위키 쓰기 경로 확인. `wiki/` 아래 `.md`만, `index.md`·`log.md`·`reports/` 제외, 링크·
    정션·8.3 짧은 이름(`~`)·예약 장치 이름 없음, 실경로도 같은 규칙. 아니면 `policy_path`."""

    def refuse() -> KnowledgeError:
        return KnowledgeError(
            "policy_path",
            "위키 쓰기는 wiki/ 아래 .md 파일만 된다 (index.md·log.md·reports/와 다른 경로 제외)",
        )

    if not isinstance(path, str) or "\\" in path or path.startswith("/"):
        raise refuse()
    parts = path.split("/")
    for part in parts:
        if (
            part in ("", ".", "..")
            or _BAD_CHARS.search(part)
            or part.endswith((".", " "))
            or _RESERVED.fullmatch(part)
        ):
            raise refuse()
    if len(parts) < 2 or not parts[-1].casefold().endswith(".md") or _wiki_reserved(parts):
        raise refuse()
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink() or (current.exists() and current.is_junction()):
            raise refuse()
    real_root = Path(os.path.realpath(root))
    real = Path(os.path.realpath(current))
    try:
        real_parts = list(real.relative_to(real_root).parts)
    except ValueError:
        raise refuse() from None
    if _wiki_reserved(real_parts) or not real.is_relative_to(Path(os.path.realpath(root / "wiki"))):
        raise refuse()
    return path


def wiki_write(
    root: Path,
    path: str,
    text: str,
    base_sha256: str | None,
    *,
    actor: Actor,
    check_secrets: SecretCheck,
) -> dict[str, Any]:
    """`kb_wiki_write`. 같은 파일 sha 대조(`revision_conflict`), 1 MB 상한(`too_large`), 글자 검사.
    기능 페이지(`wiki/features/<기능>.md`)는 주장 표를 다시 넣어 쓴다. 판정 근거로 쓰이지 않는다."""
    rel = check_wiki_path(root, path)
    data = text.encode("utf-8")
    if len(data) > MAX_WIKI_BYTES:
        raise KnowledgeError("too_large", "위키 페이지는 1 MB까지다")
    check_secrets([("path", rel), ("text", text), *actor.texts()])
    try:
        with filetx.locked(root):
            store.ensure_layout(root)
            old = filetx.read(root, rel)
            current = None if old is None else filetx.sha256_of(old)
            if current != base_sha256:
                raise KnowledgeError(
                    "revision_conflict", "위키 페이지가 바뀌었다 — 다시 읽고 쓴다", sha256=current
                )
            features = _all_features(root)
            parts = rel.split("/")
            feature = parts[2][:-3] if len(parts) == 3 and parts[1] == "features" else None
            if feature is not None and feature in features:
                text = render.render_feature_page(text, features[feature])
                data = text.encode("utf-8")
            tx = filetx.Tx(root)
            tx.write(rel, data, expect_sha=current)
            entry = {"op": "wiki_write", "file": rel, "fields": [], "result": "applied"}
            body, sha, all_lines = _log_bytes(root, [entry], actor, None)
            tx.write(LOG_FILE, body, expect_sha=sha)
            refresh_wiki(
                root,
                tx,
                features=features,
                changed_features=[],
                log_entries=all_lines,
                page_texts={rel: text},
            )
            commit = tx.commit()
    except filetx.TxError as exc:
        raise _tx_error(exc) from exc
    return {
        "path": rel,
        "sha256": filetx.sha256_of(data),
        "rendered_claims": feature is not None and feature in features,
        "warnings": commit["warnings"],
    }
