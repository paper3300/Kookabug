"""실행기 (한 프로세스).

    program = load_program(workspace, "tests/a.graph.json")
    result = Executor(platform=FakePlatform(frames=[...]), clock=FakeClock()).run(program)

반복·재시도는 M0a T8에서 붙인다.
"""

from kookabug_core.engine.cancel import Cancelled, CancelToken, DeadlineExceeded
from kookabug_core.engine.clock import Clock, FakeClock, SystemClock
from kookabug_core.engine.context import ArtifactStore, Platform
from kookabug_core.engine.errors import EngineError
from kookabug_core.engine.events import EventSink, MemoryEventSink, event_value
from kookabug_core.engine.executor import (
    DEFAULT_DEADLINE_MS,
    ExecOptions,
    Executor,
    GraphInvalid,
    RunResult,
)
from kookabug_core.engine.invoker import InProcessInvoker, NodeInvoker, RoutingInvoker
from kookabug_core.engine.platform_fake import FakePlatform, MemoryArtifacts
from kookabug_core.engine.verdict import Cause, Facts, Judgement, judge

__all__ = [
    "DEFAULT_DEADLINE_MS",
    "ArtifactStore",
    "CancelToken",
    "Cancelled",
    "Cause",
    "Clock",
    "DeadlineExceeded",
    "EngineError",
    "EventSink",
    "ExecOptions",
    "Executor",
    "Facts",
    "FakeClock",
    "FakePlatform",
    "GraphInvalid",
    "InProcessInvoker",
    "Judgement",
    "MemoryArtifacts",
    "MemoryEventSink",
    "NodeInvoker",
    "Platform",
    "RoutingInvoker",
    "RunResult",
    "SystemClock",
    "event_value",
    "judge",
]
