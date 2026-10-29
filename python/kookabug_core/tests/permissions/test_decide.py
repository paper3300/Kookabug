import copy
from typing import Any

import pytest

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.permissions import (
    PRESETS,
    TOOLS,
    Decision,
    LayerName,
    LayerPolicy,
    Policy,
    Preset,
    Principal,
    Verdict,
    decide,
)

AGENT = Principal("agent", "conn-1", attended=False)
ATTENDED = Principal("agent", "panel", attended=True)
HUMAN = Principal("user", "cli", attended=True)


def layer(name: LayerName, **permissions: Any) -> LayerPolicy:
    return LayerPolicy.from_permissions(name, permissions, f"<{name}>")


def policy(
    user: dict[str, Any] | None = None,
    project: dict[str, Any] | None = None,
    team: dict[str, Any] | None = None,
) -> Policy:
    return Policy(
        layer("user", **(user or {})),
        layer("project", **(project or {})),
        layer("team", **(team or {})),
    )


def rules(*items: tuple[Verdict, str]) -> dict[str, Any]:
    return {"rules": [{"rule": r, "verdict": v} for v, r in items]}


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        (("allow", "ask"), "ask"),
        (("ask", "allow"), "ask"),
        (("allow", "deny"), "deny"),
        (("deny", "ask", "allow"), "deny"),
        (("allow",), "allow"),
    ],
)
def test_deny_beats_ask_beats_allow(verdicts: tuple[Verdict, ...], expected: Verdict) -> None:
    # 같은 계층·다른 계층 모두 가장 엄격한 규칙이 이긴다
    layers: list[LayerName] = ["user", "project", "team"]
    spread: dict[str, dict[str, Any]] = {name: {"rules": []} for name in layers}
    for i, verdict in enumerate(verdicts):
        spread[layers[i % 3]]["rules"].append({"rule": "kb_graph_get(*)", "verdict": verdict})
    d = decide(policy(**spread), ATTENDED, "kb_graph_get", "tests/a.graph.json")
    assert (d.verdict, d.reason) == (expected, "rule")

    same: list[tuple[Verdict, str]] = [(v, "kb_graph_get") for v in verdicts]
    same_layer = policy(project=rules(*same))
    assert decide(same_layer, ATTENDED, "kb_graph_get").verdict == expected


def test_rule_beats_toolset_value() -> None:
    p = policy(
        project={"toolsets": {"run": "deny"}} | rules(("allow", "kb_run_start(tests/smoke/*)"))
    )
    d = decide(p, AGENT, "kb_run_start", "tests/smoke/a.graph.json")
    assert (d.final, d.reason, d.layer, d.source) == (
        "allow", "rule", "project", "rule:kb_run_start(tests/smoke/*)"
    )  # fmt: skip
    # 맞지 않는 인자는 툴셋 값으로
    d = decide(p, AGENT, "kb_run_start", "tests/full/a.graph.json")
    assert (d.final, d.reason, d.source) == ("deny", "toolset", "toolset:run")


def test_rule_beats_preset() -> None:
    p = policy(user={"preset": "read_only"} | rules(("allow", "kb_graph_patch")))
    assert decide(p, AGENT, "kb_graph_patch").final == "allow"


def test_toolset_project_over_user() -> None:
    p = policy(user={"toolsets": {"run": "deny"}}, project={"toolsets": {"run": "allow"}})
    d = decide(p, AGENT, "kb_run_start")
    assert (d.final, d.layer, d.reason) == ("allow", "project", "toolset")

    p = policy(user={"toolsets": {"run": "allow"}}, project={"toolsets": {"graph_edit": "deny"}})
    d = decide(p, AGENT, "kb_run_start")
    assert (d.final, d.layer) == ("allow", "user")


def test_toolset_beats_preset_across_layers() -> None:
    # 사용자 툴셋 값이 프로젝트 프리셋보다 먼저다 (툴셋 → 프리셋 순서가 계층 순서보다 앞)
    p = policy(user={"toolsets": {"run": "allow"}}, project={"preset": "read_only"})
    assert decide(p, AGENT, "kb_run_start").final == "allow"


def test_preset_project_over_user() -> None:
    p = policy(user={"preset": "full"}, project={"preset": "read_only"})
    d = decide(p, AGENT, "kb_graph_create")
    assert (d.final, d.layer, d.source) == ("deny", "project", "preset:read_only")
    d = decide(policy(user={"preset": "full"}), AGENT, "kb_graph_create")
    assert (d.final, d.layer, d.source) == ("allow", "user", "preset:full")


def test_readonly_tools_allowed_unless_toolset_deny() -> None:
    for value, read, change in [("ask", "allow", "ask"), ("allow", "allow", "allow"),
                                ("deny", "deny", "deny")]:  # fmt: skip
        p = policy(project={"toolsets": {"run": value, "screens": value}})
        assert decide(p, ATTENDED, "kb_run_events").final == read
        assert decide(p, ATTENDED, "kb_run_artifact_get").final == read
        assert decide(p, ATTENDED, "kb_screen_get").final == read
        assert decide(p, ATTENDED, "kb_run_start").final == change
        assert decide(p, ATTENDED, "kb_screen_save").final == change
    # core 툴셋은 조회 도구뿐이다. deny로 막으면 막힌다
    assert decide(policy(project={"toolsets": {"core": "deny"}}), AGENT, "kb_graph_get").final == (
        "deny"
    )


def test_team_toolset_is_ceiling() -> None:
    team = {"toolsets": {"run": "deny", "control": "ask", "screens": "ask"}}
    p = policy(project={"preset": "full"} | rules(("allow", "kb_run_start")), team=team)
    d = decide(p, ATTENDED, "kb_run_start")
    assert (d.final, d.layer, d.source, d.reason) == ("deny", "team", "toolset:run", "team_ceiling")
    # 조회 도구는 툴셋이 deny일 때만 막힌다
    assert decide(p, ATTENDED, "kb_run_events").final == "deny"
    assert decide(p, ATTENDED, "kb_screen_get").final == "allow"
    assert decide(p, ATTENDED, "kb_screen_save").final == "ask"
    d = decide(p, ATTENDED, "kb_input_click")
    assert (d.final, d.reason) == ("ask", "team_ceiling")
    # 상한보다 엄격한 결과는 그대로
    p = policy(project={"toolsets": {"control": "deny"}}, team=team)
    d = decide(p, ATTENDED, "kb_input_click")
    assert (d.final, d.layer, d.reason) == ("deny", "project", "toolset")
    # 팀 툴셋 값 allow는 풀어 주지 않는다
    p = policy(project={"preset": "read_only"}, team={"toolsets": {"run": "allow"}})
    assert decide(p, ATTENDED, "kb_run_start").final == "deny"


def test_team_preset_is_ceiling() -> None:
    p = policy(user={"preset": "full"}, team={"preset": "graph_author"})
    d = decide(p, ATTENDED, "kb_run_start")
    assert (d.final, d.layer, d.source, d.reason) == (
        "deny", "team", "preset:graph_author", "team_ceiling"
    )  # fmt: skip
    d = decide(p, ATTENDED, "kb_graph_patch")
    assert (d.final, d.reason) == ("ask", "team_ceiling")
    assert decide(p, ATTENDED, "kb_graph_get").final == "allow"
    # 팀 안에서는 툴셋 값이 프리셋보다 먼저다
    p = policy(user={"preset": "full"}, team={"preset": "read_only", "toolsets": {"run": "allow"}})
    assert decide(p, ATTENDED, "kb_run_start").final == "allow"
    assert decide(p, ATTENDED, "kb_graph_patch").final == "deny"


def test_team_rules_join_rule_step() -> None:
    p = policy(project=rules(("allow", "kb_run_start")), team=rules(("deny", "kb_run_start(x/*)")))
    d = decide(p, ATTENDED, "kb_run_start", "x/a.graph.json")
    assert (d.final, d.layer, d.reason) == ("deny", "team", "rule")
    assert decide(p, ATTENDED, "kb_run_start", "y/a.graph.json").final == "allow"


def test_unattended_ask_becomes_deny() -> None:
    d = decide(policy(), AGENT, "kb_graph_patch")
    assert (d.verdict, d.final, d.reason) == ("ask", "deny", "unattended_ask")
    assert (d.layer, d.source) == ("default", "preset:graph_author")
    assert not d.allowed and not d.needs_approval
    # 팀 상한이 ask로 만든 것도
    p = policy(user={"preset": "full"}, team={"toolsets": {"control": "ask"}})
    d = decide(p, AGENT, "kb_input_key")
    assert (d.verdict, d.final, d.layer) == ("ask", "deny", "team")


def test_attended_ask_stays_ask() -> None:
    d = decide(policy(), ATTENDED, "kb_graph_patch")
    assert (d.verdict, d.final, d.reason) == ("ask", "ask", "preset")
    assert d.needs_approval


def test_user_principal_always_allowed() -> None:
    strict = policy(
        user={"preset": "read_only"},
        project=rules(("deny", "*")),
        team={"preset": "read_only", "toolsets": {"run": "deny"}},
    )
    broken = Policy(
        team=LayerPolicy(
            "team", "kookabug.json", diagnostics=(Diagnostic("error", "json_invalid", "x"),)
        )
    )
    for p in (strict, broken):
        for tool in [*TOOLS, "kb_unknown"]:
            d = decide(p, HUMAN, tool)
            assert (d.final, d.reason, d.layer) == ("allow", "human", None)


def test_default_preset_graph_author() -> None:
    d = decide(policy(), ATTENDED, "kb_run_start")
    assert (d.final, d.layer, d.source, d.reason) == (
        "deny", "default", "preset:graph_author", "preset"
    )  # fmt: skip
    assert decide(policy(), ATTENDED, "kb_screen_save").final == "ask"
    assert decide(policy(), ATTENDED, "kb_screen_list").final == "allow"


# 계획 2.10 프리셋 표 그대로 (read_only, graph_author, runner, full)
CORE = ["kb_project_info", "kb_toolset_enable", "kb_graph_list", "kb_graph_get",
        "kb_graph_validate", "kb_node_search", "kb_run_status", "kb_log_search"]  # fmt: skip
PRESET_TABLE: list[tuple[list[str], tuple[Verdict, Verdict, Verdict, Verdict]]] = [
    (CORE, ("allow", "allow", "allow", "allow")),
    (["kb_graph_create", "kb_graph_patch", "kb_target_create"], ("deny", "ask", "ask", "allow")),
    (["kb_run_start", "kb_run_cancel"], ("deny", "deny", "allow", "allow")),
    (["kb_run_events", "kb_run_artifact_get"], ("allow", "allow", "allow", "allow")),
    (["kb_screen_capture", "kb_image_find", "kb_ocr_read"], ("allow", "allow", "allow", "allow")),
    (
        ["kb_input_click", "kb_input_key", "kb_input_type", "kb_app_launch"],
        ("deny", "deny", "ask", "allow"),
    ),
    (["kb_screen_list", "kb_screen_get"], ("allow", "allow", "allow", "allow")),
    (["kb_screen_save"], ("deny", "ask", "ask", "allow")),
]
PRESET_CASES = [
    (preset, tool, values[i])
    for tools, values in PRESET_TABLE
    for tool in tools
    for i, preset in enumerate(("read_only", "graph_author", "runner", "full"))
]


def test_preset_table_covers_every_tool() -> None:
    assert sorted(t for tools, _ in PRESET_TABLE for t in tools) == sorted(TOOLS)
    assert len(PRESET_CASES) == 4 * len(TOOLS)
    assert set(PRESETS) == {"read_only", "graph_author", "runner", "full"}


@pytest.mark.parametrize(("preset", "tool", "expected"), PRESET_CASES)
def test_presets_table(preset: Preset, tool: str, expected: Verdict) -> None:
    d = decide(policy(project={"preset": preset}), ATTENDED, tool)
    assert (d.final, d.reason, d.source) == (expected, "preset", f"preset:{preset}")


def test_unknown_tool_denied() -> None:
    p = policy(project={"preset": "full"} | rules(("allow", "*")))
    d = decide(p, ATTENDED, "kb_not_a_tool")
    assert (d.final, d.reason) == ("deny", "unknown_tool")


def test_invalid_policy_denies_agent_not_user() -> None:
    bad = Diagnostic("error", "invalid_value", "bad", file=".kookabug/local.json", pointer="/x")
    p = Policy(
        user=layer("user", preset="full"),
        project=LayerPolicy("project", ".kookabug/local.json", diagnostics=(bad,)),
    )
    for principal in (AGENT, ATTENDED):
        d = decide(p, principal, "kb_graph_get")
        assert (d.final, d.reason, d.layer) == ("deny", "policy_invalid", "project")
        assert d.source == ".kookabug/local.json"
        assert d.diagnostics == (bad,)
    assert decide(p, HUMAN, "kb_run_start").final == "allow"
    # 경고만 있으면 잘못된 정책이 아니다
    warn = Diagnostic("warning", "x", "w")
    p = Policy(project=LayerPolicy("project", diagnostics=(warn,)))
    assert decide(p, ATTENDED, "kb_graph_get").final == "allow"


def test_decision_names_layer_and_source() -> None:
    p = policy(
        user={"toolsets": {"control": "allow"}},
        project={"preset": "runner"} | rules(("deny", "kb_graph_create(tests/*)")),
        team={"toolsets": {"screens": "deny"}},
    )
    cases: list[tuple[str, str, Decision]] = [
        ("kb_graph_create", "tests/a.graph.json",
         Decision("deny", "deny", "project", "rule:kb_graph_create(tests/*)", "rule")),
        ("kb_input_click", "", Decision("allow", "allow", "user", "toolset:control", "toolset")),
        ("kb_run_start", "", Decision("allow", "allow", "project", "preset:runner", "preset")),
        ("kb_screen_save", "", Decision("deny", "deny", "team", "toolset:screens", "team_ceiling")),
    ]  # fmt: skip
    for tool, arg, expected in cases:
        assert decide(p, AGENT, tool, arg) == expected
    d = decide(p, AGENT, "kb_graph_create", "tests/a.graph.json")
    assert d.to_dict() == {
        "diagnostics": [],
        "final": "deny",
        "layer": "project",
        "reason": "rule",
        "source": "rule:kb_graph_create(tests/*)",
        "verdict": "deny",
    }
    assert "kb_graph_create" in d.describe("kb_graph_create")
    assert ".kookabug/local.json" in d.describe("kb_graph_create")


def test_decide_is_pure(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    p = policy(
        user={"preset": "runner"},
        project=rules(("ask", "kb_run_start(a/*)")),
        team={"toolsets": {"control": "ask"}},
    )
    before = copy.deepcopy(p)
    calls = [(AGENT, "kb_run_start", "a/b"), (ATTENDED, "kb_input_key", ""), (HUMAN, "x", "")]
    first = [decide(p, *c) for c in calls]
    # 환경·현재 폴더·파일에 의존하지 않는다
    monkeypatch.setenv("KOOKABUG_USER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("KOOKABUG_AGENT", "other")
    monkeypatch.chdir(tmp_path)

    def no_io(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("decide가 파일을 열었다")

    monkeypatch.setattr("builtins.open", no_io)
    assert [decide(p, *c) for c in calls] == first
    assert p == before
