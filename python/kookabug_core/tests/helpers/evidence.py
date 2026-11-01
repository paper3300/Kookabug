"""증거 프레임·썸네일 검사 도우미 (구현 계획 M3 T6).

    ran = run_scene(tmp_path, graph, setup=crop_targets)
    ran.end("n_wait")["evidence"]
    ran.thumbs()  # 남아 있는 thumbs/*.jpg

예제 게임 장면 표(`FakeScenario`) + 실제 찾기 엔진 + 프레임 저장소 + 파일 artifacts로 실행기를
돌린다. 시계는 손으로 넘기는 `FakeClock`이라 폴링 캡처 시각이 정확하다(증거 시각 검사).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np
from testkit import registry_with_testkit

from helpers.epoch import Debugger
from helpers.graphs import GraphBuilder, make_workspace
from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.engine import ExecOptions, Executor, FakeClock, RunResult
from kookabug_core.engine.scenario import FakeScenario, ScenarioPlatform
from kookabug_core.loader import load_program
from kookabug_core.record.artifacts import THUMBS_DIR, FileArtifacts
from kookabug_core.workspace import MemorySecrets
from kookabug_platform.engines import RunEngines
from kookabug_platform.frames import DEFAULT_BUDGET_BYTES, FrameStore, decode_image

__all__ = [
    "CROPS",
    "LOADING_TEXT",
    "LOGIN_TITLE",
    "START",
    "SceneRun",
    "crop_targets",
    "run_scene",
]

SCENARIO: Final = FRAMES_DIR / "scenario.json"
TEST: Final = "tests/t.graph.json"
CROPS: Final[dict[str, tuple[str, tuple[int, int, int, int]]]] = {
    "targets/title/start.target.json": ("title.png", (412, 380, 200, 64)),
    "targets/login/title.target.json": ("login.png", (300, 95, 424, 50)),
    "targets/loading/text.target.json": ("loading.png", (300, 260, 424, 60)),
}
LOADING_TEXT: Final = "targets/loading/text.target.json"
"""로딩 화면 글자 (타이틀에서는 안 보인다)."""
START: Final = "targets/title/start.target.json"
"""타이틀 화면 "게임 시작" 버튼 (타이틀에서 보인다)."""
LOGIN_TITLE: Final = "targets/login/title.target.json"
"""로그인 화면 제목 (타이틀에서는 안 보인다)."""


def crop_targets(root: Path) -> None:
    """예제 게임 화면을 잘라 target 파일들을 쓴다 (`CROPS`)."""
    for rel, (frame, (x, y, w, h)) in CROPS.items():
        pixels = decode_image((FRAMES_DIR / frame).read_bytes())
        ok, data = cv2.imencode(".png", np.ascontiguousarray(pixels[y : y + h, x : x + w]))
        assert ok
        path = root.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        image = path.name.removesuffix(".target.json") + ".png"
        (path.parent / image).write_bytes(data.tobytes())
        body = {
            "format": "kookabug.target/0",
            "image": image,
            "recorded": {"client_size": [1024, 640], "dpi": 96},
        }
        path.write_text(json.dumps(body), encoding="utf-8")


@dataclass
class SceneRun:
    result: RunResult
    folder: Path
    """실행 폴더 흉내 (artifacts·썸네일을 파일로 둔 곳)."""
    store: FrameStore
    clock: FakeClock

    @property
    def events(self) -> list[dict[str, Any]]:
        return self.result.events

    def of(self, event: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["event"] == event]

    def steps(self, node: str) -> list[str]:
        return [e["step"] for e in self.of("step.start") if e["node"] == node]

    def step(self, node: str) -> str:
        (step,) = self.steps(node)
        return step

    def end(self, node: str) -> dict[str, Any]:
        step = self.step(node)
        (found,) = [e for e in self.of("step.end") if e["step"] == step]
        return found

    def thumbs(self) -> set[str]:
        """남아 있는 썸네일 (`thumbs/<스텝>.jpg`)."""
        folder = self.folder / THUMBS_DIR
        return (
            {f"{THUMBS_DIR}/{p.name}" for p in folder.glob("*.jpg")} if folder.exists() else set()
        )

    def image(self, rel: str) -> Any:
        return decode_image((self.folder / rel).read_bytes())


def run_scene(
    tmp_path: Path,
    graph: GraphBuilder,
    *,
    setup: Callable[[Path], None] | None = crop_targets,
    secrets: Mapping[str, str] | None = None,
    budget_bytes: int = DEFAULT_BUDGET_BYTES,
    subgraphs: Mapping[str, GraphBuilder] | None = None,
    ws_record: Mapping[str, Any] | None = None,
    debugger: Debugger | None = None,
) -> SceneRun:
    """`debugger`(`helpers.epoch.Debugger`)를 주면 그 멈춤·세대·시계로 돈다."""
    ws = make_workspace(tmp_path / "ws", record=ws_record)
    if setup is not None:
        setup(ws.root)
    for rel, sub in (subgraphs or {}).items():
        sub.write(ws, rel)
    graph.write(ws, TEST)
    program = load_program(ws, TEST, secrets=MemorySecrets(dict(secrets or {})))
    store = FrameStore(budget_bytes=budget_bytes)
    platform = ScenarioPlatform(
        FakeScenario.load(SCENARIO), decode=decode_image, engines=RunEngines(store)
    )
    folder = tmp_path / "run"
    folder.mkdir()
    clock = FakeClock() if debugger is None else debugger.clock
    result = Executor(
        registry_with_testkit(),
        platform=platform,
        clock=clock,
        artifacts=FileArtifacts(folder),
        frames=store,
        before_step=None if debugger is None else debugger.before_step,
        pause_point=debugger,
        epochs=None if debugger is None else debugger.epochs,
    ).run(program, ExecOptions(run_id="evid0001"))
    return SceneRun(result, folder, store, clock)
