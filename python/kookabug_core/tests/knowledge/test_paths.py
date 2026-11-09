"""지식 쓰기 경계 (M8 계획 3.3 "경로 차단").

정책·플레이북·증거·렌더 파일로 가는 Agent 경로가 없다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers.knowledge import AGENT, CHECK, add, apply, make_ws, tree

from kookabug_core.knowledge import ops
from kookabug_core.knowledge.formats import KnowledgeError


def make_junction(link: Path, target: Path) -> None:
    import _winapi  # Windows 전용 (관리자 권한 없이 폴더 별칭)

    _winapi.CreateJunction(str(target), str(link))


def wiki(root: Path, path: str, base: str | None = None) -> str:
    with pytest.raises(KnowledgeError) as info:
        ops.wiki_write(root, path, "# 글\n", base, actor=AGENT, check_secrets=CHECK)
    return info.value.code


def op_file(root: Path, file: str, rid: str) -> str:
    item = {"id": "x.y", "kind": "guess", "statement": "s", "basis": [], "status": "hypothesis"}
    with pytest.raises(KnowledgeError) as info:
        apply(root, [add(file, item)], rid=rid)
    return info.value.code


WIKI_REFUSED = [
    "kookabug.json",
    "AGENTS.md",
    ".claude/settings.md",
    ".codex/x.md",
    ".kookabug/local.md",
    "knowledge/evidence/e-1/manifest.md",
    "wiki/index.md",
    "wiki/INDEX.md",
    "wiki/log.md",
    "wiki/reports/2026-11-09-j-1.md",
    "wiki/Reports/x.md",
    "wiki/REPORT~1/x.md",
    "wiki/../AGENTS.md",
    "wiki/./a.md",
    "wiki/a.md.",
    "wiki/a.md::$DATA",
    "wiki\\a.md",
    "/wiki/a.md",
    "wiki/a.txt",
    "wiki/con.md",
    "C:/x/wiki/a.md",
]
FILE_REFUSED = [
    "../kookabug",
    "kookabug",
    "AGENTS",
    "features/../../AGENTS",
    "features/Shop",
    "evidence/e-1/manifest",
    "cases/c-1",
    "working/claims/shop",
    "log",
    "wiki/index",
]


def test_policy_paths_unreachable(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    (root / ".claude").mkdir()
    (root / ".claude/settings.json").write_text("{}", "utf-8")
    (root / "knowledge/evidence/e-1").mkdir(parents=True)
    (root / "knowledge/evidence/e-1/manifest.json").write_text("{}", "utf-8")
    before = tree(root)
    for path in WIKI_REFUSED:
        assert wiki(root, path) == "policy_path", path
    for i, file in enumerate(FILE_REFUSED):
        assert op_file(root, file, f"r{i}") == "policy_path", file
    after = tree(root)
    # 정책·플레이북·증거·렌더 파일은 바이트 그대로 (거부 기록만 감사 이력·일지에 남는다)
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert changed <= {"knowledge/log.jsonl", "wiki/log.md"}

    # 정션: wiki 아래 폴더가 루트를 가리키면 그 아래로 쓰지 않는다
    make_junction(root / "wiki" / "alias", root)
    assert wiki(root, "wiki/alias/AGENTS.md") == "policy_path"
    assert wiki(root, "wiki/alias/wiki/reports/x.md") == "policy_path"
    # 정션: 지식 폴더가 다른 곳(.claude)을 가리키면 연산이 쓰지 않는다
    (root / "knowledge" / "features").rmdir()
    make_junction(root / "knowledge" / "features", root / ".claude")
    assert op_file(root, "features/settings", "rj") == "policy_path"
    assert (root / ".claude/settings.json").read_text("utf-8") == "{}"
    assert not (root / ".claude/settings.json.tmp").exists()
    assert sorted(p.name for p in (root / ".claude").iterdir()) == ["settings.json"]


def test_wiki_page_written_and_index_rendered(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    out = ops.wiki_write(
        root, "wiki/overview.md", "# 개요\n", None, actor=AGENT, check_secrets=CHECK
    )
    assert (root / "wiki/overview.md").read_text("utf-8") == "# 개요\n"
    assert "overview.md" in (root / "wiki/index.md").read_text("utf-8")
    with pytest.raises(KnowledgeError) as info:
        ops.wiki_write(root, "wiki/overview.md", "x", None, actor=AGENT, check_secrets=CHECK)
    assert info.value.code == "revision_conflict"
    ops.wiki_write(
        root, "wiki/overview.md", "# 둘\n", out["sha256"], actor=AGENT, check_secrets=CHECK
    )
    with pytest.raises(KnowledgeError) as info:
        ops.wiki_write(
            root,
            "wiki/big.md",
            "x" * (ops.MAX_WIKI_BYTES + 1),
            None,
            actor=AGENT,
            check_secrets=CHECK,
        )
    assert info.value.code == "too_large"
