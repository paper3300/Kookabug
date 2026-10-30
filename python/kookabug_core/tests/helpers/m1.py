"""M1 runner 연결 검사 도우미: 예제 게임 장면 표(`FakeScenario`)와 정해 둔 답을 주는 찾기 엔진.

    ws = make_workspace(tmp_path)
    target = write_target(ws, "targets/start.target.json")
    platform = ScenePlatform.sample(engines=StubEngines())
    ran = run_on(ws, graph, platform)

`StubEngines`는 opencv 없이 찾기 결과를 정한다(`answers[target 이름]` = 찾을 때마다 앞에서 하나씩
쓰는 상자 목록, 마지막 것을 반복, `None`이면 못 찾음). `ScenePlatform`은 창 크기·DPI를 바꾼 것처럼
보이게 할 수 있다(`view`) — 재검증 검사용.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from testkit import registry_with_testkit

from helpers.graphs import GraphBuilder
from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.engine import ExecOptions, Executor, FakeClock, MemoryArtifacts, RunResult
from kookabug_core.engine.scenario import FakeScenario, ScenarioPlatform
from kookabug_core.loader import Program, load_program
from kookabug_core.workspace import Workspace
from kookabug_sdk.types import FrameRef, Image, Match, OcrResult, Rect, Target, WindowRef

__all__ = [
    "SCENARIO",
    "START",
    "Ran",
    "ScenePlatform",
    "StubEngines",
    "clicks",
    "run_on",
    "write_target",
]

SCENARIO: Final = FRAMES_DIR / "scenario.json"
START: Final = Rect(412, 380, 200, 64)
"""타이틀 화면 "게임 시작" 버튼 (클라이언트 1024x640)."""
TEST: Final = "tests/t.graph.json"


def write_target(ws: Workspace | Path, rel: str, image: str = "title.png") -> str:
    """target 파일과 그 이미지(예제 게임 화면 PNG 복사)를 워크스페이스에 쓴다."""
    root = ws.root if isinstance(ws, Workspace) else ws
    path = root.joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FRAMES_DIR / image, path.parent / "t.png")
    body = {"format": "kookabug.target/0", "image": "t.png"}
    path.write_text(json.dumps(body), encoding="utf-8")
    return rel


@dataclass
class StubEngines:
    """정해 둔 상자를 찾았다고 답하는 엔진. `Match`에는 그때 창·관측 조건을 싣는다."""

    answers: dict[str, list[Rect | None]] = field(default_factory=dict[str, list[Rect | None]])
    with_target: bool = True
    platform: ScenePlatform | None = None
    calls: list[str] = field(default_factory=list[str])
    after_find: list[Callable[[], None]] = field(default_factory=list[Callable[[], None]])

    def find(
        self, image: Image, target: Target, *, region: Rect | None, limits: Any
    ) -> Match | None:
        self.calls.append(target.name)
        answers = self.answers.get(target.name, [None])
        rect = answers[min(len(self.calls_of(target.name)) - 1, len(answers) - 1)]
        assert self.platform is not None
        game = self.platform.scenario.latest()
        size, dpi = self.platform.view or (self.platform.scenario.client_size, 96)
        for hook in self.after_find:
            hook()
        if rect is None:
            return None
        return Match(
            rect,
            0.99,
            window=game.window,
            frame=image.frame,
            method="stub",
            frame_info=FrameRef("fake", size, dpi, image.capture_id),
            target=target.name if self.with_target else None,
        )

    def calls_of(self, name: str) -> list[str]:
        return [c for c in self.calls if c == name]

    def diff(self, a: Image, b: Image, *, region: Rect | None) -> float:
        return 0.0 if a.path == b.path else 1.0

    def read_text(
        self, image: Image, *, region: Rect | None, sensitive: bool, limits: Any
    ) -> OcrResult:
        return OcrResult("")


class ScenePlatform(ScenarioPlatform):
    """`ScenarioPlatform` + 창 크기·DPI 바꾸기 흉내(`view`, 재검증이 보는 "지금 창")."""

    def __init__(self, scenario: FakeScenario, **kwargs: Any) -> None:
        super().__init__(scenario, **kwargs)
        self.view: tuple[tuple[int, int], int] | None = None

    @classmethod
    def sample(cls, engines: StubEngines | None = None, **kwargs: Any) -> ScenePlatform:
        platform = cls(FakeScenario.load(SCENARIO), engines=engines, **kwargs)
        if engines is not None:
            engines.platform = platform
        return platform

    def resize(self, size: tuple[int, int], dpi: int = 96) -> None:
        self.view = (size, dpi)

    def state(self, window: WindowRef) -> Any:
        state = super().state(window)
        if self.view is None:
            return state
        return type(state)(state.backend, self.view[0], self.view[1])


@dataclass
class Ran:
    result: RunResult
    platform: ScenePlatform
    program: Program
    clock: FakeClock

    @property
    def events(self) -> list[dict[str, Any]]:
        return self.result.events

    def of(self, event: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["event"] == event]

    def ends(self, node: str) -> list[dict[str, Any]]:
        """그 노드의 `step.end`들 (실행 순서)."""
        steps = [e["step"] for e in self.of("step.start") if e["node"] == node]
        return [e for e in self.of("step.end") if e["step"] in steps]

    def end(self, node: str) -> dict[str, Any]:
        (found,) = self.ends(node)
        return found

    def logs(self, node: str) -> list[str]:
        step = self.end(node)["step"]
        return [e["message"] for e in self.of("log") if e["step"] == step]


def run_on(
    ws: Workspace,
    graph: GraphBuilder,
    platform: ScenePlatform,
    *,
    frames: Any = None,
    capture_timeout_ms: int = 2000,
) -> Ran:
    graph.write(ws, TEST)
    program = load_program(ws, TEST)
    clock = FakeClock()
    executor = Executor(
        registry_with_testkit(),
        platform=platform,
        clock=clock,
        artifacts=MemoryArtifacts(),
        frames=frames,
    )
    result = executor.run(program, ExecOptions(run_id="r1", capture_timeout_ms=capture_timeout_ms))
    return Ran(result, platform, program, clock)


def clicks(platform: ScenarioPlatform) -> list[tuple[int, int, int]]:
    """장면에 닿은 클릭들 `(창 HWND, x, y)`."""
    return [
        (hwnd, args[0], args[1]) for hwnd, kind, args in platform.scenario.inputs if kind == "click"
    ]


def kinds(platform: ScenarioPlatform, kind: str) -> list[tuple[int, Sequence[Any]]]:
    """장면에 닿은 그 종류의 입력들 `(창 HWND, 인수)`."""
    return [(hwnd, args) for hwnd, k, args in platform.scenario.inputs if k == kind]
