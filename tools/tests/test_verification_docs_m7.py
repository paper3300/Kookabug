"""M7 사람 확인 문서 (M7 계획 B6·8장): 절차서·결과 양식의 항목이 서로 맞고, 절차서가 가리키는 검사·
파일·스모크 단계가 있다."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
VERIFY_DIR: Final = REPO_ROOT / "Docs" / "verification"
MANUAL: Final = VERIFY_DIR / "m7-manual.md"
RESULT: Final = VERIFY_DIR / "m7-result-template.md"
ACCEPTANCE: Final = REPO_ROOT / "python" / "kookabug_core" / "tests" / "acceptance" / "test_m7.py"
E2E: Final = REPO_ROOT / "apps" / "desktop" / "e2e" / "acceptance.m7.spec.ts"
SMOKE: Final = REPO_ROOT / "tools" / "installer" / "smoke.py"
PLAN_DIR: Final = REPO_ROOT / ".orchestration" / "M7"

SECTION_IDS: Final = ["D1", "D2", *(f"H{i}" for i in range(1, 8))]
U_IDS: Final = [f"U{i}" for i in range(1, 15)]
ACCEPTANCE_TESTS: Final = [
    "test_agent_explores_sample_game_into_explored",
    "test_reexplore_marks_known_and_merges",
    "test_screen_map_from_explored_and_runs",
    "test_promote_moves_into_screens_atomically",
    "test_explore_click_permissions",
    "test_explore_conflicts_with_run_and_recording",
    "test_no_secret_through_any_exit",
]
E2E_TESTS: Final = [
    "test_map_shows_cards_edges_sources",
    "test_promote_dialog_moves_card",
    "test_explore_approval_and_status_bar",
]


def manual() -> str:
    return MANUAL.read_text(encoding="utf-8")


def test_sections_and_result_rows_match() -> None:
    text, result = manual(), RESULT.read_text(encoding="utf-8")
    assert re.findall(r"^### ([DH]\d+)\b", text, re.MULTILINE) == SECTION_IDS
    for item in SECTION_IDS:
        assert re.search(rf"^\| {item} \|", result, re.MULTILINE), item
    for item in U_IDS:
        assert re.search(rf"^\| {item} \|", text, re.MULTILINE), item
        assert re.search(rf"^\| {item} \|", result, re.MULTILINE), item
    assert "mvp-human-check" in text and "mvp-human-check.md" in result


def test_acceptance_and_smoke_step_exist() -> None:
    source = ACCEPTANCE.read_text(encoding="utf-8")
    for name in ACCEPTANCE_TESTS:
        assert f"def {name}(" in source, name
    spec = E2E.read_text(encoding="utf-8")
    for title in E2E_TESTS:
        assert f'test("{title}"' in spec, title
    text = manual()
    assert "test_m7.py" in text and "acceptance.m7.spec.ts" in text
    smoke = SMOKE.read_text(encoding="utf-8")
    assert 'report.step("cli.screen"' in smoke
    assert "`cli.screen`" in text and "`cli.screen`" in RESULT.read_text(encoding="utf-8")


def test_known_differences_and_recovery_documented() -> None:
    """앞 묶음 보고의 "설계 한 줄 후보" 중 사람이 알아야 할 것: `screen test` 3 ≠ `run` 3,
    미완성 후보 승격 불가, 제어 실행 이미지 기록 없음, 남은 승격·보호 기록 손상 푸는 법."""
    text = manual()
    for needle in (
        "판정 불가",
        "skipped",
        "승격할 수 없다",
        "이미지 기록이 없고",
        "kookabug screen recover --show",
        "screens-tx-kept/",
        "promoted",
        "agent-protect.json",
        "protect_state_unknown",
        "screen protect --clear-keys",
        "이 탐색 동안 허용",
    ):
        assert needle in text, needle


def test_referenced_files_exist() -> None:
    text = manual()
    paths = set(
        re.findall(
            r"\b((?:python|fixtures|tools|Docs|examples|apps)/[\w./ -]+?\.(?:py|md|ts|html|mjs))",
            text,
        )
    )
    assert len(paths) >= 4, paths
    for rel in paths:
        assert (REPO_ROOT / rel).is_file(), rel


def test_u_defaults_cover_plan_decisions() -> None:
    """U1~U14는 M7 계획 7장 "사용자 결정 필요" 표와 같은 번호다 (계획이 있으면 대조)."""
    plan = PLAN_DIR / "plan.md"
    if not plan.is_file():  # .orchestration은 레포에 없다 (CI)
        return
    ids = re.findall(
        r"^\| (U\d+)(?: \(rev\d\))? \|", plan.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert ids == U_IDS
