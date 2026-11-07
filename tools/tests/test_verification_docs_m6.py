"""M6 사람 확인 문서 (M6 계획 B7): 절차서·결과 양식의 항목이 서로 맞고, 절차서가 가리키는 검사·
파일·스모크 단계가 있다."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
VERIFY_DIR: Final = REPO_ROOT / "Docs" / "verification"
MANUAL: Final = VERIFY_DIR / "m6-manual.md"
RESULT: Final = VERIFY_DIR / "m6-result-template.md"
ACCEPTANCE: Final = REPO_ROOT / "python" / "kookabug_core" / "tests" / "acceptance" / "test_m6.py"
E2E: Final = REPO_ROOT / "apps" / "desktop" / "e2e" / "acceptance.m6.spec.ts"
SMOKE: Final = REPO_ROOT / "tools" / "installer" / "smoke.py"
PLAN_DIR: Final = REPO_ROOT / ".orchestration" / "M6"

SECTION_IDS: Final = ["D1", "D2", *(f"H{i}" for i in range(1, 9))]
U_IDS: Final = [f"U{i}" for i in range(1, 15)]
ACCEPTANCE_TESTS: Final = [
    "test_external_repo_plugin_installs_and_runs",
    "test_conflicting_plugins_isolated",
    "test_failed_installs_keep_environment",
    "test_kill_right_after_commit_install_stays_valid",
    "test_runs_survive_concurrent_installs",
    "test_lock_reproduces_on_other_pc",
    "test_sdist_only_refused_before_commit",
    "test_sdk_changed_refused_then_relock",
    "test_agents_cannot_install_or_run_dev_modules",
    "test_preview_runs_no_code_and_hides_credentials",
]
E2E_TESTS: Final = [
    "install sample from git via dialog, run graph with widget-edited node",
    "failed install leaves plugins and graph working",
    "widget sandboxed (module load, no network, no navigation, no other plugin, no secret fields, "
    "readOnly)",
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
    assert "M7 끝에 몰아서" in text and "M7 끝에 몰아서" in result


def test_acceptance_and_smoke_step_exist() -> None:
    source = ACCEPTANCE.read_text(encoding="utf-8")
    for name in ACCEPTANCE_TESTS:
        assert f"def {name}(" in source, name
    spec = E2E.read_text(encoding="utf-8")
    for title in E2E_TESTS:
        assert f'test("{title}"' in spec, title
    text = manual()
    assert "test_m6.py" in text and "acceptance.m6.spec.ts" in text
    # 설치본 스모크 플러그인 단계: 절차서·결과 양식의 단계 이름이 스모크와 같다
    assert 'report.step("cli.plugin"' in SMOKE.read_text(encoding="utf-8")
    assert "`cli.plugin`" in text and "`cli.plugin`" in RESULT.read_text(encoding="utf-8")


def test_h3_records_lock_digests_and_verify_ok() -> None:
    """H3 증거: 두 PC 잠금의 환경별 digest + 양쪽 `verify --json`의 ok (verify 응답에는 digest가
    없다 — B7 검수 M2)."""
    text = manual()
    h3 = text[text.index("### H3") : text.index("### H4")]
    assert "environments" in h3 and ".digest" in h3 and "plugin verify --json" in h3
    assert '"ok": true' in h3 and "h3_digests_" in h3 and "h3_verify_" in h3
    row = next(line for line in RESULT.read_text("utf-8").splitlines() if line.startswith("| H3 |"))
    for pc in ("pc1", "pc2"):
        assert f"h3_digests_{pc}.txt" in row and f"h3_verify_{pc}.json" in row, pc


def test_referenced_files_exist() -> None:
    text = manual()
    paths = set(
        re.findall(r"\b((?:python|fixtures|tools|Docs|examples|apps)/[\w./-]+\.(?:py|md|ts))", text)
    )
    assert len(paths) >= 4, paths
    for rel in paths:
        assert (REPO_ROOT / rel).is_file(), rel
    assert (REPO_ROOT / "examples" / "plugins" / "kookabug-plugin-sample").is_dir()


def test_u_defaults_cover_plan_decisions() -> None:
    """U1~U14는 M6 계획 7장 "사용자 결정 필요"와 같은 번호다 (계획이 있으면 대조)."""
    plan = PLAN_DIR / "plan.md"
    if not plan.is_file():  # .orchestration은 레포에 없다 (CI)
        return
    ids = re.findall(r"^- \*\*(U\d+) ", plan.read_text(encoding="utf-8"), re.MULTILINE)
    assert ids == U_IDS
