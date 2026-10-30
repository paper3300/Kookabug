"""공통 입력 `window`와 `ctx.set_window`의 실행기 쪽 (구현 계획 M1 2.8): 그 스텝 ctx·그 스텝 입력
요청의 창만 바꾸고, `set_window`는 호출 프레임의 현재 창을 다음 스텝부터 바꾼다. 서브그래프는 부른
쪽의 창을 이어받고, 안에서 바꾼 것은 밖으로 나오지 않는다. 공통 `window`는 노드 함수 인자·서브그래프
입력·서브그래프 출력으로 새지 않는다."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import link, make_workspace, subgraph_interface
from helpers.m1 import ScenePlatform, clicks, run_on
from helpers.run import run_graph, tk

from kookabug_core.engine import InProcessInvoker
from kookabug_core.ir import Node
from kookabug_core.registry import NodeDef
from kookabug_sdk import Result
from kookabug_sdk.context import Context
from kookabug_sdk.types import WindowRef

SUB = "subgraphs/inner.graph.json"
A, B = WindowRef(0x100), WindowRef(0x200)


class RetrySetsWindow(InProcessInvoker):
    """`n_start`는 현재 창을 `start`로, `n_wait`는 시도마다 `ctx.window`를 남기고 `set_window(B)`
    한 뒤 첫 시도는 재시도 출구(`timeout`), 둘째는 `found`. `n_after`는 자기 창을 남긴다."""

    def __init__(self, start: WindowRef | None) -> None:
        self.start = start
        self.seen: list[WindowRef | None] = []
        self.after: list[WindowRef | None] = []

    def invoke(
        self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
    ) -> Result:
        if node.id == "n_start":
            if self.start is not None:
                ctx.set_window(self.start)
            return Result("done", "ok")
        if node.id == "n_wait":
            self.seen.append(ctx.window)
            ctx.set_window(B)
            return Result("timeout", "fail") if len(self.seen) == 1 else Result("found", "ok")
        if node.id == "n_after":
            self.after.append(ctx.window)
            return Result("done", "ok")
        return super().invoke(nodedef, node, ctx, inputs)


@pytest.mark.parametrize("start", [A, None], ids=["window", "none"])
def test_retry_keeps_step_start_window(tmp_path: Path, start: WindowRef | None) -> None:
    """재시도의 모든 시도가 스텝 시작 때의 창을 쓴다 (시작 창이 None이어도 None 그대로). 앞
    시도의 `set_window`는 다음 스텝부터 (T9 검수 2)."""
    g = (
        tk()
        .entry("n_start")
        .node(
            "n_start", "testkit.m1.set_window", inputs={"title": "unused"}, next={"done": "n_wait"}
        )
        .node(
            "n_wait",
            "testkit.observe.wait",
            inputs={"expect": "lobby", "timeout_ms": 0},
            config={"retry": {"max_attempts": 2}},
            next={"found": "n_after"},
        )
        .node("n_after", "testkit.m1.window", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    invoker = RetrySetsWindow(start)
    ran = run_graph(make_workspace(tmp_path), g, invoker=invoker)
    assert ran.result.verdict == "pass", ran.result.reason
    assert invoker.seen == [start, start]
    assert invoker.after == [B]


def test_window_input_applies_to_that_step_only(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    platform = ScenePlatform.sample()
    g = (
        tk()
        .entry("n_a")
        .node("n_a", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_b"})
        .node("n_b", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_w1"})
        .node(
            "n_w1",
            "testkit.m1.window",
            inputs={"window": link("n_a.window")},
            next={"done": "n_c1"},
        )
        .node(
            "n_c1",
            "testkit.input.tap",
            inputs={"x": 1, "y": 1, "window": link("n_a.window")},
            next={"done": "n_w2"},
        )
        .node("n_w2", "testkit.m1.window", next={"done": "n_c2"})
        .node("n_c2", "testkit.input.tap", inputs={"x": 2, "y": 2}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    ran = run_on(ws, g, platform)
    assert ran.result.verdict == "pass", ran.result.reason
    a = ran.end("n_a")["outputs"]["handle"]
    b = ran.end("n_b")["outputs"]["handle"]
    assert ran.end("n_w1")["outputs"]["handle"] == a
    assert ran.end("n_w2")["outputs"]["handle"] == b  # 다음 스텝은 다시 현재 창
    assert clicks(platform) == [(a, 1, 1), (b, 2, 2)]


def test_set_window_frame_scoped_and_inherited_by_subgraph(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    platform = ScenePlatform.sample()
    (
        tk("subgraph", interface=subgraph_interface())
        .entry("n_w")
        .node("n_w", "testkit.m1.window", next={"done": "n_x"})
        .exit("n_x", "done")
        .write(ws, SUB)
    )
    g = (
        tk()
        .entry("n_a")
        .node("n_a", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_b"})
        .node("n_b", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_set"})
        .node("n_set", "testkit.m1.set_window", inputs={"title": "Sample"}, next={"done": "n_call"})
        .node("n_call", "core.graph.call", config={"graph": SUB}, next={"done": "n_call2"})
        .node(
            "n_call2",
            "core.graph.call",
            config={"graph": SUB},
            inputs={"window": link("n_a.window")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run_on(ws, g, platform)
    assert ran.result.verdict == "pass", ran.result.reason
    b = ran.end("n_b")["outputs"]["handle"]
    a = ran.end("n_a")["outputs"]["handle"]
    found = ran.end("n_set")["outputs"]
    # set_window한 노드 자신의 ctx.window는 그대로(B), 찾은 창(가장 앞 = B)이 다음 스텝부터
    assert found["kept"] == b and found["handle"] == b
    inner = ran.ends("n_w")
    assert [e["outputs"]["handle"] for e in inner] == [b, a]  # 이어받음, in.window = 시작 창


def test_subgraph_window_change_not_leaked(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    platform = ScenePlatform.sample()
    (
        tk("subgraph", interface=subgraph_interface())
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_x"})
        .exit("n_x", "done", inputs={"window": link("n_launch.window")})
        .write(ws, SUB)
    )
    g = (
        tk()
        .entry("n_a")
        .node("n_a", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_call"})
        .node("n_call", "core.graph.call", config={"graph": SUB}, next={"done": "n_w"})
        .node("n_w", "testkit.m1.window", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    ran = run_on(ws, g, platform)
    assert ran.result.verdict == "pass", ran.result.reason
    a = ran.end("n_a")["outputs"]["handle"]
    inner = ran.end("n_launch")["outputs"]["handle"]
    assert inner != a
    assert ran.end("n_w")["outputs"]["handle"] == a  # 안에서 띄운 창은 밖의 현재 창이 아니다
    # exit 노드의 공통 window는 서브그래프 출력으로 새지 않는다
    assert ran.end("n_call")["outputs"] == {}
