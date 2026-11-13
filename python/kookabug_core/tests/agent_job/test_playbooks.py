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
    for name in ("init", "followup", "entry", "triage", "repair", "explore", "author", "lint"):
        body = every[name].body
        assert "kb_report_note" in body, name  # 요약 글은 이 도구로만
        assert "ask = deny" in body, name
    for name in ("triage", "repair"):
        body = every[name].body
        assert "kb_adopt_request" in body and "kb_case_open" in body, name
        assert "은폐 금지" in body, name  # 버그 은폐 금지 (KB문서 3장 4, 8장)
        assert "resolved" in body and "closed" in body, name  # 사건을 닫지 않는다
    # 작업 허용 범위의 control (9장 R0·R7): 직접 입력은 탐침용 — 닫기·채택 근거가 아님을 적는다
    for name in ("triage", "repair", "explore", "init", "followup", "entry", "author"):
        assert "control" in every[name].tools, name
        body = every[name].body
        assert "탐침용" in body and "채택 근거로 쓸 수 없다" in body, name
        assert "Kookabug가 고른 실행만" in body, name
    for name in ("lint", "probe"):
        assert "control" not in every[name].tools, name  # 양성 대조: 입력이 필요 없는 플레이북
    assert "kb_project_info" in every["probe"].body
    # UX2: 원본은 Kookabug 도구로만 읽는다 (워크스페이스 밖 원본도), 이어 하기는 답 읽기 → 제안
    for name in ("init", "followup"):
        body = every[name].body
        assert "kb_source_list" in body and "kb_source_read" in body, name
    followup = every["followup"]
    assert followup.tools == every["init"].tools
    assert "kb_setting_propose" in followup.body and "answered" in followup.body
    assert "재귀 금지" in followup.body
    # UX5: Init·이어 하기는 시작할 수 있을 만큼만 — 실행·종료 서브그래프, 깊은 기능 지도·로그인 없음
    for name in ("init", "followup"):
        body = every[name].body
        assert "게임 실행" in body and "게임 종료" in body, name
        assert "subgraphs/common/" in body and "kb_run_start" in body, name
        assert "기능 지도" in body and "하지 않는다" in body, name
        # 사람 질문 대신 막힘 보고 (보충 2)
        assert "question_limit" in body and "needs_info" in body, name
        assert "모르는 것" in body and "시도한 것과 결과" in body, name
    init = every["init"].body
    assert "로그인" in init and "다음 단계" in init
    assert "4. 기능 지도" not in init  # 옛 4단계 기능 지도 탐색이 빠졌다
    entry = every["entry"]
    assert entry.tools == every["init"].tools
    assert "게임 접속" in entry.body and "subgraphs/common/game_enter.graph.json" in entry.body
    assert '"credential"' in entry.body and "secret_keys" in entry.body and "$secret" in entry.body
    assert "다음: 기능 테스트 만들기" in entry.body and "이어서 진행" in entry.body
    # 보충 1: 먼저 직접 알아본다 (형식 검사 수준)
    for name in ("init", "followup", "entry"):
        assert "먼저 직접 알아본다" in every[name].body, name
    assert playbooks.versions()["init"] >= 5 and playbooks.versions()["followup"] >= 3
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
