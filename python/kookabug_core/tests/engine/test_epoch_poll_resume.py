"""폴링 중 멈췄다 재개 (구현 계획 M3 2.4 "폴링 재개", 계획 검수 H2, T4).

대기 노드의 폴링 기다림(`ctx.sleep`)에서 멈췄다 재개하면 세대가 오른다. 그래서

1. 그 스텝이 시작 때 검사해 통과한 입력도 이제 재개 전 관측이다: 다음 관측·입력·출구 선택 전에
   `stale_observation`으로 끝난다
2. 노드가 들고 있던 관측(직전 프레임·안정 시작 시각·후보)은 버리고 재개 뒤 프레임으로 다시 잰다.
   버렸다고 알린 노드의 출력은 재개 뒤 관측이고, 알리지 않은 노드의 출력은 재개 전 관측으로 남는다

실제 코어 노드(`ocr.wait_text`·`screen.wait_stable`·`image.wait_any`)를 가짜 장면에서 돌린다.
"""

from __future__ import annotations

from pathlib import Path

from helpers.epoch import Debugger, SceneEngines, platform_with, run_debug, scene
from helpers.graphs import GraphBuilder, link, make_workspace, target
from helpers.m1 import Ran, ScenePlatform, clicks, write_target
from helpers.run import tk

from kookabug_sdk.types import Rect

A = "targets/a.target.json"
B = "targets/b.target.json"


def launch(first: str) -> GraphBuilder:
    return (
        tk()
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": first})
    )


def branch_on(source: str, equals: str, then: str = "n_pass") -> GraphBuilder:
    """`launch` 없이 붙일 꼬리: `n_cmp`(source == equals) → `n_br` → `then`."""
    return (
        GraphBuilder()
        .node("n_cmp", "core.logic.compare", inputs={"a": link(source), "op": "==", "b": equals})
        .node(
            "n_br",
            "core.flow.branch",
            inputs={"condition": link("n_cmp.result")},
            next={"true": then},
        )
    )


def with_tail(g: GraphBuilder, tail: GraphBuilder) -> GraphBuilder:
    g.nodes.update(tail.nodes)
    return g


def run(
    tmp_path: Path, graph: GraphBuilder, engines: SceneEngines, dbg: Debugger
) -> tuple[Ran, ScenePlatform]:
    ws = make_workspace(tmp_path)
    write_target(ws, A)
    write_target(ws, B)
    platform = platform_with(engines)
    return run_debug(ws, graph, platform, dbg), platform


def test_poll_resume_stale_contains_input_fails_before_next_observation(tmp_path: Path) -> None:
    """OCR 글자를 `wait_text.contains`에 연결하고 그 노드 폴링 중 멈춤 → 재개 → 다음 캡처·출구
    선택 없이 `stale_observation`, 뒤 분기는 실행하지 않는다."""
    g = with_tail(
        launch("n_read")
        .node("n_read", "core.ocr.read", next={"done": "n_set"})
        # 읽은 글자(string|secret)를 string 핀에 잇는 길: 변수 → var.get(any)
        .node(
            "n_set",
            "core.var.set",
            inputs={"name": "t", "value": link("n_read.text")},
            next={"done": "n_wait"},
        )
        .node("n_get", "core.var.get", inputs={"name": "t"})
        .node(
            "n_wait",
            "core.ocr.wait_text",
            inputs={"contains": link("n_get.value"), "timeout_ms": 5000},
            next={"found": "n_br", "timeout": "n_fail"},
        )
        .node("n_pass", "core.test.pass")
        .node("n_fail", "core.test.fail"),
        branch_on("n_wait.text", "START"),
    )
    # 첫 읽기 "START", 그 뒤 화면에는 그 글자가 없다 (계속 폴링한다)
    engines = SceneEngines(script=["START", "LOADING"])
    ran, _ = run(tmp_path, g, engines, Debugger(poll={"n_wait": 1}))
    result = ran.result
    assert (result.verdict, result.code, result.failure_path) == (
        "fail",
        "unhandled_fail",
        ("n_wait",),
    ), result.reason
    end = ran.end("n_wait")
    assert (end["status"], end["exit"]) == ("fail", None)
    assert str(end["message"]).startswith("stale_observation:")
    assert "'contains'" in end["message"] and "'n_read'" in end["message"]
    assert len(engines.reads) == 2  # n_read 한 번 + n_wait 재개 전 한 번 — 재개 뒤 관측 없음
    assert "n_br" not in [e["node"] for e in ran.of("step.start")]


def test_wait_stable_resume_discards_previous_frame_and_restarts_stability(
    tmp_path: Path,
) -> None:
    """화면이 그대로여도 재개 전 프레임과 비교하지 않고, 안정 시간을 재개 뒤 프레임만으로 다시 잰다
    (멈추기 전 100ms 안정은 버린다 → 재개 뒤 300ms를 다시 채운다)."""
    g = (
        launch("n_ws")
        .node(
            "n_ws",
            "core.screen.wait_stable",
            inputs={"stable_ms": 300, "timeout_ms": 5000},
            next={"stable": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    engines = SceneEngines()
    dbg = Debugger(poll={"n_ws": 3})  # 두 번째 폴링 기다림 (캡처 2장 뒤)
    ran, _ = run(tmp_path, g, engines, dbg)
    assert ran.result.verdict == "pass", ran.result.reason
    assert dbg.pauses == [("n_ws", "poll")]
    # 재개 전: (1, 2). 재개 뒤: 3부터 새로 — 재개 전 프레임 2와 비교하지 않는다
    assert engines.diffs == [(1, 2), (3, 4), (4, 5), (5, 6)]


def test_node_without_reset_keeps_old_floor_outputs_stale(tmp_path: Path) -> None:
    """관측을 버렸다고 알리지 않는 노드(시험용)의 출력은 재개 전 세대 → 뒤 분기가 실패한다."""
    g = with_tail(
        launch("n_hold").node(
            "n_hold", "testkit.epoch.hold_poll", inputs={"polls": 3}, next={"done": "n_br"}
        ),
        branch_on("n_hold.scene", "title"),
    ).node("n_pass", "core.test.pass")
    ran, _ = run(tmp_path, g, SceneEngines(), Debugger(poll={"n_hold": 2}))
    assert ran.end("n_hold")["status"] == "success"
    assert (ran.result.verdict, ran.result.failure_path) == ("fail", ("n_br",))
    assert str(ran.end("n_br")["message"]).startswith("stale_observation:")


def test_core_wait_resets_and_outputs_fresh_value(tmp_path: Path) -> None:
    """버렸다고 알리는 코어 대기 노드는 재개 뒤 관측으로 출력한다 → 뒤 분기가 그대로 돈다."""
    g = with_tail(
        launch("n_wait").node(
            "n_wait",
            "core.ocr.wait_text",
            inputs={"contains": "LOBBY", "timeout_ms": 5000},
            next={"found": "n_br"},
        ),
        branch_on("n_wait.text", "LOBBY"),
    ).node("n_pass", "core.test.pass")
    holder: dict[str, ScenePlatform] = {}

    def to_lobby(d: Debugger, point: object) -> None:
        scene(holder["platform"], "lobby")

    engines = SceneEngines(texts={"title": "START", "lobby": "LOBBY"})
    platform = platform_with(engines)
    holder["platform"] = platform
    ran = run_debug(
        make_workspace(tmp_path), g, platform, Debugger(poll={"n_wait": 1}, while_paused=to_lobby)
    )
    assert ran.result.verdict == "pass", ran.result.reason
    assert ran.end("n_br")["exit"] == "true"


def test_wait_any_resume_clears_best_candidate(tmp_path: Path) -> None:
    """`wait_any`는 폴링 사이에 후보를 쥐지 않는다(한 프레임 안에서 순서대로 찾음). 그래서 확인하는
    것은 재개 뒤 공용 폴링이 바닥을 되돌린다는 것: 멈춘 동안 화면이 바뀌면 재개 뒤 프레임에서 찾은
    후보로 나가고 그 출력은 재개 뒤 관측이다 (클릭은 다시 찾지 않고 그 자리로, 뒤 일반 스텝도
    받는다). 폴링을 넘어 쥔 관측을 버리는 것은 `test_assert_text_resume_discards_last_read_text`."""
    box = Rect(600, 300, 100, 40)
    g = (
        launch("n_any")
        .node(
            "n_any",
            "core.image.wait_any",
            config={"exits": ["a", "b"]},
            inputs={"targets": {"a": target(A), "b": target(B)}, "timeout_ms": 5000},
            next={"a": "n_use", "b": "n_pass"},
        )
        .node(
            "n_use",
            "testkit.epoch.use",
            inputs={"value": link("n_any.match")},
            next={"done": "n_click"},
        )
        .node(
            "n_click",
            "core.input.click",
            inputs={"match": link("n_any.match")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    engines = SceneEngines(where={A: {"lobby": box}})
    holder: dict[str, ScenePlatform] = {}

    def to_lobby(d: Debugger, point: object) -> None:
        scene(holder["platform"], "lobby")

    ws = make_workspace(tmp_path)
    write_target(ws, A)
    write_target(ws, B)
    platform = platform_with(engines)
    holder["platform"] = platform
    ran = run_debug(ws, g, platform, Debugger(poll={"n_any": 1}, while_paused=to_lobby))
    assert ran.result.verdict == "pass", ran.result.reason
    assert ran.end("n_any")["exit"] == "a"
    hwnd = platform.scenario.latest().window.handle
    assert clicks(platform) == [(hwnd, box.center.x, box.center.y)]
    # 재개 전 프레임(title)에서 a·b 한 번씩, 재개 뒤 lobby에서 a를 찾음 — 클릭 전 다시 찾기 없음
    assert engines.finds == [(A, "title"), (B, "title"), (A, "lobby")]


def test_assert_text_resume_discards_last_read_text(tmp_path: Path) -> None:
    """`assert.text`가 폴링을 넘어 쥔 마지막 읽은 글자도 재개 때 버린다 (검수 T4-1 High 2).

    재개 전: 영역 A가 보이고 글자 "READY"(조건 "OK"와 다름) → 폴링 중 멈춤 → 멈춘 동안 영역이
    사라짐 → 재개 뒤 OCR 없이 기한 → fail 출구 `text`는 재개 전 글자가 아니다(빈 글자) → 뒤 분기가
    재개 전 OCR 글자로 `true`에 가지 않는다."""
    box = Rect(412, 380, 200, 64)
    g = (
        launch("n_at")
        .node(
            "n_at",
            "core.assert.text",
            inputs={"region": target(A), "contains": "OK", "timeout_ms": 1000},
            next={"ok": "n_pass", "fail": "n_br"},
        )
        .node(
            "n_cmp", "core.logic.compare", inputs={"a": link("n_at.text"), "op": "==", "b": "READY"}
        )
        .node(
            "n_br",
            "core.flow.branch",
            inputs={"condition": link("n_cmp.result")},
            next={"true": "n_pass", "false": "n_fail"},
        )
        .node("n_pass", "core.test.pass")
        .node("n_fail", "core.test.fail")
    )
    engines = SceneEngines(where={A: {"title": box}}, texts={"title": "READY", "lobby": "LOBBY"})
    holder: dict[str, ScenePlatform] = {}

    def to_lobby(d: Debugger, point: object) -> None:
        scene(holder["platform"], "lobby")

    ws = make_workspace(tmp_path)
    write_target(ws, A)
    platform = platform_with(engines)
    holder["platform"] = platform
    dbg = Debugger(poll={"n_at": 1}, while_paused=to_lobby)
    ran = run_debug(ws, g, platform, dbg)
    assert dbg.pauses == [("n_at", "poll")]
    assert len(engines.reads) == 1  # 재개 뒤에는 영역을 못 찾아 읽지 않았다
    end = ran.end("n_at")
    assert end["exit"] == "fail"
    assert end["outputs"]["text"] != "READY"  # 재개 전 글자를 내지 않는다
    assert ran.end("n_br")["exit"] == "false"
    assert (ran.result.verdict, ran.result.code) == ("fail", "test_fail"), ran.result.reason
