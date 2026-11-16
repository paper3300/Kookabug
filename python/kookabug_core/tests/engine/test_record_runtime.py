"""실행 중 기록 정책 집행 (스키마 v0 6장 "화면에 찍힌 비밀값", 계획 2.9).

`testkit.shot`: `captures`번 캡처, `save`면 `ctx.artifacts.save`, `boom`이면 예외, `value`는 받기만.
"""

from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import (
    check,
    link,
    literal,
    make_workspace,
    secret,
    subgraph_interface,
    write_json,
)
from helpers.run import Ran, run_graph, tk
from testkit import registry_with_testkit

from kookabug_core.engine import ExecOptions, Executor, FakeClock, FakePlatform, MemoryArtifacts
from kookabug_core.loader import load_program
from kookabug_core.record import FileArtifacts
from kookabug_core.schema import check_shape
from kookabug_core.workspace import MemorySecrets, Workspace
from kookabug_sdk import Secret
from kookabug_sdk.types import Image, Match, OcrLine, OcrResult, Rect

SUB = "subgraphs/s.graph.json"
INNER = "subgraphs/inner.graph.json"
TEST_FILE = "tests/t.graph.json"
FRAMES = ["a", "b", "c"]
REDACT = {"redact_secrets": True}
"""비밀값 가림을 켠 워크스페이스 기록 정책 — UX11 B부터 무시된다 (켜도 원문 그대로)."""


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
    ws = make_workspace(tmp_path / "ws", record=REDACT)
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
@pytest.mark.parametrize("blocked_by", ["policy"])
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
    # 워크스페이스에서 on을 명시한다 (정하지 않으면 failed_only — 아래 기본값 검사)
    ws = make_workspace(tmp_path, record={"video": "on", **REDACT})
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
    assert allowed("n_secret") == ("on", True, True)  # 비밀값 입력도 막지 않는다
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


# ---------------------------------------------------------------- OCR 글자 기록·민감 target (M1)

GOLD_TEXT = "Gold 12,345"


class _OcrPlatform(FakePlatform):
    """가짜 프레임 + 정해 둔 답의 찾기·OCR (`core.ocr.read`를 실행기에서 돌린다). 민감하게
    읽으면 글자를 비밀값으로 준다 (플랫폼 엔진과 같다)."""

    def find(self, image: Image, target: Any, *, region: Any, limits: Any) -> Match | None:
        return Match(Rect(20, 20, 240, 52), 0.99, frame=image.frame, target=target.name)

    def diff(self, a: Image, b: Image, *, region: Any) -> float:
        return 0.0

    def read_text(self, image: Image, *, region: Any, sensitive: bool, limits: Any) -> OcrResult:
        text: str | Secret = Secret(GOLD_TEXT) if sensitive else GOLD_TEXT
        line = OcrLine(text, Rect(20, 20, 240, 52), 0.9)
        return OcrResult(text, (line,), 0.9)


def _gold_target(ws: Workspace, *, sensitive: bool) -> str:
    rel = "targets/world/gold.target.json"
    body: dict[str, Any] = {"format": "kookabug.target/0", "image": "gold.png"}
    if sensitive:
        body["sensitive"] = True
    path = write_json(ws, rel, body)
    (path.parent / "gold.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return rel


def _run_ocr(ws: Workspace, g: Any) -> Ran:
    g.write(ws, TEST_FILE)
    program = load_program(ws, TEST_FILE, secrets=MemorySecrets({}))
    platform = _OcrPlatform(FRAMES)
    clock = FakeClock()
    artifacts = MemoryArtifacts()
    executor = Executor(
        registry_with_testkit(), platform=platform, clock=clock, artifacts=artifacts
    )
    result = executor.run(program, ExecOptions(run_id="r1"))
    return Ran(result, platform, clock, program, artifacts)


def _read_graph(rel: str, then: str | None = None) -> Any:
    g = tk().entry("n_read")
    g.node(
        "n_read",
        "core.ocr.read",
        inputs={"region": {"$target": rel}, "parse": "number"},
        next={"done": then or "n_ok"},
    )
    if then is None:
        g.node("n_ok", "core.assert.compare", inputs={"a": 1, "op": "==", "b": 1})
    return g


def test_ocr_text_artifact_is_last_read(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    ran = _run_ocr(ws, _read_graph(_gold_target(ws, sensitive=False)))
    assert ran.result.verdict == "pass", ran.result.reason
    step = ran.step_of("n_read")
    assert ran.end("n_read")["artifacts"] == [f"steps/{step}_ocr.txt"]
    assert ran.artifacts.texts[f"steps/{step}_ocr.txt"] == GOLD_TEXT
    assert ran.end("n_read")["outputs"]["number"] == 12345


def test_ocr_text_artifact_follows_screenshot_policy(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    g = _read_graph(_gold_target(ws, sensitive=False))
    g.nodes["n_read"]["record"] = {"screenshots": "off"}
    ran = _run_ocr(ws, g)
    (omitted,) = ran.end("n_read")["omitted"]
    assert (omitted["kind"], omitted["reason"]) == ("text", "policy_off")
    assert ran.artifacts.texts == {}


def test_default_keeps_secret_screens_and_values(tmp_path: Path) -> None:
    """D3: 워크스페이스가 `record.redact_secrets`를 켜지 않으면(기본) 비밀값을 받은 스텝의
    스크린샷을 남기고 이벤트·로그·판정 사유에 원문을 남긴다. 비밀값 형식(`secret`)은 그대로다."""
    g = (
        tk()
        .entry("n_shot")
        .node(
            "n_shot",
            "testkit.shot",
            inputs={"save": True, "value": secret("acc.pw")},
            next={"done": "n_log"},
        )
        .node("n_log", "core.log.message", inputs={"text": secret("acc.pw")}, next={"done": "n_x"})
        .node("n_x", "core.test.pass", inputs={"reason": secret("acc.pw")})
    )
    ran = run(make_workspace(tmp_path), g, secrets={"acc.pw": "hunter2"})
    assert (ran.result.verdict, ran.result.reason) == ("pass", "hunter2")
    assert omitted(ran, "n_shot") == []
    assert ran.end("n_shot")["outputs"]["saved"] is not None
    assert ran.artifacts.saved != {}
    (log,) = [e for e in ran.of("log") if e["node"] == "n_log"]
    assert log["message"] == "hunter2"
    # 가림을 켜도(무시 — UX11 B) false를 명시해도 같다
    for n, record in enumerate(({"redact_secrets": False}, REDACT), start=2):
        again = run(
            make_workspace(tmp_path / str(n), record=record), g, secrets={"acc.pw": "hunter2"}
        )
        assert omitted(again, "n_shot") == [] and "hunter2" in repr(again.events)
        assert "***" not in repr(again.events)


def test_default_keeps_sensitive_ocr_text(tmp_path: Path) -> None:
    """D3: 민감 target으로 읽은 글자도 기본은 OCR 글자 기록·이벤트에 그대로 남는다 (값은 여전히
    secret 형식이라 string 핀에는 못 간다)."""
    ws = make_workspace(tmp_path)
    ran = _run_ocr(ws, _read_graph(_gold_target(ws, sensitive=True)))
    assert ran.result.verdict == "pass", ran.result.reason
    end = ran.end("n_read")
    assert "omitted" not in end
    assert list(ran.artifacts.texts.values()) == [GOLD_TEXT]
    assert end["outputs"]["text"] == GOLD_TEXT and end["outputs"]["number"] is None


@pytest.mark.parametrize("redact", [False, True], ids=["default", "redact"])
def test_compare_fail_message_follows_policy(tmp_path: Path, redact: bool) -> None:
    """P1 검수 4: 서로 다른 두 비밀값 비교 실패 메시지·판정 사유는 원문 (가림 설정은 무시 —
    UX11 B)."""
    g = tk().entry("n_cmp")
    g.node("n_cmp", "core.assert.compare", inputs={"a": secret("a"), "op": "==", "b": secret("b")})
    ws = make_workspace(tmp_path, record=REDACT if redact else None)
    ran = run(ws, g, secrets={"a": "hunter2", "b": "hunter3"})
    expected = '"hunter2" == "hunter3"이(가) 아니다'  # 가림을 켜도 원문 (UX11 B)
    assert ran.result.verdict == "fail"
    assert ran.end("n_cmp")["message"] == expected
    assert ran.result.reason is not None and ran.result.reason.endswith(expected)
    assert "hunter2" in repr(ran.events)


class _PlainWordPlatform(_OcrPlatform):
    """숫자 없는 글자 (`parse: number`가 `unreadable`로 끝난다)."""

    def read_text(self, image: Image, *, region: Any, sensitive: bool, limits: Any) -> OcrResult:
        text: str | Secret = Secret("Gold") if sensitive else "Gold"
        return OcrResult(text, (OcrLine(text, Rect(20, 20, 240, 52), 0.9),), 0.9)


@pytest.mark.parametrize("redact", [False, True], ids=["default", "redact"])
def test_sensitive_ocr_fail_messages_follow_policy(tmp_path: Path, redact: bool) -> None:
    """P1 검수 4: 민감 target으로 읽은 글자가 든 실패 메시지(`assert.text`·`ocr.read`)도 기록 정책을
    따른다. 출력 `text`는 여전히 비밀값 형식이다."""
    ws = make_workspace(tmp_path, record=REDACT if redact else None)
    rel = _gold_target(ws, sensitive=True)
    g = tk().entry("n_text")
    g.node(
        "n_text",
        "core.assert.text",
        inputs={"region": {"$target": rel}, "equals": "Gold 0", "timeout_ms": 0},
    )
    ran = _run_ocr(ws, g)
    shown = repr(GOLD_TEXT)  # 가림을 켜도 원문 (UX11 B)
    assert ran.end("n_text")["message"] == f"읽은 글자 {shown}이(가) 'Gold 0'와(과) 같지 않는다"

    g = tk().entry("n_read")
    g.node("n_read", "core.ocr.read", inputs={"region": {"$target": rel}, "parse": "number"})
    g.write(ws, TEST_FILE)
    result = Executor(
        registry_with_testkit(),
        platform=_PlainWordPlatform(FRAMES),
        clock=FakeClock(),
        artifacts=MemoryArtifacts(),
    ).run(load_program(ws, TEST_FILE, secrets=MemorySecrets({})), ExecOptions(run_id="r2"))
    (start,) = [e for e in result.events if e["event"] == "step.start" and e["node"] == "n_read"]
    (end,) = [e for e in result.events if e["event"] == "step.end" and e["step"] == start["step"]]
    shown = "'Gold'"
    assert end["message"] == f"읽은 글자 {shown}에 수가 없다"


def test_sensitive_text_cannot_reach_string_only_pin(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    rel = _gold_target(ws, sensitive=True)
    g = _read_graph(rel, then="n_set")
    g.node("n_set", "core.input.key", inputs={"keys": link("n_read.text")})
    g.write(ws, TEST_FILE)
    diags = [d for d in check(ws, TEST_FILE) if d.severity == "error"]
    assert [(d.code, d.node) for d in diags] == [("type_mismatch", "n_set")]


def test_workspace_without_video_defaults_to_failed_only(tmp_path: Path) -> None:
    # M3: 워크스페이스에 record.video가 없으면 영상은 failed_only (성공한 실행의 영상은 지운다)
    ws = make_workspace(tmp_path)
    g = (
        tk()
        .entry("n_plain")
        .node("n_plain", "testkit.shot", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    ran = run(ws, g)
    recorder = ran.result.recorder
    assert recorder is not None
    step = ran.step_of("n_plain")
    assert recorder.video_policy(step) == "failed_only"
    assert not recorder.video_allowed(step, run_failed=False)
    assert recorder.policy(step).policy.sources.get("video") is None  # 정한 곳 없음(기본값)
