"""설정 바꾸기 제안 (UX2 C) — Agent는 제안만, 사람이 보고함에서 수락한다.
엄격: Agent 권한·비밀값.

- Agent 도구 `kb_setting_propose`(작업 토큰 연결 전용)가 `propose`를 부른다. 제안은 작업 폴더
  `.kookabug/jobs/<작업>/proposals.json`(`kookabug.setting-proposals/0`, 이 PC)에만 쌓이고, 작업
  보고를 만들 때 보고 항목 `setting_change`가 된다. **설정 파일은 바꾸지 않는다**
- 팀 보고(`knowledge/reports/`)에는 제안 ID·키·이유·근거 질문만 싣는다. 값·현재 값은 이 PC 파일에만
  두고 보고함 화면(`reports.get`)이 붙여 보인다(검수 1 H1)
- 키는 허용 목록(`KEYS`)뿐이다 — 마법사가 이미 쓰는 사람 설정 키(2단계 게임, 6단계 원본 추가,
  7단계 금지 동작 추가, 치트 분류 추가). 그 밖은 `setting_not_allowed`. 계정·비밀값·Agent 설정은
  없다
- 값·이유는 제안 단계에서 글자 검사(`secret_in_text`). 값 모양은 제안 단계와 수락 단계 둘 다 본다
- 제안은 그때의 그 키 값의 해시(`current_hash`)를 기억한다. 원문 스냅샷(`current`)은 글자 검사를
  지날 때만 남긴다(아니면 `current_hidden` — 화면은 "[가림]"). 수락은 지금 값 해시가 같을 때만
  하고(아니면 `revision_conflict`), 쓰기는 마법사 그 단계 저장과 같은 함수·같은 sha/revision
  대조로 한다(daemon `methods.proposals`). 키 단위로 보는 까닭: 한 보고의 제안 여럿을 차례로
  수락할 수 있게
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

from kookabug_core import filetx
from kookabug_core.agent_job import jobdir
from kookabug_core.knowledge.formats import KnowledgeError, SecretCheck, now, shape_problem
from kookabug_core.workspace import LOCAL_FILE, WORKSPACE_FILE

__all__ = [
    "FORMAT",
    "KEYS",
    "LOCAL_KEYS",
    "MAX_PROPOSALS",
    "PROPOSAL_ID",
    "REASON_HIDDEN",
    "current_value",
    "find_proposal",
    "load_proposals",
    "local_view",
    "propose",
    "source_entry",
    "validate",
    "value_hash",
]

FORMAT: Final = "kookabug.setting-proposals/0"
REASON_HIDDEN: Final = "(이유는 이 PC의 제안 파일에만 있다)"
"""팀 보고에 이유를 싣지 못할 때(쓰기 직전 글자 검사를 못 하거나 걸림)의 자리 글."""
PROPOSALS: Final = "proposals.json"
MAX_PROPOSALS: Final = 50
PROPOSAL_ID: Final = re.compile(r"^s-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
UNKNOWN_ID: Final = re.compile(r"^u-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
KEYS: Final = (
    "game.title",
    "game.executable",
    "game.args",
    "game.cwd",
    "sources.add",
    "cheats.categories.add",
    "automation.forbidden.add",
)
"""제안할 수 있는 키 (허용 목록). 2단계 게임·6단계 원본·7단계 금지 동작·치트 분류."""
LOCAL_KEYS: Final = frozenset({"game.executable", "game.args", "game.cwd"})
"""이 PC(`local.json` settings)에 저장되는 키 (마법사 2단계와 같은 곳)."""
SOURCE_KINDS: Final = ("code", "data", "strings", "design_doc", "patch_notes", "qa_sheet", "other")
SOURCE_SLOTS: Final = {
    "code": "game_code",
    "data": "data_table",
    "strings": "string_table",
    "design_doc": "design_doc",
    "patch_notes": "patch_notes",
    "qa_sheet": "qa_sheet",
    "other": "other",
}
"""원본 종류 → 6단계 칸 ID (새 원본 ID는 칸 ID, 있으면 `<칸>_<6자 hex>`)."""
SOURCE_TITLES: Final = {
    "code": "게임 코드",
    "data": "데이터 테이블",
    "strings": "문자열 테이블",
    "design_doc": "기획 문서",
    "patch_notes": "패치 노트",
    "qa_sheet": "QA 시트",
    "other": "기타 원본",
}
_CATEGORY_ID: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SCREEN_ID: Final = _CATEGORY_ID
_TARGET: Final = re.compile(r"^[^\\:]+\.target\.json$")


def _no(message: str) -> KnowledgeError:
    return KnowledgeError("format", message)


def _text(value: Any, name: str, *, limit: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise _no(f"{name}은(는) 1~{limit}자 글이다")
    if any(ord(ch) < 32 for ch in value):
        raise _no(f"{name}에 줄바꿈·제어 문자를 쓸 수 없다")
    return value


def validate(key: str, value: Any) -> Any:
    """키·값 모양 (허용 목록 밖이면 `setting_not_allowed`). 정리한 값."""
    if key not in KEYS:
        raise KnowledgeError(
            "setting_not_allowed", "제안할 수 없는 설정 키다 (게임·원본 추가·금지 동작·치트 분류만)"
        )
    if key in ("game.title", "game.executable", "game.cwd"):
        return _text(value, key, limit=200 if key == "game.title" else 1000)
    if key == "game.args":
        if not isinstance(value, list) or len(cast(list[Any], value)) > 64:
            raise _no("game.args는 글 목록(64개까지)이다")
        items = cast(list[Any], value)
        if not all(isinstance(v, str) and len(v) <= 1000 for v in items):
            raise _no("game.args 항목은 1000자까지의 글이다")
        return [str(v) for v in items]
    if not isinstance(value, dict):
        raise _no(f"{key} 값은 객체다")
    v = cast(dict[str, Any], value)
    if key == "sources.add":
        if set(v) - {"kind", "location", "title"} or v.get("kind") not in SOURCE_KINDS:
            raise _no("sources.add는 {kind, location, title?}이고 kind는 원본 종류다")
        out: dict[str, Any] = {"kind": v["kind"], "location": _text(v.get("location"), "location")}
        if v.get("title") is not None:
            out["title"] = _text(v["title"], "title", limit=200)
        return out
    if key == "cheats.categories.add":
        if set(v) - {"id", "title", "description", "unattended"}:
            raise _no("cheats.categories.add는 {id, title, description?, unattended}다")
        if not isinstance(v.get("id"), str) or not _CATEGORY_ID.fullmatch(v["id"]):
            raise _no("치트 분류 id는 소문자로 시작하는 [a-z0-9_] 64자까지다")
        if not isinstance(v.get("unattended"), bool):
            raise _no("unattended(무인 허용 여부)는 참·거짓이다")
        out = {
            "id": v["id"],
            "title": _text(v.get("title"), "title", limit=200),
            "unattended": v["unattended"],
        }
        if v.get("description") is not None:
            out["description"] = _text(v["description"], "description", limit=2000)
        return out
    # automation.forbidden.add: 7단계 금지 동작 하나 (자동화 정책 스키마 Forbidden)
    kind = v.get("kind")
    if kind == "text" and set(v) == {"kind", "value"}:
        return {"kind": "text", "value": _text(v.get("value"), "value", limit=200)}
    path, screen = v.get("path"), v.get("id")
    target_ok = isinstance(path, str) and _TARGET.fullmatch(path) is not None
    if kind == "target" and set(v) == {"kind", "path"} and target_ok:
        return {"kind": "target", "path": path}
    screen_ok = isinstance(screen, str) and _SCREEN_ID.fullmatch(screen) is not None
    if kind == "screen" and set(v) == {"kind", "id"} and screen_ok:
        return {"kind": "screen", "id": screen}
    raise _no("금지 동작은 {kind: text, value} · {kind: target, path} · {kind: screen, id}다")


def _json_file(root: Path, rel: str) -> dict[str, Any]:
    try:
        raw = filetx.read(root, rel)
    except filetx.TxError:
        return {}
    if raw is None:
        return {}
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError, ValueError:
        return {}
    return cast(dict[str, Any], doc) if isinstance(doc, dict) else {}


def current_value(root: Path, key: str) -> Any:
    """그 키의 지금 값 (제안·수락 비교용). 게임 키는 저장하는 층(팀 `kookabug.json` 또는 이 PC
    `local.json`)의 값, 목록에 더하는 키는 지금 목록."""
    config = _json_file(root, WORKSPACE_FILE)
    if key in LOCAL_KEYS:
        settings = _json_file(root, LOCAL_FILE).get("settings")
        return cast(dict[str, Any], settings).get(key) if isinstance(settings, dict) else None
    if key == "game.title":
        settings = config.get("settings")
        return cast(dict[str, Any], settings).get(key) if isinstance(settings, dict) else None
    if key == "sources.add":
        sources = config.get("sources")
        return (
            [s.get("id") for s in sources if isinstance(s, dict)]
            if isinstance(sources, list)
            else []
        )
    if key == "cheats.categories.add":
        cheats = config.get("cheats")
        categories = (
            cast(dict[str, Any], cheats).get("categories") if isinstance(cheats, dict) else None
        )
        return (
            [c.get("id") for c in categories if isinstance(c, dict)]
            if isinstance(categories, list)
            else []
        )
    automation = config.get("automation")
    forbidden = (
        cast(dict[str, Any], automation).get("forbidden") if isinstance(automation, dict) else None
    )
    return list(forbidden) if isinstance(forbidden, list) else []


def source_entry(
    value: Mapping[str, Any], existing: Sequence[Mapping[str, Any]], tag: str | None = None
) -> tuple[dict[str, Any], str | None]:
    """6단계 저장과 같은 원본 정의: URL은 팀, 절대 경로는 이 PC(`local: true` + `local.json` 경로),
    상대 경로는 팀. ID는 칸 ID, 이미 있으면 `<칸>_<6자 hex>`. (정의, 이 PC 경로 또는 None)."""
    kind = str(value["kind"])
    slot = SOURCE_SLOTS[kind]
    taken = {str(s.get("id")) for s in existing}
    source_id = slot
    while source_id in taken:
        source_id = f"{slot}_{tag or f'{random.randrange(1 << 24):06x}'}"
        tag = None
    title = str(value.get("title") or SOURCE_TITLES[kind])
    head = {"id": source_id, "kind": kind, "title": title}
    location = str(value["location"]).strip()
    if re.match(r"^https?://", location, re.I):
        return {**head, "url": location}, None
    if re.match(r"^[A-Za-z]:[\\/]|^\\\\", location):
        return {**head, "local": True}, location
    return {**head, "path": location.replace("\\", "/")}, None


def _new_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"s-{stamp}-{random.randrange(1 << 16):04x}"


def _rel(job: str) -> str:
    return f"{jobdir.JOBS_DIR}/{job}/{PROPOSALS}"


def load_proposals(root: Path, job: str) -> list[dict[str, Any]]:
    """그 작업의 제안들 (없거나 깨졌으면 빈 목록)."""
    if not jobdir.JOB_ID.fullmatch(job):
        return []
    doc = _json_file(root, _rel(job))
    if doc.get("format") != FORMAT:
        return []
    items = doc.get("proposals")
    return (
        [cast(dict[str, Any], p) for p in items if isinstance(p, dict)]
        if isinstance(items, list)
        else []
    )


def _unknown_ids(root: Path) -> set[str]:
    doc = _json_file(root, "knowledge/unknowns.json")
    items = doc.get("unknowns")
    return (
        {str(u.get("id")) for u in items if isinstance(u, dict)}
        if isinstance(items, list)
        else set()
    )


def _dry_check(root: Path, key: str, value: Any) -> None:
    """적용했을 때 설정 파일 형식이 맞는가 (제안 단계 — 쓰지 않는다)."""
    if key in LOCAL_KEYS:
        local = _json_file(root, LOCAL_FILE) or {"format": "kookabug.local/0"}
        local["settings"] = {**dict(local.get("settings") or {}), key: value}
        problem = shape_problem(local, "local")
    else:
        config = _json_file(root, WORKSPACE_FILE)
        if key == "game.title":
            config["settings"] = {**dict(config.get("settings") or {}), key: value}
        elif key == "sources.add":
            existing = [s for s in config.get("sources") or [] if isinstance(s, dict)]
            entry, _ = source_entry(value, existing)
            config["sources"] = [*existing, entry]
        elif key == "cheats.categories.add":
            cheats = dict(config.get("cheats") or {})
            cheats["categories"] = [*list(cheats.get("categories") or []), value]
            config["cheats"] = cheats
        else:
            automation = dict(config.get("automation") or {})
            automation["forbidden"] = [*list(automation.get("forbidden") or []), value]
            config["automation"] = automation
        problem = shape_problem(config, "workspace")
    if problem is not None:
        raise _no(f"적용하면 설정 형식이 틀린다 ({problem})")


def propose(
    root: Path,
    job: str,
    key: str,
    value: Any,
    reason: str,
    unknowns: Sequence[str],
    *,
    check_secrets: SecretCheck,
) -> dict[str, Any]:
    """제안 하나를 작업 폴더에 더한다. 설정 파일은 쓰지 않는다. 더한 제안."""
    if not jobdir.JOB_ID.fullmatch(job):
        raise KnowledgeError("job_only", "설정 제안은 작업 토큰 연결만 한다")
    clean = validate(key, value)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise _no("reason은 1~2000자 글이다")
    reason = reason.strip()
    ids = [str(u) for u in unknowns]
    if len(ids) > 50 or not all(UNKNOWN_ID.fullmatch(u) for u in ids):
        raise _no("unknowns는 미지수 ID 목록(50개까지)이다")
    known = _unknown_ids(root)
    missing = [u for u in ids if u not in known]
    if missing:
        raise KnowledgeError("unknown_id", "없는 미지수다", id=missing[0])
    texts = [("reason", reason)]
    texts += [(f"value/{n}", t) for n, t in enumerate(_strings(clean))]
    check_secrets(texts)
    if key == "cheats.categories.add" and clean["id"] in (current_value(root, key) or []):
        raise KnowledgeError("exists", "이미 있는 치트 분류다")
    if key == "automation.forbidden.add" and clean in (current_value(root, key) or []):
        raise KnowledgeError("exists", "이미 있는 금지 동작이다")
    _dry_check(root, key, clean)
    with filetx.locked(root):
        items = load_proposals(root, job)
        if len(items) >= MAX_PROPOSALS:
            raise KnowledgeError("too_large", f"작업 하나의 설정 제안은 {MAX_PROPOSALS}개까지다")
        # 현재 값 스냅샷: 충돌 비교는 해시로. 원문은 글자 검사를 지날 때만 이 PC 파일에 남긴다
        # (지금 설정에 비밀값이 있으면 원문을 쓰지 않고 화면에는 "[가림]" — 검수 1 H1)
        current = current_value(root, key)
        shown: Any = current
        try:
            check_secrets([(f"current/{n}", t) for n, t in enumerate(_strings(current))])
        except Exception:
            shown = None
        proposal = {
            "id": _new_id(),
            "key": key,
            "value": clean,
            "current": shown,
            "current_hidden": shown is None and current is not None,
            "current_hash": value_hash(current),
            "reason": reason,
            "unknowns": sorted(set(ids)),
            "at": now(),
        }
        items.append(proposal)
        body = {"format": FORMAT, "job": job, "proposals": items}
        data = (json.dumps(body, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        jobdir.write_bytes(root, _rel(job), data)
    return proposal


def value_hash(value: Any) -> str:
    """설정 값의 비교용 해시 (정렬한 JSON의 sha256)."""
    import hashlib

    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def find_proposal(root: Path, job: str, proposal_id: str) -> dict[str, Any] | None:
    """이 PC 작업 폴더의 제안 하나 (없으면 None — 다른 PC에서 만든 보고)."""
    return next((p for p in load_proposals(root, job) if p.get("id") == proposal_id), None)


def local_view(root: Path, job: str, proposal_id: str) -> dict[str, Any] | None:
    """보고함 화면용: 이 PC 제안 파일의 값·현재 값(가렸으면 `current_hidden`). 없으면 None."""
    found = find_proposal(root, job, proposal_id)
    if found is None:
        return None
    return {
        "value": found.get("value"),
        "current": found.get("current"),
        "current_hidden": bool(found.get("current_hidden")),
        "reason": found.get("reason"),
    }


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in cast(list[Any], value) for s in _strings(v)]
    if isinstance(value, dict):
        return [s for v in cast(dict[str, Any], value).values() for s in _strings(v)]
    return []
