"""작업·보고함 메서드 (M8 계획 3.9·3.11·3.13, 9장 R7·R8).

- `job.begin`·`job.end`·`job.finish`·`job.heartbeat`·`jobs.list`·`reports.*`·`report.decide`는 사람
  전용(`ui_only` + `AGENT_DENIED`): Agent 연결은 작업을 만들거나 끝내거나 보고를 결정하지 못한다
  (재귀 금지, E11). `agent-job` CLI가 `ui` 연결로 부른다
- `job.begin`을 부른 연결이 **소유 연결**이다(R8). 사람 입력 임대권·녹화 중이면 토큰 없이
  `prep_failed`로 끝내고 보고 하나를 남긴다
- `job.end`·`job.finish`와 감독(소유 연결 유실·heartbeat 유실·기한)은 같은 종료 경로
  (`JobSupervisor.end`)를 지난다: 토큰 폐기 → 실행·채택 검증 취소 → 감독자 입력 복구 완료 → 보고
- `job.note`(`kb_report_note`)는 작업 토큰 연결 전용(`job_only`). 글자 검사를 지난 글만 둔다
- `project.qa_info`(`kb_project_info`): 플레이북 판·원본 상태·자동화 정책·치트 설정·경고
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

from kookabug_core import adopt as rules
from kookabug_core import playbooks
from kookabug_core.agent_job import activity, jobdir
from kookabug_core.agent_job import report as reports
from kookabug_core.knowledge.formats import KnowledgeError
from kookabug_core.knowledge.sources import check_sources, source_path, sources_of
from kookabug_core.workspace import Workspace
from kookabug_daemon.jobs import DEFAULT_TTL_S
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods.adopt import checker_of, guarded
from kookabug_daemon.methods.proposals import apply_setting
from kookabug_daemon.protocol import RequestFailed

__all__ = ["METHODS"]

_END_STATES: Final = {
    "cancelled": "cancelled",
    "timeout": "budget_exhausted",
    "budget_exhausted": "budget_exhausted",
    "done": "done",
    "failed": "failed",
    "interrupted": "interrupted",
}


async def _begin(call: Call) -> dict[str, Any]:
    p = call.params
    daemon = call.daemon
    budget = {str(k): int(v) for k, v in dict(p.get("budget") or {}).items()}
    toolsets = p.get("toolsets")
    ttl = float(p.get("ttl_s", DEFAULT_TTL_S))
    if "minutes" in budget:
        # 토큰은 시간 예산보다 오래 산다 (기한은 감독이 따로 본다)
        ttl = max(ttl, budget["minutes"] * 60 + 600.0)
    job, token = daemon.jobs.begin(
        str(p["playbook"]),
        basis=None if p.get("basis") is None else str(p["basis"]),
        trigger=str(p.get("trigger", "manual")),
        budget=budget,
        toolsets=None if toolsets is None else [str(t) for t in toolsets],
        ttl_s=ttl,
        owner=call.connection,
        profile=None if p.get("agent") is None else str(p["agent"]),
    )
    busy = await asyncio.to_thread(daemon.input_busy)
    if busy is not None:
        # 준비 실패 (R8·3.9): 토큰을 쓰지 않고 같은 종료 경로로 끝낸다 (보고 하나)
        ended = await asyncio.to_thread(daemon.job_supervisor.end, job.id, "prep_failed", prep=busy)
        return {"job": job.id, "state": "prep_failed", "reason": busy, "report": ended["report"]}
    daemon.job_changed(job)
    return {
        "job": job.id,
        "agent_id": job.agent,
        "token": token,
        "expires_at": job.expires_at,
        "started_at": job.started_at,
        "state": "running",
    }


def _job_or_missing(call: Call, job_id: str) -> None:
    if call.daemon.jobs.get(job_id) is None:
        raise RequestFailed(
            "not_found", "모르는 작업이다 (이 daemon이 만든 작업이 아니다)", path=job_id
        )


async def _end(call: Call) -> dict[str, Any]:
    job_id = str(call.params["job"])
    _job_or_missing(call, job_id)
    state = _END_STATES[str(call.params["reason"])]
    return await asyncio.to_thread(call.daemon.job_supervisor.end, job_id, state)


async def _finish(call: Call) -> dict[str, Any]:
    job_id = str(call.params["job"])
    _job_or_missing(call, job_id)
    state = str(call.params.get("state") or "done")
    prep = call.params.get("prep_reason")
    return await asyncio.to_thread(
        call.daemon.job_supervisor.end,
        job_id,
        state,
        prep=None if prep is None else str(prep),
    )


async def _heartbeat(call: Call) -> dict[str, Any]:
    job = call.daemon.jobs.heartbeat(str(call.params["job"]), call.connection)
    return {"job": job.id, "state": "running"}


def _note_sync(call: Call) -> dict[str, Any]:
    job = call.principal.job
    if job is None:
        raise RequestFailed("job_only", "보고 메모는 작업 토큰 연결만 쓴다")
    text = str(call.params["text"])
    try:
        checker_of(call)([("text", text)])
    except KnowledgeError as exc:
        raise RequestFailed(exc.code, exc.message) from exc
    return {"job": job, "bytes": call.daemon.jobs.note(job, text)}


async def _note(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_note_sync, call)


def _list_sync(call: Call) -> dict[str, Any]:
    jobs = call.daemon.jobs
    live = {j.id: jobs.describe(j) for j in jobs.all()}
    out: dict[str, dict[str, Any]] = {}
    for doc in jobdir.list_jobs(call.daemon.root):
        out[str(doc["id"])] = {
            "job": doc.get("id"),
            "playbook": doc.get("playbook"),
            "trigger": doc.get("trigger"),
            "basis": doc.get("basis"),
            "agent": (doc.get("agent") or {}).get("profile"),
            "started_at": doc.get("started_at"),
            "state": doc.get("state"),
            "budget": doc.get("budget"),
            "used": doc.get("used"),
            "report": doc.get("report"),
        }
    for job_id, described in live.items():
        out[job_id] = {**out.get(job_id, {}), **described}
    return {"jobs": [out[k] for k in sorted(out, reverse=True)]}


async def _list(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_list_sync, call)


def _activity_sync(call: Call) -> dict[str, Any]:
    """진행 중 작업의 활동 목록·agent.log 꼬리 (UX1 U3, 사람 전용 읽기). 작업 ID는 스키마 형식 +
    이 워크스페이스의 작업(살아 있거나 `job.json`이 있는 것)만. 경로는 `jobdir.job_path` 경계."""
    job_id = str(call.params["job"])
    root = call.daemon.root
    live = call.daemon.jobs.get(job_id)
    doc = jobdir.read_job(root, job_id)
    if live is None and doc is None:
        raise RequestFailed("not_found", "모르는 작업이다", path=job_id)
    head: dict[str, Any] = {
        "state": None if doc is None else doc.get("state"),
        "started_at": None if doc is None else doc.get("started_at"),
        "used": None if doc is None else doc.get("used"),
    }
    if live is not None:
        described = call.daemon.jobs.describe(live)
        head = {k: described.get(k, head[k]) for k in head}
    after = int(call.params.get("after") or 0)
    used = head["used"]
    return {
        "job": job_id,
        "state": str(head["state"] or "-"),
        "started_at": None if head["started_at"] is None else str(head["started_at"]),
        "used": used
        if isinstance(used, dict) and {"minutes", "runs", "tool_calls"} <= used.keys()
        else None,
        "entries": activity.read(root, job_id, after),
        "log_tail": activity.log_tail(root, job_id),
    }


async def _activity(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(guarded, _activity_sync, call)


async def _reports_list(call: Call) -> dict[str, Any]:
    found = await asyncio.to_thread(guarded, reports.list_reports, call.daemon.root)
    return {"reports": found}


async def _reports_get(call: Call) -> dict[str, Any]:
    job = str(call.params["job"])
    found = await asyncio.to_thread(guarded, reports.read_report, call.daemon.root, job)
    if found is None:
        raise RequestFailed("not_found", "그 작업의 보고가 없다", path=job)
    await asyncio.to_thread(_attach_local, call.daemon.root, job, found)
    return {"report": found}


def _attach_local(root: Any, job: str, report: dict[str, Any]) -> None:
    """설정 제안 항목에 이 PC `proposals.json`의 값·현재 값을 붙인다 (UX2 검수 1 H1 — 팀 보고
    파일에는 없다). 이 PC에 그 제안이 없으면 `local: null`(화면은 값을 못 보이고 수락을 끈다)."""
    from kookabug_core.knowledge import setting_change

    for group in report.get("groups") or []:
        for item in group.get("items") or []:
            setting = item.get("setting") if item.get("kind") == "setting_change" else None
            if isinstance(setting, dict):
                try:
                    setting["local"] = setting_change.local_view(root, job, str(setting.get("id")))
                except Exception:
                    setting["local"] = None


def _decide_sync(call: Call) -> dict[str, Any]:
    p = call.params
    root = call.daemon.root
    by = call.principal.id
    job, group, decision = str(p["job"]), str(p["group"]), str(p["decision"])
    if reports.setting_of(reports.read_report(root, job), group) is not None:
        # 설정 바꾸기 제안 (UX2 C): 마법사 그 단계와 같은 검사·저장으로 적용한 뒤 결정을 남긴다
        return reports.decide_setting(
            root,
            job,
            group,
            decision,
            apply=lambda setting: apply_setting(call.daemon, job, setting),
            by=by,
        )

    def apply(changes: list[str], accept: bool, also: Any) -> Any:
        # 보고 결정·렌더는 같은 거래 안 (`also`) — 팀 변경과 따로 반영되지 않는다
        return rules.decide(root, changes=changes, claims=[], accept=accept, by=by, also=also)

    return reports.decide(root, str(p["job"]), str(p["group"]), str(p["decision"]), apply=apply)


async def _decide(call: Call) -> dict[str, Any]:
    done = await asyncio.to_thread(guarded, _decide_sync, call)
    call.daemon.post(lambda: call.daemon.notify_ui("reports.changed", {}))
    return done


def _source_location(workspace: Workspace, state: dict[str, Any]) -> dict[str, Any]:
    """원본 상태 한 줄에 종류·이름·위치를 더한다 (UX1 U4): 같은 종류 원본이 여럿이어도
    (`design_doc`·`design_doc_2`) Agent가 모두 찾아 읽게. 위치는 URL 또는 이 PC 경로(팀 상대 경로는
    워크스페이스 기준)."""
    found = next((s for s in sources_of(workspace) if s.get("id") == state.get("id")), None)
    if found is None:
        return {}
    extra: dict[str, Any] = {"kind": found.get("kind"), "title": found.get("title")}
    path = source_path(workspace, found)
    if path is not None:
        extra["path"] = str(path)
    elif isinstance(found.get("url"), str):
        extra["url"] = found["url"]
    return extra


def _qa_info_sync(call: Call) -> dict[str, Any]:
    workspace = Workspace.open(call.daemon.root)
    sources = [{**s, **_source_location(workspace, s)} for s in check_sources(workspace)]
    automation = workspace.automation()
    warnings: list[str] = []
    if not automation.get("forbidden"):
        warnings.append("forbidden_empty")
    warnings += [f"source_{s['state']}:{s['id']}" for s in sources if s["state"] != "ok"]
    job_id = call.principal.job
    job = None if job_id is None else call.daemon.jobs.get(job_id)
    return {
        "playbooks": playbooks.versions(),
        "sources": sources,
        "automation": automation,
        "cheats": workspace.cheats_policy(),
        "warnings": warnings,
        "job": None if job is None else call.daemon.jobs.describe(job),
    }


async def _qa_info(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(guarded, _qa_info_sync, call)


METHODS: Final[dict[str, MethodSpec]] = {
    "job.begin": MethodSpec(_begin),
    "job.end": MethodSpec(_end),
    "job.finish": MethodSpec(_finish),
    "job.heartbeat": MethodSpec(_heartbeat),
    "job.note": MethodSpec(_note),
    "jobs.list": MethodSpec(_list),
    "jobs.activity": MethodSpec(_activity),
    "reports.list": MethodSpec(_reports_list),
    "reports.get": MethodSpec(_reports_get),
    "report.decide": MethodSpec(_decide),
    "project.qa_info": MethodSpec(_qa_info),
}
