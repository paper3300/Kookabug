"""관측 세대 검사 도우미 (구현 계획 M3 T4): runner 멈춤 게이트 흉내와 장면에 따라 답하는 엔진.

    dbg = Debugger(at={"n_click"}, while_paused=lambda d, point: scene(platform, "lobby"))
    ran = run_debug(ws, graph, platform, dbg)

`Debugger`는 실행기와 같은 스레드에서 경계 멈춤(`before_step`)·폴링 멈춤(`PausePoint`)을 흉내 낸다:
정해 둔 노드의 경계에서, 또는 그 노드의 n번째 폴링 기다림에서 멈추고, 멈춘 동안 `while_paused`를
부른 뒤 재개한다. 재개마다 관측 세대를 올린다(runner `PauseGate`와 같다). 폴링 기다림은
`FakeClock`을 그만큼 진행시킨다.

`SceneEngines`는 opencv 없이 가짜 장면 이름으로 답한다: `where[target 이름][장면] = 상자`(없으면 못
찾음), `texts[장면] = 읽은 글자`, 비교는 같은 장면 PNG면 0.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from testkit import registry_with_testkit

from helpers.graphs import GraphBuilder
from helpers.m1 import TEST, Ran, ScenePlatform
from kookabug_core.engine import ExecOptions, Executor, FakeClock, MemoryArtifacts
from kookabug_core.engine.debug import StepPoint
from kookabug_core.engine.provenance import Epochs
from kookabug_core.loader import load_program
from kookabug_core.workspace import Workspace
from kookabug_sdk.types import FrameRef, Image, Match, OcrLine, OcrResult, Rect, Target

__all__ = ["Debugger", "SceneEngines", "platform_with", "run_debug", "scene"]

type WhilePaused = Callable[["Debugger", StepPoint], None]


class Debugger:
    """runner 멈춤 게이트 흉내 (`before_step` + `PausePoint`)."""

    def __init__(
        self,
        *,
        at: Iterable[str] = (),
        poll: Mapping[str, int] | None = None,
        while_paused: WhilePaused | None = None,
        clock: FakeClock | None = None,
    ) -> None:
        self.clock = clock or FakeClock()
        self.epochs = Epochs()
        self.at = set(at)
        """경계에서 (처음 한 번) 멈출 노드."""
        self.poll = dict(poll or {})
        """노드 → 그 노드의 몇 번째 폴링 기다림(1부터)에서 멈출지."""
        self.while_paused = while_paused
        self.current: StepPoint | None = None
        self.waits: Counter[str] = Counter()
        self.requested = False
        self.pauses: list[tuple[str, str]] = []
        """멈춘 자리 (노드, `boundary`·`poll`)."""
        self.resumed_ms: list[int] = []
        """재개한 시각 (기한 시계)."""

    def before_step(self, point: StepPoint) -> None:
        self.current = point
        if point.node in self.at:
            self.at.discard(point.node)
            self._pause(point, "boundary")

    def wait_request(self, timeout_s: float) -> bool:
        assert self.current is not None
        node = self.current.node
        self.waits[node] += 1
        if self.poll.get(node) == self.waits[node]:
            self.requested = True
            return True
        self.clock.sleep(max(1, round(timeout_s * 1000)))
        return False

    def at_poll(self, point: StepPoint) -> None:
        if not self.requested:
            return
        self.requested = False
        self._pause(point, "poll")

    def _pause(self, point: StepPoint, where: str) -> None:
        self.pauses.append((point.node, where))
        if self.while_paused is not None:
            self.while_paused(self, point)
        self.epochs.advance()
        self.resumed_ms.append(self.clock.now_ms())


def scene(platform: ScenePlatform, name: str) -> None:
    """가장 나중에 띄운 가짜 게임의 장면을 바꾼다 (멈춘 동안 게임 화면이 바뀐 흉내)."""
    state = platform.scenario.latest().state
    state.scene = name


@dataclass
class SceneEngines:
    """장면 이름으로 답하는 찾기·비교·OCR."""

    where: dict[str, dict[str, Rect]] = field(default_factory=dict[str, dict[str, Rect]])
    texts: dict[str, str] = field(default_factory=dict[str, str])
    script: list[str] | None = None
    """있으면 장면과 무관하게 OCR 차례마다 앞에서 하나씩 읽는다 (마지막 것을 반복)."""
    platform: ScenePlatform | None = None
    finds: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    """찾기 호출 (target 이름, 장면)."""
    diffs: list[tuple[int | None, int | None]] = field(
        default_factory=list[tuple[int | None, int | None]]
    )
    """비교 호출 (두 이미지의 캡처 번호)."""
    reads: list[int | None] = field(default_factory=list[int | None])
    """OCR 호출 (이미지의 캡처 번호)."""

    def _seen(self, image: Image) -> tuple[str, Any, FrameRef]:
        assert self.platform is not None
        game = self.platform.scenario.latest()
        name = image.path.stem if image.path is not None else ""
        info = FrameRef("fake", self.platform.scenario.client_size, 96, image.capture_id)
        return name, game.window, info

    def find(
        self, image: Image, target: Target, *, region: Rect | None, limits: Any
    ) -> Match | None:
        name, window, info = self._seen(image)
        self.finds.append((target.name, name))
        rect = self.where.get(target.name, {}).get(name)
        if rect is None:
            return None
        return Match(
            rect,
            0.99,
            window=window,
            frame=image.frame,
            method="stub",
            frame_info=info,
            target=target.name,
        )

    def diff(self, a: Image, b: Image, *, region: Rect | None) -> float:
        self.diffs.append((a.capture_id, b.capture_id))
        return 0.0 if a.path == b.path else 1.0

    def read_text(
        self, image: Image, *, region: Rect | None, sensitive: bool, limits: Any
    ) -> OcrResult:
        name, window, info = self._seen(image)
        self.reads.append(image.capture_id)
        if self.script is not None:
            text = self.script[min(len(self.reads), len(self.script)) - 1]
        else:
            text = self.texts.get(name, "")
        lines = (OcrLine(text, Rect(100, 100, 200, 30), 0.95),) if text else ()
        return OcrResult(text, lines, 0.95 if text else None, window=window, frame_info=info)


def platform_with(engines: SceneEngines) -> ScenePlatform:
    platform = ScenePlatform.sample()
    platform.engines = engines
    engines.platform = platform
    return platform


def run_debug(
    ws: Workspace,
    graph: GraphBuilder,
    platform: ScenePlatform,
    debugger: Debugger | None = None,
    *,
    rel: str = TEST,
) -> Ran:
    """`graph`를 가짜 장면에서 실행한다. `debugger`가 있으면 그 멈춤·세대로."""
    graph.write(ws, rel)
    program = load_program(ws, rel)
    dbg = debugger or Debugger()
    executor = Executor(
        registry_with_testkit(),
        platform=platform,
        clock=dbg.clock,
        artifacts=MemoryArtifacts(),
        before_step=dbg.before_step if debugger is not None else None,
        pause_point=dbg if debugger is not None else None,
        epochs=dbg.epochs,
    )
    result = executor.run(program, ExecOptions(run_id="r1"))
    return Ran(result, platform, program, dbg.clock)
