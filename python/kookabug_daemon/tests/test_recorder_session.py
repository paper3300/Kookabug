"""녹화 세션의 상태별 마무리 (M4 계획 2.9 표, 검수 M3·2차 N1, T8): 일시정지 중 입력 버림, 훅 끊김·
중요 입력 유실 정지와 유실 전 동작 보존, 우리 표식·다른 프로그램 입력이 섞인 스트림.

각본은 가짜 훅 원천이 실제 훅 프로세스와 같은 번호 규칙(`event_id`·`crit_seq`·`batch_no`·누적
생략 개수)으로 흘린다. 고장 줄(`fault`)로 훅 종료·큐 넘침·묶음 잃음을 흉내 낸다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from helpers.recorder_rig import HOTKEYS, RecorderRig, steps_of

from kb_testing.proc import wait_until
from kb_testing.recorder_scripts import ACCOUNT_POINT, LOGIN_POINT, START_POINT, ScriptBuilder
from kookabug_daemon.client import DaemonClient
from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.recorder_lease import RecorderLease
from kookabug_platform.inputmark import KOOKABUG_INPUT_MARK

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

START = {"launch": {}, "hotkeys": HOTKEYS}
EMPTY = (60, 600)
"""게임 안 빈 자리 (장면을 바꾸지 않는 클릭)."""


def kinds(steps: list[dict[str, Any]]) -> list[str]:
    return [s["kind"] for s in steps if s["kind"] not in ("wait", "delay")]


def lease_free(rig: RecorderRig) -> bool:
    lease = RecorderLease(rig.root, environ=rig.env)
    try:
        lease.acquire()
    except RequestFailed:
        return False
    lease.release()
    return True


def wait_stopped(ui: DaemonClient) -> dict[str, Any]:
    state: dict[str, Any] = {}

    def stopped() -> bool:
        state.update(ui.call("recorder.state", {}))
        return state["state"] == "stopped"

    wait_until(stopped, timeout=30, interval=0.1)
    return state


def test_pause_ignores_events(tmp_path: Path) -> None:
    s = ScriptBuilder()
    s.at(500).click(START_POINT)
    s.at(1500).click(ACCOUNT_POINT)  # 일시정지 중 (게임에는 간다)
    s.at(2000).type("abc")
    s.at(3000).key("tab")  # 계속한 뒤
    s.wait(400).type("xy")
    s.wait(600).click(EMPTY)
    rig = RecorderRig.make(tmp_path, s.lines)
    with rig.daemon(speed=None) as d, d.client() as ui:
        ui.call("recorder.start", START)
        rig.advance(d, 1000)
        assert ui.call("recorder.pause", {})["state"] == "paused"
        rig.advance(d, 2800)
        assert ui.call("recorder.resume", {})["state"] == "recording"
        rig.advance(d, 6000)
        ui.call("recorder.stop", {})
        steps = steps_of(ui)
        # 일시정지 중의 계정 칸 클릭·글자 `abc`는 스텝이 아니다
        assert kinds(steps) == ["click", "key", "text", "click"], steps
        assert [s["text_len"] for s in steps if s["kind"] == "text"] == [2]
        assert lease_free(rig)
        ui.call("recorder.discard", {})


def test_hook_child_killed_stops_with_hook_lost_and_finalizes(tmp_path: Path) -> None:
    s = ScriptBuilder()
    s.at(500).click(START_POINT)
    s.at(1500).click(ACCOUNT_POINT)
    s.at(2000).type("qa_tester")
    s.wait(200).fault("hook_exit")
    s.wait(500).key("tab")  # 훅이 없으니 오지 않는다
    rig = RecorderRig.make(tmp_path, s.lines)
    with rig.daemon() as d, d.client() as ui:
        ui.call("recorder.start", START)
        state = wait_stopped(ui)
        assert state["stop_reason"] == "hook_lost"
        steps = steps_of(ui)
        assert kinds(steps) == ["click", "click", "text"], steps
        cut = steps[-1]
        assert "cut_by_stop" in cut["needs_review"] or cut["text_state"] != "ordinary"
        assert lease_free(rig)
        assert d.daemon.run_manager.recording_state() is None
        ui.call("recorder.discard", {})


def test_overflow_stops_and_keeps_actions_before_gap(tmp_path: Path) -> None:
    s = ScriptBuilder()
    s.at(500).click(START_POINT)
    s.at(1500).click(ACCOUNT_POINT)
    s.at(2000).type("qa")
    s.wait(300).fault("overflow", count=1)  # 다음 중요 이벤트(Tab down)를 잃는다
    s.wait(10).key("tab")
    s.wait(400).type("zz")
    s.wait(400).click(LOGIN_POINT)
    rig = RecorderRig.make(tmp_path, s.lines)
    with rig.daemon() as d, d.client() as ui:
        ui.call("recorder.start", START)
        state = wait_stopped(ui)
        assert state["stop_reason"] == "input_overflow"
        steps = steps_of(ui)
        # 유실 앞 동작은 남고(클릭 둘·계정 칸 글자), 빈틈 뒤 입력(Tab·글자·로그인 클릭)은 없다
        assert kinds(steps) == ["click", "click", "text"], steps
        assert steps[-1]["text_len"] == 2
        assert "cut_by_stop" in steps[-1]["needs_review"] or steps[-1]["text_state"] != "ordinary"
        assert lease_free(rig)
        ui.call("recorder.discard", {})


def mixed_script(*, lose_batch: bool) -> list[dict[str, Any]]:
    """사람 클릭·글자 사이에 우리 표식 입력(클릭·키)·다른 프로그램 입력·많은 이동을 섞는다."""
    marked = {"injected": True, "extra_info": KOOKABUG_INPUT_MARK}
    s = ScriptBuilder()
    s.at(500).click(START_POINT)
    s.at(900).click(EMPTY, **marked)  # 우리 SendInput: 훅 프로세스가 버린다
    s.at(1500).click(ACCOUNT_POINT)
    for i in range(200):  # 사람 이동 (8 ms 합치기)
        s.at(1600 + i * 2).move((300 + i, 500))
    s.at(2000).type("qa")
    s.wait(100).key("esc", **marked)
    s.wait(100).click(EMPTY, injected=True)  # 다른 프로그램 입력: daemon이 세고 버린다
    if lose_batch:
        s.wait(100).fault("batch_gap")
    s.wait(300).key("tab")
    s.wait(300).type("zz")
    s.wait(500).click(LOGIN_POINT)
    return s.lines


def test_mixed_stream_session(tmp_path: Path) -> None:
    rig = RecorderRig.make(tmp_path, mixed_script(lose_batch=False))
    with rig.daemon() as d, d.client() as ui:
        ui.call("recorder.start", START)
        wait_until(lambda: len(steps_of(ui)) >= 6, timeout=30, interval=0.1)
        state = ui.call("recorder.state", {})
        assert state["state"] == "recording"  # 표식 제외·이동 합치기는 유실이 아니다
        assert state["counts"]["ignored_injected"] == 2  # 다른 프로그램 클릭 down·up
        assert any(w["code"] == "injected_ignored" for w in state["warnings"])
        ui.call("recorder.stop", {})
        steps = steps_of(ui)
        assert kinds(steps) == ["click", "click", "text", "key", "text", "click"], steps
        assert ui.call("recorder.state", {})["stop_reason"] == "user"
        ui.call("recorder.discard", {})


def test_batch_lost_on_pipe_stops(tmp_path: Path) -> None:
    rig = RecorderRig.make(tmp_path, mixed_script(lose_batch=True))
    with rig.daemon() as d, d.client() as ui:
        ui.call("recorder.start", START)
        state = wait_stopped(ui)
        assert state["stop_reason"] == "input_overflow"
        steps = steps_of(ui)
        assert kinds(steps)[:3] == ["click", "click", "text"]
        assert "key" not in kinds(steps)  # 잃은 묶음 뒤 입력은 이어 붙이지 않는다
        assert lease_free(rig)
        ui.call("recorder.discard", {})
