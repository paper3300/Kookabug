"""daemon 실행 메서드 검사 헬퍼 (M2 T5). daemon이 감독자다.

    rig = RunRig.make(tmp_path, graph, hooks=..., faults=...)
    with rig.daemon() as d, d.client() as client:          # 같은 프로세스의 daemon (ThreadDaemon)
        started = client.call("run.start", {"path": TEST})
        client.call("run.subscribe", {"run_id": started["run_id"], "after_seq": 0})
        log = EventLog(client, started["run_id"]).until_ended()

runner는 런처 없이 띄운다(`RUNNER_CMD`). 환경은 격리 + testkit `PYTHONPATH` + 고장 규칙
(`cli_env`)이고, daemon은 `testkit.nodes`를 플러그인 모듈로 받아 사전 검증·워커가 testkit 노드를
안다.
"""

from __future__ import annotations

import queue
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from helpers.cli import cli_env, platform_file
from helpers.graphs import GraphBuilder, make_workspace, write_json
from helpers.runner import RUNNER_CMD
from helpers.worker import PLUGIN_MODULES
from kb_testing.daemon import ThreadDaemon
from kookabug_core.service import WorkspaceService
from kookabug_core.supervisor import Supervisor
from kookabug_daemon.client import DaemonClient

__all__ = ["GRACE", "TEST", "EventLog", "RunRig", "run_workspace"]

TEST: Final = "tests/t.graph.json"
GRACE: Final = {"shutdown_grace_ms": 2_000, "worker_cancel_grace_ms": 1_000}


def run_workspace(
    tmp_path: Path, graph: GraphBuilder | None = None, run: Mapping[str, int] | None = None
) -> Path:
    root = tmp_path / "ws"
    make_workspace(root)
    write_json(root, "kookabug.json", {"format": "kookabug.workspace/0", "run": run or GRACE})
    if graph is not None:
        graph.write(root, TEST)
    return root.resolve()


@dataclass
class RunRig:
    root: Path
    env: dict[str, str]
    platform: Path
    input_log: Path

    @classmethod
    def make(
        cls,
        tmp_path: Path,
        graph: GraphBuilder | None = None,
        *,
        hooks: Mapping[str, Mapping[str, str]] | None = None,
        faults: Sequence[Mapping[str, Any]] | None = None,
        run: Mapping[str, int] | None = None,
        **extra: str,
    ) -> RunRig:
        root = run_workspace(tmp_path, graph, run)
        spec, log = platform_file(tmp_path, hooks)
        return cls(root, cli_env(tmp_path, faults, **extra), spec, log)

    def service(self) -> WorkspaceService:
        supervisor = Supervisor(runner_cmd=RUNNER_CMD, env=self.env)
        return WorkspaceService(self.root, environ=self.env, supervisor=supervisor)

    def daemon(self, **kwargs: Any) -> ThreadDaemon:
        return ThreadDaemon(
            self.root,
            service=self.service(),
            plugin_modules=PLUGIN_MODULES,
            platform_fake=self.platform,
            **kwargs,
        )

    def daemon_args(self) -> list[str]:
        """하위 프로세스 daemon(`DaemonProcess`)에 같은 플러그인·가짜 플랫폼을 주는 인자."""
        modules = [a for m in PLUGIN_MODULES for a in ("--plugin-module", m)]
        return [*modules, "--platform-fake", str(self.platform)]


@dataclass
class EventLog:
    """연결 하나가 받은 실행 알림을 렌더러 규칙(M2 계획 2.8)으로 적용한다: seq 순서로만 적용하고,
    빈틈·중복·역행은 실패다(`strict`). `strict=False`면 중복·역행은 버리고 빈틈만 실패다."""

    client: DaemonClient
    run_id: str
    strict: bool = True
    events: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    ended: dict[str, Any] | None = None
    lagged: int = 0
    duplicates: int = 0
    others: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    @property
    def last(self) -> int:
        return self.events[-1]["seq"] if self.events else self.base

    base: int = 0
    """이 연결이 구독을 시작한 `after_seq` (그 앞은 이미 적용했다)."""

    def apply(self, message: Mapping[str, Any]) -> None:
        method = message["method"]
        params: dict[str, Any] = message["params"]
        if params.get("run_id") != self.run_id:
            self.others.append(dict(message))
            return
        if method == "run.event":
            seq = params["seq"]
            assert params["event"]["seq"] == seq
            if seq <= self.last:
                assert not self.strict, f"중복·역행: {seq} (적용한 마지막 {self.last})"
                self.duplicates += 1
                return
            assert seq == self.last + 1, f"빈틈: {self.last} 다음에 {seq}"
            assert self.ended is None, "run.ended 뒤에 run.event"
            self.events.append(params["event"])
        elif method == "run.ended":
            assert self.ended is None, "run.ended가 두 번"
            assert params["last_seq"] == self.last, (params, self.last)
            self.ended = params
        elif method == "run.lagged":
            self.lagged += 1
        else:
            self.others.append(dict(message))

    def pump(self, until: Callable[[EventLog], bool], timeout: float = 60.0) -> EventLog:
        deadline = time.monotonic() + timeout
        while not until(self):
            left = deadline - time.monotonic()
            if left <= 0:
                raise AssertionError(
                    f"{timeout}초 안에 조건이 맞지 않았다 (마지막 seq {self.last}, "
                    f"ended {self.ended is not None})"
                )
            try:
                message = self.client.notifications.get(timeout=min(left, 0.5))
            except queue.Empty:
                continue
            self.apply(message)
        return self

    def until_ended(self, timeout: float = 60.0) -> EventLog:
        return self.pump(lambda log: log.ended is not None, timeout)

    def until_event(
        self, match: Callable[[Mapping[str, Any]], bool], timeout: float = 60.0
    ) -> dict[str, Any]:
        self.pump(lambda log: any(match(e) for e in log.events), timeout)
        return next(e for e in self.events if match(e))

    def quiet(self, seconds: float) -> None:
        """`seconds` 동안 받은 알림을 적용한다 (기다림의 끝은 시간이다: 오지 않아야 하는 알림)."""
        end = time.monotonic() + seconds
        self.pump(lambda _: time.monotonic() >= end, seconds + 5)

    @property
    def seqs(self) -> list[int]:
        return [e["seq"] for e in self.events]

    def kinds(self) -> list[str]:
        return [e["event"] for e in self.events]
