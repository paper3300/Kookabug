"""값의 관측 출처 전파 (구현 계획 M3 2.4 "값의 출처", T4).

실행기는 값 옆에 "기댄 가장 오래된 관측의 세대"를 붙여 출력 표·순수 노드 계산·변수·서브그래프
경계로 옮긴다. 출력 출처는 그 스텝의 관측 바닥(입력·캡처·읽은 변수 중 가장 오래된 것)이고 끝난
시각의 세대가 아니다. 관측과 무관한 값(설정·상수·반복 회차)은 출처가 없어 재개 뒤에도 쓸 수 있다.

출처는 재개 뒤 그 값을 받은 일반 스텝(`testkit.epoch.use`·분기)의 `stale_observation` 메시지(출처
노드·세대)로 확인한다.
"""

from __future__ import annotations

from pathlib import Path

from helpers.epoch import Debugger, SceneEngines, platform_with, run_debug, scene
from helpers.graphs import GraphBuilder, link, make_workspace, setting, subgraph_interface
from helpers.m1 import Ran, ScenePlatform
from helpers.run import tk

SUB = "subgraphs/read.graph.json"
TEXTS = {"title": "START", "lobby": "LOBBY"}


def launch(first: str) -> GraphBuilder:
    return (
        tk()
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": first})
    )


def run(
    tmp_path: Path, graph: GraphBuilder, dbg: Debugger | None = None, **subs: GraphBuilder
) -> Ran:
    ws = make_workspace(tmp_path, settings={"expected": "START"})
    for rel, sub in subs.items():
        sub.write(ws, rel.replace("__", "/") + ".graph.json")
    platform: ScenePlatform = platform_with(SceneEngines(texts=dict(TEXTS)))
    return run_debug(ws, graph, platform, dbg)


def stale_message(ran: Ran, node: str) -> str:
    result = ran.result
    assert (result.verdict, result.failure_path) == ("fail", (node,)), result.reason
    message = str(ran.end(node)["message"])
    assert message.startswith("stale_observation:"), message
    return message


def test_capture_outputs_tagged_with_step_floor_not_end_epoch(tmp_path: Path) -> None:
    """폴링 중 멈췄다 재개한 뒤 다시 캡처하고 끝난 스텝이라도, 재개 전 관측을 버렸다고 알리지
    않았으면 출력은 재개 전 세대다 (끝난 시각의 세대로 세탁되지 않는다)."""
    g = (
        launch("n_hold")
        .node("n_hold", "testkit.epoch.hold_poll", inputs={"polls": 3}, next={"done": "n_use"})
        .node(
            "n_use",
            "testkit.epoch.use",
            inputs={"value": link("n_hold.scene")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run(tmp_path, g, Debugger(poll={"n_hold": 2}))
    assert ran.end("n_hold")["status"] == "success"  # 재개 뒤 캡처까지 하고 끝났다
    message = stale_message(ran, "n_use")
    assert "'n_hold'" in message and "세대 0 < 지금 1" in message


def test_pure_node_inherits_oldest_epoch(tmp_path: Path) -> None:
    """재개 뒤 새로 읽은 값만 쓰는 순수 계산은 통과하고, 재개 전 값이 하나라도 섞이면 가장 오래된
    출처(재개 전 읽기)로 실패한다."""
    g = (
        launch("n_old")
        .node("n_old", "core.ocr.read", next={"done": "n_new"})
        .node("n_new", "core.ocr.read", next={"done": "n_br1"})
        .node(
            "n_fresh",
            "core.logic.compare",
            inputs={"a": link("n_new.text"), "op": "==", "b": "START"},
        )
        .node(
            "n_br1",
            "core.flow.branch",
            inputs={"condition": link("n_fresh.result")},
            next={"true": "n_br2"},
        )
        .node(
            "n_mixed",
            "core.logic.compare",
            inputs={"a": link("n_old.text"), "op": "==", "b": link("n_new.text")},
        )
        .node(
            "n_br2",
            "core.flow.branch",
            inputs={"condition": link("n_mixed.result")},
            next={"true": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run(tmp_path, g, Debugger(at={"n_new"}))
    assert ran.end("n_br1")["exit"] == "true"
    message = stale_message(ran, "n_br2")
    assert "'n_old'" in message and "세대 0" in message


def test_var_set_get_keeps_epoch(tmp_path: Path) -> None:
    """변수에 저장한 관측값은 세대를 같이 저장한다: 재개 뒤 `var.get`으로 읽어 분기하면 실패, 재개
    전에 같은 세대 안에서 분기하면 통과."""
    g = (
        launch("n_read")
        .node("n_read", "core.ocr.read", next={"done": "n_set"})
        .node(
            "n_set",
            "core.var.set",
            inputs={"name": "t", "value": link("n_read.text")},
            next={"done": "n_br1"},
        )
        .node("n_get", "core.var.get", inputs={"name": "t"})
        .node(
            "n_cmp",
            "core.logic.compare",
            inputs={"a": link("n_get.value"), "op": "==", "b": "START"},
        )
        .node(
            "n_br1",
            "core.flow.branch",
            inputs={"condition": link("n_cmp.result")},
            next={"true": "n_br2"},
        )
        .node(
            "n_br2",
            "core.flow.branch",
            inputs={"condition": link("n_cmp.result")},
            next={"true": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run(tmp_path, g, Debugger(at={"n_br2"}))
    assert ran.end("n_br1")["exit"] == "true"
    assert "'n_read'" in stale_message(ran, "n_br2")


def test_subgraph_exit_carries_epoch_to_call_outputs(tmp_path: Path) -> None:
    """서브그래프 안에서 읽은 값은 exit → 호출 노드 출력으로 세대를 같이 넘긴다."""
    sub = (
        tk("subgraph", interface=subgraph_interface(outputs={"text": "any"}))
        .entry("n_in")
        .node("n_in", "core.ocr.read", next={"done": "n_exit"})
        .exit("n_exit", "done", inputs={"text": link("n_in.text")})
    )
    g = (
        launch("n_call")
        .call("n_call", SUB, next={"done": "n_use"})
        .node(
            "n_use",
            "testkit.epoch.use",
            inputs={"value": link("n_call.text")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run(tmp_path, g, Debugger(at={"n_use"}), subgraphs__read=sub)
    assert "'n_call/n_in'" in stale_message(ran, "n_use")


def test_subgraph_input_carries_epoch(tmp_path: Path) -> None:
    """호출 노드는 재개 전 값을 받아 넘기고(예외 목록), 서브그래프 안에서 그 값을 쓰는 스텝이
    실패한다."""
    sub = (
        tk("subgraph", interface=subgraph_interface(inputs={"t": "any"}))
        .entry("n_use")
        .node(
            "n_use",
            "testkit.epoch.use",
            inputs={"value": link("n_entry.t")},
            next={"done": "n_exit"},
        )
        .exit("n_exit", "done")
    )
    g = (
        launch("n_read")
        .node("n_read", "core.ocr.read", next={"done": "n_call"})
        .call("n_call", SUB, inputs={"t": link("n_read.text")}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    ran = run(tmp_path, g, Debugger(at={"n_call"}), subgraphs__read=sub)
    result = ran.result
    assert (result.verdict, result.failure_path) == ("fail", ("n_call", "n_use")), result.reason
    assert ran.end("n_call")["status"] == "fail"


def test_settings_and_constants_have_no_epoch(tmp_path: Path) -> None:
    """설정·상수·반복 회차(`index`)는 관측과 무관하다: 재개 뒤에도 분기한다."""
    g = (
        launch("n_read")
        .node("n_read", "core.ocr.read", next={"done": "n_loop"})
        .node(
            "n_loop",
            "core.flow.repeat",
            inputs={"times": 2},
            next={"body": "n_br", "done": "n_br2"},
        )
        .node("n_cmp", "core.logic.compare", inputs={"a": link("n_loop.index"), "op": "<", "b": 5})
        .node("n_br", "core.flow.branch", inputs={"condition": link("n_cmp.result")})
        .node(
            "n_cmp2",
            "core.logic.compare",
            inputs={"a": setting("expected"), "op": "==", "b": "START"},
        )
        .node(
            "n_br2",
            "core.flow.branch",
            inputs={"condition": link("n_cmp2.result")},
            next={"true": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    dbg = Debugger(at={"n_loop", "n_br", "n_br2"}, while_paused=lambda d, p: None)
    ran = run(tmp_path, g, dbg)
    assert ran.result.verdict == "pass", ran.result.reason
    assert dbg.epochs.current == 3


def test_scene_change_while_paused_not_seen_by_old_value(tmp_path: Path) -> None:
    """멈춘 동안 화면이 바뀌어도 재개 뒤 새로 읽으면 새 값이다 (세대는 화면이 아니라 재개를
    센다)."""
    g = (
        launch("n_read")
        .node("n_read", "core.ocr.read", next={"done": "n_use"})
        .node(
            "n_use",
            "testkit.epoch.use",
            inputs={"value": link("n_read.text")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    holder: dict[str, ScenePlatform] = {}

    def lobby(d: Debugger, point: object) -> None:
        scene(holder["platform"], "lobby")

    ws = make_workspace(tmp_path)
    platform = platform_with(SceneEngines(texts=dict(TEXTS)))
    holder["platform"] = platform
    ran = run_debug(ws, g, platform, Debugger(at={"n_read"}, while_paused=lobby))
    assert ran.result.verdict == "pass", ran.result.reason
    assert ran.end("n_use")["outputs"] == {"value": "LOBBY"}
