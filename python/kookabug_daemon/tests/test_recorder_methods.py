"""daemon 녹화 메서드 (M4 계획 2.3·2.9, T8): 가짜 각본 → 세션 → 조각 → 그래프 → 실제 runner(가짜
플랫폼) 재생, 연결 소유권, 시작 되돌리기, 연결 끊김, 실행 거부, 권한, 두 단계 커밋.

가짜 원천: 예제 로그인 각본(`kb_testing.recorder_scripts`)을 가짜 훅 원천(실제 훅 프로세스와 같은
번호 규칙)으로 흘리고, 같은 시각에 가짜 사람이 가짜 게임 장면에 입력을 적용한다(부품 합성 프레임).
판정·이름은 실제 OCR이다.
"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder
from helpers.recorder_rig import (
    HOTKEYS,
    SECRET_KEY,
    RecorderRig,
    graph_from_fragment,
    run_graph,
    steps_of,
)
from helpers.run import tk
from helpers.runner import RunnerHarness

from kb_testing.proc import Spawned, wait_until
from kb_testing.recorder_scripts import ACCOUNT_POINT, ScriptBuilder, login_script
from kb_testing.sample_game import EXAMPLE_SECRET_ENV
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.methods.tools import RECORDER_METHODS
from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.recorder_lease import RecorderLease
from kookabug_daemon.recorder_sources import FakeRecording
from kookabug_daemon.recorder_store import recorder_cache_dir

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-7"}
LOBBY_TITLE = [412, 90, 200, 60]
"""로비 화면 "서버 선택" 제목 자리 (화면 확인 영역)."""
GRAPH = "tests/rec_login.graph.json"
SECRET_TEXT = "sample-pass-01"
"""예제 각본의 비밀번호 원문 (`EXAMPLE_SECRET_ENV` 값)."""
START = {"launch": {}, "hotkeys": HOTKEYS}


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """daemon 사전 검증은 daemon 프로세스 환경에서 비밀값을 찾는다 (runner는 rig 환경)."""
    for name, value in EXAMPLE_SECRET_ENV.items():
        monkeypatch.setenv(name, value)


def refused(client: DaemonClient, method: str, params: dict[str, Any] | None = None) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params or {})
    return caught.value


def wait_recorded(ui: DaemonClient, count: int = 6) -> None:
    wait_until(lambda: len(steps_of(ui)) >= count, timeout=30, interval=0.1)


def record_login(ui: DaemonClient) -> list[dict[str, Any]]:
    """게임 띄워서 녹화 → (각본이 다 흐름) → 로비 화면 확인 넣기 → 정지. 스텝 목록."""
    started = ui.call("recorder.start", START)
    assert started["state"] == "recording" and started["owned"]
    wait_recorded(ui)
    live = ui.call("recorder.frame", {"which": "live"})
    ui.call(
        "recorder.insert_check",
        {"kind": "visible", "frame_id": live["frame"]["frame_id"], "rect": LOBBY_TITLE},
    )
    stopped = ui.call("recorder.stop", {})
    assert stopped["state"] == "stopped" and stopped["stop_reason"] == "user"
    return steps_of(ui)


def choose_secret(ui: DaemonClient, steps: list[dict[str, Any]]) -> None:
    secret = next(s for s in steps if s.get("text_state") == "secret")
    ui.call("recorder.step.update", {"step": secret["step"], "patch": {"secret_key": SECRET_KEY}})


def lease_free(rig: RecorderRig) -> bool:
    lease = RecorderLease(rig.root, environ=rig.env)
    try:
        lease.acquire()
    except RequestFailed:
        return False
    lease.release()
    return True


def no_session_folders(rig: RecorderRig) -> bool:
    folder = recorder_cache_dir(rig.root)
    return not folder.is_dir() or not any(folder.iterdir())


# ---------------------------------------------------------------- 핵심 경로


@pytest.mark.usefixtures("secret_env")
def test_start_stop_commit_new_test_fragment(tmp_path: Path) -> None:
    """쉬었다 이어 친·Backspace 비밀번호 각본 → 구간 하나로 비밀값 → 키 고름 → 그래프(`$secret` 한
    번·`clear`) → 실제 runner 재생이 고른 비밀값으로 로비 도착(화면 확인 pass)."""
    rig = RecorderRig.make(tmp_path, login_script(split=True, backspace=True))
    with rig.daemon() as d, d.client() as ui:
        steps = record_login(ui)
        kinds = [s["kind"] for s in steps if s["kind"] not in ("wait", "delay")]
        assert kinds == ["click", "click", "text", "key", "text", "click", "check_visible"], steps
        texts = [s for s in steps if s["kind"] == "text"]
        assert texts[0]["text_state"] == "ordinary" and texts[0]["text"] == "qa_tester_01"
        assert texts[1]["text_state"] == "secret" and "text" not in texts[1]
        assert texts[1]["text_len"] == len("sample-pass-01")
        error = refused(ui, "recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        assert (error.kind, error.data["steps"]) == ("secret_unresolved", [texts[1]["step"]])
        choose_secret(ui, steps)
        prepared = ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        assert ui.call("recorder.state", {})["state"] == "committing"
        fragment = prepared["fragment"]
        types = [n["type"] for n in fragment["nodes"]]
        assert types[0] == "core.app.launch" and "core.test.pass" not in types
        assert types.count("core.input.type_text") == 2
        secret_nodes = [
            n for n in fragment["nodes"] if n["in"].get("text") == {"$secret": SECRET_KEY}
        ]
        assert len(secret_nodes) == 1 and secret_nodes[0]["in"]["clear"] is True
        assert types[-1] == "core.assert.visible"
        ended = run_graph(ui, rig.root, GRAPH, graph_from_fragment(fragment))
        assert ended["outcome"]["verdict"] == "pass", ended
        ui.call("recorder.commit_finish", {"token": prepared["token"], "graph_path": GRAPH})
        assert ui.call("recorder.state", {})["state"] == "committed"
        assert no_session_folders(rig)


# ---------------------------------------------------------------- 소유권·권한


def test_other_connection_cannot_read_update_commit_discard(tmp_path: Path) -> None:
    rig = RecorderRig.make(tmp_path)
    with rig.daemon() as d, d.client() as ui, d.client() as other:
        ui.call("recorder.start", START)
        wait_recorded(ui)
        step = steps_of(ui)[0]["step"]
        live = ui.call("recorder.frame", {"which": "live"})
        for method, params in (
            ("recorder.steps", {}),
            ("recorder.frame", {"which": "live"}),
            ("recorder.step.update", {"step": step, "patch": {"keep": True}}),
            (
                "recorder.insert_check",
                {"kind": "visible", "frame_id": live["frame"]["frame_id"], "rect": LOBBY_TITLE},
            ),
            ("recorder.pause", {}),
            ("recorder.stop", {}),
            ("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH}),
            ("recorder.commit_finish", {"token": "x" * 22, "graph_path": GRAPH}),
            ("recorder.commit_abort", {"token": "x" * 22}),
            ("recorder.discard", {}),
            ("secrets.create", {"key": "a.b", "from_step": step}),
        ):
            error = refused(other, method, params)
            assert error.kind == "not_owner", method
        assert refused(other, "recorder.start", START).kind == "recorder_state_invalid"
        seen = other.call("recorder.state", {})
        assert seen["owned"] is False and seen["state"] == "recording"
        assert set(seen) <= {"owned", "state", "started_at", "elapsed_ms"}
        mine = ui.call("recorder.state", {})
        assert mine["owned"] and mine["window"]["title"] == "SampleRPG"
        ui.call("recorder.discard", {})


VALID_PARAMS: dict[str, dict[str, Any]] = {
    "recorder.start": START,
    "recorder.step.update": {"step": "rs1", "patch": {"keep": True}},
    "recorder.frame": {"which": "live"},
    "recorder.insert_check": {"kind": "visible", "frame_id": "f_1", "rect": LOBBY_TITLE},
    "recorder.commit_prepare": {"mode": "new_test", "graph_path": GRAPH},
    "recorder.commit_finish": {"token": "x" * 22, "graph_path": GRAPH},
    "recorder.commit_abort": {"token": "x" * 22},
    "recorder.target.materialize": {"step": "rs1"},
    "secrets.create": {"key": "a.b", "from_step": "rs1"},
    "target.read_text": {"frame_id": "f_1", "rect": LOBBY_TITLE},
}


def test_methods_ui_only_agent_denied(tmp_path: Path) -> None:
    rig = RecorderRig.make(tmp_path)
    with rig.daemon() as d, d.client(AGENT) as agent, d.client() as ui:
        ui.call("recorder.start", START)
        for method in sorted(RECORDER_METHODS - {"target.read_text"}):  # 처리기는 B4(T11)
            error = refused(agent, method, VALID_PARAMS.get(method, {}))
            assert error.kind == "permission_denied", method
        # 에이전트는 녹화 상태도 못 본다 — 사람의 녹화는 그대로
        assert ui.call("recorder.state", {})["state"] == "recording"
        ui.call("recorder.discard", {})


# ---------------------------------------------------------------- 시작·끊김


@pytest.mark.parametrize("step", ["lease", "window", "frames", "hook"])
def test_start_rolls_back_on_each_failure_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    def fail(*_: Any, **__: Any) -> None:
        raise RequestFailed("hook_failed" if step == "hook" else "capture_failed", f"주입: {step}")

    owner: type = {"lease": RecorderLease}.get(step, FakeRecording)
    name = {"lease": "acquire", "window": "__init__", "frames": "start_frames"}.get(
        step, "start_hook"
    )
    monkeypatch.setattr(owner, name, fail)
    rig = RecorderRig.make(tmp_path)
    with rig.daemon() as d, d.client() as ui:
        assert refused(ui, "recorder.start", START).kind in ("hook_failed", "capture_failed")
        assert ui.call("recorder.state", {}) == {"owned": False, "state": "idle"}
        assert d.daemon.run_manager.recording_state() is None  # 실행 거부 예약이 풀렸다
        assert no_session_folders(rig)
        assert d.daemon.recorder_secrets is None
        monkeypatch.undo()
        assert lease_free(rig)
    with rig.daemon() as d, d.client() as ui:  # 다시 시작할 수 있다
        assert ui.call("recorder.start", START)["state"] == "recording"
        ui.call("recorder.discard", {})


def test_disconnect_discards_session_and_releases_lease(tmp_path: Path) -> None:
    rig = RecorderRig.make(tmp_path)
    with rig.daemon() as d:
        ui = d.client()
        ui.call("recorder.start", START)
        wait_recorded(ui)
        assert not lease_free(rig)
        ui.close()
        session = d.daemon.recorder.session
        assert session is not None
        wait_until(lambda: session.state == "discarded", timeout=20)
        assert lease_free(rig)
        assert d.daemon.run_manager.recording_state() is None
        assert no_session_folders(rig)
        assert session.pipeline is not None and session.pipeline.texts.wiped
        with d.client() as again:
            assert again.call("recorder.state", {})["state"] == "discarded"
            assert again.call("recorder.start", START)["state"] == "recording"


def test_connection_closed_during_starting_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = threading.Event(), threading.Event()
    original = FakeRecording.start_frames

    def slow(self: FakeRecording) -> None:
        entered.set()
        release.wait(20)
        original(self)

    monkeypatch.setattr(FakeRecording, "start_frames", slow)
    rig = RecorderRig.make(tmp_path)
    with rig.daemon() as d:
        ui = d.client()
        ui.request("recorder.start", START)
        assert entered.wait(20)
        assert d.daemon.run_manager.recording_state() == "starting"
        ui.close()
        wait_until(
            lambda: d.daemon.recorder.session is not None and d.daemon.recorder.session.s.cancelled,
            timeout=20,
        )
        release.set()
        wait_until(lambda: d.daemon.recorder.session is None, timeout=20)
        assert d.daemon.run_manager.recording_state() is None
        assert lease_free(rig)
        assert no_session_folders(rig)


# ---------------------------------------------------------------- 실행 거부·임대권


def test_runs_rejected_while_recording_and_lease_released_on_stop(
    tmp_path: Path, spawned: Spawned
) -> None:
    rig = RecorderRig.make(tmp_path)
    graph = (
        tk()
        .entry("n_key")
        .node("n_key", "testkit.input.hold", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    plain = (
        GraphBuilder()
        .entry("n_log")
        .node("n_log", "core.log.message", inputs={"text": "하나"}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    with rig.daemon() as d, d.client() as ui:
        plain.write(rig.root, "tests/plain.graph.json")
        ui.call("recorder.start", START)
        wait_recorded(ui)
        error = refused(ui, "run.start", {"path": "tests/plain.graph.json"})
        assert (error.kind, error.data["state"]) == ("recording_active", "recording")
        ui.call("recorder.pause", {})
        error = refused(ui, "run.start", {"path": "tests/plain.graph.json"})
        assert (error.kind, error.data["state"]) == ("recording_active", "paused")
        assert not lease_free(rig)  # 일시정지 중에도 쥔다
        # 다른 runner(같은 임대권 이름): 임대권에서 input_lease_busy
        h = RunnerHarness.make(
            tmp_path / "other",
            graph,
            lease_name=rig.env["KOOKABUG_INPUT_LEASE_NAME"],
            state_dir=Path(rig.env["KOOKABUG_STATE_DIR"]),
        ).start(spawned)
        done = h.finish()
        assert done.run_end is not None and done.run_end["code"] == "input_lease_busy"
        assert "recorder" in done.run_end["reason"]
        ui.call("recorder.resume", {})
        ui.call("recorder.stop", {})
        assert lease_free(rig)
        assert d.daemon.run_manager.recording_state() is None
        ui.call("recorder.discard", {})


# ---------------------------------------------------------------- 두 단계 커밋


def test_coordinate_conversion_clears_missing_target(tmp_path: Path) -> None:
    """비밀 칸을 다시 눌러 target 없는 클릭 → 좌표 클릭으로 바꾸면 target 없이 커밋된다 (B3 검수
    M1, plan 2.9 "이미지 클릭 ↔ 좌표 클릭")."""
    s = ScriptBuilder(scene="login")
    s.at(500).click(ACCOUNT_POINT)
    s.at(1000).type("vaultcode42")
    s.at(3500).key("tab")
    s.at(5000).click(ACCOUNT_POINT)
    s.at(6000).mark("second_click")
    rig = RecorderRig.make(tmp_path, s.lines)
    with rig.daemon(speed=None) as d, d.client() as ui:
        ui.call("recorder.start", START)
        rig.advance(d, 4500)
        text = next(s for s in steps_of(ui) if s["kind"] == "text")
        patch = {"text_state": "secret", "secret_key": "review.test"}
        ui.call("recorder.step.update", {"step": text["step"], "patch": patch})
        rig.advance(d, 6000)
        ui.call("recorder.stop", {})
        step = [s for s in steps_of(ui) if s["kind"] == "click"][-1]
        assert step["target"]["source"] == "none", step
        params = {"mode": "new_test", "graph_path": "tests/coordinate.graph.json"}
        assert refused(ui, "recorder.commit_prepare", params).kind == "target_missing"
        ui.call(
            "recorder.step.update",
            {"step": step["step"], "patch": {"node_type": "core.input.click"}},
        )
        prepared = ui.call("recorder.commit_prepare", params)
        clicks = [n for n in prepared["fragment"]["nodes"] if n["type"] == "core.input.click"]
        assert clicks and clicks[0]["in"]["point"] == list(ACCOUNT_POINT)


def drafts_rig(tmp_path: Path) -> RecorderRig:
    """워크스페이스 target을 지운 사본: 모든 클릭이 새 초안 (커밋이 target 파일을 쓴다)."""
    rig = RecorderRig.make(tmp_path)
    shutil.rmtree(rig.root / "targets")
    shutil.rmtree(rig.root / "subgraphs")
    shutil.rmtree(rig.root / "tests")
    return rig


def written_targets(rig: RecorderRig) -> list[str]:
    base = rig.root / "targets" / "rec"
    return sorted(p.relative_to(rig.root).as_posix() for p in base.rglob("*.target.json"))


def test_commit_two_phase_abort_retry_other_name_reuses_targets(tmp_path: Path) -> None:
    rig = drafts_rig(tmp_path)
    with rig.daemon() as d, d.client() as ui:
        steps = record_login(ui)
        choose_secret(ui, steps)
        params = {"mode": "new_test", "graph_path": GRAPH}
        first = ui.call("recorder.commit_prepare", params)
        # 응답을 잃어 다시 부름: 같은 조각·토큰
        assert ui.call("recorder.commit_prepare", params) == first
        paths = sorted(t["path"] for t in first["targets"])
        assert paths == written_targets(rig) and len(paths) >= 3
        assert all(not t["reused"] for t in first["targets"])
        before = {p: (rig.root / p).read_bytes() for p in paths}
        # 렌더러가 같은 이름 그래프를 저장하지 못함 → 중단 → 다른 이름으로 (재녹화 없음)
        ui.call("recorder.commit_abort", {"token": first["token"]})
        assert ui.call("recorder.state", {})["state"] == "stopped"
        assert (
            refused(
                ui, "recorder.commit_finish", {"token": first["token"], "graph_path": GRAPH}
            ).kind
            == "recorder_state_invalid"
        )
        other = ui.call(
            "recorder.commit_prepare", {"mode": "new_test", "graph_path": "tests/other.graph.json"}
        )
        assert sorted(t["path"] for t in other["targets"]) == paths  # 써진 target 재사용
        assert written_targets(rig) == paths
        assert {p: (rig.root / p).read_bytes() for p in paths} == before
        ui.call(
            "recorder.commit_finish",
            {"token": other["token"], "graph_path": "tests/other.graph.json"},
        )


def test_second_target_write_failure_then_retry_writes_rest_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = drafts_rig(tmp_path)
    with rig.daemon() as d, d.client() as ui:
        steps = record_login(ui)
        choose_secret(ui, steps)
        store = d.daemon.targets
        original = store.save
        calls: list[str] = []

        def flaky(where: Any, *args: Any) -> Any:
            calls.append(where.rel)
            if len(calls) == 2:
                raise RequestFailed("io_error", "주입: 디스크", message="디스크")
            return original(where, *args)

        monkeypatch.setattr(store, "save", flaky)
        params = {"mode": "new_test", "graph_path": GRAPH}
        assert refused(ui, "recorder.commit_prepare", params).kind == "io_error"
        assert ui.call("recorder.state", {})["state"] == "stopped"
        assert written_targets(rig) == [calls[0]]
        first_bytes = (rig.root / calls[0]).read_bytes()
        done = ui.call("recorder.commit_prepare", params)
        assert calls.count(calls[0]) == 1  # 첫 target은 다시 쓰지 않았다
        assert sorted(t["path"] for t in done["targets"]) == written_targets(rig)
        # exists로 새 이름(`<이름>_2`)을 만들지 않았다: 파일 수 = 조각이 쓰는 target 수
        assert len(written_targets(rig)) == len(done["targets"])
        assert (rig.root / calls[0]).read_bytes() == first_bytes


def test_disconnect_during_committing_leaves_written_targets(tmp_path: Path) -> None:
    rig = drafts_rig(tmp_path)
    with rig.daemon() as d:
        ui = d.client()
        steps = record_login(ui)
        choose_secret(ui, steps)
        prepared = ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        paths = sorted(t["path"] for t in prepared["targets"])
        ui.close()
        session = d.daemon.recorder.session
        assert session is not None
        wait_until(lambda: session.state == "discarded", timeout=20)
        assert written_targets(rig) == paths  # 써진 target은 유효한 파일로 남는다
        assert no_session_folders(rig)


# ---------------------------------------------------------------- 미리 쓰기·값 확인 기댓값


def test_materialize_writes_one_draft_and_commit_does_not_rewrite(tmp_path: Path) -> None:
    """REC 탭 "찾기 대상 탭으로 열기": 초안 하나만 지금 파일로, 스텝은 그 파일을 가리키고 커밋은
    다시 쓰지 않는다. 소유 연결만."""
    rig = drafts_rig(tmp_path)
    with rig.daemon() as d, d.client() as ui, d.client() as other:
        steps = record_login(ui)
        click = next(s for s in steps if s["kind"] == "click")
        assert click["target"]["source"] == "draft"
        assert refused(other, "recorder.target.materialize", {"step": click["step"]}).kind == (
            "not_owner"
        )
        done = ui.call("recorder.target.materialize", {"step": click["step"]})
        rel = done["path"]
        assert rel.startswith("targets/rec/") and written_targets(rig) == [rel]
        first_bytes = (rig.root / rel).read_bytes()
        after = next(s for s in steps_of(ui) if s["step"] == click["step"])
        assert after["target"] == {"source": "file", "path": rel, "reused": False}
        # 초안이 이미 파일이 됨: 다시 부르면 초안이 없다
        error = refused(ui, "recorder.target.materialize", {"step": click["step"]})
        assert error.kind == "target_missing"
        choose_secret(ui, steps_of(ui))
        prepared = ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        paths = [t["path"] for t in prepared["targets"]]
        assert paths.count(rel) == 1
        # 미리 쓴 파일은 그대로, 같은 초안을 다른 이름으로 다시 쓰지 않았다
        assert (rig.root / rel).read_bytes() == first_bytes
        assert len(written_targets(rig)) == len(set(paths))


def test_check_text_equals_patch_and_secret_text_rejected(tmp_path: Path) -> None:
    rig = RecorderRig.make(tmp_path)
    with rig.daemon() as d, d.client() as ui:
        ui.call("recorder.start", START)
        wait_recorded(ui)
        live = ui.call("recorder.frame", {"which": "live"})
        inserted = ui.call(
            "recorder.insert_check",
            {"kind": "text", "frame_id": live["frame"]["frame_id"], "rect": LOBBY_TITLE},
        )["step"]
        assert inserted["kind"] == "check_text" and isinstance(inserted["equals"], str)
        sid = inserted["step"]
        updated = ui.call("recorder.step.update", {"step": sid, "patch": {"equals": "서버 고르기"}})
        assert updated["step"]["equals"] == "서버 고르기"
        # 비밀번호 원문을 담은 기댓값은 거부하고 원문을 오류에 싣지 않는다
        error = refused(
            ui, "recorder.step.update", {"step": sid, "patch": {"equals": "x sample-pass-01 y"}}
        )
        assert error.kind == "secret_region_overlap"
        assert "sample-pass-01" not in str(error) and "sample-pass-01" not in str(error.data)
        assert next(s for s in steps_of(ui) if s["step"] == sid)["equals"] == "서버 고르기"
        click = next(s for s in steps_of(ui) if s["kind"] == "click")
        assert refused(
            ui, "recorder.step.update", {"step": click["step"], "patch": {"equals": "a"}}
        ).kind == ("recorder_state_invalid")
        ui.call("recorder.stop", {})
        choose_secret(ui, steps_of(ui))
        fragment = ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})[
            "fragment"
        ]
        texts = [n["in"]["equals"] for n in fragment["nodes"] if n["type"] == "core.assert.text"]
        assert texts == ["서버 고르기"]


def _assert_check_equals_never_leaks(
    rig: RecorderRig, d: Any, ui: DaemonClient, frame_id: str, rect: list[int], raw: str
) -> None:
    """새 값 확인 스텝의 OCR 기댓값이 비밀값 원문을 담을 때 세 경로 — `insert_check` 응답,
    `recorder.changed` 뒤 `recorder.steps`, 세션 `steps.json` — 어디에도 원문이 없다 (B5 검수 2차
    High). 스텝은 기댓값을 비우고 `secret_overlap`으로 버린다."""
    result = ui.call("recorder.insert_check", {"kind": "text", "frame_id": frame_id, "rect": rect})
    step = result["step"]
    assert raw not in json.dumps(result, ensure_ascii=False), "insert_check 응답에 원문"
    assert step["kind"] == "check_text" and step["equals"] == ""
    assert "secret_overlap" in step["needs_review"]
    session = d.daemon.recorder.session
    session.changed()
    listed = steps_of(ui)
    assert raw not in json.dumps(listed, ensure_ascii=False), "recorder.steps에 원문"
    stored = session.store.folder / "steps.json"
    wait_until(lambda: step["step"] in stored.read_text(encoding="utf-8-sig"), timeout=10)
    assert raw not in stored.read_text(encoding="utf-8-sig"), "steps.json에 원문"
    # 원문 없는 커밋 거부 (기댓값을 버린 값 확인)
    choose_secret(ui, steps_of(ui))
    error = refused(ui, "recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
    assert error.kind == "secret_region_overlap" and step["step"] in error.data["steps"]
    assert raw not in str(error) and raw not in str(error.data)


@pytest.mark.usefixtures("secret_env")
def test_new_check_text_equals_with_secret_ocr_not_exposed(tmp_path: Path) -> None:
    """반례 1: 안전한 영역의 OCR이 이미 알려진 비밀번호(`sample-pass-01`)를 읽은 경우."""
    rig = RecorderRig.make(tmp_path, login_script())
    with rig.daemon(speed=None) as d, d.client() as ui:
        ui.call("recorder.start", START)
        rig.advance(d, 20000)
        frame = ui.call("recorder.frame", {"which": "live"})["frame"]["frame_id"]
        ui.call("recorder.stop", {})
        assert any(s.get("text_state") == "secret" for s in steps_of(ui))
        session = d.daemon.recorder.session
        assert session is not None and session.pipeline is not None
        session.pipeline.read_text = lambda image, rect: f"안내 {SECRET_TEXT}"
        _assert_check_equals_never_leaks(rig, d, ui, frame, LOBBY_TITLE, SECRET_TEXT)


@pytest.mark.timeout(180)
def test_new_check_text_equals_real_ocr_secret_elsewhere_not_exposed(tmp_path: Path) -> None:
    """반례 2 (실제 OCR): 비밀번호 `Enter`가 화면 아래 안내문 "Enter: 로그인"에도 보인다."""
    script = ScriptBuilder(scene="login")
    script.at(500).click(ACCOUNT_POINT)
    script.at(1000).type("reviewuser")
    script.at(2800).key("tab")
    script.at(3500).type("Enter")
    script.at(5000).key("tab")
    script.at(6000).mark("done")
    rig = RecorderRig.make(tmp_path, script.lines)
    with rig.daemon(speed=None) as d, d.client() as ui:
        ui.call("recorder.start", START)
        rig.advance(d, 6000)
        frame = ui.call("recorder.frame", {"which": "live"})["frame"]["frame_id"]
        ui.call("recorder.stop", {})
        assert any(s.get("text_state") == "secret" for s in steps_of(ui))
        _assert_check_equals_never_leaks(rig, d, ui, frame, [300, 570, 430, 45], "Enter")
