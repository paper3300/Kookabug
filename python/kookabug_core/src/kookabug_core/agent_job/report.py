"""작업 보고 (M8 계획 3.11·3.12, KB문서 12장).

- **항목은 Kookabug가 작업의 구조화 기록에서 만든다**: 감사 이력(`knowledge/log.jsonl`)의
  `job` 줄(사건 열기·붙이기·고치기, 자동 채택, 지식 연산), 작업 기준 변경(`created.job`), 치트
  후보(`origin.job`). Agent 글은 `notes` 하나(`kb_report_note`, 글자 검사)뿐이다
- 항목 종류는 허용 목록(`ITEM_KINDS`)뿐이다
- 묶음 키(결정적) = (항목 종류, 사건의 `supported` 가설 중 첫째 또는 `undetermined`, 주 대상:
  target 경로 → 주장 `subject` → 테스트 경로). 키가 같으면 같은 묶음 — 종류가 키에 들어가므로 다른
  종류가 합쳐지지 않는다
- 렌더(`wiki/reports/<YYYY-MM-DD>-<작업>.md`)는 생성 시점 revision(`revisions.claims`)으로 고정한다.
  결정(`report.decide`) 뒤 다시 렌더해도 그 값이 그대로다
- 보고 파일은 작업마다 하나. 끝난 상태로 이미 쓴 보고는 덮지 않는다(종료 경로가 여러 번 와도 하나 —
  멱등)
- 확장 지점: 진입점 그룹 `kookabug.report_exporters`(`export(report: dict) -> None`) 이름만 둔다
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

from kookabug_core import filetx
from kookabug_core.knowledge import render, store
from kookabug_core.knowledge.formats import Actor, KnowledgeError, now, shape_problem

__all__ = [
    "EXPORTERS_GROUP",
    "ITEM_KINDS",
    "REPORTS_DIR",
    "SUMMARY_PLAYBOOKS",
    "build",
    "decide",
    "decide_setting",
    "group_key",
    "list_reports",
    "read_report",
    "rendered_rel",
    "report_rel",
    "setting_of",
    "write",
]

EXPORTERS_GROUP: Final = "kookabug.report_exporters"
"""보고 내보내기 확장 지점 (진입점 그룹 이름만, 구현·UI 없음 — Jira 등은 나중 플러그인)."""
REPORTS_DIR: Final = "knowledge/reports"
ITEM_KINDS: Final = (
    "auto_adopted",
    "working_only",
    "regression_suspect",
    "undetermined",
    "cheat_candidate",
    "init_summary",
    "budget",
    "stalled",
    "prep_failed",
    "setting_change",
)
"""보고 항목 종류 (허용 목록 — 여기 밖 종류는 만들지 않는다)."""
SUMMARY_PLAYBOOKS: Final = frozenset({"init", "followup"})
"""Init 요약 항목을 다는 플레이북 (UX2 D: 이어 하기도 같은 요약)."""
SETUP_PLAYBOOKS: Final = frozenset({"init", "followup", "entry"})
"""사람 질문 대신 막힘 보고(사건 needs_info)로 끝내는 준비 플레이북 (UX5)."""
BLOCKED_TITLE: Final = "막힘"
OPEN_STATES: Final = frozenset({"open", "needs_info", "watching"})
_TITLES: Final = {
    "auto_adopted": "자동 수리",
    "working_only": "작업 기준 변경 (수락·거절)",
    "regression_suspect": "회귀 의심",
    "undetermined": "판단 불가",
    "cheat_candidate": "치트 후보",
    "init_summary": "Init 요약",
    "budget": "예산 소진",
    "stalled": "진행 막힘",
    "prep_failed": "준비 실패",
    "setting_change": "설정 바꾸기 제안",
}


def report_rel(job: str) -> str:
    return f"{REPORTS_DIR}/{job}.json"


def rendered_rel(job: str, started_at: str) -> str:
    return f"wiki/reports/{started_at[:10]}-{job}.md"


def read_report(root: Path, job: str) -> dict[str, Any] | None:
    data = filetx.read(root, report_rel(job))
    if data is None:
        return None
    try:
        doc = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def list_reports(root: Path) -> list[dict[str, Any]]:
    """보고 요약 (최근 시작 먼저)."""
    try:
        base = filetx.plain(root, REPORTS_DIR)
    except filetx.TxError:
        return []
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in base.glob("j-*.json"):
        if path.is_symlink():
            continue
        doc = read_report(root, path.stem)
        if doc is None:
            continue
        out.append(
            {
                "job": doc.get("job"),
                "playbook": doc.get("playbook"),
                "trigger": doc.get("trigger"),
                "state": doc.get("state"),
                "started_at": doc.get("started_at"),
                "ended_at": doc.get("ended_at"),
                "groups": len(doc.get("groups") or []),
                "undecided": sum(
                    1
                    for g in doc.get("groups") or []
                    if g.get("decision") is None
                    and any(
                        i.get("kind") in ("working_only", "setting_change")
                        for i in g.get("items") or []
                    )
                ),
                "rendered": doc.get("rendered"),
            }
        )
    return sorted(out, key=lambda r: (str(r["started_at"]), str(r["job"])), reverse=True)


# ---------------------------------------------------------------- 기록 읽기


def _job_lines(root: Path, job: str) -> list[dict[str, Any]]:
    return [
        line
        for line in store.log_lines(root)
        if line.get("job") == job and line.get("result") == "applied"
    ]


def _json(root: Path, rel: str) -> dict[str, Any] | None:
    try:
        data = filetx.read(root, rel)
    except filetx.TxError:
        return None
    if data is None:
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        return None
    return value if isinstance(value, dict) else None


def _supported_cause(case: Mapping[str, Any] | None) -> str:
    for hypothesis in (case or {}).get("hypotheses") or []:
        if isinstance(hypothesis, dict) and hypothesis.get("state") == "supported":
            return str(hypothesis.get("cause") or "undetermined")
    return "undetermined"


def _claim_subject(root: Path, claim_id: str) -> str | None:
    feature = claim_id.split(".", 1)[0]
    doc = _json(root, f"knowledge/features/{feature}.json") or {}
    for item in doc.get("claims") or []:
        if isinstance(item, dict) and item.get("id") == claim_id:
            subject = item.get("subject")
            return str(subject) if subject else None
    return None


def _main_target(
    root: Path,
    *,
    files: Iterable[str] = (),
    claims: Iterable[str] = (),
    test: str | None = None,
) -> str:
    """주 대상: target 경로 → 주장 `subject` → 테스트 경로 (없으면 `-`)."""
    paths = sorted(files)
    targets = [p for p in paths if p.casefold().endswith(".target.json")]
    if targets:
        return targets[0]
    for claim in sorted(claims):
        subject = _claim_subject(root, claim)
        if subject:
            return subject
    graphs = [p for p in paths if p.casefold().endswith(".graph.json")]
    if test:
        return test
    return graphs[0] if graphs else "-"


def group_key(kind: str, cause: str, main: str) -> str:
    return f"{kind}|{cause}|{main}"


def _changes(root: Path, job: str) -> list[dict[str, Any]]:
    from kookabug_core import basis

    out: list[dict[str, Any]] = []
    for change in basis.load_changes(root):
        if change.job == job:
            out.append({**change.doc, "state": basis.effective_state(root, change)})
    return out


def _cheat_candidates(root: Path, job: str) -> list[str]:
    doc = _json(root, "knowledge/cheats.json") or {}
    out: list[str] = []
    for item in doc.get("cheats") or []:
        if not isinstance(item, dict):
            continue
        origin = item.get("origin") or {}
        if origin.get("job") == job and item.get("adoption") is None:
            out.append(str(item["id"]))
    return sorted(out)


def _unknowns(root: Path, ids: Iterable[str]) -> list[dict[str, Any]]:
    wanted = set(ids)
    doc = _json(root, "knowledge/unknowns.json") or {}
    return [
        u
        for u in doc.get("unknowns") or []
        if isinstance(u, dict) and u.get("id") in wanted and u.get("state") == "open"
    ]


def _claim_revs(root: Path, ids: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for claim_id in sorted(set(ids)):
        feature = claim_id.split(".", 1)[0]
        doc = _json(root, f"knowledge/features/{feature}.json") or {}
        for item in doc.get("claims") or []:
            if isinstance(item, dict) and item.get("id") == claim_id and "rev" in item:
                out[claim_id] = int(item["rev"])
    return out


def _init_summary(root: Path, lines: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    features: set[str] = set()
    added: list[tuple[str, str]] = []
    unknowns = 0
    cheats = 0
    for line in lines:
        file = str(line.get("file") or "")
        if file.startswith("features/") and line.get("op") == "add":
            features.add(file.split("/", 1)[1])
            added.append((file.split("/", 1)[1], str(line.get("id"))))
        elif file == "unknowns" and line.get("op") == "add":
            unknowns += 1
        elif file == "cheats" and line.get("op") == "add":
            cheats += 1
    guesses = 0
    for feature, claim_id in added:
        doc = _json(root, f"knowledge/features/{feature}.json") or {}
        for item in doc.get("claims") or []:
            if (
                isinstance(item, dict)
                and item.get("id") == claim_id
                and item.get("kind") == "guess"
            ):
                guesses += 1
    screens = 0
    explored = root / "screens" / "_explored"
    if explored.is_dir() and not explored.is_symlink() and not explored.is_junction():
        screens = sum(1 for _ in explored.rglob("*.screen.json"))
    return {
        "features": len(features),
        "claims": len(added),
        "guesses": guesses,
        "unknowns": unknowns,
        "cheat_candidates": cheats,
        "screens": screens,
    }


# ---------------------------------------------------------------- 만들기


def build(
    root: Path,
    job: Mapping[str, Any],
    *,
    state: str,
    used: Mapping[str, int],
    notes: str | None,
    stalled: Sequence[str] = (),
    prep: str | None = None,
    ended_at: str | None = None,
    check_secrets: Callable[[Sequence[tuple[str, str]]], None] | None = None,
) -> dict[str, Any]:
    """`job`(`job.json` 값: id·playbook·trigger·agent·started_at·budget)과 기록으로 보고를 만든다.
    쓰지 않는다 (`write`). `check_secrets`는 설정 제안 이유의 쓰기 직전 재검사 (없으면 이유를
    보고에 싣지 않는다)."""
    job_id = str(job["id"])
    lines = _job_lines(root, job_id)
    items: list[tuple[str, str, str, dict[str, Any]]] = []
    case_ids: list[str] = []
    for line in lines:
        if str(line.get("op", "")).startswith("case_") and line.get("id"):
            case_ids.append(str(line["id"]))
    case_ids = sorted(set(case_ids))
    cases = {cid: _json(root, f"knowledge/cases/{cid}.json") for cid in case_ids}
    claim_ids: list[str] = []

    # 자동 채택 (이 작업이 낸 채택 요청의 게시 — 감사 이력 op adopt, job)
    adopted_changes: set[str] = set()
    for line in lines:
        if line.get("op") != "adopt" or not str(line.get("id", "")).startswith("a-"):
            continue
        record = _json(root, f"knowledge/adoptions/{line['id']}.json")
        if record is None:
            continue
        adopted_changes.add(str(record.get("change")))
        case = _json(root, f"knowledge/cases/{record.get('case')}.json")
        runs = list(record.get("runs") or [])
        checks = ["oracle", f"negative:{len(record.get('negatives') or [])}"]
        checks.append(f"affected:{max(0, len(runs) - 1)}")
        files = [str(f.get("path")) for f in record.get("files") or []]
        cause = _supported_cause(case)
        item = {
            "kind": "auto_adopted",
            "case": record.get("case"),
            "adoption": record.get("id"),
            "change": record.get("change"),
            "checks": checks,
        }
        items.append(("auto_adopted", cause, _main_target(root, files=files), item))

    # 작업 기준에만 있는 변경 (묶음 수락·거절)
    for change in _changes(root, job_id):
        if change["id"] in adopted_changes or change["state"] not in ("active", "stale"):
            continue
        case = (
            _json(root, f"knowledge/cases/{change.get('case')}.json")
            if change.get("case")
            else None
        )
        files = [str(f.get("path")) for f in change.get("files") or []]
        item = {"kind": "working_only", "change": change["id"]}
        if change.get("case"):
            item["case"] = change["case"]
        if change["state"] == "stale":
            item["detail"] = "팀 기준이 바뀌어 다시 확인이 필요하다 (stale)"
        items.append(
            ("working_only", _supported_cause(case), _main_target(root, files=files), item)
        )

    # 사건: 회귀 의심 / 판단 불가
    unknown_ids: list[str] = []
    for line in lines:
        if line.get("file") == "unknowns" and line.get("op") == "add" and line.get("id"):
            unknown_ids.append(str(line["id"]))
    questions = [u for u in _unknowns(root, unknown_ids) if u.get("human_only")]
    blocked: set[str] = set()
    for cid in case_ids:
        case = cases[cid]
        if case is None or case.get("state") not in OPEN_STATES:
            continue
        original = case.get("original") or {}
        symptom = case.get("symptom") or {}
        claims = [dict(c) for c in original.get("claims") or [] if isinstance(c, dict)]
        claim_ids += [str(c.get("id")) for c in claims]
        main = _main_target(
            root,
            claims=[str(c.get("id")) for c in claims],
            test=symptom.get("test"),
        )
        regression = any(
            h.get("cause") == "product_regression" and h.get("state") == "supported"
            for h in case.get("hypotheses") or []
            if isinstance(h, dict)
        )
        item: dict[str, Any]
        if regression:
            item = {"kind": "regression_suspect", "case": cid}
            if original.get("evidence"):
                item["evidence"] = original["evidence"]
            if claims:
                item["claims"] = [{"id": c["id"], "rev": c["rev"]} for c in claims if "rev" in c]
            item["detail"] = (
                f"재현: {symptom.get('test') or '-'} 의 노드 {symptom.get('node') or '-'} "
                f"({symptom.get('code') or symptom.get('kind') or '-'}), 원래 실행 "
                f"{original.get('run') or '-'}"
            )
            items.append(("regression_suspect", "product_regression", main, item))
        else:
            item = {"kind": "undetermined", "case": cid}
            needs = case.get("needs") or []
            if needs:
                item["detail"] = f"필요한 추가 정보 {len(needs)}개"
            if job.get("playbook") in SETUP_PLAYBOOKS and case.get("state") == "needs_info":
                # UX5: Init·이어 하기·접속 경로의 막힘 보고 — 시도한 것과 결과(사건 needs, 글자
                # 검사를 이미 지난 글)를 그대로 보인다. 사람이 설정을 고친 뒤 "이어서 진행"
                tried = next((str(n.get("unknown")) for n in needs if isinstance(n, dict)), "")
                item["detail"] = f"막힘: {tried}"[:2000] if tried else "막힘"
                blocked.add(group_key("undetermined", _supported_cause(case)[:150], main[:400]))
            linked = [str(u["id"]) for u in questions]
            if linked:
                item["unknowns"] = linked
            items.append(("undetermined", _supported_cause(case), main, item))

    for cheat in _cheat_candidates(root, job_id):
        items.append(
            ("cheat_candidate", "undetermined", cheat, {"kind": "cheat_candidate", "cheat": cheat})
        )

    # 설정 바꾸기 제안 (UX2 C): 제안마다 묶음 하나 (수락·거절을 따로). 팀 보고에는 제안 ID·키·
    # 이유·근거 질문만 — 값·현재 값은 이 PC `proposals.json`에만 둔다 (검수 1 H1). 이유는 쓰기
    # 직전 다시 글자 검사하고, 못 하거나 걸리면 자리 글로 바꾼다
    from kookabug_core.knowledge import setting_change

    for proposal in setting_change.load_proposals(root, job_id):
        if not setting_change.PROPOSAL_ID.fullmatch(str(proposal.get("id"))):
            continue
        if str(proposal.get("key")) not in setting_change.KEYS:
            continue
        reason = str(proposal.get("reason") or "")
        try:
            if check_secrets is None or not reason:
                raise KnowledgeError("secret_unchecked", "검사기 없음")
            check_secrets([("reason", reason)])
        except Exception:
            reason = setting_change.REASON_HIDDEN
        setting = {"id": str(proposal["id"]), "key": str(proposal["key"]), "reason": reason[:2000]}
        item = {"kind": "setting_change", "setting": setting}
        if proposal.get("unknowns"):
            item["unknowns"] = [str(u) for u in proposal["unknowns"]]
        items.append(("setting_change", str(proposal.get("key")), str(proposal["id"]), item))

    if job.get("playbook") in SUMMARY_PLAYBOOKS:
        summary = _init_summary(root, lines)
        items.append(
            ("init_summary", "undetermined", "-", {"kind": "init_summary", "summary": summary})
        )
    if state == "budget_exhausted":
        budget = cast(Mapping[str, Any], job.get("budget") or {})
        detail = (
            f"예산을 다 썼다: 실행 {used.get('runs', 0)}/{budget.get('runs', '-')}, "
            f"시간 {used.get('minutes', 0)}/{budget.get('minutes', '-')}분"
        )
        items.append(("budget", "undetermined", "-", {"kind": "budget", "detail": detail}))
    for test in sorted(set(stalled)):
        detail = f"{test}이(가) 바뀌지 않은 채 같은 실패를 되풀이해 더 돌리지 않았다"
        items.append(("stalled", "undetermined", test, {"kind": "stalled", "detail": detail}))
    if state == "prep_failed":
        detail = f"작업을 준비하지 못했다 ({prep or '이유 없음'})"
        items.append(
            ("prep_failed", "undetermined", "-", {"kind": "prep_failed", "detail": detail})
        )

    groups: dict[str, dict[str, Any]] = {}
    for kind, cause, main, item in items:
        assert kind in ITEM_KINDS
        key = group_key(kind, cause[:150], main[:400])
        # 설정 제안은 묶음 키에 제안 ID, 제목에는 키 이름
        shown = cause if kind == "setting_change" else main
        title = BLOCKED_TITLE if key in blocked else _TITLES[kind]
        group = groups.setdefault(
            key,
            {
                "key": key,
                "cause": cause[:200],
                "title": (title + ("" if shown == "-" else f" · {shown}"))[:200],
                "items": [],
                "decision": None,
            },
        )
        group["items"].append(item)
    for group in groups.values():
        group["items"].sort(key=lambda i: json.dumps(i, sort_keys=True, ensure_ascii=False))
        for item in group["items"]:
            for c in item.get("claims") or []:
                claim_ids.append(str(c["id"]))
    budget = cast(Mapping[str, Any], job.get("budget") or {})
    report: dict[str, Any] = {
        "format": "kookabug.report/0",
        "job": job_id,
        "playbook": str(job.get("playbook")),
        "trigger": str(job.get("trigger") or "manual"),
        "agent": cast(Mapping[str, Any], job.get("agent") or {}).get("profile"),
        "started_at": str(job.get("started_at") or now()),
        "ended_at": None if state == "running" else (ended_at or now()),
        "state": state,
        "budget": {
            k: [int(used.get(k, 0)), int(budget[k])] for k in ("minutes", "runs") if k in budget
        },
        "groups": [groups[k] for k in sorted(groups)],
        "unknowns": sorted(str(u["id"]) for u in questions),
        "notes": notes or None,
        "revisions": {"claims": _claim_revs(root, claim_ids)},
        "rendered": None,
    }
    report["rendered"] = rendered_rel(job_id, report["started_at"])
    return report


# ---------------------------------------------------------------- 쓰기


def _encode(doc: Mapping[str, Any]) -> bytes:
    problem = shape_problem(dict(doc), "report")
    if problem is not None:
        raise KnowledgeError("format", f"보고 형식이 틀렸다 ({problem})")
    return store.encode(doc)


def _render(report: Mapping[str, Any]) -> bytes:
    pinned = cast(Mapping[str, int], (report.get("revisions") or {}).get("claims") or {})
    return render.render_report(report, dict(pinned)).encode("utf-8")


def _put(tx: filetx.Tx, root: Path, report: Mapping[str, Any]) -> None:
    from kookabug_core.knowledge.ops import index_bytes

    rel = report_rel(str(report["job"]))
    old = filetx.read(root, rel)
    tx.write(rel, _encode(report), expect_sha=None if old is None else filetx.sha256_of(old))
    md = str(report["rendered"])
    old_md = filetx.read(root, md)
    tx.write(md, _render(report), expect_sha=None if old_md is None else filetx.sha256_of(old_md))
    index, sha = index_bytes(root, extra_reports=[md.rsplit("/", 1)[1]])
    tx.write("wiki/index.md", index, expect_sha=sha)


def write(root: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    """보고를 쓴다 (json + 렌더 + 색인 + 감사 이력, 한 거래). 그 작업의 보고가 이미 끝난 상태로
    있으면 덮지 않고 있는 것을 돌려준다 (종료 경로가 여러 번 와도 보고 하나)."""
    from kookabug_core.knowledge.ops import log_into

    job = str(report["job"])
    with filetx.locked(root):
        store.ensure_layout(root)
        existing = read_report(root, job)
        if existing is not None and existing.get("state") != "running":
            return existing
        tx = filetx.Tx(root)
        _put(tx, root, report)
        entry = {"op": "report", "file": report_rel(job), "id": job, "result": "applied"}
        log_into(root, tx, [entry], Actor("kookabug", "report", job=job))
        tx.commit()
    return dict(report)


def decide(
    root: Path,
    job: str,
    group: str,
    decision: str,
    *,
    apply: Callable[[list[str], bool, Callable[[filetx.Tx], None]], Any],
) -> dict[str, Any]:
    """`report.decide` (사람 전용): 그 묶음의 `working_only` 변경을
    `apply(changes, accept, also)`(= `working.accept/reject`)로 결정한다. 보고의 결정·렌더는
    `also(tx)`로 **그 거래 안에** 넣는다 — 팀 파일·변경 상태·채택 기록·보고 결정이 전부 반영되거나
    전부 안 된다. 결정 재확인(이미 결정함·묶음 바뀜)도 그 거래의 잠금 안에서 한다. 렌더는 생성 시점
    revision 그대로."""
    if decision not in ("accept", "reject"):
        raise KnowledgeError("format", "결정은 accept·reject다")
    changes = _undecided_changes(read_report(root, job), job, group)

    def also(tx: filetx.Tx) -> None:
        # 잠금 안 재확인: 그 사이 다른 결정이 들어왔거나 묶음이 바뀌었으면 아무것도 하지 않는다
        current = read_report(root, job)
        if _undecided_changes(current, job, group) != changes:
            raise KnowledgeError("revision_conflict", "묶음이 그 사이 바뀌었다", id=group)
        assert current is not None
        for g in current.get("groups") or []:
            if g.get("key") == group:
                g["decision"] = {"decision": decision, "by": "human", "at": now()}
        _put(tx, root, current)

    result = apply(changes, decision == "accept", also)
    return {"job": job, "group": group, "decision": decision, "result": result}


def setting_of(report: Mapping[str, Any] | None, group: str) -> dict[str, Any] | None:
    """묶음의 설정 제안 (`setting_change` 항목의 `setting`). 설정 제안 묶음이 아니면 None."""
    found = next((g for g in (report or {}).get("groups") or [] if g.get("key") == group), None)
    if found is None:
        return None
    item = next((i for i in found.get("items") or [] if i.get("kind") == "setting_change"), None)
    setting = None if item is None else item.get("setting")
    return dict(setting) if isinstance(setting, dict) else None


def decide_setting(
    root: Path,
    job: str,
    group: str,
    decision: str,
    *,
    apply: Callable[[Mapping[str, Any]], Any],
    by: str | None = None,
) -> dict[str, Any]:
    """`report.decide`의 설정 제안 묶음 (UX2 C, 사람 전용). 수락이면 `apply(setting)`(마법사 그
    단계와 같은 검사·저장 — daemon이 준다)이 먼저 설정을 쓰고, 그 뒤 보고 결정·렌더·감사 이력을
    한 거래로 남긴다. 거절은 결정·감사 이력만. 이미 결정한 묶음이면 `revision_conflict`."""
    from kookabug_core.knowledge.ops import log_into

    if decision not in ("accept", "reject"):
        raise KnowledgeError("format", "결정은 accept·reject다")
    report = read_report(root, job)
    if report is None:
        raise KnowledgeError("unknown_id", "없는 보고다", id=job)
    found = next((g for g in report.get("groups") or [] if g.get("key") == group), None)
    if found is None:
        raise KnowledgeError("unknown_id", "보고에 없는 묶음이다", id=group)
    if found.get("decision") is not None:
        raise KnowledgeError("revision_conflict", "이미 결정한 묶음이다", id=group)
    setting = setting_of(report, group)
    if setting is None:
        raise KnowledgeError("format", "이 묶음에는 설정 제안이 없다")
    result: Any = None
    if decision == "accept":
        result = apply(setting)
    with filetx.locked(root):
        current = read_report(root, job)
        target = next(
            (g for g in (current or {}).get("groups") or [] if g.get("key") == group), None
        )
        if current is None or target is None or target.get("decision") is not None:
            raise KnowledgeError("revision_conflict", "묶음이 그 사이 바뀌었다", id=group)
        target["decision"] = {"decision": decision, "by": "human", "at": now()}
        tx = filetx.Tx(root)
        _put(tx, root, current)
        entry = {
            "op": "setting_accept" if decision == "accept" else "setting_reject",
            "file": "settings",
            "id": str(setting.get("id")),
            "fields": [str(setting.get("key"))],
            "result": "applied",
        }
        log_into(root, tx, [entry], Actor("human", by, job=job))
        tx.commit()
    return {"job": job, "group": group, "decision": decision, "result": {"applied": result}}


def _undecided_changes(report: Mapping[str, Any] | None, job: str, group: str) -> list[str]:
    """아직 결정하지 않은 묶음의 `working_only` 변경 ID (아니면 KnowledgeError)."""
    if report is None:
        raise KnowledgeError("unknown_id", "없는 보고다", id=job)
    found = next((g for g in report.get("groups") or [] if g.get("key") == group), None)
    if found is None:
        raise KnowledgeError("unknown_id", "보고에 없는 묶음이다", id=group)
    if found.get("decision") is not None:
        raise KnowledgeError("revision_conflict", "이미 결정한 묶음이다", id=group)
    changes = [
        str(i["change"]) for i in found.get("items") or [] if i.get("kind") == "working_only"
    ]
    if not changes:
        raise KnowledgeError("format", "이 묶음에는 수락·거절할 작업 기준 변경이 없다")
    return changes
