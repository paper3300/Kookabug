"""실행 이벤트 (스키마 v0 5장 `events.jsonl` 필드)."""

from pathlib import Path

from helpers.graphs import GraphBuilder, make_workspace, subgraph_interface
from helpers.run import run_graph, tk

from kookabug_core.engine import event_value
from kookabug_sdk import Secret
from kookabug_sdk.types import Match, Rect

OUTER = "subgraphs/outer.graph.json"
INNER = "subgraphs/inner.graph.json"

# 설계 5장 예시의 필드. M0a는 시각 `t`를 남기지 않는다 (M0b가 쓸 때 붙인다)
DOC_START = {"event", "node", "parent", "path", "run", "step", "attempt"}
DOC_END = {"duration_ms", "event", "exit", "outputs", "run", "status", "step", "attempt"}
END_OPTIONAL = {"artifacts", "error", "graph", "iteration", "message"}


def _nested(tmp_path: Path):
    """테스트 → outer(n_c2) → inner(n_x) 두 단계 호출."""
    ws = make_workspace(tmp_path)
    (
        GraphBuilder("subgraph", interface=subgraph_interface())
        .entry("n_x")
        .node("n_x", "core.log.message", inputs={"text": "안쪽"}, next={"done": "n_exit"})
        .exit("n_exit", "done")
        .write(ws, INNER)
    )
    (
        GraphBuilder("subgraph", interface=subgraph_interface())
        .entry("n_c2")
        .call("n_c2", INNER, next={"done": "n_exit"})
        .exit("n_exit", "done")
        .write(ws, OUTER)
    )
    g = (
        tk()
        .entry("n_c1")
        .call("n_c1", OUTER, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    return run_graph(ws, g)


def test_step_ids_unique_and_parent_links(tmp_path: Path) -> None:
    ran = _nested(tmp_path)
    assert ran.result.verdict == "pass"
    starts = ran.of("step.start")
    ends = ran.of("step.end")
    ids = [e["step"] for e in starts]
    assert len(ids) == len(set(ids))
    assert sorted(e["step"] for e in ends) == sorted(ids)  # 시작한 스텝은 모두 끝난다
    by_path = {tuple(e["path"]): e for e in starts}
    c1 = by_path[("n_c1",)]["step"]
    c2 = by_path[("n_c1", "n_c2")]["step"]
    assert by_path[("n_entry",)]["parent"] is None
    assert by_path[("n_c1",)]["parent"] is None
    assert by_path[("n_pass",)]["parent"] is None
    assert by_path[("n_c1", "n_entry")]["parent"] == c1
    assert by_path[("n_c1", "n_c2")]["parent"] == c1
    assert by_path[("n_c1", "n_c2", "n_x")]["parent"] == c2
    assert {e["run"] for e in ran.events} == {"r1"}


def test_path_for_nested_call(tmp_path: Path) -> None:
    ran = _nested(tmp_path)
    assert [e["path"] for e in ran.of("step.start")] == [
        ["n_entry"],
        ["n_c1"],
        ["n_c1", "n_entry"],
        ["n_c1", "n_c2"],
        ["n_c1", "n_c2", "n_entry"],
        ["n_c1", "n_c2", "n_x"],
        ["n_c1", "n_c2", "n_exit"],
        ["n_c1", "n_exit"],
        ["n_pass"],
    ]
    (log,) = ran.of("log")
    x = next(e for e in ran.of("step.start") if e["node"] == "n_x")
    assert (log["step"], log["node"], log["message"]) == (x["step"], "n_x", "안쪽")


def test_step_end_fields_match_doc(tmp_path: Path) -> None:
    ran = _nested(tmp_path)
    for start in ran.of("step.start"):
        assert set(start) == DOC_START
        assert start["attempt"] == 1
    for end in ran.of("step.end"):
        assert DOC_END <= set(end) <= DOC_END | END_OPTIONAL
        assert end["status"] in {"success", "fail", "error", "cancelled"}
        assert isinstance(end["duration_ms"], int)
    calls = [e for e in ran.of("step.end") if "graph" in e]
    assert [(e["graph"], e["exit"], e["status"]) for e in calls] == [
        (INNER, "done", "success"),
        (OUTER, "done", "success"),
    ]


def test_fail_and_error_fields(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_f")
        .node("n_f", "testkit.fail_once", inputs={"exit": "fail"}, next={"fail": "n_boom"})
        .node("n_boom", "testkit.boom", inputs={"message": "펑"})
    )
    ran = run_graph(make_workspace(tmp_path), g)
    fail = ran.end("n_f")
    assert (fail["status"], fail["exit"], fail["message"]) == (
        "fail",
        "fail",
        "testkit.fail_once: fail",
    )
    error = ran.end("n_boom")
    assert (error["status"], error["exit"]) == ("error", None)
    assert error["error"] == {"code": "node_error", "message": "RuntimeError: 펑"}


def test_event_value_masks_secrets_and_flattens_types() -> None:
    value = {"pw": Secret("hunter2"), "m": Match(Rect(1, 2, 3, 4), 0.5), "xs": (1, [Secret("a")])}
    assert event_value(value) == {
        "pw": "***",
        "m": {
            "rect": {"x": 1, "y": 2, "width": 3, "height": 4},
            "score": 0.5,
            "window": None,
            "frame": None,
        },
        "xs": [1, ["***"]],
    }
