"""실행기가 남기는 실패 증거 `steps/<스텝>_fail` (구현 계획 M1 2.15, 계획 검수 15).

fail 출구로 나간 스텝(서브그래프 호출이면 그 호출 스텝)과 재검증 실패 스텝이 그 스텝 아래(자기와
안쪽 스텝)의 마지막 캡처를 한 번 남긴다 — 처리되지 않은 fail의 원인 스텝(실패 위치)은 늘 그중
하나다. 다른 스텝(앞·뒤 노드)의 캡처는 쓰지 않는다. 기록 정책은 스크린샷과 같다. 가짜 프레임은 파일
이름(`a`·`b`·`c`)으로 구별한다.
"""

from pathlib import Path
from typing import Any

from helpers.graphs import make_workspace, subgraph_interface
from helpers.run import Ran, run_graph, tk

from kookabug_core.workspace import Workspace

SUB = "subgraphs/s.graph.json"
FRAMES = ["a", "b", "c", "d", "e"]


def fails(ran: Ran) -> list[str]:
    """저장된 실패 증거 경로들."""
    return [p for p in ran.artifacts.saved if p.endswith("_fail")]


def saved_frame(ran: Ran, path: str) -> str:
    image = ran.artifacts.saved[path]
    assert image.path is not None
    return image.path.name


def write_sub(ws: Workspace, *, captures: int, record: dict[str, Any] | None = None) -> None:
    """`captures`번 캡처하고 공개 fail 출구 `bad`로 나가는 서브그래프."""
    sub = tk(
        "subgraph", interface=subgraph_interface(exits={"ok": "ok", "bad": "fail"}), record=record
    )
    if captures:
        sub.entry("n_shot").node(
            "n_shot", "testkit.shot", inputs={"captures": captures}, next={"done": "n_bad"}
        )
    else:
        sub.entry("n_bad")
    sub.exit("n_bad", "bad").exit("n_ok", "ok").write(ws, SUB)


def test_unhandled_fail_in_subgraph_saves_last_inner_frame_at_call_step(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_sub(ws, captures=2)
    g = (
        tk()
        .entry("n_before")
        .node("n_before", "testkit.shot", next={"done": "n_call"})  # 앞 스텝: a
        .call("n_call", SUB)  # 안쪽: b, c → 공개 fail 출구 bad (연결 안 됨)
    )
    ran = run_graph(ws, g, frames=FRAMES)
    assert ran.result.verdict == "fail"
    step = ran.step_of("n_call")
    assert ran.result.failure_step == step
    assert ran.end("n_call")["artifacts"] == [f"steps/{step}_fail"]
    assert saved_frame(ran, f"steps/{step}_fail") == "c"  # 안쪽에서 얻은 마지막 캡처


def test_unhandled_fail_at_step_saves_its_last_frame(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    g = (
        tk()
        .entry("n_shot")
        .node("n_shot", "testkit.shot", next={"done": "n_wait"})
        .node("n_wait", "testkit.observe.wait", inputs={"expect": "zzz", "timeout_ms": 200})
    )
    ran = run_graph(ws, g, frames=["a", "b", "c"])
    step = ran.step_of("n_wait")
    assert fails(ran) == [f"steps/{step}_fail"]
    assert saved_frame(ran, f"steps/{step}_fail") == "c"


def test_no_capture_under_step_no_evidence(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_sub(ws, captures=0)
    g = (
        tk()
        .entry("n_before")
        .node("n_before", "testkit.shot", next={"done": "n_call"})  # 앞 스텝은 캡처했다
        .call("n_call", SUB)
    )
    ran = run_graph(ws, g, frames=FRAMES)
    assert ran.result.verdict == "fail"
    assert fails(ran) == []
    assert "artifacts" not in ran.end("n_call")


def test_evidence_respects_record_policy_omitted(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_sub(ws, captures=1)
    # 호출 노드에서 끈 구간: 그 호출 스텝의 실패 증거도 남기지 않는다
    off = tk().entry("n_call").call("n_call", SUB, record={"screenshots": "off"})
    ran = run_graph(ws, off, frames=FRAMES)
    assert fails(ran) == []
    assert ran.end("n_call")["omitted"] == [
        {
            "kind": "screenshot",
            "name": "fail",
            "reason": "policy_off",
            "source": "tests/t.graph.json#/nodes/n_call/record",
        }
    ]
    # 서브그래프가 끈 구간에서 얻은 프레임: 켜진 호출 스텝도 그 프레임을 남기지 않는다
    write_sub(ws, captures=1, record={"screenshots": "off"})
    ran = run_graph(ws, tk().entry("n_call").call("n_call", SUB), frames=FRAMES)
    assert fails(ran) == []
    (omitted,) = ran.end("n_call")["omitted"]
    assert (omitted["name"], omitted["reason"]) == ("fail", "capture_policy")


def test_evidence_saved_once(tmp_path: Path) -> None:
    """안쪽 스텝에서 확정된 fail은 안쪽 스텝만 남긴다. 지나가는 호출 스텝은 다시 남기지 않는다."""
    ws = make_workspace(tmp_path)
    sub = tk("subgraph", interface=subgraph_interface(exits={"ok": "ok"}))
    sub.entry("n_wait").node(
        "n_wait",
        "testkit.observe.wait",
        inputs={"expect": "zzz", "timeout_ms": 200},
        next={"found": "n_ok"},
    ).exit("n_ok", "ok").write(ws, SUB)
    ran = run_graph(ws, tk().entry("n_call").call("n_call", SUB), frames=FRAMES)
    assert ran.result.verdict == "fail"
    inner = ran.step_of("n_wait")
    assert ran.result.failure_step == inner
    assert fails(ran) == [f"steps/{inner}_fail"]
    assert "artifacts" not in ran.end("n_call")


def test_connected_fail_reaching_path_end_keeps_evidence_at_cause_step(tmp_path: Path) -> None:
    """검수 T11-1 5: fail 출구에 다른 노드(로그 등)만 이어도 실패 위치(원인 스텝)의 증거가 남는다.
    원인 스텝이 fail 출구로 나갈 때 자기 프레임으로 남긴다 — 뒤 노드의 프레임은 쓰지 않는다."""
    ws = make_workspace(tmp_path)
    g = (
        tk()
        .entry("n_wait")
        .node(
            "n_wait",
            "testkit.observe.wait",
            inputs={"expect": "zzz", "timeout_ms": 200},
            next={"timeout": "n_shot"},
        )
        .node("n_shot", "testkit.shot")  # 뒤 노드도 캡처한다 (d)
    )
    ran = run_graph(ws, g, frames=["a", "b", "c", "d"])
    step = ran.step_of("n_wait")
    assert ran.result.verdict == "fail" and ran.result.failure_step == step
    assert fails(ran) == [f"steps/{step}_fail"]
    assert ran.end("n_wait")["artifacts"] == [f"steps/{step}_fail"]
    assert saved_frame(ran, f"steps/{step}_fail") == "c"  # 원인 스텝의 마지막 프레임 (d 아님)


def test_connected_fail_to_log_only_keeps_evidence(tmp_path: Path) -> None:
    """검수 반례 그대로의 모양: fail 출구 → `core.log.message` → 경로 끝."""
    ws = make_workspace(tmp_path)
    g = (
        tk()
        .entry("n_wait")
        .node(
            "n_wait",
            "testkit.observe.wait",
            inputs={"expect": "zzz", "timeout_ms": 200},
            next={"timeout": "n_log"},
        )
        .node("n_log", "core.log.message", inputs={"text": "failed"})
    )
    ran = run_graph(ws, g, frames=FRAMES)
    step = ran.step_of("n_wait")
    assert ran.result.failure_step == step
    assert f"steps/{step}_fail" in [p for e in ran.events for p in e.get("artifacts", [])]


def test_handled_fail_branch_still_keeps_its_evidence(tmp_path: Path) -> None:
    """fail 분기가 뒤에서 처리돼도(종료 노드) 그 스텝은 fail 출구로 나간 증거를 남긴다."""
    ws = make_workspace(tmp_path)
    g = (
        tk()
        .entry("n_wait")
        .node(
            "n_wait",
            "testkit.observe.wait",
            inputs={"expect": "zzz", "timeout_ms": 200},
            next={"timeout": "n_skip"},
        )
        .node("n_skip", "core.test.skip")
    )
    ran = run_graph(ws, g, frames=FRAMES)
    assert ran.result.verdict == "skipped"
    assert fails(ran) == [f"steps/{ran.step_of('n_wait')}_fail"]
