"""실제 창 녹화 (구현 계획 M3 2.5, T5, `desktop` + `media`).

예제 게임 창을 WGC 최신 프레임으로 2초 녹화해 Media Foundation H.264 조각을 쓰고 다시 읽는다. 입력은
보내지 않는다(게임의 로딩 타이머가 화면을 바꾼다).
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import pytest

from kb_testing.sample_game import launch_sample_game
from kookabug_core.record.finalize import finalize_video
from kookabug_core.record.video import VIDEO_DIR, VideoGate, VideoRecorder, scaled_size
from kookabug_platform.platform import WindowsPlatform
from kookabug_platform.video import MsmfFactory
from kookabug_platform.windows import window_info

pytestmark = [pytest.mark.desktop, pytest.mark.media]


def test_live_window_recording_sample_game(tmp_path: Path) -> None:
    with launch_sample_game(workdir=tmp_path / "game") as game:
        platform = WindowsPlatform(run_id="videolive")
        try:
            window = platform._ref(game.hwnd)  # pyright: ignore[reportPrivateUsage]
            gate = VideoGate()
            gate.hold("s1")
            gate.classify("s1", "on", secret=False, window=window)
            run_dir = tmp_path / "run"
            run_dir.mkdir()
            recorder = VideoRecorder(run_dir, gate, platform, MsmfFactory()).start()
            time.sleep(3.0)
            gate.release("s1")
            assert recorder.stop()
        finally:
            platform.close()
        size = window_info(game.hwnd).client_size
    index = finalize_video(run_dir, {"verdict": "fail", "t": "2026-11-02T00:00:00.000Z"})
    assert index is not None and index["status"] == "recorded", index
    (seg,) = index["segments"]
    assert tuple(seg["size"]) == scaled_size(size)
    assert seg["frames"] >= 5
    cap = cv2.VideoCapture(str(run_dir / VIDEO_DIR / seg["file"]), cv2.CAP_MSMF)
    frames = 0
    while cap.read()[0]:
        frames += 1
    cap.release()
    assert frames == seg["frames"]
