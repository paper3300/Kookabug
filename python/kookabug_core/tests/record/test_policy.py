"""기록 정책 상속 (스키마 v0 6장 "화면에 찍힌 비밀값", 계획 2.9)."""

from typing import Any

import pytest

from kookabug_core.record.policy import (
    RecordPolicy,
    StepPolicy,
    find_secret,
    graph_source,
    node_source,
)
from kookabug_sdk import Secret

LEVELS = ["workspace", "test", "call_node", "subgraph", "node"]


def chain(off_at: str | None, record: dict[str, Any] | None = None) -> RecordPolicy:
    """워크스페이스 → 테스트 → 호출 노드 → 서브그래프 → 노드. `off_at` 층에만 `record`."""
    policy = RecordPolicy()
    for level in LEVELS:
        layer = (record or {"screenshots": "off"}) if level == off_at else None
        policy = policy.layer(layer, level)
    return policy


def test_default_is_on() -> None:
    policy = chain(None)
    assert (policy.screenshots, policy.video) == ("on", "on")
    assert policy.sources == {}
    assert StepPolicy(policy).screenshot_block() is None
    assert StepPolicy(policy).video == "on"


@pytest.mark.parametrize("level", LEVELS)
def test_off_at_any_level_wins(level: str) -> None:
    policy = chain(level, {"screenshots": "off", "video": "off"})
    assert (policy.screenshots, policy.video) == ("off", "off")
    assert policy.sources == {"screenshots": level, "video": level}
    assert StepPolicy(policy).screenshot_block() == ("policy_off", level)


def test_lower_level_cannot_reenable() -> None:
    policy = RecordPolicy().layer({"screenshots": "off", "video": "off"}, "workspace")
    for level in LEVELS[1:]:
        policy = policy.layer({"screenshots": "on", "video": "on"}, level)
    assert (policy.screenshots, policy.video) == ("off", "off")
    # 끈 곳은 처음 끈 가장 위 층이다
    assert policy.sources == {"screenshots": "workspace", "video": "workspace"}
    # 아래에서 다시 꺼도 위치는 위 층 그대로
    assert policy.layer({"screenshots": "off"}, "node").sources["screenshots"] == "workspace"


@pytest.mark.parametrize(
    ("upper", "lower", "expected"),
    [
        ("on", "failed_only", "failed_only"),
        ("failed_only", "on", "failed_only"),
        ("failed_only", "off", "off"),
        ("off", "failed_only", "off"),
        ("off", "on", "off"),
        ("on", "on", "on"),
    ],
)
def test_video_strength_order(upper: str, lower: str, expected: str) -> None:
    policy = RecordPolicy().layer({"video": upper}, "upper").layer({"video": lower}, "lower")
    assert policy.video == expected
    # 스크린샷은 영상과 따로 간다
    assert policy.screenshots == "on"
    if expected != "on":
        assert policy.sources["video"] == ("upper" if upper == expected else "lower")


def test_nested_subgraph_chain() -> None:
    # 테스트 → 호출 A → 서브그래프 A(failed_only) → 호출 B(screenshots off) → 서브그래프 B → 노드
    ws = RecordPolicy().layer(None, graph_source("kookabug.json"))
    test = ws.layer(None, graph_source("tests/t.graph.json"))
    in_a = test.layer(None, node_source("tests/t.graph.json", "n_a")).layer(
        {"video": "failed_only"}, graph_source("subgraphs/a.graph.json")
    )
    in_b = in_a.layer({"screenshots": "off"}, node_source("subgraphs/a.graph.json", "n_b")).layer(
        {"screenshots": "on", "video": "on"}, graph_source("subgraphs/b.graph.json")
    )
    node = in_b.layer({"screenshots": "on"}, node_source("subgraphs/b.graph.json", "n_x"))
    assert (node.screenshots, node.video) == ("off", "failed_only")
    assert node.sources == {
        "screenshots": "subgraphs/a.graph.json#/nodes/n_b/record",
        "video": "subgraphs/a.graph.json#/record",
    }
    # 형제 구간(서브그래프 A 안의 다른 노드)은 B의 끄기를 받지 않는다
    sibling = in_a.layer(None, node_source("subgraphs/a.graph.json", "n_other"))
    assert (sibling.screenshots, sibling.video) == ("on", "failed_only")


def test_layer_without_change_returns_same_policy() -> None:
    policy = RecordPolicy().layer({"screenshots": "off"}, "a")
    assert policy.layer({}, "b") is policy
    assert policy.layer({"screenshots": "off"}, "b") is policy


def test_secret_step_blocks_screenshots_and_video() -> None:
    step = StepPolicy(RecordPolicy(), secret="t#/nodes/n/in/password")
    assert step.screenshot_block() == ("secret_input", "t#/nodes/n/in/password")
    assert step.video == "off"
    # 구간 끄기가 같이 있으면 구간 끄기를 이유로 든다
    off = StepPolicy(RecordPolicy().layer({"screenshots": "off"}, "g"), secret="x")
    assert off.screenshot_block() == ("policy_off", "g")


@pytest.mark.parametrize(
    ("value", "pointer"),
    [
        (Secret("p"), ""),
        ({"password": Secret("p")}, "/password"),
        ({"values": [1, [2, Secret("p")]]}, "/values/1/1"),
        ({"a": ("x", {"b/c": Secret("p")})}, "/a/1/b~1c"),
        ({"a": 1, "b": ["x"], "c": None}, None),
    ],
)
def test_find_secret_recursive(value: Any, pointer: str | None) -> None:
    assert find_secret(value) == pointer
