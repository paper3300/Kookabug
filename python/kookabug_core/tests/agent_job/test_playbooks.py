"""플레이북 배포 (M8 계획 3.10) — 설치본 패키지 데이터, 필수 규칙 문장 몇 개만 검사."""

from __future__ import annotations

from pathlib import Path

import pytest

from kb_testing import packaging as pk
from kookabug_core import playbooks


def test_playbooks_mention_required_rules() -> None:
    assert set(playbooks.versions()) == set(playbooks.NAMES)
    every = {name: playbooks.load(name) for name in playbooks.NAMES}
    for name, book in every.items():
        assert book.version >= 1 and "core" in book.tools, name
    for name in ("init", "followup", "triage", "repair", "explore", "author", "lint"):
        body = every[name].body
        assert "kb_report_note" in body, name  # 요약 글은 이 도구로만
        assert "ask = deny" in body, name
    for name in ("triage", "repair"):
        body = every[name].body
        assert "kb_adopt_request" in body and "kb_case_open" in body, name
        assert "은폐 금지" in body, name  # 버그 은폐 금지 (KB문서 3장 4, 8장)
        assert "resolved" in body and "closed" in body, name  # 사건을 닫지 않는다
    # 작업 허용 범위의 control (9장 R0·R7): 직접 입력은 탐침용 — 닫기·채택 근거가 아님을 적는다
    for name in ("triage", "repair", "explore", "init", "followup", "author"):
        assert "control" in every[name].tools, name
        body = every[name].body
        assert "탐침용" in body and "채택 근거로 쓸 수 없다" in body, name
        assert "Kookabug가 고른 실행만" in body, name
    for name in ("lint", "probe"):
        assert "control" not in every[name].tools, name  # 양성 대조: 입력이 필요 없는 플레이북
    init = every["init"].body
    assert "확인된 향후 일정 없음" in init and "QA 계획" in init  # 9장 로드맵
    assert "human_only" in init and "미지수" in init
    assert "kb_project_info" in every["probe"].body
    # UX2: 원본은 Kookabug 도구로만 읽는다 (워크스페이스 밖 원본도), 이어 하기는 답 읽기 → 제안
    for name in ("init", "followup"):
        body = every[name].body
        assert "kb_source_list" in body and "kb_source_read" in body, name
    followup = every["followup"]
    assert followup.tools == every["init"].tools
    assert "kb_setting_propose" in followup.body and "answered" in followup.body
    assert "다시 만들지 않는다" in followup.body  # 이미 답한 것은 다시 묻지 않는다
    assert "QA 계획" in followup.body and "재귀 금지" in followup.body
    # 허용 목록 밖 이름 (경로 조각으로 다른 파일을 읽지 못한다)
    for bad in ("../README", "init.md", "wiki", ""):
        with pytest.raises(playbooks.PlaybookError):
            playbooks.load(bad)


@pytest.mark.packaging
def test_packaged_in_install(tmp_path: Path) -> None:
    core = pk.build_dists(pk.REPO_ROOT / "python" / "kookabug_core", tmp_path / "dist-core")
    files = core.wheel_files()
    for name in playbooks.NAMES:
        assert f"kookabug_core/playbooks/{name}.md" in files
    assert "kookabug_core/playbooks/__init__.py" in files
