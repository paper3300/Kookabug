"""실행기 테스트 헬퍼: 그래프를 쓰고 읽어 가짜 플랫폼·`FakeClock`으로 실행한다.

ws = make_workspace(tmp_path)
ran = run_graph(ws, tk().entry("n_pass").node("n_pass", "core.test.pass"))
assert ran.result.verdict == "pass"
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from testkit import registry_with_testkit

from helpers.graphs import GraphBuilder
from kookabug_core.engine import (
    DEFAULT_DEADLINE_MS,
    CancelToken,
    ExecOptions,
    Executor,
    FakeClock,
    FakePlatform,
    NodeInvoker,
    RunResult,
)
from kookabug_core.loader import Program, load_program
from kookabug_core.workspace import MemorySecrets, Workspace

TEST = "tests/t.graph.json"


def tk(kind: str = "test", *, interface: Mapping[str, Any] | None = None) -> GraphBuilder:
    """testkit 플러그인을 쓰는 그래프."""
    return GraphBuilder(kind, interface=interface, plugins={"testkit": "0"})


@dataclass
class Ran:
    result: RunResult
    platform: FakePlatform
    clock: FakeClock
    program: Program

    @property
    def events(self) -> list[dict[str, Any]]:
        return self.result.events

    def of(self, event: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["event"] == event]

    def order(self) -> list[str]:
        """실행된 노드 ID (step.start 순서)."""
        return [e["node"] for e in self.of("step.start")]

    def starts(self, node: str) -> list[dict[str, Any]]:
        return [e for e in self.of("step.start") if e["node"] == node]

    def step_of(self, node: str) -> str:
        """노드의 (유일한) 스텝 ID."""
        (start,) = self.starts(node)
        return start["step"]

    def end(self, node: str) -> dict[str, Any]:
        """노드의 (유일한) step.end."""
        step = self.step_of(node)
        (found,) = [e for e in self.of("step.end") if e["step"] == step]
        return found


def run_graph(
    ws: Workspace,
    graph: GraphBuilder,
    rel: str = TEST,
    *,
    frames: Iterable[str] = (),
    secrets: Mapping[str, str] | None = None,
    validate: bool = True,
    deadline_ms: int = DEFAULT_DEADLINE_MS,
    cancel: CancelToken | None = None,
    on_capture: Callable[[int], None] | None = None,
    clock: FakeClock | None = None,
    invoker: NodeInvoker | None = None,
) -> Ran:
    graph.write(ws, rel)
    program = load_program(ws, rel, secrets=MemorySecrets(secrets or {}))
    platform = FakePlatform(frames, on_capture=on_capture)
    clock = clock or FakeClock()
    executor = Executor(
        registry_with_testkit(), platform=platform, clock=clock, cancel=cancel, invoker=invoker
    )
    result = executor.run(
        program, ExecOptions(deadline_ms=deadline_ms, validate=validate, run_id="r1")
    )
    return Ran(result, platform, clock, program)


def check_ok(**extra: Any) -> dict[str, Any]:
    """늘 성공하는 `core.assert.compare` 입력 (1 == 1)."""
    return {"a": 1, "op": "==", "b": 1, **extra}
