"""영상 검사 도우미 (구현 계획 M3 T5).

- `write_scenario(폴더)`: 장면마다 단색 PNG를 갖는 가짜 장면 표. 어느 장면에서든 `KEYS[장면]` 키를
  누르면 그 장면으로 간다 (가짜 인코더는 장면 이름을 `marker`로 적고, 실제 MP4는 색으로 가린다)
- `run_video(...)`: 실행기 + 녹화 게이트 + 녹화 스레드 + 가짜 인코더를 한 프로세스에서 돌리고
  마무리(`finalize_video`)까지. 이벤트에는 벽시계 시각(`_t`)을 붙인다
- `fake_lines(run_dir)`: 가짜 인코더가 조각 파일에 적은 칸 전부 (지우기 전 것을 보려면 마무리 전에)
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np
from testkit import registry_with_testkit

from helpers.graphs import GraphBuilder, make_workspace
from kb_testing.proc import wait_until
from kookabug_core.engine import ExecOptions, Executor, MemoryArtifacts, RunResult
from kookabug_core.engine.scenario import FakeScenario, ScenarioPlatform
from kookabug_core.loader import load_program
from kookabug_core.record.finalize import finalize_video
from kookabug_core.record.video import (
    SEGMENTS_FILE,
    VIDEO_DIR,
    EncoderFactory,
    EncoderProbe,
    FakeEncoderFactory,
    VideoGate,
    VideoRecorder,
    stamp,
)
from kookabug_core.workspace import MemorySecrets, Workspace

__all__ = [
    "COLORS",
    "KEYS",
    "SCENES",
    "VideoRun",
    "fake_lines",
    "go",
    "launch",
    "run_video",
    "segment_lines",
    "wait_slots",
    "write_scenario",
]

SCENES: Final = ("idle", "a", "b", "c", "d", "e", "f", "g", "h")
KEYS: Final = {scene: f"f{i + 1}" for i, scene in enumerate(SCENES)}
COLORS: Final = {
    "idle": (40, 40, 40),
    "a": (0, 0, 220),
    "b": (0, 220, 0),
    "c": (220, 0, 0),
    "d": (0, 220, 220),
    "e": (220, 0, 220),
    "f": (220, 220, 0),
    "g": (255, 255, 255),
    "h": (0, 120, 255),
}
"""장면 → BGR 색."""
SIZE: Final = (320, 200)
VIDEO_ON: Final[Mapping[str, Any]] = {"video": "on"}
"""`run_video`의 기본 워크스페이스 정책: 조각 파일을 보려고 `on` (기본값 `failed_only`는 pass에서
지운다 — `ws_record=None`이면 워크스페이스에 `record`가 없다)."""
TEST: Final = "tests/t.graph.json"


def write_scenario(folder: Path, size: tuple[int, int] = SIZE) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    w, h = size
    for scene in SCENES:
        pixels = np.full((h, w, 3), COLORS[scene], np.uint8)
        ok, data = cv2.imencode(".png", pixels)
        assert ok
        (folder / f"{scene}.png").write_bytes(data.tobytes())
    transitions = [
        {"after_frames": 0, "from": src, "on": {"key": KEYS[dst], "kind": "key"}, "to": dst}
        for src in SCENES
        for dst in SCENES
        if src != dst
    ]
    spec = {
        "format": "kookabug.fake-scenario/0",
        "launch": [{"variant": "default"}],
        "process": {"name": "game.exe"},
        "scenes": {scene: f"{scene}.png" for scene in SCENES},
        "start": "idle",
        "transitions": transitions,
        "variants": ["default"],
        "window": {"client_size": [w, h], "dpi": 96, "title": "Video Test"},
    }
    path = folder / "scenario.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def go(scene: str) -> dict[str, Any]:
    """`core.input.key` 입력: 그 장면으로 바꾼다."""
    return {"keys": KEYS[scene]}


def launch(g: GraphBuilder, node: str, then: str) -> GraphBuilder:
    return g.node(node, "core.app.launch", inputs={"path": "game.exe"}, next={"attached": then})


def segment_lines(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / VIDEO_DIR / SEGMENTS_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def fake_lines(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """조각 파일(`.mp4`·`.part.mp4`) → 가짜 인코더가 적은 칸들."""
    out: dict[str, list[dict[str, Any]]] = {}
    for path in sorted((run_dir / VIDEO_DIR).glob("seg-*.mp4")):
        lines = path.read_text(encoding="utf-8").splitlines()
        out[path.name] = [json.loads(line) for line in lines if line]
    return out


@dataclass
class VideoRun:
    result: RunResult
    events: list[dict[str, Any]]
    run_dir: Path
    written: dict[str, list[dict[str, Any]]]
    """마무리 전에 읽은 조각별 칸 (지운 조각 포함)."""
    index: dict[str, Any] | None
    writer_done: bool
    gate: VideoGate
    platform: ScenarioPlatform

    def markers(self) -> set[str | None]:
        return {line["marker"] for lines in self.written.values() for line in lines}

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["event"] == kind]

    def step(self, node: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        (start,) = [e for e in self.of("step.start") if e["node"] == node]
        ends = [e for e in self.of("step.end") if e["step"] == start["step"]]
        return start, (ends[0] if ends else None)

    def span(self, node: str) -> tuple[str, str]:
        start, end = self.step(node)
        assert end is not None
        return stamp(start["_t"]), stamp(end["_t"])

    def segments(self) -> list[dict[str, Any]]:
        return [line for line in segment_lines(self.run_dir) if "file" in line]

    def gaps(self) -> list[dict[str, Any]]:
        return [line for line in segment_lines(self.run_dir) if "gap" in line]


@dataclass
class _Sink:
    events: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    hooks: list[Callable[[dict[str, Any]], None]] = field(
        default_factory=list[Callable[[dict[str, Any]], None]]
    )

    def emit(self, event: Mapping[str, Any]) -> None:
        stamped = {**event, "_t": time.time()}
        self.events.append(stamped)
        for hook in self.hooks:
            hook(stamped)


def run_video(
    tmp_path: Path,
    graph: GraphBuilder,
    *,
    subgraphs: Mapping[str, GraphBuilder] | None = None,
    ws_record: Mapping[str, Any] | None = VIDEO_ON,
    secrets: Mapping[str, str] | None = None,
    factory: EncoderFactory | None = None,
    hooks: Sequence[Callable[[dict[str, Any], ScenarioPlatform, VideoGate], None]] = (),
    before_step: Callable[[Any], None] | None = None,
    run_end: Mapping[str, Any] | None = None,
    finalize: bool = True,
    stop_grace_s: float = 3.0,
    video: bool = True,
    decode: Callable[[bytes], Any] | None = None,
    wrap: Callable[[ScenarioPlatform], Any] | None = None,
) -> VideoRun:
    """실행기 + 녹화 스레드 + 가짜 인코더(기본)를 돌리고 마무리한다. `hooks`는 이벤트마다 불린다
    (실행기 스레드에서 — `step.start` 직후·`step.end` 직후에 장면을 바꾸는 데 쓴다). 실제 인코더는
    `decode`(장면 PNG → 픽셀)를 주고, `wrap`은 녹화 프레임 출처를 감싼다(지연 주입)."""
    ws: Workspace = make_workspace(tmp_path / "ws", record=ws_record)
    graph.write(ws, TEST)
    for rel, sub in (subgraphs or {}).items():
        sub.write(ws, rel)
    scenario = FakeScenario.load(write_scenario(tmp_path / "scenario"))
    platform = ScenarioPlatform(scenario, decode=decode)
    source = wrap(platform) if wrap is not None else platform
    gate = VideoGate()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    encoders = factory or FakeEncoderFactory()
    recorder = None
    if video:
        # runner처럼 인코더 시험을 먼저 끝낸다 (차가운 MF 첫 열기가 첫 장면을 가리지 않게)
        probe = EncoderProbe(encoders)
        assert probe.done.wait(30)
        recorder = VideoRecorder(run_dir, gate, source, encoders, probe=probe).start()
    sink = _Sink()
    for hook in hooks:
        sink.hooks.append(lambda e, h=hook: h(e, platform, gate))
    program = load_program(ws, TEST, secrets=MemorySecrets(dict(secrets or {})))
    executor = Executor(
        registry_with_testkit(),
        platform=platform,
        artifacts=MemoryArtifacts(),
        sink=sink,
        video=gate if video else None,
        before_step=before_step,
    )
    result = executor.run(program, ExecOptions(run_id="r1", collect_events=False))
    done = recorder.stop(stop_grace_s) if recorder is not None else True
    fake = factory is None or isinstance(factory, FakeEncoderFactory)
    written = fake_lines(run_dir) if fake and done and recorder is not None else {}
    end: dict[str, Any] = {"t": stamp(time.time()), "verdict": result.verdict}
    end.update(run_end or {})
    index = finalize_video(run_dir, end) if finalize and done and recorder is not None else None
    return VideoRun(result, sink.events, run_dir, written, index, done, gate, platform)


def wait_slots(run_dir: Path, segments: int = 1, timeout: float = 10.0) -> None:
    """녹화 스레드가 조각 `segments`개에 칸을 쓸 때까지 (칸 없이 닫힌 조각은 지워져 세지 않는다).

    녹화 시작·차단이 풀린 뒤 첫 프레임은 늦을 수 있다(설계상 허용: 2초 전까지는 조각도 빈 구간도
    없다). 느린 러너에서 "그 스텝 앞 조각" 검사가 빈 목록이 되지 않게 스텝을 붙잡아 둔다."""

    def written() -> bool:
        files = (run_dir / VIDEO_DIR).glob("seg-*.frames.jsonl")
        return sum(1 for p in files if p.stat().st_size > 0) >= segments

    wait_until(written, timeout=timeout, message=f"녹화 조각 {segments}개에 칸이 쓰이지 않았다")


def switch(platform: ScenarioPlatform, scene: str) -> None:
    """실행기 밖에서 장면을 바꾼다 (가짜 게임의 키 전이)."""
    game = platform.scenario.latest()
    platform.scenario.apply(game, "key", KEYS[scene])


def on_event(
    kind: str, node: str | None, action: Callable[[ScenarioPlatform, VideoGate], None]
) -> Callable[[dict[str, Any], ScenarioPlatform, VideoGate], None]:
    """그 노드의 그 이벤트 직후 `action` (노드 None이면 모든 노드)."""
    steps: dict[str, str] = {}

    def hook(event: dict[str, Any], platform: ScenarioPlatform, gate: VideoGate) -> None:
        if event["event"] == "step.start":
            steps[event["step"]] = event["node"]
        if event["event"] != kind:
            return
        if node is not None and steps.get(event.get("step", "")) != node:
            return
        action(platform, gate)

    return hook


class Blocker:
    """녹화 프레임 가져오기를 붙잡아 두는 출처 래퍼 (가져오는 중 게이트가 바뀌는 경우)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.armed = threading.Event()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.after_release: Callable[[], None] | None = None

    def video_frame(self, window: Any, timeout_ms: int) -> Any:
        if self.armed.is_set():
            self.armed.clear()
            self.entered.set()
            self.release.wait(10)
            if self.after_release is not None:
                self.after_release()
        return self.inner.video_frame(window, timeout_ms)
