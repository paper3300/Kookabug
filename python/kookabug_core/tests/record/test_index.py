"""실행 색인 (M3 계획 2.7, T7): 스텝 트리·반복 회차 묶음·실패 사슬·통계·늘리기·캐시.

- 실행기 이벤트는 실제 실행기(같은 프로세스)로 만들어 실행 폴더 모양으로 쓴다(`seq`·`t`를 붙임)
- 입력 계산 실패 세 가지(2차 N1)와 경계 취소는 실제 runner로 만든 실행 폴더를 읽는다
- 예전 실행 폴더(M0b·M2 예제, 스냅샷 없음)도 읽힌다
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder, link, make_workspace, secret, subgraph_interface
from helpers.run import TEST, run_graph, tk
from helpers.runner import RunnerHarness
from helpers.video import launch, write_scenario

from kb_testing.proc import Spawned, wait_until
from kookabug_core.engine.debug import Breakpoint
from kookabug_core.record.index import (
    RunIndex,
    RunState,
    cached_index,
    thumbnails,
    video_view,
)
from kookabug_core.record.video import TEST_ENV
from kookabug_core.schema import check_shape

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "run-history"
SUB = "subgraphs/s.graph.json"
BASE = datetime(2026, 11, 2, 1, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------- 도움


def stamp(ms: int) -> str:
    return (BASE + timedelta(milliseconds=ms)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def write_events(
    folder: Path, events: Iterable[Mapping[str, Any]], *, run: str = "abcd1234"
) -> Path:
    """이벤트에 `seq`·`t`·`run`을 붙여 `events.jsonl`로 쓴다 (`t`는 1 ms씩)."""
    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, event in enumerate(events, start=1):
        line = {**event, "seq": i, "run": run}
        line.setdefault("t", stamp(i))
        lines.append(json.dumps(line, ensure_ascii=False))
    (folder / "events.jsonl").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return folder


def executor_run(
    tmp_path: Path, graph: GraphBuilder, subgraphs: Mapping[str, GraphBuilder] = {}
) -> Path:
    """실제 실행기로 돌린 이벤트를 실행 폴더로 쓴다 (스냅샷 포함)."""
    ws = make_workspace(tmp_path / "ws")
    for rel, sub in subgraphs.items():
        sub.write(ws, rel)
    ran = run_graph(ws, graph)
    folder = tmp_path / "runs" / "2026-11-02T01-00-00_t_abcd1234"
    head = {"event": "run.start", "graph": TEST, "protocol": 1, "runner": {"pid": 1}}
    res = ran.result
    tail = {
        "event": "run.end",
        "verdict": res.verdict,
        "code": res.code,
        "reason": res.reason,
        "failure_step": res.failure_step,
        "failure_path": None if res.failure_path is None else list(res.failure_path),
        "finalized_by": "runner",
        "duration_ms": 1,
    }
    write_events(folder, [head, *ran.events, tail])
    for rel in (TEST, *subgraphs):
        target = folder / "snapshot" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ws.root / rel, target)
    return folder


def result(index: RunIndex, state: RunState = "ended") -> dict[str, Any]:
    out = index.result(
        run_dir=f"runs/{index.folder.name}",
        state=state,
        run_json=None,
        video=video_view(index.folder),
        thumbs=thumbnails(index.folder),
    )
    assert check_shape(out, "run-index") == []
    return out


def by_node(index: RunIndex, node: str) -> list[str]:
    return [r.step for r in index.rows.values() if r.node == node]


def loop_graph() -> tuple[GraphBuilder, dict[str, GraphBuilder]]:
    """반복 3회 안에 (서브그래프 호출 → 안쪽 반복 2회 → 회차 검사). 마지막 회차의 검사가
    실패한다."""
    sub = GraphBuilder("subgraph", interface=subgraph_interface()).entry("n_x")
    sub.node("n_x", "core.log.message", inputs={"text": "x"}, next={"done": "n_exit"})
    sub.exit("n_exit", "done")
    graph = (
        tk()
        .entry("n_loop")
        .node(
            "n_loop",
            "core.flow.repeat",
            inputs={"times": 3},
            next={"body": "n_c", "done": "n_pass"},
            title="세 번",
        )
        .call("n_c", SUB, next={"done": "n_in"})
        .node(
            "n_in", "core.flow.repeat", inputs={"times": 2}, next={"body": "n_log", "done": "n_chk"}
        )
        .node("n_log", "core.log.message", inputs={"text": "안"})
        .node(
            "n_chk",
            "core.assert.compare",
            inputs={"a": link("n_loop.index"), "op": "<", "b": 2},
            title="회차 검사",
        )
        .node("n_pass", "core.test.pass")
    )
    return graph, {SUB: sub}


# ---------------------------------------------------------------- 트리·실패 사슬


@pytest.mark.parametrize("snapshot", [True, False])
def test_index_tree_and_failure_chain(tmp_path: Path, snapshot: bool) -> None:
    graph, subs = loop_graph()
    folder = executor_run(tmp_path, graph, subs)
    if not snapshot:
        # 스냅샷이 없는 폴더는 출구 body로 반복 스텝을 안다
        shutil.rmtree(folder / "snapshot")
    index = RunIndex(folder).update()
    out = result(index)

    (loop,) = [s for s in out["steps"] if s["node"] == "n_loop"]
    assert loop["parent"] is None and "iterations" in loop
    iterations = loop["iterations"]
    assert [i["iteration"] for i in iterations] == [0, 1, 2]
    assert [i["status"] for i in iterations] == ["success", "success", "fail"]
    # 회차 0: 호출(진입·로그·exit 셋 포함 4) + 안쪽 반복(첫 도착 + 본문 2 + 되돌아옴 2 = 5) + 검사 1
    # + 반복 노드로 되돌아옴 1
    assert iterations[0]["steps"] == 11
    assert all(i["duration_ms"] is not None for i in iterations)
    # 최상위는 진입·반복 스텝뿐 (본문은 반복 아래)
    top = [s["node"] for s in out["steps"] if s["parent"] is None]
    assert top == ["n_entry", "n_loop"]

    # 실패 사슬: 반복 스텝 → 마지막 회차의 검사
    run_end = index.run_end
    assert run_end is not None and run_end["failure_step"] is not None
    assert out["failure_chain"] == [loop["step"], run_end["failure_step"]]
    failing = next(s for s in out["steps"] if s["step"] == run_end["failure_step"])
    assert (failing["node"], failing["iteration"], failing["status"]) == ("n_chk", 2, "fail")
    # 반복 스텝 줄은 반복 전체: 반복 노드로 돌아오지 못하고 마지막 회차에서 실패 (T7 검수 Low)
    assert (loop["status"], loop["exit"], loop["t_end"]) == ("fail", None, failing["t_end"])
    assert loop["duration_ms"] is not None
    assert loop["duration_ms"] >= sum(i["duration_ms"] for i in iterations)

    # 회차 아래 스텝: 호출 → 안쪽 반복 → 검사 → 되돌아옴
    total, page = index.children(loop["step"], 0, 0, 50, state="ended", thumbs=frozenset())
    assert [s["node"] for s in page] == ["n_c", "n_in", "n_chk", "n_loop"]
    assert total == 4 and page[-1]["exit"] == "body"
    call = page[0]
    assert call["calls"] == SUB and call["graph"] == TEST and call["children"] == 3
    _, inner = index.children(call["step"], None, 0, 50, state="ended", thumbs=frozenset())
    assert [(s["node"], s["graph"]) for s in inner] == [
        ("n_entry", SUB),
        ("n_x", SUB),
        ("n_exit", SUB),
    ]
    inner_loop = page[1]
    assert [i["iteration"] for i in inner_loop["iterations"]] == [0, 1]
    total, body = index.children(inner_loop["step"], 1, 0, 50, state="ended", thumbs=frozenset())
    assert [s["node"] for s in body] == ["n_log", "n_in"] and body[-1]["exit"] == "done"
    # done으로 끝난 반복: 마지막 도착(되돌아옴) 스텝의 결과·출구·끝 시각
    assert (inner_loop["status"], inner_loop["exit"], inner_loop["t_end"]) == (
        "success",
        "done",
        body[-1]["t_end"],
    )
    # 회차 없이 부르면 모든 회차 (마지막 회차는 검사가 실패해 되돌아오지 않는다)
    total, every = index.children(loop["step"], None, 0, 2, state="ended", thumbs=frozenset())
    assert total == loop["children"] == 4 + 4 + 3 and len(every) == 2

    # 노드별 통계: 끝난 스텝만, 실패 수·마지막 실패 스텝
    stats = {(s["graph"], s["node"]): s for s in out["stats"]}
    chk = stats[(TEST, "n_chk")]
    assert (chk["count"], chk["success"], chk["fail"]) == (3, 2, 1)
    assert chk["last_failure_step"] == run_end["failure_step"]
    assert stats[(SUB, "n_x")]["count"] == 3


def test_index_step_events_and_offsets(tmp_path: Path) -> None:
    graph, subs = loop_graph()
    folder = executor_run(tmp_path, graph, subs)
    index = RunIndex(folder).update()
    (log_step,) = [s for s in by_node(index, "n_x")][:1]
    events = index.step_events(log_step)
    assert [e["event"] for e in events] == ["step.start", "log", "step.end"]
    assert all(e["step"] == log_step for e in events)
    with pytest.raises(KeyError):
        index.step_events("s9999")


def failure_harness(tmp_path: Path, g: GraphBuilder, **kw: Any) -> RunnerHarness:
    scenario = write_scenario(tmp_path / "scenario")
    env = {TEST_ENV: json.dumps({"encoder": "fake"}), "KOOKABUG_SECRET_ACC_PW": "hunter2"}
    return RunnerHarness.make(tmp_path, g, scenario=str(scenario), env_extra=env, **kw)


def type_mismatch_graph() -> GraphBuilder:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_sec")
    g.node(
        "n_sec",
        "testkit.sleep",
        inputs={"ms": 0, "value": secret("acc.pw")},
        next={"done": "n_set"},
    )
    g.node("n_get", "core.var.get", inputs={"name": "x"})
    g.node("n_set", "core.var.set", inputs={"name": "x", "value": 7}, next={"done": "n_fail"})
    return g.node("n_fail", "core.log.message", inputs={"text": link("n_get.value")})


def pure_error_graph() -> GraphBuilder:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_fail")
    g.node("n_cmp", "core.logic.compare", inputs={"a": 1, "op": "<", "b": "x"})
    g.node(
        "n_fail",
        "core.flow.branch",
        inputs={"condition": link("n_cmp.result")},
        next={"true": "n_pass", "false": "n_pass"},
    )
    return g.node("n_pass", "core.test.pass")


def stale_graph() -> GraphBuilder:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_cap")
    g.node("n_cap", "core.screen.capture", next={"done": "n_set"})
    g.node("n_get", "core.var.get", inputs={"name": "img"})
    g.node(
        "n_set",
        "core.var.set",
        inputs={"name": "img", "value": link("n_cap.image")},
        next={"done": "n_fail"},
    )
    return g.node("n_fail", "testkit.epoch.use", inputs={"value": link("n_get.value")})


@pytest.mark.process
@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("type_mismatch", "type_mismatch"),
        ("pure_error", "node_error"),
        ("stale_var_get", "unhandled_fail"),
    ],
)
def test_index_failure_chain_for_input_eval_failures(
    tmp_path: Path, spawned: Spawned, kind: str, code: str
) -> None:
    # 2차 N1: 입력 계산 실패도 그 스텝의 step.start·step.end가 남아 색인의 실패 사슬 끝이 된다
    if kind == "stale_var_get":
        h = failure_harness(
            tmp_path, stale_graph(), breakpoints=(Breakpoint(TEST, "n_fail"),)
        ).start(spawned)
        wait_until(lambda: h.has_event("debug.pause"), timeout=60, message=lambda: h.stderr())
        assert h.resume() == "running"
    else:
        graph = type_mismatch_graph() if kind == "type_mismatch" else pure_error_graph()
        h = failure_harness(tmp_path, graph).start(spawned)
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    run_end = done.run_end
    assert run_end is not None and run_end["code"] == code, run_end

    index = RunIndex(h.run_dir).update()
    out = result(index)
    chain = out["failure_chain"]
    assert chain and chain[-1] == run_end["failure_step"]
    failing = next(s for s in out["steps"] if s["step"] == chain[-1])
    assert failing["node"] == "n_fail" and failing["status"] in ("error", "fail")
    if kind == "stale_var_get":
        assert str(failing["message"]).startswith("stale_observation:")
        assert out["pauses"] and out["pauses"][0]["t_end"] is not None
    kinds = [e["event"] for e in index.step_events(chain[-1])]
    assert kinds[0] == "step.start" and kinds[-1] == "step.end"


@pytest.mark.process
def test_index_boundary_cancel_has_no_failure_step_node(tmp_path: Path, spawned: Spawned) -> None:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_x")
    g.node("n_x", "core.flow.delay", inputs={"ms": 1}, next={"done": "n_pass"})
    g.node("n_pass", "core.test.pass")
    h = failure_harness(tmp_path, g, breakpoints=(Breakpoint(TEST, "n_x"),)).start(spawned)
    wait_until(lambda: h.has_event("debug.pause"), timeout=60, message=lambda: h.stderr())
    h.cancel()
    done = h.finish()
    assert done.run_end is not None and done.run_end["failure_step"] is None

    out = result(RunIndex(h.run_dir).update())
    assert out["failure_chain"] == []
    assert [s["node"] for s in out["steps"]] == ["n_entry", "n_launch"]
    # 멈춘 채 취소: 재개 없는 멈춤 구간
    assert len(out["pauses"]) == 1 and out["pauses"][0]["t_end"] is None
    assert out["pauses"][0]["reason"] == "breakpoint"


# ---------------------------------------------------------------- 큰 반복


def synthetic_loop(iterations: int, body: int) -> list[dict[str, Any]]:
    """반복 `iterations`회, 회차마다 본문 `body`개 (실행기와 같은 모양)."""
    events: list[dict[str, Any]] = [
        {"event": "run.start", "graph": TEST, "protocol": 1, "runner": {"pid": 1}}
    ]
    n = 0

    def step(node: str, exit_: str, iteration: int | None, status: str = "success") -> None:
        nonlocal n
        n += 1
        start: dict[str, Any] = {
            "event": "step.start",
            "attempt": 1,
            "node": node,
            "parent": None,
            "path": [node],
            "step": f"s{n}",
        }
        end: dict[str, Any] = {
            "event": "step.end",
            "attempt": 1,
            "duration_ms": 1,
            "exit": exit_,
            "outputs": {},
            "status": status,
            "step": f"s{n}",
        }
        if iteration is not None:
            start["iteration"] = end["iteration"] = iteration
        events.extend((start, end))

    step("n_entry", "start", None)
    step("n_loop", "body", None)
    for i in range(iterations):
        for b in range(body):
            step(f"n_b{b}", "done", i)
        step("n_loop", "body" if i < iterations - 1 else "done", None)
    step("n_pass", "pass", None)
    events.append(
        {
            "event": "run.end",
            "verdict": "pass",
            "code": "passed",
            "reason": "",
            "failure_step": None,
            "failure_path": None,
            "finalized_by": "runner",
            "duration_ms": 1,
        }
    )
    return events


def test_index_loop_row_is_whole_loop_last_arrival(tmp_path: Path) -> None:
    """반복 스텝 줄의 status·exit·t_end·duration_ms는 마지막 도착 기준 (진행 중·캐시 복원 포함)."""
    events = synthetic_loop(3, 1)
    for i, event in enumerate(events):
        if "step" in event:
            event["t"] = f"2026-11-02T00:00:{i:02d}.000Z"
    folder = write_events(tmp_path / "run", events)
    index = RunIndex(folder).update()
    out = result(index)
    loop = next(s for s in out["steps"] if s["node"] == "n_loop")
    last = max((r for r in index.rows.values() if r.node == "n_loop"), key=lambda r: r.t_start)
    assert (loop["status"], loop["exit"], loop["t_end"]) == ("success", "done", last.t_end)
    first = index.rows[loop["step"]]
    assert first.exit == "body" and first.t_end != loop["t_end"]
    assert last.t_end is not None
    seconds = int(last.t_end[17:19]) - int(first.t_start[17:19])
    assert loop["duration_ms"] == seconds * 1000 > 0
    # 캐시에서 되살려도 같다
    restored = RunIndex.from_cache(folder, index.to_cache())
    assert result(restored)["steps"] == out["steps"]

    # 진행 중: 두 번째 회차 본문이 끝나고 되돌아오기 전 → 반복은 실행 중, 끝 없음
    cut = next(
        i for i, e in enumerate(events) if e.get("event") == "step.end" and e.get("iteration") == 1
    )
    live = write_events(tmp_path / "live", events[: cut + 1])
    running = (
        RunIndex(live)
        .update()
        .result(run_dir="runs/live", state="running", run_json=None, video=None, thumbs=frozenset())
    )
    loop = next(s for s in running["steps"] if s["node"] == "n_loop")
    assert (loop["status"], loop["exit"], loop["t_end"], loop["duration_ms"]) == (
        "running",
        None,
        None,
        None,
    )
    # 같은 폴더를 끝난 실행으로 보면 반복은 중단
    ended = (
        RunIndex(live)
        .update()
        .result(run_dir="runs/live", state="ended", run_json=None, video=None, thumbs=frozenset())
    )
    loop = next(s for s in ended["steps"] if s["node"] == "n_loop")
    assert (loop["status"], loop["exit"]) == ("aborted", None)
    assert loop["t_end"] is not None


def test_index_loop_iterations_summarized_10k_steps_under_2s(tmp_path: Path) -> None:
    events = synthetic_loop(10_000, 4)
    assert len(events) >= 100_000
    folder = write_events(tmp_path / "run", events)
    begin = time.perf_counter()
    index = RunIndex(folder).update()
    out = index.result(
        run_dir="runs/run", state="ended", run_json=None, video=None, thumbs=frozenset()
    )
    loop = next(s for s in out["steps"] if s["node"] == "n_loop")
    _, page = index.children(loop["step"], 9_999, 0, 500, state="ended", thumbs=frozenset())
    elapsed = time.perf_counter() - begin
    assert elapsed < 2.0, f"{elapsed:.2f}초"
    # 결과는 최상위만 담고 회차는 요약이다
    assert [s["node"] for s in out["steps"]] == ["n_entry", "n_loop", "n_pass"]
    assert len(loop["iterations"]) == 10_000
    assert loop["iterations"][-1] == {
        "iteration": 9_999,
        "t_start": loop["iterations"][-1]["t_start"],
        "duration_ms": loop["iterations"][-1]["duration_ms"],
        "status": "success",
        "steps": 5,
    }
    assert [s["node"] for s in page] == ["n_b0", "n_b1", "n_b2", "n_b3", "n_loop"]
    assert loop["children"] == 50_000
    assert check_shape(out, "run-index") == []


# ---------------------------------------------------------------- 중단·예전 폴더·캐시


def test_index_aborted_steps_marked(tmp_path: Path) -> None:
    folder = tmp_path / "died"
    shutil.copytree(FIXTURES / "m0b-runner-died-truncated", folder)
    index = RunIndex(folder).update()
    ended = result(index, "ended")
    unfinished = [s for s in ended["steps"] if s["t_end"] is None]
    assert unfinished and all(s["status"] == "aborted" for s in unfinished)
    # 진행 중 실행이면 같은 스텝이 running이다
    running = result(index, "running")
    assert all(s["status"] == "running" for s in running["steps"] if s["t_end"] is None)
    # 실패 스텝이 중단된 스텝이면 그것이 사슬 끝이다
    assert ended["failure_chain"] == [unfinished[-1]["step"]]


def test_index_reads_m2_run_folder() -> None:
    folders = sorted(p for p in FIXTURES.iterdir() if p.is_dir())
    assert any(p.name.startswith("m2-") for p in folders)
    for folder in folders:
        out = result(RunIndex(folder).update())
        assert out["run_id"] and out["steps"], folder.name
    index = RunIndex(FIXTURES / "m2-swapped-target-timeout").update()
    out = result(index)
    # 스냅샷이 없는 폴더: 서브그래프 안 스텝의 그래프는 호출 스텝의 step.end.graph에서
    chain = [next(s for s in out["steps"] if s["step"] == c) for c in out["failure_chain"]]
    assert [s["node"] for s in chain] == ["n_enter_world", "n_wait_title"]
    assert chain[1]["graph"] == chain[0]["calls"]
    assert chain[1]["graph"].startswith("subgraphs/")


def test_index_cache_reused_until_events_change(tmp_path: Path) -> None:
    graph, subs = loop_graph()
    folder = executor_run(tmp_path, graph, subs)
    cache = tmp_path / "cache" / "abcd1234.index.json"
    first = cached_index(folder, cache)
    assert cache.is_file()
    want = result(first)

    # 캐시가 맞으면 events.jsonl을 읽지 않는다: 캐시에 표시를 남겨 확인한다
    data = json.loads(cache.read_text(encoding="utf-8"))
    data["last_seq"] = 999_999
    cache.write_text(json.dumps(data), encoding="utf-8")
    again = cached_index(folder, cache)
    assert again.last_seq == 999_999
    restored = result(again)
    assert {**restored, "last_seq": want["last_seq"]} == want
    total, page = again.children(
        want["steps"][1]["step"], 2, 0, 50, state="ended", thumbs=frozenset()
    )
    assert [s["node"] for s in page] == ["n_c", "n_in", "n_chk"] and total == 3
    assert again.step_events(page[0]["step"])[0]["event"] == "step.start"

    # 이벤트 파일이 바뀌면 다시 만들어 캐시를 고친다
    events = folder / "events.jsonl"
    with events.open("ab") as f:
        line = json.dumps({"event": "log", "seq": 100_000, "step": None, "t": stamp(0)}) + "\n"
        f.write(line.encode("utf-8"))
    stat = events.stat()
    os.utime(events, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    rebuilt = cached_index(folder, cache)
    assert rebuilt.last_seq == 100_000
    assert json.loads(cache.read_text(encoding="utf-8"))["last_seq"] == 100_000


def test_index_update_grows_and_restarts_when_truncated(tmp_path: Path) -> None:
    events = synthetic_loop(3, 1)
    folder = write_events(tmp_path / "run", events[:5])
    path = folder / "events.jsonl"
    whole = path.read_bytes()
    # 끝 줄이 잘린 채 쓰는 중
    path.write_bytes(whole + b'{"event": "step.start", "se')
    index = RunIndex(folder).update()
    assert index.last_seq == 5 and index.position == len(whole)
    write_events(folder, events)
    index.update()
    assert index.last_seq == len(events)
    loop = index.rows["s2"]
    assert loop.loop and loop.children == 6
    # 파일이 줄면(다른 기록) 처음부터 다시 만든다
    write_events(folder, events[:3])
    index.update()
    assert index.last_seq == 3 and set(index.rows) == {"s1"}
