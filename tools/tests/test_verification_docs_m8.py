"""M8 사람 확인 문서 (M8 계획 B8): 절차서·결과 양식의 항목이 서로 맞고, 절차서가 가리키는 검사·
파일·스모크 단계가 있다."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
VERIFY_DIR: Final = REPO_ROOT / "Docs" / "verification"
MANUAL: Final = VERIFY_DIR / "m8-manual.md"
RESULT: Final = VERIFY_DIR / "m8-result-template.md"
ACCEPTANCE: Final = REPO_ROOT / "python" / "kookabug_core" / "tests" / "acceptance" / "test_m8.py"
E2E: Final = REPO_ROOT / "apps" / "desktop" / "e2e" / "acceptance.m8.spec.ts"
SMOKE: Final = REPO_ROOT / "tools" / "installer" / "smoke.py"
COMPARE: Final = REPO_ROOT / "tools" / "design-ref" / "compare.mjs"
PLAN_DIR: Final = REPO_ROOT / ".orchestration" / "M8"

SECTION_IDS: Final = ["D1", "D2", *(f"H{i}" for i in range(1, 8))]
PLAN_U_IDS: Final = [f"U{i}" for i in range(1, 12)]
"""M8 계획 7장 "사용자 결정 필요" 표."""
U_IDS: Final = [*PLAN_U_IDS, *(f"U{i}" for i in range(12, 16))]
"""+ 구현 중 기본값으로 정한 것 (4단계 계정 값·예약 UI·control 상한·시작 화면 단추)."""
ACCEPTANCE_TESTS: Final = [
    "test_scenario_ui_change_auto_adopted",
    "test_scenario_missing_button_not_hidden",
    "test_run_basis_frozen_mid_change",
    "test_agent_cannot_reach_policy_or_playbook",
    "test_qa_runner_only_adopted_cheats",
    "test_forbidden_text_click_refused",
    "test_agent_job_budget_cancel_and_lease",
    "test_agent_job_single_per_workspace",
    "test_init_collects_unknowns",
    "test_no_secret_in_knowledge_outputs",
    "test_schedule_xml_dry_run",
]
E2E_TESTS: Final = [
    "test_report_shows_adoption_and_revert",
    "test_report_regression_and_batch_reject",
    "test_wizard_to_init",
    "test_wizard_required_skip_resume_short",
]
BOUNDARY: Final = (
    "Kookabug는 Kookabug 도구(MCP·KOOKABUG_AGENT CLI·agent-job) 안에서만 막습니다. "
    "Agent CLI가 자기 셸·파일 도구를 쓰면 막을 수 없습니다. "
    "무인 실행은 Agent CLI 자체 권한 설정으로 셸·파일 쓰기를 끄세요."
)


def manual() -> str:
    return MANUAL.read_text(encoding="utf-8")


def test_sections_and_result_rows_match() -> None:
    text, result = manual(), RESULT.read_text(encoding="utf-8")
    assert re.findall(r"^### ([DH]\d+)\b", text, re.MULTILINE) == SECTION_IDS
    for item in SECTION_IDS:
        assert re.search(rf"^\| {item} \|", result, re.MULTILINE), item
    assert re.findall(r"^\| (U\d+) \|", text, re.MULTILINE) == U_IDS
    assert re.findall(r"^\| (U\d+) \|", result, re.MULTILINE) == U_IDS
    assert "mvp-human-check" in text and "mvp-human-check.md" in result


def test_acceptance_smoke_and_compare_exist() -> None:
    source = ACCEPTANCE.read_text(encoding="utf-8")
    for name in ACCEPTANCE_TESTS:
        assert f"def {name}(" in source, name
    spec = E2E.read_text(encoding="utf-8")
    for title in E2E_TESTS:
        assert f'test("{title}"' in spec, title
    text = manual()
    assert "test_m8.py" in text and "acceptance.m8.spec.ts" in text
    assert 'report.step("cli.qa"' in SMOKE.read_text(encoding="utf-8")
    assert "`cli.qa`" in text and "`cli.qa`" in RESULT.read_text(encoding="utf-8")
    compare = COMPARE.read_text(encoding="utf-8")
    line = re.search(r"compare\.mjs ((?:[\w-]+ ?)+)", text)
    assert line is not None
    for key in line.group(1).split():
        assert re.search(rf'^\s*"?{re.escape(key)}"?: \{{', compare, re.MULTILINE), key


def test_user_checks_and_risks_documented() -> None:
    """B8 지시의 사람 확인·사용자 확인·리스크 항목이 절차서에 있다."""
    text = manual()
    assert BOUNDARY in text  # 보안 경계 문구 (계획 3.15: 절차서에도)
    for needle in (
        "탐침 입력은 실행되지만 사건 닫기·채택 근거 불가",  # ⑦
        "agent-job probe",
        "--agent claude",
        "--agent codex",
        "schtasks",
        "--dry-run",
        "짧은 마법사",
        "되돌리기",
        "[수락]",
        "[거절]",
        "계정 값을 받지 않는다",  # U12
        "예약 등록 UI는 M9",  # U13
        "도구 호출 상한이 없다",  # U14
        "시안과 반대",  # U15
        "평문 칸 비밀값",
        "job_active",
        "basis_derived",
        "wiki/index.md",
    ):
        assert needle in text, needle


def test_no_local_paths_or_accounts() -> None:
    """공개 레포: 로컬 절대 경로·사람 이름 폴더·실제 계정이 없다(예제 계정·환경 변수 이름만)."""
    for doc in (MANUAL, RESULT):
        text = doc.read_text(encoding="utf-8")
        assert not re.search(r"\b[A-Za-z]:[\\/](?!\.\.\.)", text), doc.name
        assert not re.search(r"\\Users\\|/Users/|AppData", text), doc.name
        assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), doc.name


def test_referenced_files_exist() -> None:
    text = manual()
    paths = set(
        re.findall(
            r"\b((?:python|fixtures|tools|Docs|examples|apps)/[\w./ -]+?\.(?:py|md|ts|html|mjs))",
            text,
        )
    )
    assert len(paths) >= 5, paths
    for rel in paths:
        assert (REPO_ROOT / rel).is_file(), rel


def test_u_defaults_cover_plan_decisions() -> None:
    """U1~U11은 M8 계획 7장 "사용자 결정 필요" 표와 같은 번호다 (계획이 있으면 대조)."""
    plan = PLAN_DIR / "plan.md"
    if not plan.is_file():  # .orchestration은 레포에 없다 (CI·워크트리)
        return
    ids = re.findall(r"^\| (U\d+) \|", plan.read_text(encoding="utf-8"), re.MULTILINE)
    assert ids == PLAN_U_IDS
