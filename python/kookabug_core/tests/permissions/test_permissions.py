"""M8 프리셋 `curator`·`qa_runner`와 작업 토큰 연결의 판정 순서 (계획 3.14, 9장 R0·R7) — 엄격.

적용 순서: 명시 deny(규칙·툴셋 값) → 팀 상한 → (작업 안이면 `curator` control ask → allow) → 프리셋.
"""

from __future__ import annotations

from typing import Any

import pytest

from kookabug_core.permissions import (
    TOOLS,
    LayerName,
    LayerPolicy,
    Policy,
    Principal,
    decide,
    preset_verdict,
)

# 계획 3.14 표 그대로 (변경 도구, 툴셋별). 조회 도구는 모두 allow
TABLE: dict[str, dict[str, str]] = {
    "curator": {
        "graph_edit": "allow", "run": "allow", "control": "ask", "screens": "allow",
        "knowledge": "allow", "cases": "allow",
    },
    "qa_runner": {
        "graph_edit": "deny", "run": "allow", "control": "deny", "screens": "deny",
        "knowledge": "deny", "cases": "allow",
    },
}  # fmt: skip

UNATTENDED = Principal("agent", "a1", attended=False)
JOB = Principal("agent", "job:j-20261110-000000-abcd", attended=False, job="j-20261110-000000-abcd")


def layer(name: LayerName, **permissions: Any) -> LayerPolicy:
    return LayerPolicy.from_permissions(name, permissions, f"<{name}>")


def policy(
    project: dict[str, Any] | None = None,
    team: dict[str, Any] | None = None,
    user: dict[str, Any] | None = None,
) -> Policy:
    return Policy(
        layer("user", **(user or {})),
        layer("project", **(project or {})),
        layer("team", **(team or {})),
    )


@pytest.mark.parametrize("preset", sorted(TABLE))
def test_curator_qa_runner_table(preset: str) -> None:
    for tool, info in TOOLS.items():
        if not info.mutating:
            want = "allow"
        elif preset == "qa_runner" and tool == "kb_adopt_request":
            want = "deny"  # cases 안에서도 채택 요청은 못 한다 (3.14)
        else:
            want = TABLE[preset][info.toolset]
        assert preset_verdict(preset, tool) == want, (preset, tool)  # type: ignore[arg-type]
        attended = Principal("agent", "p", attended=True)
        assert decide(policy({"preset": preset}), attended, tool).verdict == want, (preset, tool)


def test_job_token_curator_control_allowed() -> None:
    """R0: 사람이 시작한 agent-job 안에서만 curator의 control ask → allow (무인이어도)."""
    p = policy({"preset": "curator"})
    for tool in ("kb_input_click", "kb_input_key", "kb_input_type", "kb_app_launch"):
        d = decide(p, JOB, tool)
        assert (d.final, d.reason, d.source) == ("allow", "preset", "preset:curator"), tool
    # 다른 프리셋은 작업 안이어도 그대로 (runner는 ask → 무인 deny, qa_runner는 deny)
    assert decide(policy({"preset": "runner"}), JOB, "kb_input_click").final == "deny"
    assert decide(policy({"preset": "qa_runner"}), JOB, "kb_input_click").final == "deny"
    # 팀 상한이 curator 프리셋이면 작업 안 값으로 본다 (상한이 다시 ask로 내리지 않는다)
    team = policy({"preset": "curator"}, {"preset": "curator"})
    assert decide(team, JOB, "kb_input_click").final == "allow"


def test_job_explicit_deny_kept() -> None:
    """명시 deny·ask(규칙·툴셋 값)와 팀 상한은 작업 안 allow보다 먼저다."""
    rule = {"preset": "curator", "rules": [{"rule": "kb_input_click", "verdict": "deny"}]}
    d = decide(policy(rule), JOB, "kb_input_click")
    assert (d.final, d.reason) == ("deny", "rule")
    assert decide(policy(rule), JOB, "kb_input_key").final == "allow"
    ask = {"preset": "curator", "toolsets": {"control": "ask"}}
    d = decide(policy(ask), JOB, "kb_input_key")
    assert (d.final, d.reason) == ("deny", "unattended_ask")
    ceiling = policy({"preset": "curator"}, {"toolsets": {"control": "deny"}})
    d = decide(ceiling, JOB, "kb_input_key")
    assert (d.final, d.reason) == ("deny", "team_ceiling")
    team_preset = policy({"preset": "curator"}, {"preset": "qa_runner"})
    assert decide(team_preset, JOB, "kb_input_key").final == "deny"


def test_outside_job_ask() -> None:
    """작업 밖 curator는 control ask: 사람 없는 연결은 deny, 사람 있는 연결은 확인 요청."""
    p = policy({"preset": "curator"})
    d = decide(p, UNATTENDED, "kb_input_click")
    assert (d.verdict, d.final, d.reason) == ("ask", "deny", "unattended_ask")
    attended = Principal("agent", "panel", attended=True)
    assert decide(p, attended, "kb_input_click").final == "ask"


def test_job_does_not_widen_other_toolsets() -> None:
    """작업 값은 curator의 control 하나뿐이다 — 다른 프리셋·툴셋은 작업 밖과 같다."""
    for preset in ("read_only", "graph_author", "runner", "full", "explorer", "qa_runner"):
        for tool in TOOLS:
            outside = Principal("agent", JOB.id, attended=False)
            assert decide(policy({"preset": preset}), JOB, tool) == decide(
                policy({"preset": preset}), outside, tool
            ), (preset, tool)
    for tool, info in TOOLS.items():
        if info.toolset != "control":
            outside = Principal("agent", JOB.id, attended=False)
            p = policy({"preset": "curator"})
            assert decide(p, JOB, tool) == decide(p, outside, tool), tool


# (프로젝트 프리셋, 사용자 프리셋, 팀 프리셋) → 작업 연결의 kb_input_key 최종 판정
JOB_CEILING_TABLE: list[tuple[str | None, str | None, str | None, str]] = [
    # 유효 프리셋이 curator가 아니면 작업이어도 팀 curator 상한(control ask → 무인 deny) 그대로
    ("full", None, "curator", "deny"),
    ("full", "curator", "curator", "deny"),  # 유효 = 프로젝트 full (사용자 curator는 안 봄)
    ("graph_author", None, "curator", "deny"),
    ("runner", None, "curator", "deny"),
    ("explorer", None, "curator", "deny"),
    (None, None, "curator", "deny"),  # 유효 = 기본 graph_author
    # 유효 프리셋이 curator인 작업 연결만 control ask → allow (팀 상한도 같은 조건)
    ("curator", None, "curator", "allow"),
    (None, "curator", "curator", "allow"),  # 유효 = 사용자 curator
    ("curator", None, "full", "allow"),
    ("curator", None, None, "allow"),
    # 팀 상한이 curator가 아닌 프리셋이면 작업 값으로 넓히지 않는다
    ("curator", None, "runner", "deny"),
    ("curator", None, "graph_author", "deny"),
    ("curator", None, "qa_runner", "deny"),
]


@pytest.mark.parametrize(("project", "user", "team", "want"), JOB_CEILING_TABLE)
def test_job_keeps_team_ceiling_for_other_presets(
    project: str | None, user: str | None, team: str | None, want: str
) -> None:
    """R0·R7: 작업 예외(작업 안 curator control ask → allow)는 유효 프리셋이 curator인 작업 연결에만
    — 팀 상한에도 같은 조건. 유효 프리셋이 curator가 아니면 작업 연결의 판정은 작업 밖과 같다."""
    p = policy(
        None if project is None else {"preset": project},
        None if team is None else {"preset": team},
        None if user is None else {"preset": user},
    )
    assert decide(p, JOB, "kb_input_key").final == want
    effective = project or user or "graph_author"
    if effective != "curator":
        outside = Principal("agent", JOB.id, attended=False)
        for tool in TOOLS:
            assert decide(p, JOB, tool) == decide(p, outside, tool), tool
