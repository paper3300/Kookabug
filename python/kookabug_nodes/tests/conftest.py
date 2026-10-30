"""노드 검사 공용.

- `targets`: 예제 게임 화면 PNG를 잘라 만든 target
- `scene`: 예제 게임 장면 표(`FakeScenario`) + 실제 매칭·OCR 엔진 + 프레임 저장소로 그래프를
  실행기에서 돌린다 (공용 입력 서비스·기록 정책·실패 증거까지 실제 경로)
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.graphs import GraphBuilder, make_workspace
from testkit import registry_with_testkit

from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.engine import ExecOptions, Executor, FakeClock, MemoryArtifacts, RunResult
from kookabug_core.engine.scenario import FakeScenario, ScenarioPlatform
from kookabug_core.loader import load_program
from kookabug_core.workspace import MemorySecrets
from kookabug_platform.engines import RunEngines
from kookabug_platform.frames import DEFAULT_BUDGET_BYTES, FrameStore, decode_image

SCENARIO: Final = FRAMES_DIR / "scenario.json"
TEST: Final = "tests/t.graph.json"


class Targets:
    """예제 게임 화면 PNG를 잘라 target 파일을 쓴다."""

    # 로그인 화면(1024x640)의 칸 이름표를 잘라 target으로 쓰고, 클릭 지점은 칸 가운데로 옮긴다.
    # 칸 테두리는 포커스에 따라 색이 바뀌므로 이미지에 넣지 않는다.
    # target 경로 → (이름표 상자 [x, y, w, h], 상자 가운데에서 칸 가운데까지 offset)
    LOGIN: Final[dict[str, tuple[tuple[int, int, int, int], tuple[int, int]]]] = {
        "targets/login/account_field.target.json": ((320, 210, 60, 40), (210, 0)),
        "targets/login/password_field.target.json": ((280, 290, 100, 40), (230, 0)),
    }
    ACCOUNT: Final = "targets/login/account_field.target.json"
    PASSWORD: Final = "targets/login/password_field.target.json"

    def crop(
        self,
        root: Path,
        rel: str,
        frame: str,
        rect: tuple[int, int, int, int],
        *,
        offset: tuple[int, int] = (0, 0),
        extra: Mapping[str, Any] | None = None,
    ) -> Path:
        """`frames/<frame>`의 `rect`를 잘라 PNG와 target 파일을 쓴다 (클릭 = 가운데 + offset)."""
        import cv2
        import numpy as np

        from kookabug_platform.frames import decode_image

        pixels = decode_image((FRAMES_DIR / frame).read_bytes())
        x, y, w, h = rect
        ok, data = cv2.imencode(".png", np.ascontiguousarray(pixels[y : y + h, x : x + w]))
        assert ok
        path = root.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        image = path.name.removesuffix(".target.json") + ".png"
        (path.parent / image).write_bytes(data.tobytes())
        body: dict[str, Any] = {
            "click": {"anchor": "center", "offset": list(offset)},
            "format": "kookabug.target/0",
            "image": image,
            "recorded": {"client_size": [1024, 640], "dpi": 96},
            **(extra or {}),
        }
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        return path

    def login(self, root: Path) -> None:
        """로그인 칸 target 두 개 (`ACCOUNT`·`PASSWORD`)."""
        for rel, (rect, offset) in self.LOGIN.items():
            self.crop(root, rel, "login.png", rect, offset=offset)


@pytest.fixture
def targets() -> Targets:
    return Targets()


@dataclass
class SceneRun:
    """`scene` 픽스처의 실행 결과."""

    result: RunResult
    platform: ScenarioPlatform
    store: FrameStore
    artifacts: MemoryArtifacts
    clock: Any

    @property
    def events(self) -> list[dict[str, Any]]:
        return self.result.events

    def of(self, event: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["event"] == event]

    def step(self, node: str) -> str:
        (step,) = [e["step"] for e in self.of("step.start") if e["node"] == node]
        return step

    def end(self, node: str) -> dict[str, Any]:
        step = self.step(node)
        (found,) = [e for e in self.of("step.end") if e["step"] == step]
        return found

    def png(self, path: str) -> Any:
        """저장한 스크린샷 artifact의 픽셀."""
        data = self.artifacts.saved[path].data
        assert data is not None
        return decode_image(data)


type Scene = Callable[..., SceneRun]


@pytest.fixture
def scene(tmp_path: Path) -> Scene:
    """`scene(graph, setup=…, budget_bytes=…, secrets=…, ocr=…, clock=…)`: 워크스페이스를 만들고
    (`setup(root)`로 target 등을 쓰고) 그래프를 예제 게임 장면 표에서 실행한다. 게임은 그래프의
    `core.app.launch`(경로는 아무거나, `args`로 갈래)가 띄운다. `ocr`은 OCR 엔진(기본: 실제 모델),
    `clock`은 실행기 시계(기본: 손으로 넘기는 `FakeClock`)."""

    def run(
        graph: GraphBuilder,
        *,
        setup: Callable[[Path], None] | None = None,
        budget_bytes: int = DEFAULT_BUDGET_BYTES,
        secrets: Mapping[str, str] | None = None,
        ocr: Any = None,
        clock: Any = None,
    ) -> SceneRun:
        ws = make_workspace(tmp_path / "ws")
        if setup is not None:
            setup(ws.root)
        graph.write(ws, TEST)
        program = load_program(ws, TEST, secrets=MemorySecrets(dict(secrets or {})))
        store = FrameStore(budget_bytes=budget_bytes)
        platform = ScenarioPlatform(
            FakeScenario.load(SCENARIO), decode=decode_image, engines=RunEngines(store, ocr=ocr)
        )
        artifacts = MemoryArtifacts()
        clock = FakeClock() if clock is None else clock
        result = Executor(
            registry_with_testkit(),
            platform=platform,
            clock=clock,
            artifacts=artifacts,
            frames=store,
        ).run(program, ExecOptions(run_id="r1"))
        return SceneRun(result, platform, store, artifacts, clock)

    return run
