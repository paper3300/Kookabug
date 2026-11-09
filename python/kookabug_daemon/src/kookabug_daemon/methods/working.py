"""작업 기준 (M8 계획 3.6·3.8·E3·E4·9장 R4): `working.list/accept/reject`와 그래프·target 쓰기 분기.

- `working.*`는 사람 전용(`ui_only` + `AGENT_DENIED`). 수락은 파일 변경·작업 주장을 한 거래로 팀에
  반영하고(전부 또는 없음), 거절은 덧씌움에서 뺀다. 화면 지도 후보는 다루지 않는다(D6)
- **쓰기 분기** `working_actor`: 작업 토큰이 붙은 Agent 연결(프리셋 무관)과 `curator`·`qa_runner`
  프리셋의 Agent는 `graph.create/patch`·`target.save`가 팀 파일 대신 작업 기준(`basis.write`)으로
  간다. 그 연결은 `graph.save`(문서 표 저장)를 쓰지 못한다(팀 파일 쓰기 경로가 없게). 그 밖 프리셋·
  사람은 지금처럼 팀 파일에 쓴다
- Agent 연결은 `knowledge/`·`wiki/` 아래 그래프·target을 직접 쓰지 못한다(작업 사본·지식 우회 차단)
"""

from __future__ import annotations

import asyncio
import posixpath
from typing import Any, Final

from kookabug_core import adopt as rules
from kookabug_core import basis, forbidden
from kookabug_core.knowledge import store
from kookabug_core.knowledge.formats import Actor
from kookabug_core.permissions import effective_preset
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods.adopt import actor_of, guarded
from kookabug_daemon.protocol import RequestFailed

__all__ = ["METHODS", "refuse_policy_path", "working_actor"]

_POLICY_ROOTS: Final = ("knowledge", "wiki")


def working_actor(call: Call) -> Actor | None:
    """이 연결의 그래프·target 쓰기가 작업 기준으로 가면 그 주체, 아니면 None (E3·R4)."""
    p = call.principal
    if p.kind != "agent":
        return None
    preset = effective_preset(call.daemon.service.policy())
    if not basis.writes_working(p.kind, p.job, preset):
        return None
    return actor_of(call)


def refuse_policy_path(call: Call, *rels: str) -> None:
    """Agent 연결은 `knowledge/`·`wiki/` 아래와 금지 동작이 가리키는 target·화면 파일(M8 3.7 —
    `forbidden.protected_paths`)을 그래프·target 도구로 쓰지 못한다. 금지 목록을 읽을 수 없으면
    쓰지 않는다(fail closed)."""
    if call.principal.kind != "agent":
        return
    root = call.daemon.root
    # 적힌 철자(`.`·`..`·빈 조각·대소문자를 푼 것)와 실제 경로(링크·정션을 푼 것)를 모두 본다 —
    # 별칭으로 쓰는 경로·별칭으로 적힌 금지 경로 어느 쪽도 비교에서 빠지지 않게 (`real_key`)
    keys = [rules.path_key(posixpath.normpath(rel.replace("\\", "/"))) for rel in rels]
    try:
        real = [forbidden.real_key(root, rel) for rel in rels]
    except forbidden.UnresolvablePath as exc:
        raise RequestFailed(
            "policy_path", "실제 경로로 풀 수 없거나 워크스페이스 밖이라 Agent가 쓰지 않는다"
        ) from exc
    for key in (*keys, *real):
        if key.split("/", 1)[0] in _POLICY_ROOTS:
            raise RequestFailed(
                "policy_path", "그래프·target 도구로 knowledge/·wiki/ 아래를 쓰지 않는다"
            )
    try:
        protected = forbidden.protected_paths(root, forbidden.load_items(root))
    except forbidden.ForbiddenConfigError as exc:
        # 목록 형식 오류·보호 경로를 실제 경로로 풀 수 없음 → 쓰기 전부 거부 (fail closed)
        raise RequestFailed(
            "policy_path", "금지 동작 목록을 확인하지 못해 Agent의 target·그래프 쓰기를 하지 않는다"
        ) from exc
    if any(key in protected for key in real):
        raise RequestFailed(
            "policy_path", "금지 동작이 가리키는 target·화면 파일은 Agent가 고치지 않는다"
        )


def _list_sync(call: Call) -> dict[str, Any]:
    root = call.daemon.root
    changes: list[dict[str, Any]] = []
    for change in basis.load_changes(root):
        item = dict(change.doc)
        item["effective_state"] = basis.effective_state(root, change)
        changes.append(item)
    claims: list[dict[str, Any]] = []
    for feature in _working_features(root):
        over = store.load_working_claims(root, feature).doc
        for entry in over["claims"]:
            claims.append(
                {
                    "feature": feature,
                    "id": entry["claim"]["id"],
                    "rev": entry["claim"]["rev"],
                    "base_rev": entry["base_rev"],
                    "ops": entry["ops"],
                    "by": entry.get("by") or {},
                }
            )
    return {"changes": changes, "claims": claims}


def _working_features(root: Any) -> list[str]:
    folder = root / "knowledge" / "working" / "claims"
    if not folder.is_dir() or folder.is_symlink() or folder.is_junction():
        return []
    return sorted(p.stem for p in folder.glob("*.json") if p.is_file() and not p.is_symlink())


async def _list(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(guarded, _list_sync, call)


def _decide(call: Call, *, accept: bool) -> dict[str, Any]:
    p = call.params
    return rules.decide(
        call.daemon.root,
        changes=[str(c) for c in p.get("changes") or []],
        claims=[dict(c) for c in p.get("claims") or []],
        accept=accept,
        by=call.principal.id,
    )


async def _accept(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(guarded, _decide, call, accept=True)


async def _reject(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(guarded, _decide, call, accept=False)


METHODS: Final[dict[str, MethodSpec]] = {
    "working.list": MethodSpec(_list),
    "working.accept": MethodSpec(_accept),
    "working.reject": MethodSpec(_reject),
}
