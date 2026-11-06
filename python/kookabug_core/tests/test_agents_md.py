"""`AGENTS.md` 관리 구간 (M5 계획 3.12, 워크스페이스 구조 "`AGENTS.md`").

툴이 관리하는 표시 사이만 다시 쓰고 사용자 글은 그대로 둔다. 예제 워크스페이스의 파일은 지금
관리 구간과 같다(다시 써도 바이트가 그대로).
"""

from __future__ import annotations

from pathlib import Path

from kb_testing.packaging import REPO_ROOT
from kookabug_core.permissions import exact_rule, parse_rule
from kookabug_core.workspace import (
    AGENTS_BEGIN,
    AGENTS_END,
    AGENTS_SECTION,
    agents_md_section,
    write_agents_md,
)

SAMPLE = REPO_ROOT / "fixtures" / "sample-game" / "workspace"


def test_sample_agents_md_is_current(tmp_path: Path) -> None:
    assert agents_md_section(SAMPLE) == AGENTS_SECTION.strip("\n")
    (tmp_path / "AGENTS.md").write_bytes((SAMPLE / "AGENTS.md").read_bytes())
    write_agents_md(tmp_path)
    assert (tmp_path / "AGENTS.md").read_bytes() == (SAMPLE / "AGENTS.md").read_bytes()


def test_write_keeps_user_text(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    write_agents_md(tmp_path)
    assert agents_md_section(tmp_path) == AGENTS_SECTION.strip("\n")
    text = path.read_text(encoding="utf-8")
    old = text.replace("Kookabug 워크스페이스 규칙", "옛 규칙")
    path.write_text(f"사용자 머리말\n\n{old}\n사용자 꼬리말\n", encoding="utf-8")
    write_agents_md(tmp_path, "새 규칙")
    after = path.read_text(encoding="utf-8")
    assert after.startswith("사용자 머리말\n\n")
    assert after.endswith("\n사용자 꼬리말\n")
    assert agents_md_section(tmp_path) == "새 규칙"
    assert "옛 규칙" not in after


def test_write_appends_block_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text("# 우리 팀 규칙\n- 손으로 쓴 것", encoding="utf-8")
    write_agents_md(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# 우리 팀 규칙\n- 손으로 쓴 것\n")
    assert text.count(AGENTS_BEGIN) == text.count(AGENTS_END) == 1
    assert agents_md_section(tmp_path) == AGENTS_SECTION.strip("\n")


def test_exact_rule_escapes_glob() -> None:
    for arg in ("tests/[ab].graph.json", "tests/*.graph.json", "a?b", "", "창 (1)"):
        text = exact_rule("kb_graph_patch", arg)
        rule = parse_rule(text, "allow")
        assert rule.matches("kb_graph_patch", arg)
        assert not rule.matches("kb_graph_patch", arg + "x")
    rule = parse_rule(exact_rule("kb_graph_patch", "tests/[ab].graph.json"), "allow")
    assert not rule.matches("kb_graph_patch", "tests/a.graph.json")
    assert not rule.matches("kb_graph_patch", "tests/b.graph.json")
    star = parse_rule(exact_rule("kb_graph_patch", "tests/*.graph.json"), "allow")
    assert not star.matches("kb_graph_patch", "tests/x.graph.json")
