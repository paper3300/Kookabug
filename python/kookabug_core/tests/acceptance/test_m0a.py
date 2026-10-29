"""M0a 완료 기준 (구현 계획 v0 1장) 인수 테스트.

다른 테스트 모듈을 import하지 않고 그래프를 여기서 따로 만든다. 자세한 경우는 각 작업의 테스트에
있다 (`tests/engine/*`, `tests/validate/*`, `tests/schema/*`).
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fixtures.doc_examples.stub_nodes import registry_with_stubs
from helpers.graphs import GraphBuilder, check, check_program, link, make_workspace, write_json
from helpers.run import Ran, run_graph, tk
from testkit import registry_with_testkit

from kb_testing.doc_examples import json_blocks
from kookabug_core.schema import check_shape
from kookabug_core.workspace import LOCAL_FILE, WORKSPACE_FILE, Workspace
from kookabug_sdk.testing import InputCall
from kookabug_sdk.types import Point

OK = {"a": 1, "op": "==", "b": 1}


def _exits(ran: Ran, node: str) -> list[str | None]:
    steps = {e["step"] for e in ran.starts(node)}
    return [e["exit"] for e in ran.of("step.end") if e["step"] in steps]


# ---------------------------------------------------------------- 1. 판정 순서표


def _row(name: str) -> GraphBuilder:
    g = tk()
    if name == "error_over_assert":
        g.entry("n_ok").node("n_ok", "core.assert.compare", inputs=OK, next={"ok": "n_x"})
        g.node("n_x", "testkit.boom")
    elif name == "unhandled_fail_over_pass":
        g.entry("n_ok").node("n_ok", "core.assert.compare", inputs=OK, next={"ok": "n_x"})
        g.node("n_x", "testkit.fail_once", inputs={"exit": "fail"}, next={"ok": "n_pass"})
        g.node("n_pass", "core.test.pass")
    elif name in {"test_fail_over_assert", "skip_over_assert"}:
        terminal = "core.test.fail" if name == "test_fail_over_assert" else "core.test.skip"
        g.entry("n_ok").node("n_ok", "core.assert.compare", inputs=OK, next={"ok": "n_x"})
        g.node("n_x", terminal, inputs={"reason": "끝"})
    elif name == "assert_then_end":
        g.entry("n_x").node("n_x", "core.assert.compare", inputs=OK)
    elif name == "test_pass_only":
        g.entry("n_x").node("n_x", "core.test.pass")
    elif name == "no_assertion":
        g.entry("n_x").node("n_x", "core.log.message", inputs={"text": "검증 없음"})
    return g


@pytest.mark.parametrize(
    ("row", "verdict", "code", "failure_node"),
    [
        ("error_over_assert", "error", "node_error", "n_x"),  # 1행
        ("unhandled_fail_over_pass", "fail", "unhandled_fail", "n_x"),  # 2행
        ("test_fail_over_assert", "fail", "test_fail", "n_x"),  # 3행
        ("skip_over_assert", "skipped", "test_skip", "n_x"),  # 4행
        ("assert_then_end", "pass", "assertion_passed", None),  # 5행
        ("test_pass_only", "pass", "test_pass", None),  # 5행
        ("no_assertion", "fail", "no_assertion", None),  # 6행
    ],
)
def test_verdict_table_rows(
    tmp_path: Path, row: str, verdict: str, code: str, failure_node: str | None
) -> None:
    ran = run_graph(make_workspace(tmp_path), _row(row))
    r = ran.result
    assert (r.verdict, r.code) == (verdict, code)
    assert r.failure_path == ((failure_node,) if failure_node else None)


# ---------------------------------------------------------------- 2. 반복 안 변수 → 다음 조건


def test_loop_var_changes_next_condition(tmp_path: Path) -> None:
    # 조건 var.get("stop") == false. 본문에서 index >= 2면 stop = true → 본문 3회 후 done
    g = (
        tk()
        .entry("n_init")
        .node(
            "n_init", "core.var.set", inputs={"name": "stop", "value": False}, next={"done": "n_w"}
        )
        .node("n_get", "core.var.get", inputs={"name": "stop"})
        .node(
            "n_cond",
            "core.logic.compare",
            inputs={"a": link("n_get.value"), "op": "==", "b": False},
        )
        .node(
            "n_w",
            "core.flow.while",
            inputs={"condition": link("n_cond.result"), "max_iterations": 10},
            next={"body": "n_br", "done": "n_ok"},
        )
        .node("n_late", "core.logic.compare", inputs={"a": link("n_w.index"), "op": ">=", "b": 2})
        .node(
            "n_br",
            "core.flow.branch",
            inputs={"condition": link("n_late.result")},
            next={"true": "n_stop"},
        )
        .node("n_stop", "core.var.set", inputs={"name": "stop", "value": True})
        .node("n_ok", "core.assert.compare", inputs=OK)
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"
    assert _exits(ran, "n_w") == ["body", "body", "body", "done"]
    assert _exits(ran, "n_br") == ["false", "false", "true"]


# ---------------------------------------------------------------- 3. 지난 반복 출력 참조 거부


def test_previous_iteration_output_rejected(tmp_path: Path) -> None:
    # 1회차에 n_make가 값을 만들고 2회차에 n_read가 읽는다
    g = (
        tk()
        .entry("n_loop")
        .node(
            "n_loop",
            "core.flow.repeat",
            inputs={"times": 2},
            next={"body": "n_br", "done": "n_pass"},
        )
        .node(
            "n_later", "core.logic.compare", inputs={"a": link("n_loop.index"), "op": ">", "b": 0}
        )
        .node(
            "n_br",
            "core.flow.branch",
            inputs={"condition": link("n_later.result")},
            next={"false": "n_make", "true": "n_read"},
        )
        .node("n_make", "testkit.fail_once", inputs={"exit": "ok", "value": 7})
        .node(
            "n_read", "core.assert.compare", inputs={"a": link("n_make.value"), "op": "==", "b": 7}
        )
        .node("n_pass", "core.test.pass")
    )
    ws = make_workspace(tmp_path)
    # 정적: 실행 전 검증 오류
    diags = check(ws, g.write(ws, "tests/t.graph.json"), registry=registry_with_testkit())
    assert [(d.code, d.node, d.pointer) for d in diags if d.severity == "error"] == [
        ("link_not_dominated", "n_read", "/nodes/n_read/in/a")
    ]
    # 런타임: 검증을 건너뛰어도 2회차에 지난 회차 값을 읽지 못한다
    ran = run_graph(ws, g, validate=False)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "link_missing", ("n_read",))
    assert ran.starts("n_read")[0]["iteration"] == 1


# ---------------------------------------------------------------- 4. 중첩 반복 done


def test_nested_loop_done(tmp_path: Path) -> None:
    # 바깥 2회, 안쪽 3회. 안쪽 본문 끝 → 안쪽 반복, 안쪽 done → 바깥 본문 계속 → 바깥 반복
    g = (
        tk()
        .entry("n_outer")
        .node(
            "n_outer", "core.flow.repeat", inputs={"times": 2}, next={"body": "n_a", "done": "n_ok"}
        )
        .node("n_a", "core.log.message", inputs={"text": "a"}, next={"done": "n_inner"})
        .node(
            "n_inner", "core.flow.repeat", inputs={"times": 3}, next={"body": "n_b", "done": "n_c"}
        )
        .node("n_b", "core.log.message", inputs={"text": "b"})
        .node("n_c", "core.log.message", inputs={"text": "c"})
        .node("n_ok", "core.assert.compare", inputs=OK)
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"
    one = ["n_a", "n_inner", "n_b", "n_inner", "n_b", "n_inner", "n_b", "n_inner", "n_c", "n_outer"]
    assert ran.order() == ["n_entry", "n_outer", *one, *one, "n_ok"]
    assert _exits(ran, "n_inner") == ["body", "body", "body", "done"] * 2
    assert _exits(ran, "n_outer") == ["body", "body", "done"]
    assert [e["iteration"] for e in ran.starts("n_b")] == [0, 1, 2, 0, 1, 2]
    assert [e["iteration"] for e in ran.starts("n_c")] == [0, 1]


# ---------------------------------------------------------------- 5. 재시도 시도 기록


def test_retry_attempts_recorded(tmp_path: Path) -> None:
    def build() -> GraphBuilder:
        return (
            tk()
            .entry("n_wait")
            .node(
                "n_wait",
                "testkit.observe.wait",
                inputs={"expect": "lobby", "timeout_ms": 0},
                config={"retry": {"max_attempts": 3, "on": ["timeout"]}},
                next={"found": "n_ok"},
            )
            .node("n_ok", "core.assert.compare", inputs=OK)
        )

    # 1회 실패 뒤 성공: attempt.end 1개, step.end attempt 2 + retried
    ran = run_graph(make_workspace(tmp_path / "a"), build(), frames=["title.png", "lobby.png"])
    assert ran.result.verdict == "pass"
    step = ran.step_of("n_wait")
    assert [(e["step"], e["attempt"], e["exit"]) for e in ran.of("attempt.end")] == [
        (step, 1, "timeout")
    ]
    end = ran.end("n_wait")
    assert (end["attempt"], end["status"], end["exit"], end.get("retried")) == (
        2,
        "success",
        "found",
        True,
    )

    # 다 써도 실패: attempt.end 2개, 마지막 step.end가 fail로 판정에 들어간다
    ran = run_graph(make_workspace(tmp_path / "b"), build(), frames=["title.png"])
    assert (ran.result.verdict, ran.result.failure_path) == ("fail", ("n_wait",))
    assert [e["attempt"] for e in ran.of("attempt.end")] == [1, 2]
    end = ran.end("n_wait")
    assert (end["attempt"], end["status"], end["exit"]) == (3, "fail", "timeout")


# ---------------------------------------------------------------- 6. 문서 예시 검증

ENTER_WORLD = "subgraphs/enter_world.graph.json"
INVENTORY_OPEN = "tests/inventory_open.graph.json"


def _target_refs(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        if set(value) == {"$target"}:
            yield value["$target"]
        else:
            for v in value.values():
                yield from _target_refs(v)
    elif isinstance(value, list):
        for v in value:
            yield from _target_refs(v)


def test_doc_examples_validate(tmp_path: Path) -> None:
    blocks = [b.data for b in json_blocks()]
    whole = [d for d in blocks if "format" in d]
    # 형식: format이 있는 예시 전부 (그래프 2·target·workspace)
    assert sorted(d["format"] for d in whole) == [
        "kookabug.graph/0",
        "kookabug.graph/0",
        "kookabug.target/0",
        "kookabug.workspace/0",
    ]
    for data in whole:
        assert check_shape(data) == [], data["format"]

    # 의미: 두 그래프를 문서 그대로 워크스페이스에 놓고 실행 전 검증 전체
    (subgraph,) = [d for d in whole if d.get("kind") == "subgraph"]
    (test,) = [d for d in whole if d.get("kind") == "test"]
    (target,) = [d for d in whole if d["format"] == "kookabug.target/0"]
    (workspace,) = [d for d in whole if d["format"] == "kookabug.workspace/0"]
    write_json(tmp_path, WORKSPACE_FILE, workspace)
    local = {"format": "kookabug.local/0", "settings": {"game.executable": "D:/Games/Sample.exe"}}
    write_json(tmp_path, LOCAL_FILE, local)
    for rel in sorted({*_target_refs(subgraph), *_target_refs(test)}):
        path = write_json(tmp_path, rel, target)
        (path.parent / target["image"]).write_bytes(b"\x89PNG\r\n\x1a\n")
    write_json(tmp_path, ENTER_WORLD, subgraph)
    write_json(tmp_path, INVENTORY_OPEN, test)
    program, diags = check_program(
        Workspace.open(tmp_path),
        INVENTORY_OPEN,
        registry=registry_with_stubs(),
        secrets={"accounts.qa_tester_01": "hunter2"},
    )
    assert sorted(program.graphs) == [ENTER_WORLD, INVENTORY_OPEN]
    assert diags == []


# ---------------------------------------------------------------- 7. 가짜 캡처·입력 실행


def test_fake_platform_run(tmp_path: Path) -> None:
    # 한 프로세스 안에서: 화면 대기(가짜 캡처) → 탭(가짜 입력) → 다음 화면 대기 → 검증
    g = (
        tk()
        .entry("n_title")
        .node(
            "n_title",
            "testkit.observe.wait",
            inputs={"expect": "title", "timeout_ms": 1000},
            next={"found": "n_tap"},
        )
        .node("n_tap", "testkit.input.tap", inputs={"x": 10, "y": 20}, next={"done": "n_lobby"})
        .node(
            "n_lobby",
            "testkit.observe.wait",
            inputs={"expect": "lobby", "timeout_ms": 1000},
            next={"found": "n_ok"},
        )
        .node("n_ok", "core.assert.compare", inputs=OK)
    )
    ran = run_graph(
        make_workspace(tmp_path), g, frames=["loading.png", "title.png", "title.png", "lobby.png"]
    )
    assert (ran.result.verdict, ran.result.code) == ("pass", "assertion_passed")
    assert ran.platform.input.calls == [InputCall("click", (Point(10, 20),), {"button": "left"})]
    assert ran.platform.captured == 4
    assert ran.end("n_lobby")["outputs"]["match"]["frame"] == 3
    assert ran.clock.now_ms() == 200  # 실제 시간이 아니라 FakeClock
