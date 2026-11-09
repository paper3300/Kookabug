"""사건 메서드 (M8 계획 3.2 사건·3.13, B4) — 엄격: Agent 권한·원래 실패 보존.

Agent 도구 (툴셋 `cases`): `cases.list`·`cases.get`·`cases.signals`(조회), `cases.open`·
`cases.update`(변경). 사람 전용: `cases.close`.

- `cases.open{run}`: 실패 실행의 시그니처(`case_facts.run_facts`)로 같은 열린 사건을 찾고, 없으면
  원래 실패 증거를 **Kookabug가 먼저 고정**(`pin_of` — `evidence.pin`과 같은 길)한 뒤 사건을 만든다.
  `original{run, evidence, graph_sha, claims, basis}`·`symptom.test`가 채워져 자동 채택(3.8)이 그
  사건을 쓸 수 있다
- `cases.update`: 허용 목록 키만. `resolved`·`closed`는 `case_resolution_reserved`
- `cases.signals{id}`: 판단 재료만 모은다 — `run.diff`(에이전트 가림 그대로), 실패 프레임 화면 식별
  (보호면 `unknown` + 사유), 이 사건의 변경 없는 재실행 수·결과, 연결 원본 해시 변화, 관련 주장
  `kind/status`. 원인을 판정하지 않는다(`cause`·`verdict` 키 없음). 비교할 수 없는 것은
  `not_comparable[]`
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Mapping
from typing import Any, Final, cast

from kookabug_core.cases import close_case, get_case, list_cases, open_case, update_case
from kookabug_core.knowledge import sources, store
from kookabug_core.knowledge.formats import KnowledgeError
from kookabug_core.workspace import Workspace
from kookabug_daemon.case_facts import run_facts
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods.adopt import actor_of, checker_of, pin_of
from kookabug_daemon.methods.knowledge import run_guarded
from kookabug_daemon.protocol import RequestFailed

__all__ = ["METHODS"]

ORIGINAL_NOTE: Final = "원래 실패 (사건 열기 때 Kookabug가 고정)"


def _changed(call: Call, case_id: str) -> None:
    notify = getattr(call.daemon, "knowledge_changed", None)
    if notify is not None:
        notify([f"knowledge/cases/{case_id}.json"])


# ---------------------------------------------------------------- 조회


async def _list(call: Call) -> dict[str, Any]:
    state = call.params.get("state")
    found = await asyncio.to_thread(
        run_guarded, list_cases, call.daemon.root, None if state is None else str(state)
    )
    return {"cases": found}


async def _get(call: Call) -> dict[str, Any]:
    doc, sha = await asyncio.to_thread(
        run_guarded, get_case, call.daemon.root, str(call.params["id"])
    )
    return {"case": doc, "sha256": sha}


# ---------------------------------------------------------------- 열기·고치기·닫기


def _open_sync(call: Call) -> dict[str, Any]:
    p = call.params
    run_id = str(p["run"])
    where = call.daemon.run_manager.locate(run_id)
    if where.state != "ended":
        raise RequestFailed(
            "run_active", "끝나지 않은 실행으로는 사건을 열지 않는다", run_id=run_id
        )
    root = call.daemon.root
    facts = run_facts(root, where.run_id, where.folder)
    if facts.verdict not in ("fail", "error"):
        raise KnowledgeError("format", "사건은 실패·오류로 끝난 실행으로만 연다")
    title = p.get("title")
    signature = facts.signature()
    existing = [c for c in list_cases(root) if c["signature"] == signature]
    evidence: str | None = None
    if not any(c["state"] in ("open", "needs_info", "watching") for c in existing):
        # 새 사건이 될 것: 원래 실패 증거를 먼저 고정한다 (지우는 도구 없음 — 동시에 같은 사건이
        # 열려 붙게 되면 이 묶음은 쓰이지 않고 남는다)
        evidence = str(pin_of(call, where.run_id, None, ORIGINAL_NOTE)["id"])
    result = open_case(
        root,
        facts,
        title=None if title is None else str(title),
        evidence=evidence,
        actor=actor_of(call),
        check_secrets=checker_of(call),
    )
    _changed(call, str(result["case"]))
    return result


async def _open(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(run_guarded, _open_sync, call)


def _update_sync(call: Call) -> dict[str, Any]:
    p = call.params
    result = update_case(
        call.daemon.root,
        str(p["id"]),
        int(p["base_revision"]),
        cast(Mapping[str, Any], p["changes"]),
        actor=actor_of(call),
        check_secrets=checker_of(call),
    )
    _changed(call, str(p["id"]))
    return result


async def _update(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(run_guarded, _update_sync, call)


def _close_sync(call: Call) -> dict[str, Any]:
    p = call.params
    note = p.get("note")
    result = close_case(
        call.daemon.root,
        str(p["id"]),
        int(p["base_revision"]),
        state=str(p.get("state", "closed")),
        note=None if note is None else str(note),
        actor=actor_of(call),
        check_secrets=checker_of(call),
    )
    _changed(call, str(p["id"]))
    return result


async def _close(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(run_guarded, _close_sync, call)


# ---------------------------------------------------------------- 신호


def _diff(call: Call, run_id: str, missing: list[dict[str, Any]]) -> dict[str, Any] | None:
    from kookabug_daemon.methods.run_agent import _diff as run_diff  # pyright: ignore[reportPrivateUsage]

    try:
        return run_diff(dataclasses.replace(call, params={"run_id": run_id}))
    except RequestFailed as exc:
        missing.append({"what": "diff", "reason": exc.code})
        return None


def _screen(call: Call, run_id: str, missing: list[dict[str, Any]]) -> dict[str, Any]:
    """실패 프레임 화면 식별 (보호·분류 거부면 unknown + 사유, 글자 없음)."""
    from kookabug_daemon.agent_view import AgentRun
    from kookabug_daemon.methods.run_agent import artifact_frame
    from kookabug_daemon.screen_save import identify

    where = call.daemon.run_manager.locate(run_id)
    view = AgentRun.load(where.run_id, where.folder)
    step = view.run_info().get("failure_step")
    facts = view.steps.get(step) if isinstance(step, str) else None
    pngs = [] if facts is None else [f for f in facts.files if f.casefold().endswith(".png")]
    if not pngs:
        missing.append({"what": "screen", "reason": "no_failure_frame"})
        return {"state": "unknown", "reason": "no_failure_frame", "matches": []}
    try:
        frame = artifact_frame(call, where.run_id, pngs[0])
    except RequestFailed as exc:
        return {"state": "unknown", "reason": exc.code, "matches": []}
    guard = call.daemon.guard.effective(frame)
    if not guard.clear:
        return {"state": "unknown", "reason": str(guard.reason or "frame_protected"), "matches": []}
    try:
        found = identify(call.daemon, frame, None)
    except Exception:
        missing.append({"what": "screen", "reason": "identify_failed"})
        return {"state": "unknown", "reason": "identify_failed", "matches": []}
    matches = [
        {"id": m.get("id") or m.get("key"), "state": m.get("state")} for m in found["matches"]
    ]
    return {"state": "identified" if matches else "unmatched", "matches": matches}


def _reruns(call: Call, doc: Mapping[str, Any]) -> dict[str, Any]:
    original = cast(Mapping[str, Any], doc["original"])
    base_sha = original.get("graph_sha")
    unchanged: list[dict[str, Any]] = []
    changed = 0
    for entry in cast(list[Any], doc.get("runs") or []):
        run_id = str(cast(Mapping[str, Any], entry)["run"])
        try:
            where = call.daemon.run_manager.locate(run_id)
            facts = run_facts(call.daemon.root, where.run_id, where.folder)
        except Exception:
            continue
        if facts.graph_sha == base_sha:
            unchanged.append({"run": run_id, "result": facts.verdict, "code": facts.code})
        else:
            changed += 1
    return {"unchanged": len(unchanged), "results": unchanged, "changed_graph": changed}


def _claims(root: Any, doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    original = cast(Mapping[str, Any], doc["original"])
    refs = [cast(Mapping[str, Any], c) for c in cast(list[Any], original.get("claims") or [])]
    links = cast(Mapping[str, Any], doc.get("links") or {})
    refs += [cast(Mapping[str, Any], c) for c in cast(list[Any], links.get("claims") or [])]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        claim_id = str(ref.get("id"))
        if claim_id in seen:
            continue
        seen.add(claim_id)
        feature = claim_id.split(".", 1)[0]
        try:
            items = store.load(root, f"knowledge/features/{feature}.json", "claims", feature).doc
        except Exception:
            out.append({"id": claim_id, "found": False})
            continue
        item = next(
            (
                cast(Mapping[str, Any], c)
                for c in cast(list[Any], items.get("claims") or [])
                if isinstance(c, Mapping) and c.get("id") == claim_id
            ),
            None,
        )
        if item is None:
            out.append({"id": claim_id, "found": False})
            continue
        out.append(
            {
                "id": claim_id,
                "found": True,
                "rev": item.get("rev"),
                "case_rev": ref.get("rev"),
                "kind": item.get("kind"),
                "status": item.get("status"),
                "basis": [
                    {
                        "type": b.get("type"),
                        "ref": b.get("ref"),
                        "seen_at": b.get("seen_at"),
                        "hash": b.get("hash"),
                    }
                    for b in cast(list[Any], item.get("basis") or [])
                    if isinstance(b, Mapping)
                ],
            }
        )
    return out


def _sources(root: Any, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """주장 원본 근거의 해시가 지금 원본 상태와 다른가 (`basis.seen_at` 이후 변화)."""
    try:
        cache = {str(s.get("id")): s for s in sources.read_cache(Workspace.open(root))}
    except Exception:
        cache = {}
    out: list[dict[str, Any]] = []
    for claim in claims:
        for basis in claim.get("basis") or []:
            ref = str(basis.get("ref") or "")
            if basis.get("type") != "source" or not ref.startswith("sources:"):
                continue
            source_id = ref.removeprefix("sources:").split("#", 1)[0]
            now = cache.get(source_id)
            out.append(
                {
                    "claim": claim["id"],
                    "source": source_id,
                    "seen_at": basis.get("seen_at"),
                    "state": None if now is None else now.get("state"),
                    "changed": None
                    if now is None or now.get("hash") is None or basis.get("hash") is None
                    else now.get("hash") != basis.get("hash"),
                }
            )
    return out


def _signals_sync(call: Call) -> dict[str, Any]:
    root = call.daemon.root
    doc, _ = get_case(root, str(call.params["id"]))
    run_id = str(cast(Mapping[str, Any], doc["original"])["run"])
    missing: list[dict[str, Any]] = []
    try:
        call.daemon.run_manager.locate(run_id)
        diff = _diff(call, run_id, missing)
        screen = _screen(call, run_id, missing)
    except RequestFailed as exc:
        # 원래 실행 기록이 지워졌다: 증거 묶음만 남는다 (근거는 unverifiable)
        missing.append({"what": "original_run", "reason": exc.code})
        diff, screen = None, {"state": "unknown", "reason": exc.code, "matches": []}
    claims = _claims(root, doc)
    found = _sources(root, claims)
    if not found:
        missing.append({"what": "sources", "reason": "no_source_basis"})
    return {
        "case": doc["id"],
        "diff": diff,
        "screen": screen,
        "reruns": _reruns(call, doc),
        "sources": found,
        "claims": claims,
        "not_comparable": missing,
    }


async def _signals(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(run_guarded, _signals_sync, call)


METHODS: Final[dict[str, MethodSpec]] = {
    "cases.list": MethodSpec(_list),
    "cases.get": MethodSpec(_get),
    "cases.signals": MethodSpec(_signals),
    "cases.open": MethodSpec(_open),
    "cases.update": MethodSpec(_update),
    "cases.close": MethodSpec(_close),
}
