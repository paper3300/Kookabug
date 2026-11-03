"""외부 PR 게이트 (2026-11-03 사용자 결정: 허용한 사람만 PR).

판정 스크립트(`tools/pr_gate.py`)와 워크플로(`.github/workflows/pr-gate.yml`)의 안전 조건을
본다: `pull_request_target`에서 PR 코드를 체크아웃·실행하지 않고, 권한은 최소이고, PR이 정하는
값(작성자 이름)은 환경 변수로만 넘긴다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

import pr_gate

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-gate.yml"
SCRIPT = ROOT / "tools" / "pr_gate.py"


def workflow() -> dict[Any, Any]:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_parse_approved_list() -> None:
    text = "﻿# 주석\n\n Alice \n@Bob  # 메모\n#carol\nalice\n"
    assert pr_gate.parse_approved(text) == {"alice", "bob"}


@pytest.mark.parametrize(
    ("author", "kind", "allowed"),
    [
        ("Owner", "User", True),  # 레포 주인 (대소문자 무시)
        ("alice", "User", True),  # 허용 목록
        ("ALICE", "User", True),
        ("mallory", "User", False),
        ("dependabot[bot]", "Bot", True),  # 봇 예외
        ("", "User", False),
        ("mallory", "Organization", False),
    ],
)
def test_is_allowed(author: str, kind: str, allowed: bool) -> None:
    assert pr_gate.is_allowed(author, kind, "owner", {"alice"}) is allowed


def test_repo_list_has_only_owner() -> None:
    approved = pr_gate.parse_approved(pr_gate.APPROVED_FILE.read_text(encoding="utf-8-sig"))
    assert approved == {"paper3300"}


@pytest.mark.parametrize(("author", "expected"), [("paper3300", "true"), ("someone-else", "false")])
def test_script_prints_github_output(author: str, expected: str) -> None:
    env = {**os.environ, "PR_AUTHOR": author, "PR_AUTHOR_TYPE": "User", "REPO_OWNER": "paper3300"}
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == f"allowed={expected}"


def test_workflow_uses_pull_request_target_with_least_privilege() -> None:
    data = workflow()
    # PyYAML은 `on`을 True로 읽는다
    triggers = data["on"] if "on" in data else data[True]
    assert isinstance(triggers, dict) and set(triggers) == {"pull_request_target"}
    assert triggers["pull_request_target"] == {"types": ["opened", "reopened"]}
    assert data["permissions"] == {}
    (job,) = data["jobs"].values()
    assert job["permissions"] == {"contents": "read", "pull-requests": "write"}


def test_workflow_never_checks_out_or_runs_pr_code() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    # PR 머리(포크 코드)를 가리키는 값은 어디에도 쓰지 않는다
    for forbidden in (
        "pull_request.head",
        "head_ref",
        "github.head_ref",
        "merge_commit_sha",
        "refs/pull/",
    ):
        assert forbidden not in raw, forbidden
    (job,) = workflow()["jobs"].values()
    checkouts = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert len(checkouts) == 1
    options = checkouts[0]["with"]
    assert options["ref"] == "${{ github.event.pull_request.base.sha }}"
    assert options["persist-credentials"] is False
    assert set(options["sparse-checkout"].split()) == {".github", "tools/pr_gate.py"}


def test_workflow_passes_pr_values_only_through_env() -> None:
    (job,) = workflow()["jobs"].values()
    for step in job["steps"]:
        run = step.get("run", "")
        # 작성자 이름 등 PR이 정하는 값을 셸 글에 끼워 넣지 않는다 (명령 주입 방지)
        assert "${{" not in run, run
    runs = "\n".join(s.get("run", "") for s in job["steps"])
    assert "python3 tools/pr_gate.py" in runs
    assert "gh pr comment" in runs and "--body-file .github/pr-gate-comment.md" in runs
    assert "gh pr close" in runs
    close = next(s for s in job["steps"] if "gh pr close" in s.get("run", ""))
    assert close["if"] == "steps.check.outputs.allowed == 'false'"


def test_comment_and_policy_files_exist() -> None:
    comment = (ROOT / ".github" / "pr-gate-comment.md").read_text(encoding="utf-8")
    assert "이슈" in comment and "CONTRIBUTING.md" in comment
    policy = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for needle in ("APPROVED_CONTRIBUTORS", "이슈", "Discussions", "에이전트", "DCO"):
        assert needle in policy, needle


def test_root_readme_links_intro_and_contributing() -> None:
    # GitHub 첫 화면: 소개 문서 링크와 기여 안내 (P1-B 검수)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for link in ("(Docs/intro/README.md)", "(CONTRIBUTING.md)", "(LICENSE)"):
        assert link in readme, link
    for target in ("Docs/intro/README.md", "CONTRIBUTING.md", "LICENSE"):
        assert (ROOT / target).is_file(), target
