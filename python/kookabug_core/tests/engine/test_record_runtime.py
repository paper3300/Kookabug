"""실행 중 기록 정책 집행 (스키마 v0 6장 "화면에 찍힌 비밀값", 계획 2.9).

`testkit.shot`: `captures`번 캡처, `save`면 `ctx.artifacts.save`, `boom`이면 예외, `value`는 받기만.
"""

from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import link, literal, make_workspace, secret, subgraph_interface
from helpers.run import Ran, run_graph, tk
from testkit import registry_with_testkit

from kookabug_core.engine import ExecOptions, Executor, FakeClock, FakePlatform
from kookabug_core.loader import load_program
from kookabug_core.record import FileArtifacts
from kookabug_core.schema import check_shape
from kookabug_core.workspace import MemorySecrets, Workspace
from kookabug_sdk.types import Image

SUB = "subgraphs/s.graph.json"
INNER = "subgraphs/inner.graph.json"
TEST_FILE = "tests/t.graph.json"
FRAMES = ["a", "b", "c"]


def run(ws: Workspace, g: Any, **kw: Any) -> Ran:
    return run_graph(ws, g, frames=kw.pop("frames", FRAMES), **kw)


def omitted(ran: Ran, node: str) -> list[dict[str, Any]]:
    return ran.end(node).get("omitted", [])


def no_saved_paths(ran: Ran) -> None:
    """저장한 것이 없고 어떤 이벤트에도 artifacts 경로가 없다."""
    assert ran.artifacts.saved == {}
    assert all("artifacts" not in e for e in ran.events)
    assert "steps/" not in repr(ran.events)


def sub_off(ws: Workspace, inner: Any, *, record: dict[str, Any] | None = None) -> None:
    """`record`(기본 스크린샷 끔) 서브그래프: entry → `inner` 노드들 → exit `done`."""
    g = tk("subgraph", interface=subgraph_interface(), record=record or {"screenshots": "off"})
    inner(g)
    g.write(ws, SUB)


# ---------------------------------------------------------------- 비밀값 입력


def test_secret_input_node_screenshots_omitted(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    g = (
        tk()
        .entry("n_shot")
        .node(
            "n_shot",
            "testkit.shot",
            inputs={"save": True, "value": secret("acc.pw")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run(ws, g, secrets={"acc.pw": "hunter2"})
    assert ran.result.verdict == "pass"
    source = f"{TEST_FILE}#/nodes/n_shot/in/value"
    assert omitted(ran, "n_shot") == [
        {"kind": "screenshot", "name": "shot", "reason": "secret_input", "source": source}
    ]
    assert ran.end("n_shot")["outputs"]["saved"] is None
    no_saved_paths(ran)

    # 실패(예외) 스크린샷도 남기지 않는다
    g = (
        tk()
        .entry("n_shot")
        .node(
            "n_shot", "testkit.shot", inputs={"save": True, "boom": True, "value": secret("acc.pw")}
        )
    )
    ran = run(make_workspace(tmp_path / "2"), g, secrets={"acc.pw": "hunter2"})
    assert (ran.result.verdict, ran.result.failure_path) == ("error", ("n_shot",))
    assert [(o["name"], o["reason"]) for o in omitted(ran, "n_shot")] == [
        ("shot", "secret_input"),
        ("error", "secret_input"),
    ]
    no_saved_paths(ran)
    assert "hunter2" not in repr(ran.events)


def test_secret_nested_in_list_input_omits(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_shot")
        .node(
            "n_shot",
            "testkit.shot",
            inputs={"save": True, "value": [1, {"pw": secret("acc.pw")}]},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run(make_workspace(tmp_path), g, secrets={"acc.pw": "hunter2"})
    assert ran.result.verdict == "pass"
    (entry,) = omitted(ran, "n_shot")
    assert entry["reason"] == "secret_input"
    assert entry["source"] == f"{TEST_FILE}#/nodes/n_shot/in/value/1/pw"
    no_saved_paths(ran)


def test_secret_via_var_get_any_pin_omits(tmp_path: Path) -> None:
    # 정적으로는 any 핀일 뿐이다. 스텝 시작 때 계산한 값으로 판단한다
    g = (
        tk()
        .entry("n_set")
        .node(
            "n_set",
            "core.var.set",
            inputs={"name": "pw", "value": secret("acc.pw")},
            next={"done": "n_shot"},
        )
        .node("n_get", "core.var.get", inputs={"name": "pw"})
        .node(
            "n_shot",
            "testkit.shot",
            inputs={"save": True, "value": link("n_get.value")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run(make_workspace(tmp_path), g, secrets={"acc.pw": "hunter2"})
    assert ran.result.verdict == "pass"
    assert [(o["reason"], o["source"]) for o in omitted(ran, "n_shot")] == [
        ("secret_input", f"{TEST_FILE}#/nodes/n_shot/in/value")
    ]
    no_saved_paths(ran)


# ---------------------------------------------------------------- 구간 끄기


def test_off_subgraph_omits_inner_nodes_with_source(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    sub_off(
        ws,
        lambda g: (
            g.entry("n_in")
            .node("n_in", "testkit.shot", inputs={"save": True}, next={"done": "n_exit"})
            .exit("n_exit", "done")
        ),
    )
    g = (
        tk()
        .entry("n_call")
        .call("n_call", SUB, next={"done": "n_out"})
        .node("n_out", "testkit.shot", inputs={"save": True}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    ran = run(ws, g)
    assert ran.result.verdict == "pass"
    assert omitted(ran, "n_in") == [
        {"kind": "screenshot", "name": "shot", "reason": "policy_off", "source": f"{SUB}#/record"}
    ]
    assert "artifacts" not in ran.end("n_in")
    assert ran.end("n_in")["outputs"]["saved"] is None
    # 구간 밖의 노드는 그대로 남긴다
    out = ran.end("n_out")
    assert out["artifacts"] == [out["outputs"]["saved"]] == [f"steps/{out['step']}_shot"]
    assert list(ran.artifacts.saved) == out["artifacts"]
    assert "omitted" not in out


def test_off_call_node_and_workspace_sources(tmp_path: Path) -> None:
    # 호출 노드에서 끈 것도 서브그래프 전체에 간다. 워크스페이스에서 끄면 위치는 kookabug.json
    ws = make_workspace(tmp_path)
    sub_off(
        ws,
        lambda g: (
            g.entry("n_in")
            .node("n_in", "testkit.shot", inputs={"save": True}, next={"done": "n_exit"})
            .exit("n_exit", "done")
        ),
        record={"screenshots": "on"},
    )
    g = (
        tk()
        .entry("n_call")
        .call("n_call", SUB, next={"done": "n_pass"}, record={"screenshots": "off"})
        .node("n_pass", "core.test.pass")
    )
    ran = run(ws, g)
    assert [o["source"] for o in omitted(ran, "n_in")] == [f"{TEST_FILE}#/nodes/n_call/record"]

    ws = make_workspace(tmp_path / "2", record={"screenshots": "off"})
    g = (
        tk(record={"screenshots": "on"})
        .entry("n_shot")
        .node(
            "n_shot",
            "testkit.shot",
            inputs={"save": True},
            next={"done": "n_pass"},
            record={"screenshots": "on"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run(ws, g)
    assert [o["source"] for o in omitted(ran, "n_shot")] == ["kookabug.json#/record"]
    no_saved_paths(ran)


def test_omitted_does_not_change_verdict(tmp_path: Path) -> None:
    def graph(record: dict[str, Any] | None) -> Any:
        return (
            tk(record=record)
            .entry("n_shot")
            .node("n_shot", "testkit.shot", inputs={"save": True}, next={"done": "n_fail"})
            .node("n_fail", "core.test.fail", inputs={"reason": "끝"})
        )

    kept = run(make_workspace(tmp_path / "on"), graph(None)).result
    dropped = run(make_workspace(tmp_path / "off"), graph({"screenshots": "off"}))
    assert dropped.end("n_shot").get("omitted")
    r = dropped.result
    assert (r.verdict, r.code, r.reason, r.failure_step, r.failure_path) == (
        kept.verdict,
        kept.code,
        kept.reason,
        kept.failure_step,
        kept.failure_path,
    )
    assert [e["status"] for e in r.events if e["event"] == "step.end"] == [
        e["status"] for e in kept.events if e["event"] == "step.end"
    ]


def test_artifacts_save_returns_none_when_omitted_and_no_fake_path(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_off")
        .node(
            "n_off",
            "testkit.shot",
            inputs={"save": True},
            next={"done": "n_on"},
            record={"screenshots": "off"},
        )
        .node("n_on", "testkit.shot", inputs={"save": True}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    ran = run(make_workspace(tmp_path), g)
    off = ran.end("n_off")
    assert off["outputs"]["saved"] is None
    assert "artifacts" not in off
    on = ran.end("n_on")
    # artifacts 목록에는 실제로 저장한 것만 있다
    listed = [p for e in ran.of("step.end") for p in e.get("artifacts", [])]
    assert listed == [on["outputs"]["saved"]] == list(ran.artifacts.saved)


# ---------------------------------------------------------------- 예외 스크린샷


def test_error_screenshot_last_capture_in_same_step(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_one")
        .node("n_one", "testkit.shot", next={"done": "n_two"})  # a
        .node("n_two", "testkit.shot", inputs={"captures": 2, "boom": True})  # b, c
    )
    ran = run(make_workspace(tmp_path), g)
    assert ran.result.verdict == "error"
    end = ran.end("n_two")
    assert end["status"] == "error"
    assert end["artifacts"] == [f"steps/{end['step']}_error"]
    (image,) = ran.artifacts.saved.values()
    assert image.path is not None and image.path.stem == "c"
    assert "artifacts" not in ran.end("n_one")


def test_error_without_capture_in_step_saves_nothing(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_one")
        .node("n_one", "testkit.shot", next={"done": "n_two"})
        .node("n_two", "testkit.shot", inputs={"captures": 0, "boom": True})
    )
    ran = run(make_workspace(tmp_path), g)
    assert ran.end("n_two")["status"] == "error"
    assert "omitted" not in ran.end("n_two")
    no_saved_paths(ran)


def test_capture_in_off_section_not_reused_by_later_error(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    sub_off(
        ws,
        lambda g: (
            g.entry("n_in")
            .node("n_in", "testkit.shot", next={"done": "n_exit"})
            .exit("n_exit", "done")
        ),
    )
    g = (
        tk()
        .entry("n_call")
        .call("n_call", SUB, next={"done": "n_after"})
        .node("n_after", "testkit.shot", inputs={"captures": 0, "boom": True})
    )
    ran = run(ws, g)
    after = ran.end("n_after")
    assert after["status"] == "error"
    assert "omitted" not in after
    no_saved_paths(ran)


def test_capture_in_secret_step_not_reused(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_secret")
        .node(
            "n_secret", "testkit.shot", inputs={"value": secret("acc.pw")}, next={"done": "n_after"}
        )
        .node("n_after", "testkit.shot", inputs={"captures": 0, "boom": True})
    )
    ran = run(make_workspace(tmp_path), g, secrets={"acc.pw": "hunter2"})
    assert ran.end("n_after")["status"] == "error"
    assert "omitted" not in ran.end("n_after")
    no_saved_paths(ran)


def test_capture_in_off_step_error_in_same_step_omitted(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_off")
        .node("n_off", "testkit.shot", inputs={"boom": True}, record={"screenshots": "off"})
    )
    ran = run(make_workspace(tmp_path), g)
    assert ran.end("n_off")["status"] == "error"
    assert omitted(ran, "n_off") == [
        {
            "kind": "screenshot",
            "name": "error",
            "reason": "policy_off",
            "source": f"{TEST_FILE}#/nodes/n_off/record",
        }
    ]
    no_saved_paths(ran)


def test_nested_subgraph_error_saved_once_by_inner_step(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    (
        tk("subgraph", interface=subgraph_interface())
        .entry("n_x")
        .node("n_x", "testkit.shot", inputs={"boom": True}, next={"done": "n_exit"})
        .exit("n_exit", "done")
        .write(ws, INNER)
    )
    (
        tk("subgraph", interface=subgraph_interface())
        .entry("n_b")
        .call("n_b", INNER, next={"done": "n_exit"})
        .exit("n_exit", "done")
        .write(ws, SUB)
    )
    g = tk().entry("n_a").call("n_a", SUB, next={"done": "n_pass"}).node("n_pass", "core.test.pass")
    ran = run(ws, g)
    assert ran.result.verdict == "error"
    with_artifacts = [e for e in ran.of("step.end") if "artifacts" in e or "omitted" in e]
    (inner,) = with_artifacts
    assert inner["step"] == ran.step_of("n_x")
    assert inner["artifacts"] == [f"steps/{inner['step']}_error"]
    assert len(ran.artifacts.saved) == 1
    # 호출 스텝들은 error로 끝나지만 다시 저장하지 않는다
    calls = [e for e in ran.of("step.end") if e["step"] != inner["step"] and e["status"] == "error"]
    assert len(calls) == 2


def test_image_captured_in_off_section_saved_later_is_capture_policy(tmp_path: Path) -> None:
    # 꺼 둔 구간에서 얻은 프레임은 출력으로 밖에 나가 켜진 노드가 저장해도 막힌다 (획득 당시 표시)
    ws = make_workspace(tmp_path)
    iface = subgraph_interface(outputs={"img": {"nullable": True, "type": "image"}})
    (
        tk("subgraph", interface=iface, record={"screenshots": "off"})
        .entry("n_in")
        .node("n_in", "testkit.shot", next={"done": "n_exit"})
        .exit("n_exit", "done", inputs={"img": link("n_in.image")})
        .write(ws, SUB)
    )
    g = (
        tk()
        .entry("n_call")
        .call("n_call", SUB, next={"done": "n_save"})
        .node(
            "n_save",
            "testkit.shot",
            inputs={"captures": 0, "save": True, "image": link("n_call.img")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run(ws, g)
    assert ran.result.verdict == "pass"
    assert omitted(ran, "n_save") == [
        {
            "kind": "screenshot",
            "name": "shot",
            "reason": "capture_policy",
            "source": f"{SUB}#/record",
        }
    ]
    no_saved_paths(ran)


def test_recapture_in_on_step_is_a_new_capture(tmp_path: Path) -> None:
    # 표시는 캡처마다다. 같은 화면(가짜 플랫폼은 마지막 프레임을 되풀이)이라도 켜진 스텝이 새로
    # 얻은 캡처는 그 스텝의 정책을 따른다
    ws = make_workspace(tmp_path)
    sub_off(
        ws,
        lambda g: (
            g.entry("n_in")
            .node("n_in", "testkit.shot", next={"done": "n_exit"})
            .exit("n_exit", "done")
        ),
    )
    g = (
        tk()
        .entry("n_call")
        .call("n_call", SUB, next={"done": "n_after"})
        .node("n_after", "testkit.shot", inputs={"boom": True})
    )
    ran = run(ws, g, frames=["only"])
    after = ran.end("n_after")
    assert "omitted" not in after
    assert after["artifacts"] == [f"steps/{after['step']}_error"]


def _bytes_capture_saved_outside(
    tmp_path: Path, blocked_by: str, frame: int | None
) -> tuple[Path, list[dict[str, Any]]]:
    """바이트만 있는 캡처(`frame`·`path` 없음 가능)를 막힌 서브그래프 안에서 얻어 출력으로 내보내고,
    켜진 노드가 캡처 없이 저장한다. 실제 `FileArtifacts`를 쓴다."""
    ws = make_workspace(tmp_path / "ws")
    iface = subgraph_interface(outputs={"img": {"nullable": True, "type": "image"}})
    (
        tk(
            "subgraph",
            interface=iface,
            record={"screenshots": "off"} if blocked_by == "policy" else None,
        )
        .entry("n_in")
        .node(
            "n_in",
            "testkit.shot",
            inputs={"value": secret("acc.pw")} if blocked_by == "secret" else {},
            next={"done": "n_exit"},
        )
        .exit("n_exit", "done", inputs={"img": link("n_in.image")})
        .write(ws, SUB)
    )
    (
        tk()
        .entry("n_call")
        .call("n_call", SUB, next={"done": "n_save"})
        .node(
            "n_save",
            "testkit.shot",
            inputs={"captures": 0, "save": True, "image": link("n_call.img")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
        .write(ws, TEST_FILE)
    )
    folder = tmp_path / "run"
    program = load_program(ws, TEST_FILE, secrets=MemorySecrets({"acc.pw": "hunter2"}))
    result = Executor(
        registry_with_testkit(),
        platform=FakePlatform([Image(data=b"private-screen-pixels", frame=frame)]),
        clock=FakeClock(),
        artifacts=FileArtifacts(folder),
    ).run(program, ExecOptions(run_id="r1"))
    assert result.verdict == "pass"
    ends = [e for e in result.events if e["event"] == "step.end" and "omitted" in e]
    return folder, ends


@pytest.mark.parametrize("frame", [None, 42])
@pytest.mark.parametrize("blocked_by", ["policy", "secret"])
def test_bytes_only_capture_keeps_capture_policy_outside(
    tmp_path: Path, blocked_by: str, frame: int | None
) -> None:
    folder, ends = _bytes_capture_saved_outside(tmp_path, blocked_by, frame)
    assert not folder.exists() or [p for p in folder.rglob("*") if p.is_file()] == []
    (end,) = ends
    (entry,) = end["omitted"]
    assert (entry["name"], entry["reason"]) == ("shot", "capture_policy")
    expected = f"{SUB}#/record" if blocked_by == "policy" else f"{SUB}#/nodes/n_in/in/value"
    assert entry["source"] == expected


# ---------------------------------------------------------------- 영상 (M3가 쓴다)


def test_video_allowed_query(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    sub_off(
        ws,
        lambda g: (
            g.entry("n_in")
            .node("n_in", "testkit.shot", next={"done": "n_exit"})
            .exit("n_exit", "done")
        ),
        record={"video": "failed_only"},
    )
    g = (
        tk()
        .entry("n_plain")
        .node("n_plain", "testkit.shot", next={"done": "n_call"})
        .call("n_call", SUB, next={"done": "n_secret"})
        .node(
            "n_secret", "testkit.shot", inputs={"value": secret("acc.pw")}, next={"done": "n_off"}
        )
        .node("n_off", "testkit.shot", next={"done": "n_pass"}, record={"video": "off"})
        .node("n_pass", "core.test.pass", inputs={"reason": literal("끝")})
    )
    ran = run(ws, g, secrets={"acc.pw": "hunter2"})
    recorder = ran.result.recorder
    assert recorder is not None

    def allowed(node: str) -> tuple[str, bool, bool]:
        step = ran.step_of(node)
        return (
            recorder.video_policy(step),
            recorder.video_allowed(step, run_failed=False),
            recorder.video_allowed(step, run_failed=True),
        )

    assert allowed("n_plain") == ("on", True, True)
    assert allowed("n_in") == ("failed_only", False, True)
    assert allowed("n_secret") == ("off", False, False)
    assert allowed("n_off") == ("off", False, False)


# ---------------------------------------------------------------- 형식·방어


def test_step_end_with_artifacts_and_omitted_matches_events_schema(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_on")
        .node("n_on", "testkit.shot", inputs={"save": True}, next={"done": "n_secret"})
        .node(
            "n_secret",
            "testkit.shot",
            inputs={"save": True, "boom": True, "value": secret("acc.pw")},
        )
    )
    ran = run(make_workspace(tmp_path), g, secrets={"acc.pw": "hunter2"})
    ends = [e for e in ran.of("step.end") if "artifacts" in e or "omitted" in e]
    assert len(ends) == 2
    for end in ends:
        journaled = {**end, "run": "r8k2x7qm", "seq": 1, "t": "2026-10-30T00:00:00.000Z"}
        assert check_shape(journaled, "events") == []


class _BrokenStore:
    def save(self, step: str, image: Image, name: str) -> str:
        raise OSError("디스크가 가득 찼다")

    def save_text(self, step: str, name: str, text: str) -> str:
        raise OSError("디스크가 가득 찼다")


def test_error_screenshot_store_failure_keeps_original_error(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    tk().entry("n_x").node("n_x", "testkit.shot", inputs={"boom": True}).write(ws, TEST_FILE)
    program = load_program(ws, TEST_FILE, secrets=MemorySecrets({}))
    executor = Executor(
        registry_with_testkit(),
        platform=FakePlatform(FRAMES),
        clock=FakeClock(),
        artifacts=_BrokenStore(),
    )
    result = executor.run(program, ExecOptions(run_id="r1"))
    assert (result.verdict, result.failure_path) == ("error", ("n_x",))
    assert "testkit.shot boom" in result.reason
    (warn,) = [e for e in result.events if e["event"] == "log"]
    assert warn["level"] == "warn" and "디스크가 가득 찼다" in warn["message"]
    (end,) = [e for e in result.events if e["event"] == "step.end" and e["status"] == "error"]
    assert "artifacts" not in end
