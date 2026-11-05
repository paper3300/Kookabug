"""daemon 녹화 검사 헬퍼 (M4 T8): 예제 워크스페이스 사본 + 가짜 플랫폼 + 가짜 각본으로 실제 daemon
녹화 세션을 연다.

    rig = RecorderRig.make(tmp_path, login_script(split=True))
    with rig.daemon() as d, d.client() as ui:
        ui.call("recorder.start", {"launch": {}, "hotkeys": HOTKEYS})
        ...

각본은 기본으로 기다리지 않고 흘린다(`speed=inf`). `speed=None`이면 검사가 `rig.advance(d, t)`로
직접 흘린다. 실행(재생)은 실제 runner 프로세스(가짜 플랫폼)이고 예제 비밀값은 환경 변수로 준다.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from helpers.cli import cli_env
from helpers.runner import RUNNER_CMD
from kb_testing.daemon import ThreadDaemon
from kb_testing.proc import wait_until
from kb_testing.recorder_scripts import login_script, write_jsonl
from kb_testing.sample_game import EXAMPLE_SECRET_ENV, copy_example_workspace
from kookabug_core.recorder.build import apply_fragment
from kookabug_core.service import WorkspaceService
from kookabug_core.supervisor import Supervisor
from kookabug_daemon.client import DaemonClient, DaemonError

__all__ = [
    "HOTKEYS",
    "SECRET_KEY",
    "RecorderRig",
    "graph_from_fragment",
    "run_graph",
    "steps_of",
    "wait_steps",
]

HOTKEYS: Final = [
    {"keys": "ctrl+shift+r", "role": "stop"},
    {"keys": "ctrl+shift+p", "role": "mark_secret"},
]
SECRET_KEY: Final = "accounts.qa_tester_01"
"""예제 비밀값 키 (환경 변수 `KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01`)."""


@dataclass
class RecorderRig:
    root: Path
    env: dict[str, str]
    script: Path

    @classmethod
    def make(
        cls, tmp_path: Path, lines: Iterable[Mapping[str, Any]] | None = None, **env: str
    ) -> RecorderRig:
        root = copy_example_workspace(tmp_path / "example")
        script = tmp_path / "script.jsonl"
        write_jsonl(script, login_script(split=True) if lines is None else lines)
        return cls(root, cli_env(tmp_path, None, **EXAMPLE_SECRET_ENV, **env), script)

    def service(self) -> WorkspaceService:
        supervisor = Supervisor(runner_cmd=RUNNER_CMD, env=self.env)
        return WorkspaceService(self.root, environ=self.env, supervisor=supervisor)

    def daemon(self, *, speed: float | None = float("inf"), **kwargs: Any) -> ThreadDaemon:
        return ThreadDaemon(
            self.root,
            service=self.service(),
            platform_fake=self.root / "fake-platform.json",
            recorder_script=self.script,
            recorder_script_speed=speed,
            **kwargs,
        )

    @staticmethod
    def advance(d: ThreadDaemon, t_ms: float) -> None:
        """`speed=None` 세션의 각본을 `t_ms`까지 흘리고 처리가 끝나기를 기다린다."""
        session = d.daemon.recorder.session
        assert session is not None
        recording: Any = session.recording
        recording.advance(int(t_ms * 1_000_000))
        session.drain()


def steps_of(client: DaemonClient) -> list[dict[str, Any]]:
    return list(client.call("recorder.steps", {})["steps"])


def wait_steps(
    client: DaemonClient, done: Callable[[list[dict[str, Any]]], bool], timeout: float = 30
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def check() -> bool:
        found[:] = steps_of(client)
        return done(found)

    wait_until(check, timeout=timeout, interval=0.1)
    return found


def graph_from_fragment(fragment: Mapping[str, Any]) -> dict[str, Any]:
    """새 테스트 그래프 (렌더러 `graph.create(test)` + `insertFragment`와 같은 규칙)."""
    graph: dict[str, Any] = {
        "format": "kookabug.graph/0",
        "kind": "test",
        "plugins": {"core": "0.1.0"},
        "nodes": {"n_entry": {"type": "core.graph.entry", "version": 1, "title": "시작"}},
    }
    return apply_fragment(graph, fragment, after=("n_entry", "start"))


def run_graph(
    client: DaemonClient, root: Path, rel: str, graph: Mapping[str, Any], timeout: float = 120
) -> dict[str, Any]:
    """그래프를 쓰고 daemon `run.start`로 실제 runner(가짜 플랫폼)를 돌려 끝난 상태를 준다."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        started = client.call("run.start", {"path": rel})
    except DaemonError as exc:
        raise AssertionError(f"run.start 거부: {exc} {exc.data}") from exc
    run_id = started["run_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.call("run.status", {"run_id": run_id})
        if status["state"] == "ended":
            return {**status, "run_dir": started.get("run_dir")}
        time.sleep(0.1)
    raise AssertionError(f"실행 {run_id}이(가) {timeout}초 안에 끝나지 않았다")
