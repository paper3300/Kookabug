"""새 워크스페이스 만들기 (M8 계획 3.1·C15)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kookabug_core.workspace import (
    AGENTS_SECTION,
    AUTOMATION_DEFAULTS,
    PLAYBOOKS_FORMAT,
    Workspace,
    agents_md_section,
    workspace_id,
)
from kookabug_core.workspace_new import GITIGNORE, CreateError, create_workspace


def test_creates_layout_gitignore_agents_md(tmp_path: Path) -> None:
    root = tmp_path / "new" / "proj"
    created = create_workspace(root, "  상점 QA  ")
    ws = Workspace.open(root)
    assert ws.diagnostics == []
    assert ws.config["name"] == "상점 QA" and workspace_id(ws) == created.id
    assert (root / ".gitignore").read_text("utf-8") == GITIGNORE
    assert "runs/" in GITIGNORE and ".kookabug/" in GITIGNORE
    assert agents_md_section(root) == AGENTS_SECTION.strip("\n")
    assert PLAYBOOKS_FORMAT in AGENTS_SECTION and "kb_knowledge_apply" in AGENTS_SECTION
    for folder in (
        "tests",
        "subgraphs",
        "targets",
        "screens",
        "knowledge/features",
        "knowledge/cases",
        "knowledge/evidence",
        "knowledge/working",
        "knowledge/adoptions",
        "knowledge/reports",
    ):
        assert (root / folder).is_dir(), folder
    assert (root / "wiki/index.md").read_text("utf-8").startswith("# 위키 목차")
    # 정책 기본값 (키가 없을 때)
    auto = ws.automation()
    assert auto["auto_repair"] == AUTOMATION_DEFAULTS["auto_repair"]
    assert auto["budget"] == {"minutes": 60, "runs": 30} and auto["forbidden"] == []
    assert ws.cheats_policy() == {"enabled": False, "categories": []}
    # 빈 폴더에도 만든다
    empty = tmp_path / "empty"
    empty.mkdir()
    assert create_workspace(empty, "빈").root == empty.resolve()


def test_refuses_nonempty_folder(tmp_path: Path) -> None:
    root = tmp_path / "busy"
    root.mkdir()
    (root / "notes.txt").write_text("사용자 파일", "utf-8")
    with pytest.raises(CreateError) as info:
        create_workspace(root, "x")
    assert info.value.code == "not_empty"
    assert sorted(p.name for p in root.iterdir()) == ["notes.txt"]
    with pytest.raises(CreateError) as info:
        create_workspace(tmp_path / "a", "\x07bell")
    assert info.value.code == "invalid_name" and not (tmp_path / "a").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git 없음")
def test_git_init(tmp_path: Path) -> None:
    created = create_workspace(tmp_path / "g", "깃", git=True)
    assert created.git and (tmp_path / "g" / ".git").is_dir()


def test_automation_and_sources_keys_shape(tmp_path: Path) -> None:
    root = tmp_path / "w"
    create_workspace(root, "w")
    text = (root / "kookabug.json").read_text("utf-8").rstrip().rstrip("}")
    text += (
        ', "sources": [{"id": "a", "kind": "data", "title": "A", "path": "D:/x.csv"},'
        ' {"id": "b", "kind": "code", "title": "B", "local": true}],'
        ' "automation": {"format": "kookabug.automation/0", "auto_repair": {"enabled": false},'
        ' "forbidden": [{"kind": "text", "value": "결제"}]},'
        ' "cheats": {"enabled": true, "categories":'
        ' [{"id": "dev_safe", "title": "무해", "unattended": true}]}}'
    )
    (root / "kookabug.json").write_text(text, "utf-8")
    ws = Workspace.open(root)
    assert ws.diagnostics == []
    auto = ws.automation()
    assert auto["auto_repair"]["enabled"] is False and auto["auto_repair"]["max_adoptions"] == 20
    assert auto["forbidden"] == [{"kind": "text", "value": "결제"}]
    assert ws.cheats_policy()["enabled"] is True
    # 원본은 path·url·local 중 하나만
    bad = text.replace('"path": "D:/x.csv"}', '"path": "D:/x.csv", "url": "https://e.com"}')
    (root / "kookabug.json").write_text(bad, "utf-8")
    assert Workspace.open(root).diagnostics
