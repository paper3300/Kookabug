"""runner의 `platform.kind: windows` (구현 계획 M1 2.2·2.3, runner 연결 T9): 예제 게임 창 캡처,
창 API 전에 Per-Monitor V2, 끝날 때 창 수명 추적기 스레드 멈춤."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

import pytest
from helpers.graphs import GraphBuilder
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of

from kb_testing.proc import Spawned
from kb_testing.sample_game import FRAMES_DIR, launch_sample_game
from kookabug_platform.frames import decode_image
from kookabug_platform.platform import WindowsPlatform
from kookabug_platform.vision import diff_pixels

_PMV2 = -4
_QUERY_LIMITED = 0x1000


def _process_is_pmv2(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    user32.GetDpiAwarenessContextForProcess.restype = ctypes.c_void_p
    user32.GetDpiAwarenessContextForProcess.argtypes = (wintypes.HANDLE,)
    user32.AreDpiAwarenessContextsEqual.restype = wintypes.BOOL
    user32.AreDpiAwarenessContextsEqual.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    handle = kernel32.OpenProcess(_QUERY_LIMITED, False, pid)
    assert handle, ctypes.get_last_error()
    try:
        context = user32.GetDpiAwarenessContextForProcess(handle)
        return bool(user32.AreDpiAwarenessContextsEqual(context, ctypes.c_void_p(_PMV2)))
    finally:
        kernel32.CloseHandle(handle)


@pytest.mark.process
def test_runner_sets_pmv2_before_any_window_api(tmp_path: Path, spawned: Spawned) -> None:
    signal = tmp_path / "go"
    g = (
        tk()
        .entry("n_gate")
        .node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = RunnerHarness.make(tmp_path, g, windows=True).start(spawned)
    h.wait_log("gate")
    runner = h.runner
    assert runner is not None
    # 진입점 첫 줄에서 정한다 (창 API·플랫폼 패키지보다 먼저): 프로세스 수준이 PMv2
    assert _process_is_pmv2(runner.pid)
    signal.write_text("go", encoding="utf-8")
    done = h.finish()
    assert done.run_end is not None and done.run_end["verdict"] == "pass", done.run_end


def test_tracker_thread_stopped_at_finish() -> None:
    platform = WindowsPlatform(run_id="t9")
    assert platform.started_tracker is None  # 창을 쓰기 전에는 띄우지 않는다
    assert platform.find_window("kookabug-no-such-window-title", None, False) is None
    tracker = platform.tracker  # 창 바인딩·캡처·입력 확인이 처음 쓸 때 띄운다
    assert platform.started_tracker is tracker and tracker.running
    assert platform.close()
    assert not tracker.running


@pytest.mark.desktop
def test_runner_kind_windows_captures_game(tmp_path: Path, spawned: Spawned) -> None:
    title = f"KB T9 {tmp_path.name}"
    with launch_sample_game(("--title", title), workdir=tmp_path / "game") as game:
        game.wait_screen("title")
        g: GraphBuilder = (
            tk()
            .entry("n_attach")
            .node(
                "n_attach",
                "testkit.m1.set_window",
                inputs={"title": title},
                next={"done": "n_shot"},
            )
            .node("n_shot", "testkit.shot", inputs={"save": True}, next={"done": "n_pass"})
            .node("n_pass", "core.test.pass")
        )
        h = RunnerHarness.make(tmp_path, g, windows=True, fake_input=False).start(spawned)
        done = h.finish()
        assert done.run_end is not None and done.run_end["verdict"] == "pass", done.run_end
        _, shot = step_of(h.events(), "n_shot")
        (saved,) = shot["artifacts"]
        pixels = decode_image((h.run_dir / saved).read_bytes())
        assert pixels.shape[:2] == (640, 1024)  # 클라이언트 영역만
        expected = decode_image((FRAMES_DIR / "title.png").read_bytes())
        assert diff_pixels(pixels, expected) < 0.02
        assert shot["outputs"]["image"]["data"] is None  # 노드에는 참조 이미지
