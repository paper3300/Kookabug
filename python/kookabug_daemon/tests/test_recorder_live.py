"""실제 예제 게임·실제 훅·실제 캡처 녹화 (M4 계획 2.15, T8 `desktop_input`). **조율자가 잠금 해제
데스크톱에서 돌린다** (`KOOKABUG_DESKTOP_TESTS=require KOOKABUG_DESKTOP_INPUT=1`, 다른 데스크톱
검사와 동시에 돌리지 않는다 — 전역 훅·임대권).

"사람" 입력은 검사 표식(`TEST_MARK`, daemon `HookTesting(accept_extra_info=…)`)을 실은 SendInput,
우리 입력은 제품 표식(`KOOKABUG_INPUT_MARK`)으로 같이 보내 빠지는지 본다. 같은 녹화 안에서 검사 표식
입력이 녹화되어야 "우리 입력 0"이 의미가 있다(양성 대조).
"""

from __future__ import annotations

import ctypes
import json
import time
from collections.abc import Iterator
from ctypes import wintypes
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.cli import cli_env, run_cli
from helpers.recorder_rig import HOTKEYS, SECRET_KEY, graph_from_fragment, run_graph, steps_of
from helpers.runner import RUNNER_CMD, step_of

from kb_testing.daemon import ThreadDaemon
from kb_testing.keys import button_input, key_input, release_all_for_test, send_inputs
from kb_testing.proc import wait_until
from kb_testing.recorder_scripts import (
    ACCOUNT,
    ACCOUNT_POINT,
    LOGIN_POINT,
    PASSWORD,
    START_POINT,
    char_vk,
)
from kb_testing.sample_game import (
    EXAMPLE_SECRET_ENV,
    SampleGame,
    copy_example_workspace,
    launch_sample_game,
    post_close,
)
from kookabug_core.service import WorkspaceService
from kookabug_core.supervisor import Supervisor
from kookabug_daemon.client import DaemonClient
from kookabug_daemon.recorder_hook import HookTesting
from kookabug_platform.dpi import per_monitor_v2_thread
from kookabug_platform.inputmark import KOOKABUG_INPUT_MARK
from kookabug_platform.windows import activate, find_windows, window_info

pytestmark = [pytest.mark.desktop_input, pytest.mark.timeout(600)]

TEST_MARK: Final = 0x7E57_0001
LOBBY_TITLE: Final = [412, 90, 200, 60]
GRAPH: Final = "tests/rec_live.graph.json"
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_SetCursorPos = _user32.SetCursorPos
_SetCursorPos.restype = wintypes.BOOL
_SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
VK_SHIFT: Final = 0xA0
VK_TAB: Final = 0x09


def click(hwnd: int, point: tuple[int, int], extra: int = TEST_MARK) -> None:
    with per_monitor_v2_thread():
        origin = window_info(hwnd).client_origin
        _SetCursorPos(origin[0] + point[0], origin[1] + point[1])
    time.sleep(0.15)
    send_inputs(button_input("mouse:left", extra_info=extra))
    time.sleep(0.05)
    send_inputs(button_input("mouse:left", up=True, extra_info=extra))
    time.sleep(0.3)


def tap(vk: int, extra: int = TEST_MARK) -> None:
    send_inputs(key_input(vk, extra_info=extra))
    time.sleep(0.03)
    send_inputs(key_input(vk, up=True, extra_info=extra))
    time.sleep(0.06)


def type_text(text: str, extra: int = TEST_MARK) -> None:
    for ch in text:
        vk, shift = char_vk(ch)
        if shift:
            send_inputs(key_input(VK_SHIFT, extra_info=extra))
        tap(vk, extra)
        if shift:
            send_inputs(key_input(VK_SHIFT, up=True, extra_info=extra))


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    for name, value in EXAMPLE_SECRET_ENV.items():
        monkeypatch.setenv(name, value)
    root = copy_example_workspace(tmp_path / "example")
    yield root
    release_all_for_test()
    for hwnd in find_windows(title="SampleRPG"):
        post_close(hwnd)


def live_daemon(root: Path, tmp_path: Path) -> tuple[ThreadDaemon, dict[str, str]]:
    env = cli_env(tmp_path, None, **EXAMPLE_SECRET_ENV)
    supervisor = Supervisor(runner_cmd=RUNNER_CMD, env=env)
    service = WorkspaceService(root, environ=env, supervisor=supervisor)
    testing = HookTesting(accept_extra_info=TEST_MARK)
    return ThreadDaemon(root, service=service, recorder_testing=testing), env


def wait_state(ui: DaemonClient, state: str) -> dict[str, Any]:
    found: dict[str, Any] = {}

    def check() -> bool:
        found.update(ui.call("recorder.state", {}))
        return found["state"] == state

    wait_until(check, timeout=30, interval=0.2)
    return found


def test_record_sample_login_with_test_mark_then_replay_pass(
    workspace: Path, tmp_path: Path
) -> None:
    """실제 예제 게임·실제 훅·검사 표식 입력 → 커밋 → 실제 runner 재생 pass. 녹화 창은 로비에 둔 채
    재생은 새로 띄운 게임(다른 PID·창)이 로비까지 간다(로비 화면 확인 pass)."""
    daemon, _ = live_daemon(workspace, tmp_path)
    with daemon as d, d.client() as ui:
        started = ui.call("recorder.start", {"launch": {}, "hotkeys": HOTKEYS})
        hwnd = started["window"]["handle"]
        recorded_hwnd, recorded_pid = hwnd, window_info(hwnd).pid
        activate(hwnd)
        time.sleep(0.5)
        click(hwnd, START_POINT)
        time.sleep(0.8)
        click(hwnd, ACCOUNT_POINT)
        type_text(ACCOUNT)
        tap(VK_TAB)
        type_text(PASSWORD[:7])
        time.sleep(3.0)  # 쉬었다 이어 친다
        type_text(PASSWORD[7:])
        time.sleep(0.6)
        click(hwnd, LOGIN_POINT)
        time.sleep(1.5)
        live = ui.call("recorder.frame", {"which": "live"})
        ui.call(
            "recorder.insert_check",
            {"kind": "visible", "frame_id": live["frame"]["frame_id"], "rect": LOBBY_TITLE},
        )
        ui.call("recorder.stop", {})
        state = ui.call("recorder.state", {})
        assert state["stop_reason"] == "user", state
        steps = steps_of(ui)
        secret = next(s for s in steps if s.get("text_state") == "secret")
        ui.call(
            "recorder.step.update", {"step": secret["step"], "patch": {"secret_key": SECRET_KEY}}
        )
        prepared = ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        graph = graph_from_fragment(prepared["fragment"])
        ended = run_graph(ui, workspace, GRAPH, graph, 180)
        assert ended["outcome"]["verdict"] == "pass", ended
        ui.call("recorder.commit_finish", {"token": prepared["token"], "graph_path": GRAPH})
    # 재생은 새로 띄운 게임이었다: 재생 기록의 app.launch 출력(창·프로세스)이 녹화 창과 다르다.
    # 재생 게임은 실행 Job이 끝에 정리하므로 남은 창 개수는 보지 않는다
    launch_id = next(i for i, n in graph["nodes"].items() if n["type"] == "core.app.launch")
    events = [
        json.loads(line)
        for line in (workspace / ended["run_dir"] / "events.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]
    _, end = step_of(events, launch_id)
    assert end is not None and end.get("exit") == "attached", end
    replay_window, replay_process = end["outputs"]["window"], end["outputs"]["process"]
    assert replay_window["handle"] != recorded_hwnd
    assert replay_process["pid"] != recorded_pid


def test_product_marked_input_during_recording_not_recorded(
    workspace: Path, tmp_path: Path
) -> None:
    """녹화 중 제품 표식 입력(클릭·키·글자)은 스텝 0, 같은 녹화의 검사 표식 입력은 녹화된다(양성
    대조). 그 사이 마우스 이동을 많이 섞어도 `input_overflow`가 없다 (2차 N1)."""
    game: SampleGame = launch_sample_game(workdir=tmp_path / "game")
    daemon, _ = live_daemon(workspace, tmp_path)
    try:
        with daemon as d, d.client() as ui:
            ui.call("recorder.start", {"window": game.hwnd, "hotkeys": HOTKEYS})
            activate(game.hwnd)
            time.sleep(0.5)
            click(game.hwnd, START_POINT, KOOKABUG_INPUT_MARK)
            type_text("zz", KOOKABUG_INPUT_MARK)
            with per_monitor_v2_thread():
                origin = window_info(game.hwnd).client_origin
                for i in range(2000):
                    _SetCursorPos(origin[0] + 100 + i % 400, origin[1] + 500)
            click(game.hwnd, ACCOUNT_POINT)  # 검사 표식 = 사람
            type_text("ab")
            time.sleep(1.0)
            ui.call("recorder.stop", {})
            state = ui.call("recorder.state", {})
            assert state["stop_reason"] == "user", state
            steps = [s for s in steps_of(ui) if s["kind"] not in ("wait", "delay")]
            assert [s["kind"] for s in steps] == ["click", "text"], steps
            assert steps[1]["text_len"] == 2
            ui.call("recorder.discard", {})
    finally:
        game.close()


def test_cli_run_rejected_while_recording(workspace: Path, tmp_path: Path) -> None:
    """녹화 중 다른 창의 CLI `kookabug run`은 입력 임대권에서 `input_lease_busy`로 끝난다."""
    game: SampleGame = launch_sample_game(workdir=tmp_path / "game")
    daemon, env = live_daemon(workspace, tmp_path)
    try:
        with daemon as d, d.client() as ui:
            ui.call("recorder.start", {"window": game.hwnd, "hotkeys": HOTKEYS})
            wait_state(ui, "recording")
            done = run_cli(["run", "tests/inventory_open.graph.json"], cwd=workspace, env=env)
            assert "input_lease_busy" in done.stdout + done.stderr, done
            ui.call("recorder.discard", {})
    finally:
        game.close()
