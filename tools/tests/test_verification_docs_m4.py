"""M4 사람 확인 문서 (M4 계획 T13): 절차서·결과 양식의 항목이 서로 맞고, 절차서가 가리키는 검사·
파일이 있고, 비교 화면 명령이 CI·도구와 같다."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
VERIFY_DIR: Final = REPO_ROOT / "Docs" / "verification"
MANUAL: Final = VERIFY_DIR / "m4-manual.md"
RESULT: Final = VERIFY_DIR / "m4-result-template.md"
COMPARE: Final = REPO_ROOT / "tools" / "design-ref" / "compare.mjs"
CI: Final = REPO_ROOT / ".github" / "workflows" / "ci.yml"
ACCEPTANCE: Final = REPO_ROOT / "python" / "kookabug_core" / "tests" / "acceptance" / "test_m4.py"

M4_SCREENS: Final = [
    "target-ext",
    "recorder",
    "recorder-idle",
    "recorder-paused",
    "recorder-stopped",
    "recorder-error",
]
"""M4 비교 화면 (M4 계획 2.14, `compare.mjs` SCREENS 순서)."""
SECTION_IDS: Final = [*(f"D{i}" for i in range(1, 4)), *(f"H{i}" for i in range(1, 7))]
U_IDS: Final = [f"U{i}" for i in range(1, 17)]
LIVE_TESTS: Final = [
    "test_recorded_login_live_replays_pass",
    "test_pre_click_frame_live",
    "test_live_kookabug_sendinput_not_recorded",
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


def test_compare_set_same_in_manual_ci_and_tool() -> None:
    text = COMPARE.read_text(encoding="utf-8")
    body = text[text.index("export const SCREENS = {") : text.index("};", text.index("SCREENS"))]
    ids = re.findall(r'^\s{2}"?([a-z-]+)"?:', body, re.MULTILINE)
    assert [i for i in ids if i in M4_SCREENS] == M4_SCREENS
    command = f"node tools/design-ref/compare.mjs {' '.join(M4_SCREENS)}"
    assert command in manual()
    assert command in CI.read_text(encoding="utf-8")
    # 녹화 화면 넷은 다크만(시안에 없는 상태), recorder·target-ext는 다크·라이트
    assert "마지막 줄 `8`" in manual()


def test_live_acceptance_and_referenced_files_exist() -> None:
    text = manual()
    source = ACCEPTANCE.read_text(encoding="utf-8")
    for name in LIVE_TESTS:
        assert f"def {name}(" in source, name
        assert name in text, name
    paths = set(re.findall(r"\b((?:python|fixtures|tools|Docs)/[\w./-]+\.(?:py|md))", text))
    assert len(paths) >= 5, paths
    for rel in paths:
        assert (REPO_ROOT / rel).is_file(), rel


def test_raw_search_targets_recording_data_only() -> None:
    """원문 검색은 커밋 직후 녹화 데이터만, 재생 `runs/`는 D3로 대상이 아니라고 적는다."""
    text = manual()
    h1 = text[text.index("### H1") : text.index("### H2")]
    assert "sample-pass-01" in h1 and "runs/" in h1 and "D3" in h1
    assert "cache\\recorder" in h1 and "\\targets" in h1 and "\\tests" in h1
