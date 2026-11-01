"""실제 Media Foundation H.264 MP4 (구현 계획 M3 2.5, T5, `media` 표시).

건너뛰기는 명시적 탐지(`kookabug_platform.video.probe_media`가 "MF H.264 인코더가 등록돼 있지
않음")일 때만이다 (`kb_testing.media`). 인코더가 있는데 쓰기·디코드가 실패하면 실패다.

- FFmpeg DLL 없이(플러그인 경로를 비운 프로세스) MSMF로 쓰고 다시 읽는다
- 녹화 스레드가 칸마다 적은 장면 표시와 디코드한 프레임의 장면이 같다
- 격자로 이동 (검수 M3): 불규칙한 캡처 지연 + 영상 끈 구간 둘 + 멈춤 둘을 섞은 실행에서, 스텝 시각을
  `(t - t0) / 200 ms` 칸으로 바꿔 디코드한 프레임이 그 스텝의 장면이다
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from helpers.run import tk
from helpers.video import COLORS, go, launch, run_video, switch

from kb_testing.proc import direct_env, python_cmd
from kookabug_core.engine.scenario import ScenarioPlatform
from kookabug_core.record.video import (
    FRAME_MS,
    VIDEO_DIR,
    Encoder,
    VideoFrame,
    VideoGate,
)
from kookabug_platform.frames import decode_image
from kookabug_platform.video import MsmfFactory

pytestmark = pytest.mark.media

SCRIPT = """
import json, sys
from pathlib import Path
import cv2, numpy as np
from kookabug_core.record.video import VideoFrame
from kookabug_platform.doctor import loaded_dll
from kookabug_platform.video import MsmfFactory

out = Path(sys.argv[1])
factory = MsmfFactory()
factory.probe(out.parent)
enc = factory.open(out, (320, 200))
colors = [(0, 0, 220), (0, 220, 0), (220, 0, 0)]
for i in range(15):
    pixels = np.full((200, 320, 3), colors[i // 5], np.uint8)
    enc.write(VideoFrame(pixels, (320, 200), 0.0))
enc.release()
cap = cv2.VideoCapture(str(out), cv2.CAP_MSMF)
means = []
while True:
    ok, frame = cap.read()
    if not ok:
        break
    means.append([round(float(v)) for v in frame.reshape(-1, 3).mean(0)])
cap.release()
folder = Path(cv2.__file__).parent
names = [p.name for p in folder.glob("opencv_videoio_ffmpeg*.dll")]
print(json.dumps({
    "head": out.read_bytes()[4:8].decode("latin-1"),
    "means": means,
    "ffmpeg_files": names,
    "ffmpeg_loaded": [n for n in names if loaded_dll(n) is not None],
}))
"""


def nearest(pixels: Any) -> str:
    mean = pixels.reshape(-1, 3).mean(0)
    return min(COLORS, key=lambda s: float(np.abs(mean - np.array(COLORS[s])).sum()))


def decode(path: Path) -> list[str]:
    cap = cv2.VideoCapture(str(path), cv2.CAP_MSMF)
    scenes: list[str] = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            scenes.append(nearest(frame))
    finally:
        cap.release()
    return scenes


def test_msmf_writes_playable_h264_without_ffmpeg_dll(tmp_path: Path) -> None:
    script = tmp_path / "write.py"
    script.write_text(SCRIPT, encoding="utf-8")
    empty = tmp_path / "no-plugins"
    empty.mkdir()
    # 설치본처럼 FFmpeg 플러그인을 찾을 수 없는 프로세스 (OpenCV 플러그인 경로를 비운다)
    env = direct_env()
    env["OPENCV_VIDEOIO_PLUGIN_PATH"] = str(empty)
    env["OPENCV_VIDEOIO_PRIORITY_FFMPEG"] = "0"
    out = tmp_path / "seg-0001.part.mp4"
    proc = subprocess.run(
        python_cmd("-X", "utf8", script, out),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    body = json.loads(proc.stdout.strip().splitlines()[-1])
    assert body["head"] == "ftyp"  # MP4
    assert body["ffmpeg_loaded"] == []
    means = body["means"]
    assert len(means) == 15
    expected = [(0, 0, 220)] * 5 + [(0, 220, 0)] * 5 + [(220, 0, 0)] * 5
    for got, want in zip(means, expected, strict=True):
        assert max(abs(a - b) for a, b in zip(got, want, strict=True)) <= 12, (got, want)
    print(f"\nffmpeg 플러그인 파일 {body['ffmpeg_files']} — 읽지 않음", file=sys.stderr)


class _Tee:
    """MSMF 공장 + 조각마다 쓴 장면 표시 기록."""

    def __init__(self) -> None:
        self.inner = MsmfFactory()
        self.written: dict[str, list[str | None]] = {}

    def probe(self, folder: Path) -> None:
        self.inner.probe(folder)

    def open(self, path: Path, size: tuple[int, int]) -> Encoder:
        log = self.written.setdefault(path.name.replace(".part", ""), [])
        encoder = self.inner.open(path, size)

        class Logged:
            def write(self, frame: VideoFrame) -> None:
                encoder.write(frame)
                log.append(frame.marker)

            def release(self) -> None:
                encoder.release()

        return Logged()


def show(g: Any, node: str, scene: str, then: str, *, ms: int = 600, **kw: Any) -> Any:
    g.node(node, "core.input.key", inputs=go(scene), next={"done": f"{node}_w"}, **kw)
    return g.node(f"{node}_w", "core.flow.delay", inputs={"ms": ms}, next={"done": then})


def test_decode_frames_match_written_markers(tmp_path: Path) -> None:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_b")
    show(g, "n_b", "b", "n_c")
    show(g, "n_c", "c", "n_pass")
    g.node("n_pass", "core.test.pass")
    tee = _Tee()
    ran = run_video(tmp_path, g, factory=tee, decode=decode_image)
    assert ran.result.verdict == "pass"
    assert ran.index is not None and ran.index["status"] == "recorded"
    for seg in ran.index["segments"]:
        scenes = decode(ran.run_dir / VIDEO_DIR / seg["file"])
        assert len(scenes) == seg["frames"]
        assert scenes == tee.written[seg["file"]], seg["file"]
    seen = {s for lines in tee.written.values() for s in lines}
    assert {"a", "b", "c"} <= seen


class _Jitter:
    """녹화 프레임을 불규칙하게 늦게 주는 출처 (0~350 ms, 시드 고정)."""

    def __init__(self, inner: ScenarioPlatform) -> None:
        self.inner = inner
        self.rng = random.Random(7)

    def video_frame(self, window: Any, timeout_ms: int) -> VideoFrame:
        time.sleep(self.rng.choice((0.0, 0.02, 0.05, 0.12, 0.25, 0.35)))
        return self.inner.video_frame(window, timeout_ms)


def test_seek_by_grid_lands_on_step_marker_real_mp4(tmp_path: Path) -> None:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_off1", ms=1000)
    g.node(
        "n_off1",
        "core.flow.delay",
        inputs={"ms": 400},
        next={"done": "n_b"},
        record={"video": "off"},
    )
    show(g, "n_b", "b", "n_c", ms=1000)
    show(g, "n_c", "c", "n_off2", ms=1000)  # n_c_w 앞에서 멈춤
    g.node(
        "n_off2",
        "core.flow.delay",
        inputs={"ms": 300},
        next={"done": "n_d"},
        record={"video": "off"},
    )
    show(g, "n_d", "d", "n_e", ms=1000)
    show(g, "n_e", "e", "n_pass", ms=1000)  # n_e_w 앞에서 멈춤
    g.node("n_pass", "core.test.pass")
    holder: dict[str, Any] = {}

    def grab(event: dict[str, Any], platform: ScenarioPlatform, gate: VideoGate) -> None:
        holder.update(platform=platform, gate=gate)

    def before(point: Any) -> None:
        if point.node not in ("n_c_w", "n_e_w"):
            return
        gate: VideoGate = holder["gate"]
        gate.set_paused(True, point.step)
        switch(holder["platform"], "g")  # 멈춘 동안 화면이 바뀌었다가 돌아온다
        time.sleep(0.5)
        switch(holder["platform"], point.node[2])
        gate.set_paused(False, point.step)

    ran = run_video(
        tmp_path,
        g,
        factory=MsmfFactory(),
        decode=decode_image,
        wrap=_Jitter,
        hooks=[grab],
        before_step=before,
    )
    assert ran.result.verdict == "pass", ran.result.reason
    assert ran.index is not None
    segments = ran.index["segments"]
    gaps = [gap["gap"] for gap in ran.index["gaps"]]
    assert gaps.count("policy_off") == 2 and gaps.count("paused") == 2, gaps
    decoded = {seg["file"]: decode(ran.run_dir / VIDEO_DIR / seg["file"]) for seg in segments}
    checks = (("a", "n_a_w"), ("b", "n_b_w"), ("c", "n_c_w"), ("d", "n_d_w"), ("e", "n_e_w"))
    for scene, node in checks:
        start, _ = ran.step(node)
        # 그 스텝 장면이 보이는 동안 (늦은 캡처 0.35초 + 칸 하나 여유).
        # 경계 멈춤은 step.start 전이다
        t = start["_t"] + 0.7
        seg = next(s for s in segments if _ts(s["t0"]) <= t < _ts(s["t_end"]))
        slot = int((t - _ts(seg["t0"])) * 1000 // FRAME_MS)
        assert decoded[seg["file"]][slot] == scene, (scene, seg, slot, decoded[seg["file"]])
    # 멈춘 동안의 장면(g)은 어디에도 없다
    assert all("g" not in scenes for scenes in decoded.values())


def _ts(text: str) -> float:
    return datetime.fromisoformat(text).timestamp()
