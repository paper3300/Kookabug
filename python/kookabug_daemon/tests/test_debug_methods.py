"""디버거 메서드 (M3 계획 2.1·2.3, T3): 브레이크포인트 파일·밀어 넣기, 일시정지·재개·Step, 다시
시작(재시작 예약), 에이전트 거부, UI 실행만, UI 없이 멈춘 실행 자동 취소.

daemon은 같은 프로세스의 다른 스레드(`ThreadDaemon`), runner는 실제 프로세스, 플랫폼은 가짜다.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env, run_cli
from helpers.daemon_runs import GRACE, TEST, EventLog, RunRig
from helpers.graphs import GraphBuilder, write_json

from kb_testing.daemon import ThreadDaemon
from kb_testing.proc import wait_until
from kookabug_core.inputs.lease import STATE_DIR_ENV, read_lease_file
from kookabug_core.record import read_run, read_run_json
from kookabug_daemon.breakpoints import BREAKPOINTS_FILE
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.protocol import RequestFailed

pytestmark = [pytest.mark.process, pytest.mark.timeout(180)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-7"}
ATTENDED_AGENT = {**AGENT, "id": "agent-8", "attended": True}


# ---------------------------------------------------------------- 그래프·도우미


def delay_graph(first_ms: int = 10) -> GraphBuilder:
    """n_d1(first_ms) → n_d2 → n_d3 → 통과 (코어 노드만)."""
    return (
        GraphBuilder()
        .entry("n_d1")
        .node("n_d1", "core.flow.delay", inputs={"ms": first_ms}, next={"done": "n_d2"})
        .node("n_d2", "core.flow.delay", inputs={"ms": 10}, next={"done": "n_d3"})
        .node("n_d3", "core.flow.delay", inputs={"ms": 10}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def lease_graph() -> GraphBuilder:
    """키 하나(입력 임대권) → 긴 delay → 통과."""
    return (
        GraphBuilder()
        .entry("n_key")
        .node("n_key", "core.input.key", inputs={"keys": "a"}, next={"done": "n_d1"})
        .node("n_d1", "core.flow.delay", inputs={"ms": 30_000}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def bp(node: str, graph: str = TEST) -> dict[str, str]:
    return {"graph": graph, "node": node}


def allow_agent_runs(rig: RunRig) -> None:
    path = rig.root / ".kookabug" / "local.json"
    path.parent.mkdir(exist_ok=True)
    body = {"format": "kookabug.local/0", "permissions": {"toolsets": {"run": "allow"}}}
    path.write_text(json.dumps(body), encoding="utf-8")


def breakpoints_file(rig: RunRig) -> Any:
    return json.loads((rig.root / BREAKPOINTS_FILE).read_text(encoding="utf-8"))


def start(
    client: DaemonClient, watcher: DaemonClient | None = None, **params: Any
) -> tuple[dict[str, Any], EventLog]:
    """`client`가 시작하고 `watcher`(없으면 같은 연결)가 구독한다. 에이전트 연결은 기록 원문
    구독(`run.subscribe`)을 쓰지 못하므로(M5 3.5) 에이전트가 시작한 실행은 UI가 지켜본다."""
    started = client.call("run.start", {"path": TEST, **params})
    seer = watcher or client
    seer.call("run.subscribe", {"run_id": started["run_id"], "after_seq": 0})
    return started, EventLog(seer, started["run_id"])


def is_pause(node: str, nth: int = 1) -> Any:
    def match(log: EventLog) -> bool:
        found = [e for e in log.events if e["event"] == "debug.pause"]
        return len(found) >= nth and found[nth - 1]["node"] == node

    return match


def pauses(log: EventLog) -> list[dict[str, Any]]:
    return [e for e in log.events if e["event"] == "debug.pause"]


def wait_ended(client: DaemonClient, run_id: str, timeout: float = 60) -> dict[str, Any]:
    return wait_until(
        lambda: (s := client.call("run.status", {"run_id": run_id}))["state"] == "ended" and s,
        timeout=timeout,
        interval=0.1,
    )


def run_folders(rig: RunRig) -> list[Path]:
    runs = rig.root / "runs"
    return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() else []


class Gate:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def hold(self) -> None:
        self.entered.set()
        assert self.release.wait(60), "장벽이 풀리지 않았다"


def hold_cancel(d: ThreadDaemon, run_id: str) -> Gate:
    """다시 시작 ② 단계(옛 실행 취소)에 장벽: 재시작 예약을 쥔 채 선다."""
    gate = Gate()
    run = d.daemon.run_manager._runs[run_id]  # pyright: ignore[reportPrivateUsage]
    handle = run.handle
    assert handle is not None
    original = handle.cancel

    def blocked() -> Any:
        gate.hold()
        return original()

    handle.cancel = blocked  # type: ignore[method-assign]
    return gate


def paused_ui_run(
    rig: RunRig, client: DaemonClient, **params: Any
) -> tuple[dict[str, Any], EventLog]:
    """n_d1 브레이크포인트에서 멈춘 UI 실행."""
    client.call("debug.breakpoints.set", {"breakpoints": [bp("n_d1")]})
    started, log = start(client, **params)
    log.pump(is_pause("n_d1"))
    return started, log


# ---------------------------------------------------------------- 브레이크포인트 파일·밀어 넣기


def test_breakpoints_set_persists_and_pushes_to_active_ui_run(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, delay_graph(first_ms=1_500))
    with rig.daemon() as d, d.client() as ui, d.client() as other, d.client(AGENT) as agent:
        assert ui.call("debug.breakpoints.get", {}) == {"breakpoints": []}
        started, log = start(ui)
        log.pump(lambda lg: any(e.get("node") == "n_d1" for e in lg.events))
        # n_d1 실행 중에 바꾼다 → 파일에 원자적으로 쓰고, 진행 중인 UI 실행은 다음 경계부터
        result = ui.call(
            "debug.breakpoints.set",
            {"breakpoints": [bp("n_d2"), bp("n_d2"), bp("n_a", "x.graph.json")]},
        )
        expected = [bp("n_d2"), bp("n_a", "x.graph.json")]
        expected.sort(key=lambda b: (b["graph"], b["node"]))
        assert result == {"breakpoints": expected}
        assert breakpoints_file(rig) == {
            "format": "kookabug.breakpoints/0",
            "breakpoints": expected,
        }
        assert other.call("debug.breakpoints.get", {}) == {"breakpoints": expected}
        log.pump(is_pause("n_d2"))
        (pause,) = pauses(log)
        assert (pause["reason"], pause["where"]) == ("breakpoint", "boundary")

        # 다른 UI 연결은 알림을 받고, 바꾼 연결·에이전트 연결은 받지 않는다
        def changed_seen() -> list[dict[str, Any]]:
            return [
                m
                for m in list(other.notifications.queue)
                if m["method"] == "debug.breakpoints.changed"
            ]

        wait_until(lambda: bool(changed_seen()), timeout=10)
        assert [m["params"] for m in changed_seen()] == [{"breakpoints": expected}]
        assert not any(
            m["method"] == "debug.breakpoints.changed"
            for m in [*list(ui.notifications.queue), *log.others]
        )
        assert not any(
            m["method"] == "debug.breakpoints.changed" for m in list(agent.notifications.queue)
        )
        assert ui.call("run.resume", {"run_id": started["run_id"]}) == {"state": "running"}
        log.until_ended()
        assert log.ended is not None and log.ended["outcome"]["verdict"] == "pass"


def test_breakpoints_file_invalid_is_empty_and_rewritten(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, delay_graph())
    path = rig.root / BREAKPOINTS_FILE
    path.parent.mkdir(exist_ok=True)
    path.write_text('{"format": "kookabug.breakpoints/0", "breakpoints": [{"x": 1}]}', "utf-8")
    with rig.daemon() as d, d.client() as ui:
        assert ui.call("debug.breakpoints.get", {}) == {"breakpoints": []}
        # 형식이 틀린 파일은 실행을 막지 않는다
        started, log = start(ui)
        log.until_ended()
        assert pauses(log) == []
        ui.call("debug.breakpoints.set", {"breakpoints": [bp("n_d3")]})
        assert breakpoints_file(rig)["breakpoints"] == [bp("n_d3")]
        assert started["run_id"]


@pytest.mark.parametrize(
    "graph",
    ["./tests/t.graph.json", "tests//t.graph.json", "/tests/t.graph.json", "../t.graph.json"],
)
def test_breakpoints_set_rejects_unnormalized_graph_path(tmp_path: Path, graph: str) -> None:
    # T3 검수 Low: 어디서도 적중하지 않는 경로를 조용히 저장하지 않는다. `snapshot/` 폴더는 그대로
    rig = RunRig.make(tmp_path)
    with rig.daemon() as d, d.client() as ui:
        ui.check = False  # 클라이언트 쪽 형식 검사를 끄고 daemon이 거부하는지 본다
        with pytest.raises(DaemonError) as caught:
            ui.call("debug.breakpoints.set", {"breakpoints": [bp("n_a", graph)]})
        assert caught.value.code == -32602, caught.value
        assert not (rig.root / BREAKPOINTS_FILE).exists()
        kept = [bp("n_a", "snapshot/login.graph.json"), bp("n_b", ".hidden/x.graph.json")]
        assert ui.call("debug.breakpoints.set", {"breakpoints": kept}) == {
            "breakpoints": sorted(kept, key=lambda b: (b["graph"], b["node"]))
        }


def test_agent_run_ignores_breakpoints(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, delay_graph())
    allow_agent_runs(rig)
    with rig.daemon() as d, d.client() as ui, d.client(AGENT) as agent:
        ui.call("debug.breakpoints.set", {"breakpoints": [bp("n_d1"), bp("n_d2")]})
        started, log = start(agent, ui)
        log.until_ended()
        assert log.ended is not None and log.ended["outcome"]["verdict"] == "pass"
        assert pauses(log) == []
        run_json = read_run_json(Path(started["run_dir"]) / "run.json")
        assert run_json is not None and run_json["debug_intervened"] is False
        # 에이전트 실행에는 UI도 디버그 메서드를 쓸 수 없다
        with pytest.raises(DaemonError) as caught:
            ui.call("run.pause", {"run_id": started["run_id"]})
        assert caught.value.kind == "run_not_debuggable"


def test_ui_run_detected_by_connection_kind_not_principal_kind(tmp_path: Path) -> None:
    # 실제 UI hello의 주체는 kind "user"·id "ui:<번호>"다. 연결 종류로 UI 실행을 가린다.
    # 사람이 지켜보는(attended) 에이전트 연결도 UI가 아니다
    rig = RunRig.make(tmp_path, delay_graph())
    allow_agent_runs(rig)
    with rig.daemon() as d, d.client() as ui, d.client(ATTENDED_AGENT) as agent:
        assert ui.hello_result is not None and agent.hello_result is not None
        principal = ui.hello_result["principal"]
        assert principal["kind"] == "user" and principal["id"].startswith("ui:")
        assert agent.hello_result["principal"] == {
            "kind": "agent",
            "id": "agent-8",
            "attended": True,
        }
        ui.call("debug.breakpoints.set", {"breakpoints": [bp("n_d2")]})
        one, log = start(ui)
        log.pump(is_pause("n_d2"))
        ui.call("run.resume", {"run_id": one["run_id"]})
        log.until_ended()
        two, log2 = start(agent, ui)
        log2.until_ended()
        assert pauses(log2) == []
        manager = d.daemon.run_manager
        runs = manager._runs  # pyright: ignore[reportPrivateUsage]
        assert runs[one["run_id"]].ui is True
        assert runs[two["run_id"]].ui is False


def test_cli_run_ignores_breakpoints(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, delay_graph())
    write_json(
        rig.root,
        BREAKPOINTS_FILE,
        {"format": "kookabug.breakpoints/0", "breakpoints": [bp("n_d1"), bp("n_d2")]},
    )
    env = cli_env(tmp_path)
    done = run_cli(["run", TEST, "--json"], cwd=rig.root, env=env)
    assert done.returncode == 0, done.stderr
    (folder,) = run_folders(rig)
    view = read_run(folder)
    assert view.run_end is not None and view.run_end["verdict"] == "pass"
    assert [e for e in view.events if e["event"] == "debug.pause"] == []


# ---------------------------------------------------------------- 에이전트 거부


def test_agent_denied_all_debug_methods(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, delay_graph())
    allow_agent_runs(rig)
    with rig.daemon() as d, d.client() as ui, d.client(AGENT) as agent:
        started, log = paused_ui_run(rig, ui)
        run_id = started["run_id"]
        before = (rig.root / BREAKPOINTS_FILE).read_bytes()
        calls = {
            "debug.breakpoints.get": {},
            "debug.breakpoints.set": {"breakpoints": []},
            "run.pause": {"run_id": run_id},
            "run.resume": {"run_id": run_id, "mode": "step_over"},
            "run.restart": {"run_id": run_id},
        }
        for method, params in calls.items():
            with pytest.raises(DaemonError) as caught:
                agent.call(method, params)
            assert caught.value.kind == "permission_denied", method
        # 파일·실행 상태 그대로: 아직 멈춰 있고(재개·재시작 없음), 새 실행 폴더 없음
        assert (rig.root / BREAKPOINTS_FILE).read_bytes() == before
        log.quiet(0.5)
        assert [e["event"] for e in log.events].count("debug.resume") == 0
        assert len(run_folders(rig)) == 1
        assert d.daemon.runs.active_run() == run_id
        ui.call("run.cancel", {"run_id": run_id})
        log.until_ended()


# ---------------------------------------------------------------- 일시정지·재개·Step


def test_pause_resume_step_roundtrip_events(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, delay_graph(first_ms=3_000))
    with rig.daemon() as d, d.client() as ui:
        started, log = start(ui)
        run_id = started["run_id"]
        log.pump(lambda lg: any(e.get("node") == "n_d1" for e in lg.events))
        # 멈추지 않은 실행에 Step → not_paused (아무것도 바뀌지 않음)
        with pytest.raises(DaemonError) as caught:
            ui.call("run.resume", {"run_id": run_id, "mode": "step_over"})
        assert caught.value.kind == "not_paused" and caught.value.data["run_id"] == run_id
        assert ui.call("run.pause", {"run_id": run_id}) == {"state": "pausing"}
        log.pump(is_pause("n_d1"))
        assert pauses(log)[0]["where"] == "poll"
        assert ui.call("run.pause", {"run_id": run_id}) == {"state": "paused"}
        assert ui.call("run.resume", {"run_id": run_id, "mode": "step_over"}) == {
            "state": "running"
        }
        log.pump(is_pause("n_d2", 2))
        assert ui.call("run.resume", {"run_id": run_id, "mode": "step_into"}) == {
            "state": "running"
        }
        log.pump(is_pause("n_d3", 3))
        assert ui.call("run.resume", {"run_id": run_id}) == {"state": "running"}
        log.until_ended()
        assert log.ended is not None and log.ended["outcome"]["verdict"] == "pass"
        reasons = [(p["node"], p["reason"], p["where"]) for p in pauses(log)]
        assert reasons == [
            ("n_d1", "request", "poll"),
            ("n_d2", "step", "boundary"),
            ("n_d3", "step", "boundary"),
        ]
        modes = [e["mode"] for e in log.events if e["event"] == "debug.resume"]
        assert modes == ["step_over", "step_into", "continue"]
        # 끝난 실행: 재개는 not_paused, 일시정지는 run_not_found
        with pytest.raises(DaemonError) as caught:
            ui.call("run.resume", {"run_id": run_id})
        assert caught.value.kind == "not_paused"
        with pytest.raises(DaemonError) as caught:
            ui.call("run.pause", {"run_id": run_id})
        assert caught.value.kind == "run_not_found"
        with pytest.raises(DaemonError) as caught:
            ui.call("run.pause", {"run_id": "zzzzzzzz"})
        assert caught.value.kind == "run_not_found"
        assert d.daemon.runs.active_run() is None


# ---------------------------------------------------------------- 다시 시작


def write_profiles(rig: RunRig) -> None:
    write_json(
        rig.root,
        "kookabug.json",
        {
            "format": "kookabug.workspace/0",
            "run": GRACE,
            "profiles": {"qa": {"settings": {"from_profile": 1}}},
        },
    )


def test_restart_cancels_then_starts_same_args(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, delay_graph())
    write_profiles(rig)
    with rig.daemon() as d, d.client() as ui:
        params = {
            "profile": "qa",
            "settings": {"k": "v"},
            "deadline_ms": 45_000,
            "idempotency_key": "key-1",
        }
        old, _ = paused_ui_run(rig, ui, **params)
        new = ui.call("run.restart", {"run_id": old["run_id"]})
        assert new["run_id"] != old["run_id"] and new["graph"] == TEST
        # 옛 실행은 취소(사용자 취소)로 끝났다
        old_end = read_run(old["run_dir"]).run_end
        assert old_end is not None and old_end["cancel_reason"] == "cancelled"
        # 새 실행: 같은 경로·프로필·설정·기한, 브레이크포인트는 그 순간 파일 값
        new_log = EventLog(ui, new["run_id"])
        ui.call("run.subscribe", {"run_id": new["run_id"], "after_seq": 0})
        new_log.pump(is_pause("n_d1"))
        ui.call("run.resume", {"run_id": new["run_id"]})
        new_log.until_ended()
        old_json = read_run_json(Path(old["run_dir"]) / "run.json")
        new_json = read_run_json(Path(new["run_dir"]) / "run.json")
        assert old_json is not None and new_json is not None
        for key in ("profile", "deadline_ms", "settings"):
            assert new_json["conditions"][key] == old_json["conditions"][key], key
        assert new_json["conditions"]["profile"] == "qa"
        assert new_json["conditions"]["deadline_ms"] == 45_000
        # 중복 방지 키는 새 실행에 넘기지 않았다: 같은 키로 다시 시작하면 옛 실행을 돌려준다
        again = ui.call("run.start", {"path": TEST, **params})
        assert again["run_id"] == old["run_id"]
        manager = d.daemon.run_manager
        request = manager._runs[new["run_id"]].request  # pyright: ignore[reportPrivateUsage]
        assert request is not None and request.idempotency_key is None and request.ui


def test_restart_reservation_blocks_concurrent_start(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, delay_graph())
    with rig.daemon() as d, d.client() as ui, d.client() as other:
        old, _ = paused_ui_run(rig, ui)
        gate = hold_cancel(d, old["run_id"])
        pending = ui.request("run.restart", {"run_id": old["run_id"]})
        assert gate.entered.wait(30)
        try:
            # 재시작 취소 대기 중: 다른 시작·재시작은 run_busy, 일반 종료는 run_active
            with pytest.raises(DaemonError) as caught:
                other.call("run.start", {"path": TEST})
            assert caught.value.kind == "run_busy"
            assert caught.value.data["run_id"] == old["run_id"]
            with pytest.raises(DaemonError) as caught:
                other.call("daemon.shutdown", {})
            assert caught.value.kind == "run_active"
        finally:
            gate.release.set()
        new = pending.result(60)
        assert new["run_id"] != old["run_id"]
        assert d.daemon.runs.active_run() == new["run_id"]
        assert len(run_folders(rig)) == 2
        ui.call("run.cancel", {"run_id": new["run_id"]})
        wait_ended(ui, new["run_id"])


def test_concurrent_restarts_one_wins(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, delay_graph())
    with rig.daemon() as d, d.client() as ui, d.client() as other:
        old, _ = paused_ui_run(rig, ui)
        gate = hold_cancel(d, old["run_id"])
        first = ui.request("run.restart", {"run_id": old["run_id"]})
        assert gate.entered.wait(30)
        try:
            with pytest.raises(DaemonError) as caught:
                other.call("run.restart", {"run_id": old["run_id"]})
            assert caught.value.kind == "run_busy"
        finally:
            gate.release.set()
        new = first.result(60)
        assert len(run_folders(rig)) == 2
        ui.call("run.cancel", {"run_id": new["run_id"]})
        wait_ended(ui, new["run_id"])


def test_restart_during_shutdown_refused(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, delay_graph())
    with rig.daemon() as d, d.client() as ui:
        manager = d.daemon.run_manager
        old, _ = paused_ui_run(rig, ui)
        gate = hold_cancel(d, old["run_id"])
        result: dict[str, Any] = {}

        def restart() -> None:
            try:
                result["ok"] = manager.restart(old["run_id"])
            except RequestFailed as exc:
                result["error"] = exc

        thread = threading.Thread(target=restart)
        thread.start()
        assert gate.entered.wait(30)
        # 재시작 예약 중에 강제 종료가 정해진다 → 새 시작은 runner를 만들지 못하고 예약을 푼다
        assert manager.reserve_shutdown(force=True) is None
        gate.release.set()
        thread.join(60)
        error = result.get("error")
        assert isinstance(error, RequestFailed) and error.code == "shutting_down", result
        assert manager.active_run() is None
        assert len(run_folders(rig)) == 1
        # 종료가 정해진 뒤의 재시작은 ① 단계에서 거부
        with pytest.raises(RequestFailed) as caught:
            manager.restart(old["run_id"])
        assert caught.value.code == "shutting_down"


def test_restart_new_start_failure_releases_reservation(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, delay_graph())
    with rig.daemon() as d, d.client() as ui:
        old, _ = paused_ui_run(rig, ui)
        # 그래프를 깨뜨린다 → 새 시작의 사전 검증 실패
        broken = GraphBuilder().entry("n_x").node("n_x", "core.flow.delay", inputs={"ms": "x"})
        broken.write(rig.root, TEST)
        with pytest.raises(DaemonError) as caught:
            ui.call("run.restart", {"run_id": old["run_id"]})
        assert caught.value.kind == "validation_failed"
        # 옛 실행은 끝난 그대로, 예약은 풀렸다 → 다음 run.start 가능
        assert wait_ended(ui, old["run_id"])["state"] == "ended"
        assert d.daemon.runs.active_run() is None
        assert len(run_folders(rig)) == 1
        delay_graph().write(rig.root, TEST)
        ui.call("debug.breakpoints.set", {"breakpoints": []})
        again, log = start(ui)
        log.until_ended()
        assert log.ended is not None and log.ended["outcome"]["verdict"] == "pass"
        assert again["run_id"] != old["run_id"]


def test_restart_ended_run_allowed_only_if_tracked(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, delay_graph())
    with rig.daemon() as d, d.client() as ui:
        old, log = start(ui)
        log.until_ended()
        # 이 daemon이 기억하는 끝난 UI 실행: 취소 없이 새로 시작
        new = ui.call("run.restart", {"run_id": old["run_id"]})
        assert new["run_id"] != old["run_id"]
        wait_ended(ui, new["run_id"])
        assert d.daemon.runs.active_run() is None
        with pytest.raises(DaemonError) as caught:
            ui.call("run.restart", {"run_id": "zzzzzzzz"})
        assert caught.value.kind == "run_not_found"
    # 다른 daemon(이 실행을 기억하지 않음): 폴더가 있어도 run_not_found
    with rig.daemon() as d2, d2.client() as ui2:
        with pytest.raises(DaemonError) as caught:
            ui2.call("run.restart", {"run_id": old["run_id"]})
        assert caught.value.kind == "run_not_found"
        assert len(run_folders(rig)) == 2


def test_restart_agent_run_not_debuggable(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, delay_graph())
    allow_agent_runs(rig)
    with rig.daemon() as d, d.client() as ui, d.client(AGENT) as agent:
        started, log = start(agent, ui)
        log.until_ended()
        with pytest.raises(DaemonError) as caught:
            ui.call("run.restart", {"run_id": started["run_id"]})
        assert caught.value.kind == "run_not_debuggable"
        assert caught.value.data["run_id"] == started["run_id"]
        assert len(run_folders(rig)) == 1
        assert d.daemon.runs.active_run() is None


# ---------------------------------------------------------------- UI 없이 멈춘 실행


def test_paused_without_ui_connection_cancelled_after_timeout(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, lease_graph())
    with rig.daemon() as d:
        manager = d.daemon.run_manager
        manager.unattended_pause_s = 1.0
        manager.unattended_check_s = 0.1
        ui = d.client()
        watcher = d.client()
        ui.call("debug.breakpoints.set", {"breakpoints": [bp("n_d1")]})
        started, log = start(ui)
        log.pump(is_pause("n_d1"))
        ui.close()
        # UI 연결이 하나라도 있으면 기한을 넘겨도 취소하지 않는다
        time.sleep(2.0)
        assert manager.active_run() == started["run_id"]
        lease = read_lease_file(rig.env[STATE_DIR_ENV])
        assert lease is not None and lease["clean"] is False  # 멈춘 동안 임대권 유지
        watcher.close()
        began = time.monotonic()
        wait_until(lambda: manager.active_run() is None, timeout=30)
        # 기한(1초) + 실제 시간 마무리 유예 안에 끝났다
        assert time.monotonic() - began < 1.0 + GRACE["shutdown_grace_ms"] / 1000 + 3
    view = read_run(started["run_dir"])
    assert view.run_end is not None
    assert view.run_end["cancel_reason"] == "cancelled"
    assert view.run_end["debug_intervened"] is True
    lease = read_lease_file(rig.env[STATE_DIR_ENV])
    assert lease is not None and lease["clean"] is True
