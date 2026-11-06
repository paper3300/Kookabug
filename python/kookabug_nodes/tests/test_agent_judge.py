"""Agent 판단 노드 (MVP 노드 목록 10장, M5 계획 3.11·B4).

실행기 + 예제 게임 장면 표(화면 캡처를 이미지로)에서 돌린다. cli는 가짜 ACP 에이전트
(`kb_testing/fake_acp_agent.py`, 실제 프로세스), api는 가짜 모델 API(`kb_testing.fake_model_api`).
실제 외부 API·에이전트 CLI는 부르지 않는다.
"""

from __future__ import annotations

import base64
import json
import os
import socketserver
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.graphs import GraphBuilder, link, make_workspace, secret

from kb_testing.fake_model_api import FakeModelApi
from kb_testing.proc import wait_until
from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.agents import acp, model_api
from kookabug_core.agents.judge import (
    AgentSpec,
    JudgeEnv,
    Scrubber,
    agent_environ,
    parse_answer,
)
from kookabug_core.engine import (
    CancelToken,
    ExecOptions,
    Executor,
    FakeClock,
    GraphInvalid,
    MemoryArtifacts,
    RunResult,
)
from kookabug_core.engine.errors import EngineError
from kookabug_core.engine.scenario import FakeScenario, ScenarioPlatform
from kookabug_core.loader import load_program
from kookabug_core.registry import default_registry
from kookabug_core.service import cli_principal
from kookabug_core.win import identify, is_alive
from kookabug_core.workspace import MemorySecrets
from kookabug_nodes.agent import cli_judge
from kookabug_platform.engines import RunEngines
from kookabug_platform.frames import FrameStore, decode_image
from kookabug_sdk.context import Cancelled
from kookabug_sdk.testing import fake_context

pytestmark = [pytest.mark.process, pytest.mark.timeout(120)]

FAKE_AGENT: Final = (
    Path(__file__).resolve().parents[3] / "tools" / "kb_testing" / "fake_acp_agent.py"
)
SCENARIO: Final = FRAMES_DIR / "scenario.json"
TEST: Final = "tests/t.graph.json"
KEY: Final = "sk-test-SECRET-key-0123456789"
CHOICES: Final = ["title", "loading"]
PNG_MAGIC: Final = b"\x89PNG\r\n\x1a\n"


@dataclass
class Judged:
    result: RunResult
    artifacts: MemoryArtifacts
    log: Path
    root: Path

    def of(self, event: str) -> list[dict[str, Any]]:
        return [e for e in self.result.events if e["event"] == event]

    def step(self, node: str) -> str:
        (step,) = [e["step"] for e in self.of("step.start") if e["node"] == node]
        return step

    def end(self, node: str) -> dict[str, Any]:
        step = self.step(node)
        (found,) = [e for e in self.of("step.end") if e["step"] == step]
        return found

    def record(self, node: str) -> dict[str, Any]:
        return json.loads(self.artifacts.texts[f"steps/{self.step(node)}_judge.json"])

    def agent_log(self) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        lines = self.log.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]


class Rig:
    """워크스페이스·사용자 설정(가짜 에이전트)·가짜 각본을 만들고 그래프를 돌린다."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.user_dir = tmp_path / "user"
        self.user_dir.mkdir()
        self.log = tmp_path / "agent.jsonl"
        self.script = tmp_path / "script.json"
        self.temp_root = tmp_path / "judge-tmp"
        self.environ: dict[str, str] = dict(os.environ)
        self.agents([{"id": "fake", "name": "가짜 에이전트"}])

    def agents(self, agents: list[dict[str, Any]], default: str | None = None) -> None:
        items = []
        for agent in agents:
            env = {
                "KB_FAKE_ACP_SCRIPT": str(self.script),
                "KB_FAKE_ACP_LOG": str(self.log),
                **agent.pop("env", {}),
            }
            items.append(
                {"command": sys.executable, "args": [str(FAKE_AGENT)], "env": env, **agent}
            )
        body: dict[str, Any] = {"format": "kookabug.user-settings/0", "agents": items}
        if default is not None:
            body["default_agent"] = default
        (self.user_dir / "settings.json").write_text(
            json.dumps(body, ensure_ascii=False), encoding="utf-8"
        )

    def steps(self, *steps: Mapping[str, Any], **extra: Any) -> None:
        self.script.write_text(
            json.dumps({"steps": list(steps), **extra}, ensure_ascii=False), encoding="utf-8"
        )

    def run(
        self,
        graph: GraphBuilder,
        *,
        record: Mapping[str, Any] | None = None,
        secrets: Mapping[str, str] | None = None,
        cancel: CancelToken | None = None,
    ) -> Judged:
        root = self.tmp / "ws"
        ws = make_workspace(root, record=record)
        graph.write(ws, TEST)
        provider = MemorySecrets(dict(secrets or {}))
        program = load_program(ws, TEST, secrets=provider)
        store = FrameStore()
        platform = ScenarioPlatform(
            FakeScenario.load(SCENARIO), decode=decode_image, engines=RunEngines(store)
        )
        artifacts = MemoryArtifacts()
        env = JudgeEnv(self.user_dir, provider, self.temp_root, self.environ)
        result = Executor(
            default_registry(),
            platform=platform,
            clock=FakeClock(),
            cancel=cancel,
            artifacts=artifacts,
            frames=store,
            judge_env=env,
        ).run(program, ExecOptions(run_id="r1"))
        return Judged(result, artifacts, self.log, root)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def judge_graph(
    node_type: str = "core.agent.cli_judge",
    *,
    inputs: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
    unsure: str = "n_fail",
) -> GraphBuilder:
    """게임 띄우기 → 화면 캡처 → 판단 (`loading` → 통과, 나머지 → 실패)."""
    return (
        GraphBuilder()
        .entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_shot"}
        )
        .node("n_shot", "core.screen.capture", next={"done": "n_judge"})
        .node(
            "n_judge",
            node_type,
            inputs={"prompt": "지금 화면은?", "image": link("n_shot.image"), **(inputs or {})},
            config={"choices": CHOICES, **(config or {})},
            next={"loading": "n_pass", "title": "n_fail", "unsure": unsure},
        )
        .node("n_pass", "core.test.pass")
        .node("n_fail", "core.test.fail", inputs={"reason": "다른 답"})
    )


def process_dead(log: list[dict[str, Any]]) -> None:
    (start,) = [e for e in log if e["event"] == "start"]
    pid = start["pid"]
    wait_until(lambda: not _alive(pid), timeout=15, message=f"가짜 에이전트 {pid}가 살아 있다")


def _alive(pid: int) -> bool:
    ident = identify(pid)
    return ident is not None and is_alive(ident)


# ---------------------------------------------------------------- cli


def test_cli_judge_picks_choice_exit(rig: Rig) -> None:
    """도구 호출 뒤 마지막 메시지의 첫 JSON 객체 → 그 선택지 출구. 이미지·질문·선택지가 간다."""
    rig.steps(
        {"do": "say", "text": '생각 중 {"answer": "title"}'},
        {"do": "tool", "title": "보기"},
        {"do": "answer", "answer": "loading", "reason": "로딩 막대", "prefix": "결론: "},
    )
    ran = rig.run(judge_graph())
    assert ran.result.verdict == "pass", ran.result.reason
    end = ran.end("n_judge")
    assert end["exit"] == "loading"
    assert end["outputs"] == {"answer": "loading", "reason": "로딩 막대"}
    (prompt,) = [e for e in ran.agent_log() if e.get("method") == "session/prompt"]
    blocks = prompt["params"]["prompt"]
    assert blocks[0]["type"] == "image" and blocks[0]["mimeType"] == "image/png"
    assert blocks[0]["data_len"] > 100
    assert "지금 화면은?" in blocks[1]["text"] and '["title", "loading"]' in blocks[1]["text"]
    record = ran.record("n_judge")
    assert record["kind"] == "cli" and record["agent"] == {"id": "fake", "name": "가짜 에이전트"}
    assert (record["answer"], record["exit"], record["choices"]) == ("loading", "loading", CHOICES)
    assert record["image"]["width"] <= 1568 and "결론" in record["text"]
    assert isinstance(record["duration_ms"], int)


@pytest.mark.parametrize(
    "steps",
    [
        [{"do": "say", "text": "잘 모르겠다"}],
        [{"do": "answer", "answer": "world", "reason": "필드"}],
        [{"do": "answer", "answer": "Loading", "reason": "대소문자"}],
        [{"do": "say", "text": '{"answer": ["loading"]}'}],
    ],
    ids=["no_json", "not_a_choice", "case_differs", "not_text"],
)
def test_unparseable_or_unknown_answer_is_unsure(rig: Rig, steps: list[dict[str, Any]]) -> None:
    rig.steps(*steps)
    ran = rig.run(judge_graph(unsure="n_pass"))
    assert ran.result.verdict == "pass", ran.result.reason
    end = ran.end("n_judge")
    assert end["exit"] == "unsure"
    assert ran.record("n_judge")["exit"] == "unsure"
    assert end["outputs"]["reason"]  # 받은 글자 앞부분


def test_unsure_unconnected_fails_test(rig: Rig) -> None:
    rig.steps({"do": "say", "text": "?"})
    graph = judge_graph()
    del graph.nodes["n_judge"]["next"]["unsure"]
    ran = rig.run(graph)
    assert ran.result.verdict == "fail"


def test_timeout_is_error_and_process_killed(rig: Rig) -> None:
    rig.steps({"do": "sleep", "ms": 60000})
    ran = rig.run(judge_graph(inputs={"timeout_ms": 1500}))
    assert (ran.result.verdict, ran.result.code) == ("error", "agent_timeout")
    assert ran.end("n_judge")["error"]["code"] == "agent_timeout"
    process_dead(ran.agent_log())
    assert ran.record("n_judge")["error"]["code"] == "agent_timeout"
    assert list(rig.temp_root.iterdir()) == []  # 작업 폴더도 지웠다


def test_cancel_kills_agent(rig: Rig) -> None:
    rig.steps({"do": "sleep", "ms": 60000})
    token = CancelToken()
    out: dict[str, Judged] = {}
    worker = threading.Thread(target=lambda: out.update(ran=rig.run(judge_graph(), cancel=token)))
    worker.start()
    try:
        wait_until(
            lambda: rig.log.exists() and "session/prompt" in rig.log.read_text(encoding="utf-8"),
            timeout=30,
        )
        token.cancel()
    finally:
        worker.join(60)
    ran = out["ran"]
    assert (ran.result.verdict, ran.result.code) == ("error", "cancelled")
    process_dead(ran.agent_log())


def test_start_failed_and_not_configured(rig: Rig) -> None:
    rig.steps(die_at="initialize")
    ran = rig.run(judge_graph())
    assert ran.result.code == "agent_start_failed"
    rig.agents([{"id": "fake", "name": "x", "command": "no-such-agent-cli-kb"}])
    assert rig.run(judge_graph()).result.code == "agent_start_failed"
    ran = rig.run(judge_graph(config={"agent": "other"}))
    assert ran.result.code == "agent_not_configured"
    (rig.user_dir / "settings.json").unlink()
    assert rig.run(judge_graph()).result.code == "agent_not_configured"


def test_default_agent_and_explicit_pick(rig: Rig) -> None:
    rig.agents(
        [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        default="b",
    )
    rig.steps({"do": "answer", "answer": "loading"})
    assert rig.run(judge_graph()).record("n_judge")["agent"]["id"] == "b"
    assert rig.run(judge_graph(config={"agent": "a"})).record("n_judge")["agent"]["id"] == "a"


def test_cli_judge_agent_has_no_control_tools(rig: Rig) -> None:
    """완료 기준 5: MCP 서버 없음, fs·terminal 능력 없음, 권한 요청 거절, 빈 임시 작업 폴더(끝나면
    없음), 환경에 daemon 토큰·세션·비밀값 환경 변수 없음, `KOOKABUG_AGENT`만."""
    rig.environ.update(
        KOOKABUG_RPC_KEY="rpc-token-1",
        KOOKABUG_RPC_PIPE=r"\\.\pipe\kb-1",
        KOOKABUG_SECRET_ACC_PW="hunter2",
        KOOKABUG_USER_CONFIG_DIR=str(rig.user_dir),
    )
    rig.agents(
        [
            {
                "id": "fake",
                "name": "F",
                "env": {"KOOKABUG_DAEMON_ARGS": "x", "AGENT_TOKEN": {"$secret": "agent.tok"}},
            }
        ]
    )
    rig.steps(
        {"do": "permission"},
        {"do": "permission", "options": [{"optionId": "ok", "name": "허용", "kind": "allow_once"}]},
        {"do": "client", "method": "fs/write_text_file", "params": {"path": "x", "content": "y"}},
        {"do": "client", "method": "terminal/create", "params": {"command": "cmd"}},
        {"do": "answer", "answer": "loading"},
    )
    ran = rig.run(judge_graph(), secrets={"agent.tok": "tok-value"})
    assert ran.result.verdict == "pass", ran.result.reason
    log = ran.agent_log()
    (init,) = [e for e in log if e.get("method") == "initialize"]
    assert init["params"]["clientCapabilities"] == {
        "fs": {"readTextFile": False, "writeTextFile": False},
        "terminal": False,
    }
    (new,) = [e for e in log if e.get("method") == "session/new"]
    assert new["params"]["mcpServers"] == []
    (start,) = [e for e in log if e["event"] == "start"]
    assert start["cwd_entries"] == []
    cwd = Path(start["cwd"])
    assert Path(new["params"]["cwd"]) == cwd
    assert not cwd.exists()
    assert not cwd.resolve().is_relative_to(ran.root.resolve())  # 워크스페이스 밖
    assert start["env"] == {"KOOKABUG_AGENT": f"judge:r1:{ran.step('n_judge')}"}
    responses = [e for e in log if e["event"] == "response"]
    perms = [
        e["result"]["outcome"] for e in responses if e["method"] == "session/request_permission"
    ]
    assert perms == [{"outcome": "selected", "optionId": "reject"}, {"outcome": "cancelled"}]
    for method in ("fs/write_text_file", "terminal/create"):
        (reply,) = [e for e in responses if e["method"] == method]
        assert reply["error"]["code"] == -32601
    assert ran.record("n_judge")["permission_requests"] == 2


@pytest.mark.parametrize("fail", ["create", "assign"])
def test_job_failure_is_error_and_agent_never_runs(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, fail: str
) -> None:
    """에이전트는 멈춘 채 띄워 Job에 넣은 뒤에야 돈다. Job을 만들거나 넣지 못하면 판단 `error`
    (`agent_start_failed`)이고 에이전트는 한 줄도 실행하지 않는다 (BACKLOG M5 B5)."""
    rig.steps({"do": "answer", "answer": "loading"})

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise OSError("job 실패 (검사)")

    monkeypatch.setattr(acp.Job, fail, broken)
    ran = rig.run(judge_graph())
    assert (ran.result.verdict, ran.result.code) == ("error", "agent_start_failed")
    assert "Job" in ran.end("n_judge")["error"]["message"]
    assert ran.agent_log() == []


def test_agent_without_image_support_is_protocol_error(rig: Rig) -> None:
    rig.steps({"do": "answer", "answer": "loading"}, image=False)
    assert rig.run(judge_graph()).result.code == "agent_protocol_error"


def test_fake_ctx_not_supported() -> None:
    from kookabug_sdk import RunnerError

    ctx = fake_context(config={"choices": CHOICES, "agent": ""})
    with pytest.raises(RunnerError) as caught:
        cli_judge(ctx, prompt="?")
    assert caught.value.code == "not_supported"


def test_parse_answer_first_object() -> None:
    assert parse_answer('x {"answer": "a", "reason": "r"} {"answer": "b"}', ["a", "b"]) == (
        "a",
        "a",
        "r",
    )
    assert parse_answer('{bad json} {"answer": "b"}', ["a", "b"])[0] == "b"
    assert parse_answer("", ["a"])[0] == "unsure"


# ---------------------------------------------------------------- api


def api_graph(api: FakeModelApi, provider: str, **inputs: Any) -> GraphBuilder:
    endpoint = api.base if provider == "anthropic" else api.base + "/v1"
    return judge_graph(
        "core.agent.api_judge",
        inputs={"model": "m-1", "api_key": secret("model.key"), **inputs},
        config={"provider": provider, "endpoint": endpoint},
    )


@pytest.mark.parametrize("provider", ["anthropic", "openai_compatible"])
def test_api_judge_anthropic_and_openai_shapes(rig: Rig, provider: str) -> None:
    with FakeModelApi('```json\n{"answer": "loading", "reason": "막대"}\n```') as api:
        ran = rig.run(api_graph(api, provider), secrets={"model.key": KEY})
    assert ran.result.verdict == "pass", ran.result.reason
    assert ran.end("n_judge")["outputs"] == {"answer": "loading", "reason": "막대"}
    (request,) = api.requests
    body = request["body"]
    assert body["model"] == "m-1"
    assert not {"tools", "tool_choice", "functions"} & set(body)
    (message,) = body["messages"]
    if provider == "anthropic":
        assert request["path"] == "/v1/messages"
        assert request["headers"]["x-api-key"] == KEY
        assert request["headers"]["anthropic-version"]
        image, text = message["content"]
        assert image["source"]["media_type"] == "image/png"
        data = base64.b64decode(image["source"]["data"])
    else:
        assert request["path"] == "/v1/chat/completions"
        assert request["headers"]["authorization"] == f"Bearer {KEY}"
        text, image = message["content"]
        url = image["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        data = base64.b64decode(url.split(",", 1)[1])
    assert data.startswith(PNG_MAGIC)
    pixels = decode_image(data)
    assert max(pixels.shape[:2]) <= 1568
    assert "지금 화면은?" in text["text"]


def test_api_http_error(rig: Rig) -> None:
    """HTTP 오류 → `api_http_error`(상태 코드). 응답에 키가 섞여 와도 오류·기록에는 없다."""
    body = '{"error": {"message": "invalid x-api-key: {key}"}}'
    with FakeModelApi(status=401, error_body=body) as api:
        ran = rig.run(api_graph(api, "anthropic"), secrets={"model.key": KEY})
    assert (ran.result.verdict, ran.result.code) == ("error", "api_http_error")
    error = ran.end("n_judge")["error"]
    assert "401" in error["message"] and "***" in error["message"]
    assert KEY not in json.dumps(error) and KEY not in ran.result.reason
    record = ran.artifacts.texts[f"steps/{ran.step('n_judge')}_judge.json"]
    assert KEY not in record and json.loads(record)["error"]["code"] == "api_http_error"
    for event in ran.result.events:
        if event["event"] in ("log", "run.end") or event["event"] == "step.end":
            assert KEY not in json.dumps({k: v for k, v in event.items() if k != "inputs"})


def test_api_timeout_and_endpoint_rules(rig: Rig) -> None:
    with FakeModelApi("{}", delay_s=5) as api:
        ran = rig.run(api_graph(api, "anthropic", timeout_ms=800), secrets={"model.key": KEY})
    assert ran.result.code == "agent_timeout"
    graph = judge_graph(
        "core.agent.api_judge",
        inputs={"model": "m", "api_key": secret("model.key")},
        config={"provider": "openai_compatible", "endpoint": "http://example.com/v1"},
    )
    assert rig.run(graph, secrets={"model.key": KEY}).result.code == "api_endpoint_invalid"
    with pytest.raises(model_api.ApiFailure):
        model_api.request_for("anthropic", "https://u:p@example.com", "m", KEY, "t", None)
    # 키 원문을 그래프에 쓰면 비밀값 핀이 받지 않는다 (실행 전 검증)
    plain = judge_graph(
        "core.agent.api_judge",
        inputs={"model": "m", "api_key": KEY},
        config={"provider": "anthropic"},
    )
    with pytest.raises(GraphInvalid):
        rig.run(plain)


@pytest.mark.parametrize("redact", [False, True])
def test_judge_record_written_and_secret_policy(rig: Rig, redact: bool) -> None:
    """`steps/<스텝>_judge.json`을 남긴다. API 키는 기록에 없다. `redact_secrets: true`면 이벤트에도
    없고(가림), 이미지는 비밀값 입력 스텝이라 남기지 않는다. 기본(D3)은 원문 기록 + 에이전트용
    분류(`secret`) — agent 조회는 이 스텝 증거를 거부한다."""
    with FakeModelApi('{"answer": "title", "reason": "제목"}') as api:
        ran = rig.run(
            api_graph(api, "anthropic"),
            record={"redact_secrets": redact},
            secrets={"model.key": KEY},
        )
    assert ran.result.verdict == "fail"  # title → n_fail
    step = ran.step("n_judge")
    path = f"steps/{step}_judge.json"
    text = ran.artifacts.texts[path]
    assert KEY not in text
    record = json.loads(text)
    assert record["format"] == "kookabug.judge/0"
    assert (record["kind"], record["provider"], record["model"]) == ("api", "anthropic", "m-1")
    assert record["prompt"] == "지금 화면은?" and record["choices"] == CHOICES
    assert (record["answer"], record["reason"], record["exit"]) == ("title", "제목", "title")
    assert '"answer": "title"' in record["text"] and record["duration_ms"] >= 0
    end = ran.end("n_judge")
    assert path in end["artifacts"]
    assert end.get("secret") is True  # 에이전트용 분류 (D3 여부와 상관없이)
    image = f"steps/{step}_judge.png"
    dumped = json.dumps(ran.result.events, ensure_ascii=False)
    if redact:
        assert KEY not in dumped
        assert image not in end["artifacts"]
        assert any(o.get("reason") == "secret_input" for o in end.get("omitted", []))
    else:
        assert image in end["artifacts"]
    agent_refuses(ran, path)


def agent_run(ran: Judged, run_id: str = "r1") -> Any:
    """실행기 이벤트·텍스트 기록을 실행 폴더로 옮기고 에이전트용 보기(B2 `AgentRun`)를 연다.
    분류는 실행기가 남긴 그대로다(더하거나 빼지 않는다)."""
    agent_view = pytest.importorskip("kookabug_daemon.agent_view")
    folder = ran.root / "runs" / f"2026-11-06T00-00-00_t_{run_id}"
    folder.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {"t": f"2026-11-06T00:00:00.{i:03d}Z", **e, "seq": i, "run": run_id},
            ensure_ascii=False,
        )
        for i, e in enumerate(ran.result.events, start=1)
    ]
    (folder / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    run_json = {
        "format": "kookabug.run/0",
        "graph": TEST,
        "run_id": run_id,
        "status": "finished",
        "agent_mask": 1,
    }
    (folder / "run.json").write_text(json.dumps(run_json), encoding="utf-8")
    for rel, text in ran.artifacts.texts.items():
        path = folder.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return agent_view.AgentRun.load(run_id, folder)


def agent_refuses(ran: Judged, rel: str) -> None:
    """에이전트 연결의 `run.artifact`가 이 파일을 거부한다 (B2 분류 — 비밀값 스텝)."""
    refusal = agent_run(ran).refusal(rel)
    assert refusal is not None and refusal.code == "secret_step"


# ---------------------------------------------------------------- 인증값·전송·수명 (B4 검수 반례)

ECHO_KEY: Final = "B4-FAKE-secret-0368-not-real"


def agent_exposure(ran: Judged) -> str:
    """에이전트가 받을 수 있는 것: 가린 이벤트 + (거부되지 않으면) 판단 기록."""
    view = agent_run(ran)
    rel = f"steps/{ran.step('n_judge')}_judge.json"
    exposed: dict[str, Any] = {"events": [view.event(e) for e in view.events]}
    if view.refusal(rel) is None:
        exposed["artifact"] = ran.artifacts.texts[rel]
    return json.dumps(exposed, ensure_ascii=False)


@pytest.mark.parametrize("redact", [False, True])
def test_api_echo_is_hidden_from_agent_events(rig: Rig, redact: bool) -> None:
    """API가 답에 인증키를 섞어 보내도 출력·기록·에이전트 이벤트에 원문이 없다(가린 필드는 분류)."""
    with FakeModelApi(json.dumps({"answer": "loading", "reason": ECHO_KEY})) as api:
        ran = rig.run(
            api_graph(api, "anthropic"),
            secrets={"model.key": ECHO_KEY},
            record={"redact_secrets": redact},
        )
    assert ran.result.verdict == "pass", ran.result.reason
    end = ran.end("n_judge")
    assert end["outputs"]["reason"] == "***"
    assert "/outputs/reason" in end["secret_paths"] and end["secret"] is True
    assert ECHO_KEY not in ran.artifacts.texts[f"steps/{ran.step('n_judge')}_judge.json"]
    assert ECHO_KEY not in agent_exposure(ran)
    assert agent_run(ran).refusal(f"steps/{ran.step('n_judge')}_judge.json").code == "secret_step"


def test_api_echo_is_redacted_in_record(rig: Rig) -> None:
    with FakeModelApi(json.dumps({"answer": "loading", "reason": ECHO_KEY})) as api:
        ran = rig.run(
            api_graph(api, "openai_compatible"),
            secrets={"model.key": ECHO_KEY},
            record={"redact_secrets": True},
        )
    assert ECHO_KEY not in json.dumps(ran.artifacts.texts)
    assert ECHO_KEY not in json.dumps(ran.result.events)


@pytest.mark.parametrize("redact", [False, True])
@pytest.mark.parametrize("mode", ["echo", "error"])
def test_cli_env_secret_is_hidden(rig: Rig, redact: bool, mode: str) -> None:
    """에이전트 env의 `$secret` 값이 답(echo)·ACP 오류(error)에 섞여 와도 기록·이벤트·에이전트
    조회에 원문이 없다. env에 비밀값을 준 스텝은 `secret`이라 판단 기록을 에이전트에게 주지
    않는다."""
    rig.agents([{"id": "fake", "name": "F", "env": {"AGENT_TOKEN": {"$secret": "agent.token"}}}])
    step = (
        {"do": "say_env", "var": "AGENT_TOKEN"}
        if mode == "echo"
        else {"do": "error_env", "var": "AGENT_TOKEN"}
    )
    rig.steps(step)
    ran = rig.run(
        judge_graph(), secrets={"agent.token": ECHO_KEY}, record={"redact_secrets": redact}
    )
    if mode == "echo":
        assert ran.result.verdict == "pass", ran.result.reason
    else:
        assert ran.result.code == "agent_protocol_error"
        assert "***" in ran.end("n_judge")["error"]["message"]
    assert ECHO_KEY not in json.dumps(ran.artifacts.texts)
    assert ECHO_KEY not in json.dumps(ran.result.events)
    assert ran.end("n_judge")["secret"] is True
    assert ECHO_KEY not in agent_exposure(ran)
    assert agent_run(ran).refusal(f"steps/{ran.step('n_judge')}_judge.json").code == "secret_step"


def test_short_api_key_http_error_is_scrubbed(rig: Rig) -> None:
    with FakeModelApi(status=401, error_body="bad-token={key}") as api:
        ran = rig.run(
            api_graph(api, "anthropic"),
            secrets={"model.key": "Q7z"},
            record={"redact_secrets": True},
        )
    assert ran.result.code == "api_http_error"
    assert "Q7z" not in json.dumps(ran.artifacts.texts)
    assert "Q7z" not in json.dumps(ran.result.events)


@pytest.mark.parametrize("provider", ["anthropic", "openai_compatible"])
def test_redirect_does_not_forward_credentials(provider: str) -> None:
    """판단 API는 redirect를 따르지 않는다: 3xx = `api_http_error`, 다른 목적지에 인증 헤더 없음."""
    captured: list[dict[str, str]] = []

    class Target(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            captured.append(dict(self.headers.items()))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        do_POST = do_GET

    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)

    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["content-length"]))
            self.send_response(302)
            self.send_header(
                "Location", f"http://localhost:{target.server_port}/other?k={ECHO_KEY}"
            )
            self.end_headers()

    source = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    for server in (source, target):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(model_api.ApiFailure) as caught:
            model_api.ask(
                provider,
                f"http://127.0.0.1:{source.server_port}",
                "fake",
                ECHO_KEY,
                "?",
                None,
                deadline=time.monotonic() + 5,
                check=lambda: None,
            )
    finally:
        for server in (source, target):
            server.shutdown()
            server.server_close()
    assert caught.value.code == "api_http_error" and "302" in caught.value.message
    assert ECHO_KEY not in caught.value.message
    assert captured == []


@pytest.mark.parametrize("mode", ["timeout", "cancel"])
def test_blocked_stdin_respects_timeout(tmp_path: Path, mode: str) -> None:
    """에이전트가 입력을 읽지 않아 쓰기가 막혀도 기한·취소를 지키고 프로세스를 끝낸다."""
    log = tmp_path / "agent.jsonl"
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"stall_after": "session/new"}), encoding="utf-8")
    env = {**os.environ, "KB_FAKE_ACP_SCRIPT": str(script), "KB_FAKE_ACP_LOG": str(log)}
    started = time.monotonic()
    cancel = mode == "cancel"

    def check() -> None:
        if cancel and time.monotonic() - started > 1:
            raise Cancelled("cancelled")

    out: dict[str, str] = {}

    def call() -> None:
        try:
            acp.ask(
                acp.AgentCommand(sys.executable, [str(FAKE_AGENT)], env, tmp_path),
                [{"type": "text", "text": "x" * 300_000}],
                deadline=started + (60 if cancel else 1),
                check=check,
            )
        except acp.AgentFailure as exc:
            out["code"] = exc.code
        except Cancelled:
            out["code"] = "cancelled"

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    worker.join(8)
    assert not worker.is_alive(), "막힌 쓰기에서 기한·취소를 넘겼다"
    assert out["code"] == ("cancelled" if cancel else "agent_timeout")
    log_lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert any(e["event"] == "stall" for e in log_lines)
    process_dead(log_lines)


@pytest.mark.parametrize("cancelled", [False, True])
def test_descendant_is_killed_on_timeout_and_cancel(rig: Rig, cancelled: bool) -> None:
    pidfile = rig.tmp / "child.pid"
    rig.steps({"do": "spawn_child", "pidfile": str(pidfile)}, {"do": "sleep", "ms": 60000})
    token = CancelToken()

    def cancel_after_child() -> None:
        wait_until(pidfile.exists, timeout=15)
        token.cancel()

    helper = threading.Thread(target=cancel_after_child, daemon=True)
    if cancelled:
        helper.start()
    ran = rig.run(judge_graph(inputs={"timeout_ms": 15000 if cancelled else 2500}), cancel=token)
    if cancelled:
        helper.join(15)
    assert ran.result.code == ("cancelled" if cancelled else "agent_timeout")
    child = int(pidfile.read_text(encoding="utf-8"))
    wait_until(lambda: not _alive(child), timeout=15, message=f"손자 프로세스 {child}가 살아 있다")
    assert list(rig.temp_root.iterdir()) == []


def test_child_cli_identity_is_unattended() -> None:
    """판단 에이전트가 kookabug CLI를 불러도 사람 없는 에이전트로 판정된다."""
    env = agent_environ(
        {"KOOKABUG_RPC_KEY": "fake", "kookabug_rpc_pipe": "fake"},
        AgentSpec("fake", "fake", sys.executable),
        MemorySecrets({}),
        "judge:r:s",
    )
    who = cli_principal(env)
    assert who.kind == "agent" and who.attended is False
    assert set(env) == {"KOOKABUG_AGENT"}


@pytest.mark.parametrize(
    ("text", "exit_name"),
    [
        ("", "unsure"),
        ('{"answer":"outside"}', "unsure"),
        ('{"answer":', "unsure"),
        ('{"answer":"loading"}', "loading"),
        ('{"answer":"title"}', "title"),
    ],
)
def test_empty_malformed_and_choice_mapping(rig: Rig, text: str, exit_name: str) -> None:
    rig.steps({"do": "say", "text": text})
    ran = rig.run(judge_graph(unsure="n_pass"))
    assert ran.end("n_judge")["exit"] == exit_name


def test_all_client_tools_rejected_without_side_effect(rig: Rig) -> None:
    victim = rig.tmp / "owned-by-test.txt"
    victim.write_text("original", encoding="utf-8")
    methods = [
        "fs/read_text_file",
        "fs/write_text_file",
        "terminal/create",
        "terminal/output",
        "terminal/wait_for_exit",
        "terminal/kill",
        "terminal/release",
        "control.click",
        "graph.save",
        "run.start",
    ]
    params = {"path": str(victim), "content": "changed", "command": "fake-only"}
    rig.steps(
        *[{"do": "client", "method": m, "params": params} for m in methods],
        {"do": "permission"},
        {"do": "answer", "answer": "loading"},
    )
    ran = rig.run(judge_graph())
    assert ran.result.verdict == "pass"
    replies = {e["method"]: e for e in ran.agent_log() if e["event"] == "response"}
    assert all(replies[m]["error"]["code"] == -32601 for m in methods)
    assert replies["session/request_permission"]["result"]["outcome"]["optionId"] == "reject"
    assert victim.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("redact", [False, True])
@pytest.mark.parametrize("kind", ["api", "cli"])
def test_real_daemon_rpc_does_not_expose_judge_secret(rig: Rig, redact: bool, kind: str) -> None:
    """실제 daemon의 agent 연결(`run.events`·`run.artifact`)이 판단 인증값 원문을 주지 않는다."""
    daemon_runs = pytest.importorskip("helpers.daemon_runs")
    from kookabug_daemon.client import DaemonError

    if kind == "api":
        with FakeModelApi(json.dumps({"answer": "loading", "reason": ECHO_KEY})) as api:
            ran = rig.run(
                api_graph(api, "anthropic"),
                secrets={"model.key": ECHO_KEY},
                record={"redact_secrets": redact},
            )
    else:
        rig.agents(
            [{"id": "fake", "name": "F", "env": {"AGENT_TOKEN": {"$secret": "agent.token"}}}]
        )
        rig.steps({"do": "say_env", "var": "AGENT_TOKEN"})
        ran = rig.run(
            judge_graph(), secrets={"agent.token": ECHO_KEY}, record={"redact_secrets": redact}
        )
    agent_run(ran, "b4review")
    extra = rig.tmp / "daemon-helper"
    extra.mkdir()
    daemon_rig = daemon_runs.RunRig.make(extra)
    daemon_rig.root = ran.root
    info = {"kind": "agent", "name": "test", "version": "0", "id": "b4-test", "attended": False}
    got: dict[str, Any] = {}
    with daemon_rig.daemon() as daemon, daemon.client(info) as client:
        got["events"] = client.call("run.events", {"run_id": "b4review"})
        try:
            got["artifact"] = client.call(
                "run.artifact",
                {"run_id": "b4review", "path": f"steps/{ran.step('n_judge')}_judge.json"},
            )
        except DaemonError as exc:
            assert exc.data["code"] == "secret_step"
    assert got["events"]["events"]
    assert ECHO_KEY not in json.dumps(got)


# ---------------------------------------------------------------- 2라운드 반례 (JSON·스레드 예외)

QUOTED_KEY: Final = 'B4-test-password-"quote"-\\slash'
"""따옴표·역슬래시가 든 인증값: 답 JSON에서는 이스케이프되어 원문과 글자가 다르다."""
PLAIN_KEY: Final = "B4-test-auth-token-012345"


def strings(value: Any) -> list[str]:
    """값 안의 모든 문자열 (JSON 해석한 뒤 비교 — 이스케이프 때문에 잘못 통과하지 않게)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]  # pyright: ignore[reportUnknownVariableType]
    return []


def holds(value: Any, key: str) -> bool:
    return any(key in s for s in strings(value))


@pytest.mark.parametrize("redact", [False, True])
@pytest.mark.parametrize("kind", ["cli", "api"])
def test_json_decoded_credentials_stay_redacted(rig: Rig, redact: bool, kind: str) -> None:
    """JSON 해석이 이스케이프를 풀어 인증값을 되살려도 출력·기록·에이전트 이벤트·실제 RPC에 원문이
    없고, 가린 출력은 `secret_paths`로 분류된다."""
    daemon_runs = pytest.importorskip("helpers.daemon_runs")
    from kookabug_daemon.client import DaemonError

    if kind == "cli":
        rig.agents(
            [{"id": "fake", "name": "F", "env": {"AGENT_TOKEN": {"$secret": "agent.token"}}}]
        )
        rig.steps({"do": "say_env", "var": "AGENT_TOKEN"})
        ran = rig.run(
            judge_graph(), secrets={"agent.token": QUOTED_KEY}, record={"redact_secrets": redact}
        )
    else:
        with FakeModelApi(json.dumps({"answer": "loading", "reason": QUOTED_KEY})) as api:
            ran = rig.run(
                api_graph(api, "anthropic"),
                secrets={"model.key": QUOTED_KEY},
                record={"redact_secrets": redact},
            )
    assert ran.result.verdict == "pass", ran.result.reason
    end = ran.end("n_judge")
    assert end["outputs"]["reason"] == "***"
    assert "/outputs/reason" in end["secret_paths"]
    assert not holds(ran.record("n_judge"), QUOTED_KEY)
    view = agent_run(ran, "b4round2")
    assert not holds([view.event(e) for e in view.events], QUOTED_KEY)
    extra = rig.tmp / "daemon-helper"
    extra.mkdir()
    daemon_rig = daemon_runs.RunRig.make(extra)
    daemon_rig.root = ran.root
    info = {"kind": "agent", "name": "test", "version": "0", "id": "b4-test", "attended": False}
    with daemon_rig.daemon() as daemon, daemon.client(info) as client:
        got = client.call("run.events", {"run_id": "b4round2"})
        assert not holds(got, QUOTED_KEY)
        with pytest.raises(DaemonError) as caught:
            client.call(
                "run.artifact",
                {"run_id": "b4round2", "path": f"steps/{ran.step('n_judge')}_judge.json"},
            )
        assert caught.value.kind == "secret_step"


def test_scrubber_json_escaped_forms() -> None:
    scrub = Scrubber()
    scrub.add('한글-"q"')
    assert scrub(json.dumps({"r": '한글-"q"'})) == '{"r": "***"}'
    assert scrub(json.dumps({"r": '한글-"q"'}, ensure_ascii=False)) == '{"r": "***"}'
    assert scrub.hit


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_error_body_is_scrubbed(rig: Rig, status: int) -> None:
    with FakeModelApi(status=status, error_body='{"message":"invalid credential {key}"}') as api:
        ran = rig.run(
            api_graph(api, "anthropic"),
            secrets={"model.key": PLAIN_KEY},
            record={"redact_secrets": True},
        )
    assert ran.result.code == "api_http_error"
    assert str(status) in ran.result.reason
    assert not holds(ran.record("n_judge"), PLAIN_KEY)
    assert not holds(ran.result.events, PLAIN_KEY)


@pytest.mark.parametrize("mode", ["timeout", "cancel"])
def test_blocked_writer_and_reader_threads_are_reaped(tmp_path: Path, mode: str) -> None:
    baseline = set(threading.enumerate())
    log = tmp_path / "agent.jsonl"
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"stall_after": "session/new"}), encoding="utf-8")
    env = {**os.environ, "KB_FAKE_ACP_SCRIPT": str(script), "KB_FAKE_ACP_LOG": str(log)}
    start = time.monotonic()

    def check() -> None:
        if mode == "cancel" and time.monotonic() - start >= 1.5:
            raise Cancelled("cancelled")

    expected: type[BaseException] = Cancelled if mode == "cancel" else acp.AgentFailure
    with pytest.raises(expected):
        acp.ask(
            acp.AgentCommand(sys.executable, [str(FAKE_AGENT)], env, tmp_path),
            [{"type": "text", "text": "x" * 1_000_000}],
            deadline=start + (60 if mode == "cancel" else 1.5),
            check=check,
        )
    assert time.monotonic() - start < 10
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert any(e["event"] == "stall" for e in entries)
    process_dead(entries)
    names = ("acp-judge", "acp-judge-write")
    residual = [t.name for t in threading.enumerate() if t not in baseline and t.name in names]
    assert residual == []


def test_partial_response_error_and_stop_reason_are_scrubbed(rig: Rig) -> None:
    rig.agents([{"id": "fake", "name": "F", "env": {"AGENT_TOKEN": {"$secret": "agent.token"}}}])
    rig.steps({"do": "say", "text": PLAIN_KEY}, {"do": "error_env", "var": "AGENT_TOKEN"})
    ran = rig.run(
        judge_graph(), secrets={"agent.token": PLAIN_KEY}, record={"redact_secrets": True}
    )
    assert ran.result.code == "agent_protocol_error"
    assert not holds(ran.record("n_judge"), PLAIN_KEY)
    assert not holds(ran.result.events, PLAIN_KEY)
    rig.steps({"do": "answer", "answer": "loading"}, stop_reason=PLAIN_KEY)
    ran = rig.run(
        judge_graph(), secrets={"agent.token": PLAIN_KEY}, record={"redact_secrets": True}
    )
    assert ran.record("n_judge")["stop_reason"] == "***"


@pytest.mark.parametrize("exc_type", [acp.AgentFailure, model_api.ApiFailure, EngineError])
def test_supported_exception_messages_use_scrub(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, exc_type: type[Exception]
) -> None:
    def fail(*args: Any, **kwargs: Any) -> str:
        raise exc_type("api_http_error", "fake error: " + PLAIN_KEY)

    monkeypatch.setattr(model_api, "ask", fail)
    with FakeModelApi() as api:
        ran = rig.run(
            api_graph(api, "anthropic"),
            secrets={"model.key": PLAIN_KEY},
            record={"redact_secrets": True},
        )
    assert ran.result.code == "api_http_error"
    assert not holds(ran.record("n_judge"), PLAIN_KEY)
    assert not holds(ran.result.events, PLAIN_KEY)


def test_http_protocol_exception_does_not_log_credential(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """가짜 서버가 받은 키를 잘못된 HTTP 상태 줄에 넣어도(실제 `http.client` 파서 예외) 스레드
    예외 처리기·stderr로 나가지 않고, 호출자는 키를 가린 `api_http_error`만 받는다."""
    escaped: list[str] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: escaped.append(repr(args)))

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            self.rfile.readline()
            headers: dict[str, str] = {}
            while True:
                line = self.rfile.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                key, value = line.decode("ascii").split(":", 1)
                headers[key.lower()] = value.strip()
            self.rfile.read(int(headers.get("content-length", "0")))
            token = headers["x-api-key"]
            self.wfile.write(f"HTTP/1.1 invalid-{token}\r\n\r\n".encode("ascii"))

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with pytest.raises(model_api.ApiFailure) as caught:
                model_api.ask(
                    "anthropic",
                    f"http://127.0.0.1:{server.server_address[1]}",
                    "fake",
                    PLAIN_KEY,
                    "?",
                    None,
                    deadline=time.monotonic() + 5,
                    check=lambda: None,
                )
        finally:
            server.shutdown()
            worker.join(5)
    assert caught.value.code == "api_http_error"
    assert PLAIN_KEY not in caught.value.message and "***" in caught.value.message
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert escaped == []
    out, err = capfd.readouterr()
    assert PLAIN_KEY not in out + err
