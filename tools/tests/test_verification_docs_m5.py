"""M5 사람 확인 문서 (M5 계획 B7 — M6 B7에서 빠진 검사를 더함): 절차서·결과 양식의 항목이 서로
맞고, 절차서가 가리키는 검사·파일·비교 화면이 있다."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
VERIFY_DIR: Final = REPO_ROOT / "Docs" / "verification"
MANUAL: Final = VERIFY_DIR / "m5-manual.md"
RESULT: Final = VERIFY_DIR / "m5-result-template.md"
COMPARE: Final = REPO_ROOT / "tools" / "design-ref" / "compare.mjs"
ACCEPTANCE: Final = REPO_ROOT / "python" / "kookabug_core" / "tests" / "acceptance" / "test_m5.py"

SECTION_IDS: Final = [*(f"D{i}" for i in range(1, 4)), *(f"H{i}" for i in range(1, 8))]
U_IDS: Final = [f"U{i}" for i in range(1, 12)]
M5_SCREENS: Final = [
    "panel-empty",
    "panel-chat",
    "panel-approval",
    "panel-acp-permission",
    "agent-judge",
    "runviewer-analyze",
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


def test_compare_screens_exist_in_tool() -> None:
    text = COMPARE.read_text(encoding="utf-8")
    body = text[text.index("export const SCREENS = {") : text.index("};", text.index("SCREENS"))]
    ids = set(re.findall(r'^\s{2}"?([a-z-]+)"?:', body, re.MULTILINE))
    assert set(M5_SCREENS) <= ids, set(M5_SCREENS) - ids
    assert f"node tools/design-ref/compare.mjs {' '.join(M5_SCREENS)}" in manual()


def test_referenced_tests_and_files_exist() -> None:
    text = manual()
    assert "test_m5.py" in text and ACCEPTANCE.is_file()
    live = REPO_ROOT / "python" / "kookabug_mcp" / "tests" / "test_control_live.py"
    assert "test_control_live.py" in text and live.is_file()
    paths = set(re.findall(r"\b((?:python|fixtures|tools|Docs)/[\w./-]+\.(?:py|md))", text))
    assert len(paths) >= 3, paths
    for rel in paths:
        assert (REPO_ROOT / rel).is_file(), rel
