"""위키 렌더 (M8 계획 3.1·E8): `wiki/index.md`·`wiki/log.md`·`wiki/features/<기능>.md` 주장 표·보고.

모두 결정적이다(같은 입력 → 같은 바이트, 지금 시각을 쓰지 않음). 지식 파일은 쓰기 전에 글자 검사를
통과했고 감사 이력에는 값 대신 필드 이름만 있으므로 렌더에 비밀값이 새로 들어가지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

__all__ = [
    "CLAIMS_BEGIN",
    "CLAIMS_END",
    "render_claims_table",
    "render_feature_page",
    "render_index",
    "render_log",
    "render_report",
]

CLAIMS_BEGIN: Final = "<!-- kookabug:claims:begin -->"
CLAIMS_END: Final = "<!-- kookabug:claims:end -->"
INDEX_HEAD: Final = "# 위키 목차\n\n> Kookabug가 만든다. 고쳐도 다음 지식 변경 때 다시 쓴다.\n"


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = (
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    )
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _basis(basis: Iterable[Mapping[str, Any]]) -> str:
    out: list[str] = []
    for b in basis:
        mark = "" if b.get("verified", True) else " (확인 안 됨)"
        out.append(f"{b.get('type')}:{b.get('ref')}{mark}")
    return ", ".join(out)


def render_claims_table(doc: Mapping[str, Any]) -> str:
    """주장 파일 → 표 (ID 순). 위키 기능 페이지 표시 사이에 들어간다."""
    lines = [
        f"주장 파일 revision {doc.get('revision', 0)} "
        f"(`knowledge/features/{doc.get('feature')}.json`)",
        "",
        "| 주장 | rev | 종류 | 상태 | 명제 | 값 | 근거 |",
        "|---|---|---|---|---|---|---|",
    ]
    claims = sorted(doc.get("claims", []), key=lambda c: str(c.get("id")))
    for c in claims:
        value = c.get("value")
        if "unit" in c and value is not None:
            value = f"{_cell(value)} {c['unit']}"
        lines.append(
            "| "
            + " | ".join(
                _cell(v)
                for v in (
                    c.get("id"),
                    c.get("rev"),
                    c.get("kind"),
                    c.get("status"),
                    c.get("statement"),
                    value,
                    _basis(c.get("basis", [])),
                )
            )
            + " |"
        )
    if not claims:
        lines.append("| (없음) | | | | | | |")
    return "\n".join(lines)


def render_feature_page(existing: str | None, doc: Mapping[str, Any]) -> str:
    """기능 페이지: Agent가 쓴 글은 그대로 두고 표시 사이만 주장 표로 다시 쓴다."""
    block = f"{CLAIMS_BEGIN}\n{render_claims_table(doc)}\n{CLAIMS_END}"
    if existing is None:
        return f"# {doc.get('feature')}\n\n{block}\n"
    begin = existing.find(CLAIMS_BEGIN)
    end = existing.find(CLAIMS_END, begin + len(CLAIMS_BEGIN)) if begin >= 0 else -1
    if begin >= 0 and end >= 0:
        return existing[:begin] + block + existing[end + len(CLAIMS_END) :]
    sep = "" if existing.endswith("\n") or not existing else "\n"
    return f"{existing}{sep}\n{block}\n"


def render_index(
    pages: Sequence[str], features: Mapping[str, Mapping[str, Any]], reports: Sequence[str]
) -> str:
    """목차. `pages`는 `wiki/` 기준 페이지 경로(색인·일지·보고 제외), `features`는 기능 → 주장
    파일, `reports`는 `wiki/reports/` 안 파일 이름."""
    lines = [INDEX_HEAD, "## 기능", ""]
    if features:
        for name in sorted(features):
            doc = features[name]
            claims = doc.get("claims", [])
            counts: dict[str, int] = {}
            for c in claims:
                counts[str(c.get("status"))] = counts.get(str(c.get("status")), 0) + 1
            summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "주장 없음"
            lines.append(f"- [{name}](features/{name}.md) — 주장 {len(claims)}개 ({summary})")
    else:
        lines.append("- (아직 없음)")
    lines += ["", "## 페이지", ""]
    others = sorted(
        p for p in pages if not (p.startswith("features/") and p[len("features/") : -3] in features)
    )
    lines += [f"- [{p}]({p})" for p in others] or ["- (아직 없음)"]
    lines += ["", "## 작업 보고", ""]
    lines += [f"- [{r}](reports/{r})" for r in sorted(reports, reverse=True)] or ["- (아직 없음)"]
    lines += ["", "변경 일지: [log.md](log.md)", ""]
    return "\n".join(lines)


def render_log(entries: Iterable[Mapping[str, Any]]) -> str:
    """감사 이력 → 사람이 읽는 일지 (새것 먼저). 값은 없고 바뀐 필드 이름만."""
    lines = ["# 지식 변경 일지", "", "> `knowledge/log.jsonl`에서 Kookabug가 만든다.", ""]
    rows = sorted(entries, key=lambda e: int(e.get("seq", 0)), reverse=True)
    if not rows:
        lines.append("- (아직 없음)")
    for e in rows:
        agent = e.get("agent") or {}
        who = agent.get("kind", "?")
        if agent.get("id"):
            who += f" {agent['id']}"
        target = e.get("file", "")
        if e.get("id"):
            target += f" · {e['id']}"
        rev = ""
        if e.get("new_rev") is not None:
            rev = f" rev {e.get('base_rev')}→{e.get('new_rev')}"
        fields = f" ({', '.join(e['fields'])})" if e.get("fields") else ""
        result = e.get("result", "")
        code = f" `{e['code']}`" if e.get("code") else ""
        job = f" · 작업 {e['job']}" if e.get("job") else ""
        lines.append(
            f"- #{e.get('seq')} {e.get('at')} **{e.get('op')}** {_cell(target)}{rev}{fields}"
            f" — {result}{code} · {_cell(who)}{job}"
        )
    return "\n".join(lines) + "\n"


_ITEM_TITLES: Final = {
    "auto_adopted": "자동 채택됨 (되돌리기 가능)",
    "working_only": "작업 기준에만 반영 (수락·거절)",
    "regression_suspect": "회귀 의심",
    "undetermined": "판단 못 함 — 필요한 추가 정보",
    "cheat_candidate": "치트 후보",
    "init_summary": "Init 요약",
    "budget": "예산",
    "stalled": "진행 막힘",
    "prep_failed": "준비 실패",
}


def render_report(report: Mapping[str, Any], claims: Mapping[str, int] | None = None) -> str:
    """보고(`kookabug.report/0`) → 마크다운. 그 시점 revision으로 고정한다: 항목의 주장 rev와
    채택 ID를 그대로 쓰고, `claims`(주장 ID → 렌더 시점 rev)를 주면 함께 적는다. 생성·묶음은 B5."""
    lines = [
        f"# 작업 보고 {report.get('job')}",
        "",
        f"- 플레이북 `{report.get('playbook')}` · 트리거 {report.get('trigger')} · "
        f"Agent {_cell(report.get('agent'))} · 상태 **{report.get('state')}**",
        f"- 시작 {report.get('started_at')} · 끝 {report.get('ended_at') or '-'}",
    ]
    budget = report.get("budget") or {}
    if budget:
        parts = [f"{k} {v[0]}/{v[1]}" for k, v in sorted(budget.items())]
        lines.append(f"- 예산 {', '.join(parts)}")
    lines.append("")
    for group in report.get("groups", []):
        lines += [f"## {_cell(group.get('title'))}", "", f"원인: {group.get('cause')}", ""]
        for item in group.get("items", []):
            kind = str(item.get("kind"))
            refs = [
                f"{k} {item[k]}"
                for k in ("case", "adoption", "change", "evidence", "cheat")
                if item.get(k)
            ]
            line = f"- {_ITEM_TITLES.get(kind, kind)}"
            if refs:
                line += " — " + ", ".join(refs)
            if item.get("checks"):
                line += f" · 확인 {', '.join(item['checks'])}"
            lines.append(line)
            for c in item.get("claims", []):
                lines.append(f"  - 주장 {c.get('id')} rev {c.get('rev')}")
            if item.get("detail"):
                lines.append(f"  - {_cell(item['detail'])}")
        decision = group.get("decision")
        if decision:
            lines.append(f"- 결정: {decision.get('decision')} ({decision.get('at')})")
        lines.append("")
    if report.get("unknowns"):
        lines += ["## 사람만 답할 수 있는 질문", ""]
        lines += [f"- {u}" for u in report["unknowns"]]
        lines.append("")
    if claims:
        lines += ["## 렌더 시점 주장 revision", ""]
        lines += [f"- {k} rev {v}" for k, v in sorted(claims.items())]
        lines.append("")
    if report.get("notes"):
        lines += ["## Agent 요약", "", str(report["notes"]), ""]
    return "\n".join(lines)
