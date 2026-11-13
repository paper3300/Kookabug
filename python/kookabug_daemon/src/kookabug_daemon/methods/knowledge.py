"""지식 메서드 (M8 계획 3.3·3.4·3.13, B4) — 엄격: 지식 쓰기 경계·비밀값.

Agent 도구 (툴셋 `knowledge`): `knowledge.search`·`knowledge.get`(조회), `knowledge.apply`·
`wiki.write`(변경). 쓰기는 코어 `knowledge.ops` 한 경로뿐이고, 주체는 연결의 실제 주체
(`actor_of` — 작업 토큰이면 작업 ID까지)·글자 검사는 보호 기록의 비밀값 키(`checker_of`)다. 그래서
B1의 경계(정책 경로 차단·`human` 근거·치트 채택·`expected` 주장 작업 기준 덧씌움 R4)가 실제 연결에
그대로 걸린다.

사람 전용 (`ui_only` + `AGENT_DENIED`): `unknowns.answer`·`project.automation.set`·
`project.sources.set`·`sources.check`.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final, cast

from kookabug_core import filetx, playbooks
from kookabug_core.knowledge import human, ops, sources, store
from kookabug_core.knowledge.formats import KnowledgeError, file_kind, file_rel
from kookabug_core.workspace import Workspace, WorkspaceError, secret_env_name, workspace_id
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods.adopt import actor_of, checker_of
from kookabug_daemon.protocol import RequestFailed, request_failed_codes

__all__ = ["METHODS", "knowledge_failed", "run_guarded"]

_MAP: Final[Mapping[str, str]] = {
    "unknown_id": "not_found",
    "path_outside_workspace": "policy_path",
    "category_unknown": "not_found",
    "tx_invalid": "io_error",
}
SEARCH_LIMIT: Final = 50


def knowledge_failed(exc: KnowledgeError | filetx.TxError) -> RequestFailed:
    """코어 거부 → daemon 오류. 메시지·필드에 요청 글자 값을 넣지 않는다(코어가 이미 고정 글자)."""
    code = _MAP.get(exc.code, exc.code)
    fields = dict(getattr(exc, "fields", {}) or {})
    if code == "format":
        return RequestFailed("validation_failed", exc.message, diagnostics=[])
    if code == "not_found":
        return RequestFailed("not_found", exc.message, path=str(fields.get("id", "")))
    if code == "revision_conflict":
        return RequestFailed("revision_conflict", exc.message, revision=None)
    if code in request_failed_codes():
        # 오류 data 계약(`RequestFailedData`)에 있는 필드만 — 없는 필드(예: R5 `hash`)를 실으면
        # 응답 검사가 internal_error로 바꾼다
        safe = {k: v for k, v in fields.items() if k in ("field", "reason")}
        return RequestFailed(code, exc.message, **safe)
    return RequestFailed("io_error", exc.message, message=exc.message)


def run_guarded(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except (KnowledgeError, filetx.TxError) as exc:
        raise knowledge_failed(exc) from exc
    except WorkspaceError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc


def _changed(call: Call, files: Iterable[str]) -> None:
    notify = getattr(call.daemon, "knowledge_changed", None)
    if notify is not None:
        notify(sorted(set(files)))


# ---------------------------------------------------------------- 조회


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text)
    return "".join(folded.split()).casefold()


_TEXT_KEYS: Final = (
    "statement", "subject", "property", "title", "advice", "question", "effect", "note", "value",
    "how",
)  # fmt: skip


def _texts(item: Mapping[str, Any]) -> str:
    parts = [str(item.get("id", ""))]
    for key in _TEXT_KEYS:
        value = item.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            parts.append(str(value))
    return " · ".join(p for p in parts if p)


def _files(root: Any) -> list[str]:
    return [*(f"features/{f}" for f in store.feature_files(root)), "lessons", "cheats", "unknowns"]


def _load(root: Any, file: str) -> store.Loaded:
    found = file_kind(file)
    if found is None:
        raise KnowledgeError("policy_path", "지식 파일은 features/<기능>·lessons·cheats·unknowns다")
    kind, feature = found
    return store.load(root, file_rel(file), kind, feature)


def _items(file: str, doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    kind = file_kind(file)
    key = {"claims": "claims", "lessons": "lessons", "cheats": "cheats", "unknowns": "unknowns"}[
        kind[0] if kind else "claims"
    ]
    return [cast(dict[str, Any], i) for i in cast(list[Any], doc.get(key) or [])]


def _search_sync(call: Call) -> dict[str, Any]:
    p = call.params
    root = call.daemon.root
    needle = _fold(str(p["query"]))
    wanted = [str(f) for f in p.get("files") or _files(root)]
    limit = int(p.get("limit", SEARCH_LIMIT))
    matches: list[dict[str, Any]] = []
    truncated = False
    for file in wanted:
        doc = _load(root, file).doc
        for item in _items(file, doc):
            text = _texts(item)
            if needle not in _fold(text):
                continue
            if len(matches) >= limit:
                truncated = True
                break
            matches.append(
                {
                    "file": file,
                    "id": str(item.get("id", "")),
                    "rev": item.get("rev") if isinstance(item.get("rev"), int) else None,
                    "kind": item.get("kind") if isinstance(item.get("kind"), str) else None,
                    "status": next(
                        (item[k] for k in ("status", "state") if isinstance(item.get(k), str)),
                        None,
                    ),
                    "text": text[:400],
                }
            )
    return {"matches": matches, "truncated": truncated}


async def _search(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(run_guarded, _search_sync, call)


def _get_sync(call: Call) -> dict[str, Any]:
    root = call.daemon.root
    file = str(call.params["file"])
    loaded = _load(root, file)
    out: dict[str, Any] = {
        "file": file,
        "revision": int(loaded.doc.get("revision", 0)),
        "sha256": loaded.sha,
        "working": [],
    }
    found = file_kind(file)
    if found is not None and found[0] == "claims" and found[1] is not None:
        # 작업 기준 주장 덧씌움 (R4): 팀 파일에 아직 반영되지 않은 Agent 변경
        out["working"] = list(store.load_working_claims(root, found[1]).doc.get("claims") or [])
    item_id = call.params.get("id")
    if item_id is None:
        out["doc"] = loaded.doc
        return out
    item = next((i for i in _items(file, loaded.doc) if i.get("id") == item_id), None)
    if item is None:
        raise KnowledgeError("unknown_id", "없는 항목이다", id=str(item_id))
    out["item"] = item
    return out


async def _get(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(run_guarded, _get_sync, call)


# ---------------------------------------------------------------- 변경 (Agent 도구)


def _question_rule(call: Call) -> playbooks.QuestionRule | None:
    """작업 연결이면 그 작업 플레이북의 사람 질문 규칙 (UX5). 작업 밖 연결은 제한 없음."""
    job_id = call.principal.job
    if job_id is None:
        return None
    job = call.daemon.jobs.get(job_id)
    return None if job is None else playbooks.question_rule(job.playbook)


def _apply_sync(call: Call) -> dict[str, Any]:
    result = ops.apply(
        call.daemon.root,
        {"request_id": call.params["request_id"], "ops": call.params["ops"]},
        actor=actor_of(call),
        check_secrets=checker_of(call),
        questions=_question_rule(call),
    )
    _changed(call, ["knowledge"])
    return result


async def _apply(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(run_guarded, _apply_sync, call)


def _wiki_sync(call: Call) -> dict[str, Any]:
    p = call.params
    base = p.get("base_sha256")
    result = ops.wiki_write(
        call.daemon.root,
        str(p["path"]),
        str(p["text"]),
        None if base is None else str(base),
        actor=actor_of(call),
        check_secrets=checker_of(call),
    )
    _changed(call, [str(result["path"])])
    return result


async def _wiki(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(run_guarded, _wiki_sync, call)


# ---------------------------------------------------------------- 사람 전용


def _secret_exists(root: Any) -> Callable[[str], bool]:
    """credential 미지수 답(UX5): 키가 이 워크스페이스 비밀값으로 있나 (환경 변수 → 자격 증명
    관리자). 값은 읽어 비교하지 않고 있는지만 본다."""

    def exists(key: str) -> bool:
        if os.environ.get(secret_env_name(key)):
            return True
        if sys.platform != "win32":
            return False
        from kookabug_core.win.credentials import CredentialError, CredentialStore

        try:
            wid = workspace_id(Workspace.open(root))
            return wid is not None and key in CredentialStore().keys(wid)
        except CredentialError, WorkspaceError:
            return False

    return exists


def _answer_sync(call: Call) -> dict[str, Any]:
    p = call.params
    result = human.answer_unknown(
        call.daemon.root,
        str(p["id"]),
        int(p["base_rev"]),
        str(p["text"]),
        actor=actor_of(call),
        check_secrets=checker_of(call),
        secret_exists=_secret_exists(call.daemon.root),
    )
    _changed(call, [human.UNKNOWNS])
    return result


async def _answer(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(run_guarded, _answer_sync, call)


def _block(key: str) -> Callable[[Call], Any]:
    async def handler(call: Call) -> dict[str, Any]:
        sha = await asyncio.to_thread(
            run_guarded,
            human.set_config_block,
            call.daemon.root,
            key,
            call.params["value"],
            base_sha256=str(call.params["base_sha256"]),
        )
        return {"sha256": sha}

    return handler


def _check_sync(call: Call) -> dict[str, Any]:
    return {"sources": sources.check_sources(Workspace.open(call.daemon.root))}


async def _check(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(run_guarded, _check_sync, call)


METHODS: Final[dict[str, MethodSpec]] = {
    "knowledge.search": MethodSpec(_search),
    "knowledge.get": MethodSpec(_get),
    "knowledge.apply": MethodSpec(_apply),
    "wiki.write": MethodSpec(_wiki),
    "unknowns.answer": MethodSpec(_answer),
    "project.automation.set": MethodSpec(_block("automation")),
    "project.sources.set": MethodSpec(_block("sources")),
    "sources.check": MethodSpec(_check),
}
