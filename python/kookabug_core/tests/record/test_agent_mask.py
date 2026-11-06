"""에이전트용 비밀값 분류 (M5 계획 3.8): runner가 실행 때 "가림이 켜져 있었다면 가렸을 것"을
표시한다.

- 이벤트 `secret_paths`(입력·출력·변수·오류 메시지·로그), 스텝 `secret`, 증거 `agent_withhold`,
  `run.json` `agent_mask`
- 기본(`redact_secrets: false`)은 원문 그대로 남기고(D3) 표시만 더한다. 비밀값 목록은 어디에도
  저장하지 않는다
"""

from pathlib import Path
from typing import Any

from helpers.graphs import link, make_workspace, secret, subgraph_interface, write_json
from helpers.run import Ran, run_graph, tk
from helpers.supervisor import runner_stderr, start_run
from helpers.worker import worker_env
from testkit import registry_with_testkit

from kb_testing.proc import Spawned
from kookabug_core.engine import ExecOptions, Executor, FakeClock, FakePlatform, MemoryArtifacts
from kookabug_core.loader import load_program
from kookabug_core.record import read_run, read_run_json
from kookabug_core.schema import check_shape
from kookabug_core.workspace import MemorySecrets, Workspace
from kookabug_sdk import Secret
from kookabug_sdk.types import Image, Match, OcrLine, OcrResult, Rect

SUB = "subgraphs/s.graph.json"
TEST_FILE = "tests/t.graph.json"
FRAMES = ["a", "b", "c"]
PW = "hunter2"


def _journaled(event: dict[str, Any]) -> dict[str, Any]:
    return {**event, "run": "r8k2x7qm", "seq": 1, "t": "2026-10-30T00:00:00.000Z"}


def _all_steps(ran: Ran, node: str) -> list[dict[str, Any]]:
    steps = {e["step"] for e in ran.of("step.start") if e["node"] == node}
    return [e for e in ran.of("step.end") if e["step"] in steps]


def test_secret_marked_via_direct_link_var_and_call_arg(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    # 서브그래프: 호출 인자로 받은 비밀값을 $link로 다시 넘긴다
    inner = (
        tk("subgraph", interface=subgraph_interface(inputs={"pw": "secret"}))
        .entry("n_in")
        .node(
            "n_in",
            "testkit.shot",
            inputs={"save": True, "value": link("n_entry.pw")},
            next={"done": "n_exit"},
        )
        .exit("n_exit", "done")
    )
    inner.write(ws, SUB)
    g = (
        tk()
        .entry("n_plain")
        .node("n_plain", "testkit.shot", inputs={"save": True}, next={"done": "n_direct"})
        .node(
            "n_direct",
            "testkit.shot",
            inputs={"save": True, "value": secret("acc.pw")},
            next={"done": "n_set"},
        )
        .node(
            "n_set",
            "core.var.set",
            inputs={"name": "pw", "value": secret("acc.pw")},
            next={"done": "n_use"},
        )
        .node("n_get", "core.var.get", inputs={"name": "pw"})
        .node(
            "n_use",
            "testkit.shot",
            inputs={"save": True, "value": link("n_get.value")},
            next={"done": "n_call"},
        )
        .call("n_call", SUB, inputs={"pw": secret("acc.pw")}, next={"done": "n_log"})
        .node("n_log", "core.log.message", inputs={"text": secret("acc.pw")}, next={"done": "n_x"})
        .node("n_x", "core.test.pass", inputs={"reason": secret("acc.pw")})
    )
    ran = run_graph(ws, g, frames=FRAMES, secrets={"acc.pw": PW})
    assert ran.result.verdict == "pass", ran.result.reason
    # D3: 원문은 그대로 남는다 (가림 꺼짐)
    assert ran.result.reason == PW and PW in repr(ran.events)
    # 판정 사유에 비밀값 → run.end.secret_paths(runner가 씀)의 근거
    assert ran.result.reason_secret is True

    plain = ran.end("n_plain")
    assert "secret" not in plain and "agent_withhold" not in plain and "secret_paths" not in plain

    for node in ("n_direct", "n_use", "n_in"):
        end = ran.end(node)
        assert end["secret"] is True, node
        # 가림이 켜져 있었다면 막혔을 스크린샷·썸네일 → agent_withhold
        assert end["outputs"]["saved"] in end["agent_withhold"], node
        assert end["artifacts"] == [end["outputs"]["saved"]]
    # 변수: 쓰는 스텝(입력)과, 순수 노드 core.var.get을 $link로 받은 스텝(n_use, 위) 모두 표시
    assert ran.end("n_set")["secret"] is True
    call = ran.end("n_call")
    assert call["secret"] is True
    # 서브그래프 entry는 호출 인자(비밀값)를 출력으로 낸다
    (entry,) = [e for e in _all_steps(ran, "n_entry") if e.get("secret_paths")]
    assert entry["secret_paths"] == ["/outputs/pw"] and entry["secret"] is True

    (log,) = [e for e in ran.of("log") if e["node"] == "n_log"]
    assert log["message"] == PW and log["secret_paths"] == ["/message"]

    # 표시는 위치(pointer)뿐이다: 값이 이벤트에 더 들어가지 않는다
    for event in ran.events:
        for path in event.get("secret_paths", ()):
            assert path.startswith("/") and PW not in path
        assert check_shape(_journaled(event), "events") == [], event


def test_secret_fail_message_and_error_marked(tmp_path: Path) -> None:
    g = tk().entry("n_cmp")
    g.node("n_cmp", "core.assert.compare", inputs={"a": secret("a"), "op": "==", "b": secret("b")})
    ran = run_graph(make_workspace(tmp_path), g, frames=FRAMES, secrets={"a": PW, "b": "hunter3"})
    assert ran.result.verdict == "fail"
    end = ran.end("n_cmp")
    assert PW in end["message"] and "/message" in end["secret_paths"]
    assert end["secret"] is True
    assert ran.result.reason_secret is True

    # 가림을 켜도 표시는 같다 (값은 이미 ***)
    redacted = run_graph(
        make_workspace(tmp_path / "2", record={"redact_secrets": True}),
        g,
        frames=FRAMES,
        secrets={"a": PW, "b": "hunter3"},
    )
    end = redacted.end("n_cmp")
    assert PW not in repr(redacted.events)
    assert "/message" in end["secret_paths"] and end["secret"] is True
    assert "agent_withhold" not in end  # 가림이 켜져 있으면 이미 남기지 않았다


# ---------------------------------------------------------------- 민감 target OCR


GOLD = "Gold 12,345"


class _OcrPlatform(FakePlatform):
    def find(self, image: Image, target: Any, *, region: Any, limits: Any) -> Match | None:
        return Match(Rect(20, 20, 240, 52), 0.99, frame=image.frame, target=target.name)

    def diff(self, a: Image, b: Image, *, region: Any) -> float:
        return 0.0

    def read_text(self, image: Image, *, region: Any, sensitive: bool, limits: Any) -> OcrResult:
        text: str | Secret = Secret(GOLD) if sensitive else GOLD
        return OcrResult(text, (OcrLine(text, Rect(20, 20, 240, 52), 0.9),), 0.9)


def _ocr_run(ws: Workspace, *, sensitive: bool) -> Ran:
    rel = "targets/world/gold.target.json"
    body: dict[str, Any] = {"format": "kookabug.target/0", "image": "gold.png"}
    if sensitive:
        body["sensitive"] = True
    path = write_json(ws, rel, body)
    (path.parent / "gold.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    g = tk().entry("n_read")
    g.node(
        "n_read",
        "core.ocr.read",
        inputs={"region": {"$target": rel}, "parse": "number"},
        next={"done": "n_ok"},
    )
    g.node("n_ok", "core.assert.compare", inputs={"a": 1, "op": "==", "b": 1})
    g.write(ws, TEST_FILE)
    program = load_program(ws, TEST_FILE, secrets=MemorySecrets({}))
    platform = _OcrPlatform(FRAMES)
    artifacts = MemoryArtifacts()
    executor = Executor(
        registry_with_testkit(), platform=platform, clock=FakeClock(), artifacts=artifacts
    )
    result = executor.run(program, ExecOptions(run_id="r1"))
    return Ran(result, platform, FakeClock(), program, artifacts)


def test_sensitive_ocr_output_marked(tmp_path: Path) -> None:
    ran = _ocr_run(make_workspace(tmp_path), sensitive=True)
    assert ran.result.verdict == "pass", ran.result.reason
    end = ran.end("n_read")
    # D3: 원문 그대로, 출력 text는 비밀값 형식이었다 → 표시
    assert end["outputs"]["text"] == GOLD
    assert "/outputs/text" in end["secret_paths"]
    assert end["secret"] is True
    ocr = f"steps/{end['step']}_ocr.txt"
    assert end["artifacts"] == [ocr] and ran.artifacts.texts[ocr] == GOLD
    # 가림이 켜져 있었다면 sensitive_target으로 빠졌을 OCR 글자 → 에이전트에게 주지 않음
    assert ocr in end["agent_withhold"]
    assert check_shape(_journaled(end), "events") == []

    # 민감하지 않은 target은 표시 없음
    plain = _ocr_run(make_workspace(tmp_path / "2"), sensitive=False).end("n_read")
    assert "secret" not in plain and "agent_withhold" not in plain and "secret_paths" not in plain


# ---------------------------------------------------------------- 비밀값 목록을 쓰지 않음


def test_no_plaintext_secret_list_written(tmp_path: Path, spawned: Spawned) -> None:
    """실제 runner: 가림을 켠 워크스페이스에서 분류가 들어간 실행 폴더·워크스페이스 어디에도 비밀값
    원문이 없다(분류는 위치만 남긴다). `run.json`에 `agent_mask: 1`, 판정 사유가 비밀값이면
    `secret_paths: ["/reason"]`."""
    root = tmp_path / "ws"
    make_workspace(root, record={"redact_secrets": True})
    g = (
        tk()
        .entry("n_take")
        .node(
            "n_take",
            "testkit.sleep",
            inputs={"ms": 1, "value": secret("acc.pw")},
            next={"done": "n_log"},
        )
        .node("n_log", "core.log.message", inputs={"text": secret("acc.pw")}, next={"done": "n_x"})
        .node("n_x", "core.test.fail", inputs={"reason": secret("acc.pw")})
    )
    env = {**worker_env(tmp_path, None), "KOOKABUG_SECRET_ACC_PW": PW}
    handle = start_run(tmp_path, spawned, g, env=env)
    outcome = handle.wait(60)
    assert outcome is not None
    run_json = read_run_json(handle.run_dir / "run.json")
    assert run_json is not None
    assert run_json["agent_mask"] == 1
    assert run_json["verdict"] == "fail", (run_json, runner_stderr(handle))
    assert run_json["secret_paths"] == ["/reason"]
    assert check_shape(run_json, "run") == []
    view = read_run(handle.run_dir)
    end = view.run_end
    assert end is not None and end["secret_paths"] == ["/reason"]
    marked = [e for e in view.events if e.get("event") == "step.end" and e.get("secret") is True]
    assert len(marked) >= 2  # n_take·n_log·n_x (입력에 비밀값)
    assert all("agent_withhold" not in e for e in marked)  # 가림이 켜져 있으면 남기지 않았다
    (log,) = [e for e in view.events if e.get("event") == "log" and e.get("node") == "n_log"]
    assert log["secret_paths"] == ["/message"] and log["message"] == "***"
    for event in view.events:
        assert check_shape(event, "events") == [], event
    needle = PW.encode()
    for base in (root, tmp_path / "runs"):
        for path in base.rglob("*"):
            if path.is_file():
                assert needle not in path.read_bytes(), path
