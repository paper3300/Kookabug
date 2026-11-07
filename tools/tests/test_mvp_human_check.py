"""MVP 사람 확인 안내(`Docs/verification/mvp-human-check.md`)가 M1~M7 절차서의 절 ID를 빠짐없이
담는지 본다 (M7 계획 8장). 절차서에 절을 더하거나 빼면 안내의 전수 표·U표도 같이 고쳐야 한다."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
VERIFY_DIR: Final = REPO_ROOT / "Docs" / "verification"
GUIDE: Final = VERIFY_DIR / "mvp-human-check.md"
MILESTONES: Final = range(1, 8)

M7_SECTIONS_FALLBACK: Final = [
    ("D1", "전체 자동 검사"),
    ("D2", "설치본 스모크 (화면 단계)"),
    ("H1", "실제 에이전트 CLI로 예제 게임 탐색"),
    ("H2", "탐색 중 실행·녹화 끼어들기"),
    ("H3", "화면 지도 시안 대비·큰 지도"),
    ("H4", "승격·합치기·버리기와 그래프 출구"),
    ("H5", "비밀값을 넣은 탐색 결과 육안 확인"),
    ("H6", "실제 게임(레포 밖) 탐색"),
    ("H7", "남은 승격·보호 기록 손상 풀기"),
]
"""`m7-manual.md`가 생기기 전 기대값. 파일이 있으면 파일에서 읽는다."""
M7_U_FALLBACK: Final = [f"U{i}" for i in range(1, 15)]
"""M7 계획 7장 U1~U14."""

STATUSES: Final = {"완료", "실행 필요", "조건부", "이번에는 실행 불가"}
STEPS: Final = {str(i) for i in range(1, 6)}
SECTION_RE: Final = re.compile(r"^### ([A-Z]\d+) (.+?)\s*$", re.MULTILINE)
ROW_RE: Final = re.compile(r"^\|\s*(m[1-7]:[A-Z]\d+)\s*\|(.*)\|\s*$", re.MULTILINE)


def manual(n: int) -> str | None:
    path = VERIFY_DIR / f"m{n}-manual.md"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def manual_sections(n: int) -> list[tuple[str, str]]:
    """`### <ID> 제목` 절 (ID 없는 `###` 제목은 뺀다)."""
    text = manual(n)
    if text is None:
        assert n == 7, f"m{n}-manual.md 없음"
        return M7_SECTIONS_FALLBACK
    return SECTION_RE.findall(text)


def manual_u_ids(n: int) -> list[str]:
    """`## … (U)` 절 표의 `| U<n> |` 줄. U절이 없으면(M1) 빈 목록."""
    text = manual(n)
    if text is None:
        assert n == 7, f"m{n}-manual.md 없음"
        return M7_U_FALLBACK
    head = re.search(r"^## .*\(U\)\s*$", text, re.MULTILINE)
    if head is None:
        return []
    end = re.search(r"^## ", text[head.end() :], re.MULTILINE)
    block = text[head.end() : head.end() + end.start() if end else len(text)]
    return re.findall(r"^\|\s*(U\d+)\s*\|", block, re.MULTILINE)


def guide_chapter(title: str) -> str:
    """`## <title>`로 시작하는 장 본문 (다음 `## ` 전까지)."""
    text = GUIDE.read_text(encoding="utf-8")
    head = re.search(rf"^## {re.escape(title)}.*$", text, re.MULTILINE)
    assert head is not None, title
    end = re.search(r"^## ", text[head.end() :], re.MULTILINE)
    return text[head.end() : head.end() + end.start() if end else len(text)]


def rows(block: str) -> list[tuple[str, list[str]]]:
    return [(rid, [c.strip() for c in rest.split("|")]) for rid, rest in ROW_RE.findall(block)]


def check_ids(found: list[str], expected: list[str]) -> None:
    duplicated = sorted(i for i, c in Counter(found).items() if c > 1)
    missing = [i for i in expected if i not in found]
    unknown = [i for i in found if i not in expected]
    assert not duplicated, f"중복: {duplicated}"
    assert not missing, f"빠짐: {missing}"
    assert not unknown, f"절차서에 없는 ID: {unknown}"


def test_mvp_human_check_covers_all_ids() -> None:
    expected = {f"m{n}:{sid}": title for n in MILESTONES for sid, title in manual_sections(n)}
    table = rows(guide_chapter("3. 절 ID 전수 표"))
    check_ids([rid for rid, _ in table], list(expected))
    steps = guide_chapter("2. 단계별 할 일")
    step_text = {s: steps[steps.index(f"### {s}.") :] for s in STEPS}
    for rid, cells in table:
        assert len(cells) == 4, (rid, cells)
        title, status, evidence, step = cells
        assert title == expected[rid], (rid, title, expected[rid])
        assert status in STATUSES, (rid, status)
        if status == "완료":
            assert evidence not in {"", "—"} and step == "—", (rid, evidence, step)
        elif status == "이번에는 실행 불가":
            assert evidence not in {"", "—"}, rid
        else:
            # 실행 필요·조건부는 단계 번호가 있고 그 단계 본문에 이름이 나온다
            assert step in STEPS, (rid, step)
            if status == "조건부":
                assert evidence not in {"", "—"}, rid
            nxt = str(int(step) + 1)
            body = step_text[step]
            body = body[: body.index(f"### {nxt}.")] if f"### {nxt}." in body else body
            assert f"`{rid}`" in body, f"{rid}가 {step}단계 본문에 없음"


def test_u_table_covers_all_u_ids() -> None:
    expected = [f"m{n}:{uid}" for n in MILESTONES for uid in manual_u_ids(n)]
    assert expected, "U표가 하나도 없음"
    table = rows(guide_chapter("4. 사용자 결정(U) 한 표"))
    check_ids([rid for rid, _ in table], expected)
