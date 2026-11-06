"""MCP run 툴셋·실패 분석 (M5 계획 3.3·3.8, B2).

실제 `kookabug mcp` + 같은 프로세스 daemon + 실제 runner + 가짜 플랫폼(예제 게임 장면 표). 비밀값
가림의 세부는 daemon `test_agent_view`, 분류 기록은 core `test_agent_mask`.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np
import pytest
from helpers.cli import cli_env
from helpers.runner import RUNNER_CMD

from kb_testing.daemon import ThreadDaemon, daemon_env
from kb_testing.mcp_client import McpClient
from kb_testing.proc import Spawned
from kb_testing.sample_game import EXAMPLE_SECRET_ENV, EXAMPLE_SECRETS, copy_example_workspace
from kookabug_core.service import WorkspaceService
from kookabug_core.supervisor import Supervisor

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

GRAPH: Final = "tests/agent_title.graph.json"
BROKEN: Final = "tests/broken/swapped_target.graph.json"
PASSWORD: Final = EXAMPLE_SECRETS["accounts.qa_tester_01"]
WAIT_MS: Final = 30_000

type Start = Callable[..., McpClient]


def title_graph(target: str) -> dict[str, Any]:
    """게임을 띄우고 타이틀의 `target`을 기다린다 (없으면 timeout fail — 증거 스크린샷)."""
    return {
        "format": "kookabug.graph/0",
        "kind": "test",
        "plugins": {"core": "0.1.0"},
        "nodes": {
            "n_entry": {"type": "core.graph.entry", "version": 1, "next": {"start": "n_launch"}},
            "n_launch": {
                "type": "core.app.launch",
                "version": 1,
                "in": {
                    "args": {"$setting": "game.args"},
                    "cwd": {"$setting": "game.cwd"},
                    "path": {"$setting": "game.executable"},
                    "timeout_ms": 30000,
                    "window_title": {"$setting": "game.title"},
                },
                "next": {"attached": "n_wait"},
            },
            "n_wait": {
                "type": "core.image.wait",
                "version": 1,
                "in": {"target": {"$target": target}, "timeout_ms": 3000},
                "next": {"found": "n_pass"},
            },
            "n_pass": {"type": "core.test.pass", "version": 1},
        },
    }


def write_graph(root: Path, target: str) -> None:
    path = root / GRAPH
    path.write_text(json.dumps(title_graph(target), ensure_ascii=False), encoding="utf-8")


def set_preset(root: Path, preset: str) -> None:
    path = root / ".kookabug" / "local.json"
    body = json.loads(path.read_text("utf-8"))
    body["permissions"] = {"preset": preset}
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key, value in EXAMPLE_SECRET_ENV.items():
        monkeypatch.setenv(key, value)  # daemon 사전 검증 (이 프로세스)
    ws = copy_example_workspace(tmp_path)
    write_graph(ws, "targets/title/start_button.target.json")
    return ws


@pytest.fixture
def daemon(root: Path, tmp_path: Path) -> Iterator[ThreadDaemon]:
    env = {
        **cli_env(tmp_path),
        **EXAMPLE_SECRET_ENV,
        "KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user"),
    }
    service = WorkspaceService(
        root, environ=env, supervisor=Supervisor(runner_cmd=RUNNER_CMD, env=env)
    )
    with ThreadDaemon(
        root, service=service, platform_fake=root / "fake-platform.json", agent_toolsets=("core",)
    ) as d:
        yield d


@pytest.fixture
def start_mcp(spawned: Spawned, root: Path, tmp_path: Path) -> Iterator[Start]:
    clients: list[McpClient] = []

    def start(*args: str) -> McpClient:
        client = McpClient.start(
            spawned, root, tmp_path / f"mcp{len(clients)}", *args, env=daemon_env(tmp_path)
        )
        clients.append(client)
        client.initialize()
        return client

    yield start
    for client in clients:
        client.__exit__(None, None, None)


def run_and_wait(mcp: McpClient, path: str, key: str) -> dict[str, Any]:
    started = mcp.data("kb_run_start", {"path": path, "idempotency_key": key})
    status = mcp.data("kb_run_status", {"run": started["run"], "wait_ms": WAIT_MS})
    assert status["state"] == "ended", status
    return status


# ---------------------------------------------------------------- 완료 기준


def test_start_wait_status_failure_summary(
    root: Path, daemon: ThreadDaemon, start_mcp: Start
) -> None:
    set_preset(root, "runner")
    mcp = start_mcp()
    mcp.data("kb_toolset_enable", {"toolsets": ["run"]})
    write_graph(root, "targets/broken/start_button_swapped.target.json")
    status = run_and_wait(mcp, GRAPH, "broken-1")
    assert status["outcome"]["verdict"] == "fail"
    failure = status["failure"]
    assert failure["classified"] is True and failure["verdict"] == "fail"
    where = failure["failure"]
    assert where["node"] == "n_wait" and where["exit"] == "timeout"
    assert failure["failure_path"] == ["n_wait"]
    # 증거 경로: 실패 스텝의 timeout 스크린샷 (비밀값을 다루지 않는 스텝)
    assert any(p.startswith(f"steps/{where['step']}_") for p in failure["evidence"]), failure
    run_dir = Path(status["run_dir"])
    assert all((run_dir / p).is_file() for p in failure["evidence"])
    assert failure["last_success"] is None  # 아직 성공 실행이 없다

    # 목록(run 없이)도 kb_run_status
    listed = mcp.data("kb_run_status")
    assert listed["runs"][0]["run_id"] == status["run_id"]
    assert mcp.close() == 0


def test_run_start_idempotent_retry(root: Path, daemon: ThreadDaemon, start_mcp: Start) -> None:
    set_preset(root, "runner")
    mcp = start_mcp()
    mcp.data("kb_toolset_enable", {"toolsets": ["run"]})
    first = mcp.data("kb_run_start", {"path": GRAPH, "idempotency_key": "same-key"})
    again = mcp.data("kb_run_start", {"path": GRAPH, "idempotency_key": "same-key"})
    assert again["run"] == first["run"]
    mcp.data("kb_run_status", {"run": first["run"], "wait_ms": WAIT_MS})
    folders = [p for p in (root / "runs").iterdir() if p.is_dir()]
    assert len(folders) == 1
    # idempotency_key는 필수 (도구 입력 형식 오류 → JSON-RPC -32602)
    with pytest.raises(Exception) as caught:
        mcp.call_tool("kb_run_start", {"path": GRAPH})
    assert "-32602" in str(caught.value) or "invalid" in str(caught.value).lower()
    assert mcp.close() == 0


def test_events_artifact_compare_for_failed_run(
    root: Path, daemon: ThreadDaemon, start_mcp: Start
) -> None:
    set_preset(root, "runner")
    mcp = start_mcp()
    mcp.data("kb_toolset_enable", {"toolsets": ["run"]})
    passed = run_and_wait(mcp, GRAPH, "ok-1")
    assert passed["outcome"]["verdict"] == "pass", passed
    write_graph(root, "targets/broken/start_button_swapped.target.json")
    failed = run_and_wait(mcp, GRAPH, "broken-1")
    run = failed["run_id"]
    failure = failed["failure"]
    assert failure["last_success"] == passed["run_id"]

    events = mcp.data("kb_run_events", {"run": run, "kinds": ["step.end"]})
    assert events["events"] and all(e["event"] == "step.end" for e in events["events"])
    wait_end = next(e for e in events["events"] if e["step"] == failure["failure"]["step"])
    assert wait_end["status"] == "fail" and wait_end["exit"] == "timeout"
    page = mcp.data("kb_run_events", {"run": run, "limit": 2})
    assert len(page["events"]) == 2 and page["truncated"] is True
    more = mcp.data("kb_run_events", {"run": run, "after_seq": page["next_seq"], "limit": 500})
    assert more["events"][0]["seq"] == page["next_seq"] + 1

    shot = next(p for p in failure["evidence"] if p.endswith(".png"))
    result = mcp.call_tool("kb_run_artifact_get", {"run": run, "path": shot})
    assert result["isError"] is False, result
    (image,) = [c for c in result["content"] if c["type"] == "image"]
    assert image["mimeType"] == "image/png"
    data = base64.b64decode(image["data"])
    pixels = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert pixels is not None
    assert max(pixels.shape[:2]) <= 1568 and len(data) <= 1024 * 1024
    meta = result["structuredContent"]
    assert max(meta["width"], meta["height"]) <= 1568
    # 읽은 축소 이미지는 shim이 지운다
    agent_cache = root / ".kookabug" / "cache" / "agent"
    assert not list(agent_cache.rglob("*.png"))

    diff = mcp.data("kb_run_compare", {"run": run})
    assert diff["baseline"] == passed["run_id"] and diff["baseline_picked"] == "auto"
    assert diff["screen"]["step"] == failure["failure"]["step"]
    assert diff["screen"]["file"] == shot or diff["screen"]["file"] in failure["evidence"]

    # 영상 조각은 주지 않는다 / 실행 폴더 밖·원문 파일은 거부
    for path, code in (("events.jsonl", "not_evidence"), ("run.json", "not_evidence")):
        assert mcp.error("kb_run_artifact_get", {"run": run, "path": path})["code"] == code

    # 비밀값을 넘기는 예제 깨진 각본: 비밀번호 원문이 어떤 결과에도 없다, 호출 안쪽 증거는 없음
    set_preset(root, "full")
    broken = run_and_wait(mcp, BROKEN, "broken-sample")
    assert broken["outcome"]["verdict"] == "fail"
    summary = broken["failure"]
    assert summary["failure_path"][0] == "n_enter_world"
    assert summary["evidence"] == []  # 비밀값을 받은 호출 스텝 안쪽은 이미지를 주지 않는다
    seen = json.dumps(
        [
            broken,
            mcp.data("kb_run_events", {"run": broken["run_id"], "limit": 500}),
            mcp.data("kb_log_search", {"query": "sample"}),
        ],
        ensure_ascii=False,
    )
    assert PASSWORD not in seen
    assert mcp.close() == 0


def test_graph_author_cannot_start_run(root: Path, daemon: ThreadDaemon, start_mcp: Start) -> None:
    # 기본 프리셋 graph_author: run 변경 도구 deny. 조회(kb_run_events 등)는 allow
    mcp = start_mcp()
    mcp.data("kb_toolset_enable", {"toolsets": ["run"]})
    error = mcp.error("kb_run_start", {"path": GRAPH, "idempotency_key": "k1"})
    assert error["code"] == "permission_denied"
    assert error["decision"]["final"] == "deny"
    assert not (root / "runs").exists() or not any((root / "runs").iterdir())
    assert mcp.close() == 0
