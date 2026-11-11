"""작업 종료 감독 (M8 9장 R8, 3.9 예산) — 엄격: 입력 안전·Agent 권한.

부모 유실·`job.finish`·`job.end`·기한·heartbeat 유실은 같은 멱등 종료 경로를 지난다: 토큰 폐기 →
실행·채택 검증 취소 → 감독자 입력 복구 완료 → 보고. 유실된 소유자는 control allow를 유지하지 못한다.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers.adopt_rig import CASE, TARGET, TEST, FakeVerifier, adoptions, case_doc, setup
from helpers.graphs import GraphBuilder

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import copy_example_workspace
from kookabug_core.agent_job import report as reports
from kookabug_daemon.adopt import CANCELLED, Adopter, JobAdopts, RunVerifier, VerifyOutcome
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.jobs import JobRegistry
from kookabug_daemon.protocol import RequestFailed

SLOW = "tests/slow.graph.json"


def agent(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "agent",
        "name": "mcp",
        "version": "0",
        "id": job["agent_id"],
        "attended": False,
        "job_token": job["token"],
    }


def set_preset(ws: Path, preset: str) -> None:
    local = ws / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["permissions"] = {"preset": preset}
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = copy_example_workspace(tmp_path)
    set_preset(root, "curator")
    slow = (
        GraphBuilder()
        .entry("n_wait")
        .node("n_wait", "core.flow.delay", inputs={"ms": 120_000}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
        .build()
    )
    (root / SLOW).write_text(json.dumps(slow), encoding="utf-8")
    return root


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws, platform_fake=ws / "fake-platform.json") as d:
        yield d


def start_slow(conn: DaemonClient, key: str = "slow") -> str:
    run_id = str(conn.call("run.start", {"path": SLOW, "idempotency_key": key})["run_id"])
    deadline = time.monotonic() + 120
    while conn.call("run.status", {"run_id": run_id})["state"] != "running":
        assert time.monotonic() < deadline
        time.sleep(0.2)
    return run_id


def status(d: ThreadDaemon, run_id: str) -> dict[str, Any]:
    with d.client() as ui:
        return ui.call("run.status", {"run_id": run_id})


def cancelled_run(status: dict[str, Any]) -> bool:
    """취소로 끝난 실행 (판정 error, 코드 cancelled — runner 마무리까지)."""
    run_json = json.loads((Path(status["run_dir"]) / "run.json").read_text("utf-8"))
    return status["outcome"]["verdict"] == "error" and run_json["code"] == "cancelled"


def wait_job_state(d: ThreadDaemon, job: str, state: str, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while True:
        live = d.daemon.jobs.get(job)
        if live is not None and live.state == state and live.ended.is_set():
            return
        assert time.monotonic() < deadline, live and live.state
        time.sleep(0.1)


def refused(conn: DaemonClient, method: str, params: dict[str, Any] | None = None) -> str:
    with pytest.raises(DaemonError) as caught:
        conn.call(method, params or {}, timeout=60)
    return str(caught.value.kind)


@pytest.mark.process
@pytest.mark.timeout(600)
def test_finish_revokes_token_and_drains_runs(ws: Path, daemon: ThreadDaemon) -> None:
    job = daemon.begin_job({"playbook": "triage", "budget": {"minutes": 60, "runs": 5}})
    with daemon.client(agent(job)) as conn:
        conn.call("agent.toolsets.enable", {"toolsets": ["run"]})
        run_id = start_slow(conn)
        with daemon.client() as ui:
            ended = ui.call("job.finish", {"job": job["job"], "state": "done"}, timeout=300)
            # 같은 종료 경로를 다시 지나도 첫 결과 (멱등)
            again = ui.call("job.end", {"job": job["job"], "reason": "cancelled"}, timeout=300)
        assert ended["state"] == "done" and run_id in ended["cancelled"]
        assert ended["settled"] is True
        assert again == ended
        # 토큰은 begin 응답에만 있다: 종료 결과·작업 목록·알림(job.changed·job.budget)에 없다
        with daemon.client() as ui:
            listed = ui.call("jobs.list")
        assert any(j["job"] == job["job"] for j in listed["jobs"])  # 양성 대조
        notes: list[Any] = []
        owner: DaemonClient = job["owner"]
        while not owner.notifications.empty():
            notes.append(owner.notifications.get_nowait())
        assert any(n["method"] == "job.changed" for n in notes)  # 양성 대조
        for text in (json.dumps(ended), json.dumps(listed), json.dumps(notes)):
            assert job["token"] not in text
        # 토큰 먼저 폐기 → 그 뒤 이 연결의 모든 요청 거부
        assert refused(conn, "workspace.info") == "job_token_invalid"
    # 실행은 취소되고 감독자 마무리(입력 복구)까지 끝났다
    finished = status(daemon, run_id)
    assert finished["state"] == "ended" and cancelled_run(finished)
    assert daemon.daemon.run_manager.active_run() is None
    stored = reports.read_report(ws, job["job"])
    assert stored is not None and stored["state"] == "done"
    assert stored["budget"]["runs"] == [1, 5]  # 실행 하나를 예산에서 썼다
    assert (ws / ended["report"]).is_file()


@pytest.mark.process
@pytest.mark.timeout(600)
def test_job_parent_killed_cancels_daemon_runs(ws: Path, daemon: ThreadDaemon) -> None:
    """소유 연결이 끊기면(agent-job 유실) 같은 종료 경로로 그 작업의 daemon 실행을 끝낸다."""
    owner = daemon.client()
    job = owner.call("job.begin", {"playbook": "triage"})
    with daemon.client(agent(job)) as conn:
        conn.call("agent.toolsets.enable", {"toolsets": ["run"]})
        run_id = start_slow(conn)
        # 양성 대조: 소유자가 살아 있는 동안 실행은 계속 돈다
        time.sleep(1.0)
        assert status(daemon, run_id)["state"] == "running"
        owner.close()  # 부모가 죽었다 (연결 끊김)
        wait_job_state(daemon, job["job"], "interrupted")
        assert refused(conn, "workspace.info") == "job_token_invalid"
    finished = status(daemon, run_id)
    assert cancelled_run(finished)
    assert daemon.daemon.run_manager.active_run() is None
    stored = reports.read_report(ws, job["job"])
    assert stored is not None and stored["state"] == "interrupted"


@pytest.mark.process
@pytest.mark.timeout(300)
@pytest.mark.parametrize("loss", ["disconnect", "heartbeat"])
def test_lost_owner_cannot_keep_control_allow(ws: Path, loss: str) -> None:
    with ThreadDaemon(ws, job_heartbeat_s=0.3) as d:
        owner = d.client()
        job = owner.call("job.begin", {"playbook": "triage"})
        with d.client(agent(job)) as conn:
            # 양성 대조: 작업 안 curator는 control allow (R0)
            tools = {t["tool"]: t["final"] for t in conn.call("permissions.get")["tools"]}
            assert tools["kb_input_click"] == "allow"
            if loss == "disconnect":
                owner.close()
            else:
                # 소유 연결은 살아 있지만 heartbeat가 없다 (멈춘 agent-job): 3번 놓치면 유실
                time.sleep(0.2)
                assert d.daemon.jobs.get(job["job"]).state == "running"  # type: ignore[union-attr]
            wait_job_state(d, job["job"], "interrupted", timeout=30)
            assert refused(conn, "permissions.get") == "job_token_invalid"
            assert refused(conn, "control.click", {"window": "x", "point": [1, 1]}) == (
                "job_token_invalid"
            )
        owner.close()
        # 끝난 작업에는 heartbeat도 받지 않는다
        with d.client() as ui:
            assert refused(ui, "job.heartbeat", {"job": job["job"]}) == "permission_denied"


@pytest.mark.process
@pytest.mark.timeout(300)
def test_input_busy_prep_failed_in_daemon(ws: Path, daemon: ThreadDaemon) -> None:
    reservation = daemon.daemon.run_manager.reserve_recording()
    try:
        with daemon.client() as ui:
            begun = ui.call("job.begin", {"playbook": "triage"})
    finally:
        reservation.release()
    assert begun["state"] == "prep_failed" and begun["reason"] == "recording"
    assert "token" not in begun
    stored = reports.read_report(ws, begun["job"])
    assert stored is not None and stored["state"] == "prep_failed"
    assert [i["kind"] for g in stored["groups"] for i in g["items"]] == ["prep_failed"]
    # 양성 대조: 녹화가 없으면 토큰을 준다
    job = daemon.begin_job({"playbook": "triage"})
    assert job["state"] == "running" and job["token"]


@pytest.mark.process
@pytest.mark.timeout(300)
def test_control_start_refused_after_end_path_began(ws: Path, daemon: ThreadDaemon) -> None:
    """종료 경로가 시작된 작업은 예산을 쓰지 않는 시작(제어 실행)도 시작 잠금 안에서 막힌다 —
    게이트를 지난 요청이 종료 경로의 실행 취소 뒤에 끼어 실행을 남기지 못한다."""
    from kookabug_core.permissions import Decision, Principal

    graph = GraphBuilder().entry("n_pass").node("n_pass", "core.test.pass").build()
    allow = Decision("allow", "allow", None, "test", "human")
    manager = daemon.daemon.run_manager
    live = daemon.begin_job({"playbook": "triage"})
    principal = Principal("agent", live["agent_id"], attended=False, job=live["job"])
    # 양성 대조: 살아 있는 작업이면 시작된다
    run_id = manager.start_internal(principal, graph, allow)
    assert manager.wait_outcome(run_id, 120) is not None
    job = daemon.daemon.jobs.get(live["job"])
    assert job is not None and daemon.daemon.jobs.start_ending(job)
    with pytest.raises(RequestFailed) as caught:
        manager.start_internal(principal, graph, allow)
    assert caught.value.code == "job_token_invalid"
    assert manager.active_run() is None


@pytest.mark.process
@pytest.mark.timeout(300)
def test_job_basis_is_default_for_job_runs(ws: Path, daemon: ThreadDaemon) -> None:
    """`agent-job --basis team`이면 그 작업 연결의 실행 기본 기준이 team이다 (없으면 working)."""
    graph = GraphBuilder().entry("n_pass").node("n_pass", "core.test.pass").build()
    (ws / "tests" / "pass.graph.json").write_text(json.dumps(graph), encoding="utf-8")
    kinds: dict[str, str] = {}
    for basis in ("team", None):
        params: dict[str, Any] = {"playbook": "triage"}
        if basis is not None:
            params["basis"] = basis
        job = daemon.begin_job(params)
        with daemon.client(agent(job)) as conn:
            conn.call("agent.toolsets.enable", {"toolsets": ["run"]})
            started = conn.call("run.start", {"path": "tests/pass.graph.json"})
            while conn.call("run.status", {"run_id": started["run_id"]})["state"] != "ended":
                time.sleep(0.2)
        with daemon.client() as ui:  # 워크스페이스당 작업 하나 — 끝내고 다음
            ui.call("job.finish", {"job": job["job"]}, timeout=300)
        run_json = json.loads((Path(started["run_dir"]) / "run.json").read_text("utf-8"))
        kinds[str(basis)] = run_json["basis"]["kind"]
    assert kinds == {"team": "team", "None": "working"}


class _Host:
    """종료 경로 대역 (`JobHost`): 순서를 기록한다. `force_ok`가 서기 전에는 입력 복구를 확인하지
    못한다. `gate`가 닫혀 있으면 마무리 대기가 막힌다."""

    def __init__(self, *, settle: bool = False) -> None:
        self.events: list[str] = []
        self.settle = settle
        self.force_ok = threading.Event()
        self.gate = threading.Event()
        self.gate.set()

    def cancel_job_runs(self, job: str) -> list[str]:
        self.events.append("cancel")
        return ["r-20261110-000000-0001"]

    def wait_job_settled(self, job: str, runs: list[str], timeout: float) -> bool:
        assert self.gate.wait(60)
        self.events.append("wait")
        return self.settle

    def force_settle(self, job: str, runs: list[str], timeout: float) -> bool:
        self.events.append("force")
        return self.force_ok.is_set()

    def write_report(self, job: Any, state: str, prep: str | None) -> str | None:
        self.events.append("report")
        return f"wiki/reports/{job.id}.md"

    def job_changed(self, job: Any) -> None:
        self.events.append(f"changed:{job.state}")


def test_unsettled_end_does_not_publish() -> None:
    """R8: 입력 복구를 확인하지 못하면 끝난 것이 아니다 — `ending` 유지, 보고·끝 알림 없음, 슬롯
    유지, 새 실행·제어 거부. 강제 복구로 확인한 뒤에만 보고·알림·슬롯 해제."""
    from kookabug_daemon.jobs import JobSupervisor

    now = [0.0]
    jobs = JobRegistry("ws", clock=lambda: now[0])
    host = _Host()
    supervisor = JobSupervisor(jobs, host)
    job, token = jobs.begin("triage", owner=1)
    out = supervisor.end(job.id, "cancelled", wait_s=0)
    assert (out["state"], out["settled"], out["report"]) == ("ending", False, None)
    assert host.events == ["cancel", "wait", "force"]  # 보고·끝 알림이 없다
    assert job.state == "ending" and not job.ended.is_set() and job.revoked == "cancelled"
    # 토큰은 폐기된 채: 새 실행·제어는 거부
    for refuse in (jobs.take_run, jobs.require_running):
        with pytest.raises(RequestFailed) as caught:
            refuse(job.id)
        assert caught.value.code == "job_token_invalid"
    # 보고를 쓰기 전이라 원문은 메모리에 남아 글자 검사 대상이다
    assert token in jobs.secret_values()
    # 작업 슬롯을 쥔다
    with pytest.raises(RequestFailed) as caught:
        jobs.begin("triage", owner=2)
    assert caught.value.code == "job_active"
    # 감독의 재시도: 아직 확인하지 못하면 그대로
    now[0] += 10
    supervisor.retry_unsettled(wait_s=0)
    assert "report" not in host.events and job.state == "ending"
    assert host.events.count("force") == 2
    # 양성 대조: 강제 복구로 확인되면 그때 보고 → 끝 알림 → 슬롯 해제
    host.force_ok.set()
    now[0] += 10
    supervisor.retry_unsettled(wait_s=0)
    assert host.events[-3:] == ["force", "report", "changed:cancelled"]
    assert job.state == "cancelled" and job.ended.is_set()
    assert job.result is not None and job.result["settled"] is True
    assert job.result["report"] == f"wiki/reports/{job.id}.md"
    assert token not in jobs.secret_values()  # 보고를 쓴 뒤 지운다
    again, _ = jobs.begin("triage", owner=2)
    assert again.state == "running"


def test_concurrent_end_waits_same_completion() -> None:
    """겹친 종료 호출(job.finish·job.end·감독)은 같은 완료를 기다려 같은 결과를 받는다 — 보고·알림은
    한 번."""
    from kookabug_daemon.jobs import JobSupervisor

    jobs = JobRegistry("ws")
    host = _Host(settle=True)
    host.gate.clear()
    supervisor = JobSupervisor(jobs, host)
    job, _ = jobs.begin("triage", owner=1)
    results: dict[str, dict[str, Any]] = {}

    def call(name: str, state: str) -> None:
        results[name] = supervisor.end(job.id, state, wait_s=60)

    first = threading.Thread(target=call, args=("finish", "done"))
    first.start()
    deadline = time.monotonic() + 30
    while "cancel" not in host.events:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    second = threading.Thread(target=call, args=("end", "cancelled"))
    second.start()
    time.sleep(0.3)
    # 둘 다 마무리 대기 중 — 아직 아무것도 내지 않았다
    assert first.is_alive() and second.is_alive() and "report" not in host.events
    host.gate.set()
    first.join(30)
    second.join(30)
    assert results["finish"] == results["end"]
    assert results["finish"]["state"] == "done" and results["finish"]["settled"] is True
    assert host.events.count("report") == 1 and host.events.count("changed:done") == 1


def test_end_waits_for_retry_in_progress() -> None:
    """첫 종료 호출과 감독 재시도가 겹쳐도 종료 호출은 `ending`으로 먼저 돌아오지 않는다 — 막
    시작한 작업은 재시도 대상이 아니고, 다른 스레드가 몰고 있으면 그 시도를 기다린 뒤 이어서 한다
    (회귀 1차의 `agent-job cancel` → `ending` 경쟁)."""
    from kookabug_daemon.jobs import JobSupervisor

    jobs = JobRegistry("ws")
    host = _Host(settle=True)
    supervisor = JobSupervisor(jobs, host)
    job, _ = jobs.begin("triage", owner=1)
    assert jobs.start_ending(job) is True
    assert jobs.unsettled() == []  # 막 들어간 종료 경로는 재시도가 가로채지 않는다
    job.ending.clear()  # 다시 첫 호출로 (아래에서 end가 처음 들어가게)
    job.drive.acquire()  # 감독 재시도가 몰고 있는 중
    box: dict[str, Any] = {}
    caller = threading.Thread(target=lambda: box.update(out=supervisor.end(job.id, "cancelled")))
    caller.start()
    time.sleep(0.3)
    assert caller.is_alive()  # snapshot(ending)으로 먼저 돌아오지 않았다
    job.drive.release()
    caller.join(30)
    assert box["out"]["state"] == "cancelled" and box["out"]["settled"] is True


@pytest.mark.process
@pytest.mark.timeout(300)
def test_two_live_jobs_refused(ws: Path, daemon: ThreadDaemon) -> None:
    """워크스페이스당 끝나지 않은 작업은 하나 (job.begin RPC도 원자적으로 job_active)."""
    first = daemon.begin_job({"playbook": "repair"})
    with daemon.client() as ui:
        assert refused(ui, "job.begin", {"playbook": "triage"}) == "job_active"
    live = [j for j in daemon.daemon.jobs.all() if not j.ended.is_set()]
    assert [j.id for j in live] == [first["job"]]
    # 양성 대조: 종료가 끝난(복구 확인·보고) 뒤에는 새 작업을 만든다
    with daemon.client() as ui:
        ended = ui.call("job.finish", {"job": first["job"]}, timeout=300)
    assert ended["state"] == "done" and ended["settled"] is True
    second = daemon.begin_job({"playbook": "triage"})
    assert second["state"] == "running" and second["job"] != first["job"]


PANEL = {"kind": "agent", "name": "mcp", "version": "0", "id": "panel:s1", "attended": False}


@pytest.mark.process
@pytest.mark.timeout(300)
def test_non_job_agent_refused_during_job(ws: Path, daemon: ThreadDaemon) -> None:
    """작업이 끝나지 않았으면 작업 토큰 없는 Agent의 실행·제어(탐색 입력 포함)·게임 띄우기는
    `job_active` — 작업 예산·종료 감독을 피하지 못한다 (R8). 사람과 작업이 끝난 뒤는 그대로."""
    graph = GraphBuilder().entry("n_pass").node("n_pass", "core.test.pass").build()
    (ws / "tests" / "pass.graph.json").write_text(json.dumps(graph), encoding="utf-8")
    # 게임을 실제로 띄우지 않게 game.executable을 뺀다 (사람 양성 대조는 launch_failed로 본다)
    local = ws / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["settings"] = {}
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    click = {"window": "없는 창", "point": [1, 1]}
    job = daemon.begin_job({"playbook": "triage"})
    with daemon.client(PANEL) as panel:
        panel.call("agent.toolsets.enable", {"toolsets": ["run"]})
        assert refused(panel, "run.start", {"path": "tests/pass.graph.json"}) == "job_active"
        assert refused(panel, "control.click", click) == "job_active"
        assert refused(panel, "app.launch", {}) == "job_active"
        # 탐색 세션 안의 입력도 같은 제어 경로다
        panel.call("explore.start", {"title": "탐색", "goal": "로비", "window": "없는 창"})
        assert refused(panel, "control.click", click) == "job_active"
        panel.call("explore.end", {})
        assert daemon.daemon.run_manager.active_run() is None
        # 양성 대조: 작업 중에도 사람은 실행을 그대로 한다. 게임을 새로 띄우기는 사람도 막는다
        # (UX1 검수 M2 — 마법사 2단계 띄우기)
        with daemon.client() as ui:
            run_id = ui.call("run.start", {"path": "tests/pass.graph.json"})["run_id"]
            outcome = daemon.daemon.run_manager.wait_outcome(run_id, 120)
            assert outcome is not None and outcome.verdict == "pass"
            assert refused(ui, "app.launch", {}) == "job_active"
        # 양성 대조: 작업이 끝난 뒤에는 같은 연결이 된다
        with daemon.client() as ui:
            ended = ui.call("job.finish", {"job": job["job"]}, timeout=300)
        assert ended["settled"] is True
        run_id = panel.call("run.start", {"path": "tests/pass.graph.json"})["run_id"]
        outcome = daemon.daemon.run_manager.wait_outcome(run_id, 120)
        assert outcome is not None and outcome.verdict == "pass"
        # 제어·게임 띄우기는 작업 판정을 지나 평소 권한 판정에 닿는다 (작업 밖 curator의 입력은
        # ask → 사람 없는 연결이라 거부 — 작업 판정은 권한 판정보다 앞이다)
        assert refused(panel, "control.click", click) == "permission_denied"
        assert refused(panel, "app.launch", {}) == "permission_denied"


@pytest.mark.process
@pytest.mark.timeout(300)
def test_report_write_failure_still_frees_slot(ws: Path, daemon: ThreadDaemon) -> None:
    """복구를 확인했는데 보고만 못 쓰면 슬롯은 풀고 `jobs.list`의 report는 null (경고 로그)."""
    from unittest import mock

    job = daemon.begin_job({"playbook": "triage"})
    with (
        mock.patch.object(reports, "write", side_effect=OSError("디스크 가득")),
        daemon.client() as ui,
    ):
        ended = ui.call("job.finish", {"job": job["job"]}, timeout=300)
    assert ended["settled"] is True and ended["state"] == "done" and ended["report"] is None
    with daemon.client() as ui:
        listed = {j["job"]: j for j in ui.call("jobs.list", {})["jobs"]}
    assert listed[job["job"]]["state"] == "done" and listed[job["job"]]["report"] is None
    # 슬롯이 풀렸다: 새 작업이 된다
    assert daemon.begin_job({"playbook": "triage"})["state"] == "running"


@pytest.mark.process
@pytest.mark.timeout(300)
def test_job_token_note_refused(ws: Path, daemon: ThreadDaemon) -> None:
    """R9: 작업 토큰 원문이 든 메모·위키·지식 쓰기는 거부한다. 보고(json·마크다운)에 토큰 0."""
    job = daemon.begin_job({"playbook": "repair"})
    token = str(job["token"])
    unknown = {
        "op": "add",
        "file": "unknowns",
        "base_revision": 0,
        "item": {"question": f"토큰 {token} 은 무엇인가?", "human_only": True},
    }
    with daemon.client(agent(job)) as conn:
        conn.call("agent.toolsets.enable", {"toolsets": ["cases", "knowledge"]})
        assert refused(conn, "job.note", {"text": f"token={token}"}) == "secret_in_text"
        wiki = {"path": "wiki/notes/token.md", "text": f"# 메모\n\n{token}\n", "base_sha256": None}
        assert refused(conn, "wiki.write", wiki) == "secret_in_text"
        request = {"request_id": "t1", "ops": [unknown]}
        assert refused(conn, "knowledge.apply", request) == "secret_in_text"
        # 양성 대조: 토큰이 없는 글은 저장된다
        assert conn.call("job.note", {"text": "구매 단추가 옮겨졌다"})["job"] == job["job"]
        conn.call("wiki.write", {**wiki, "text": "# 메모\n\n깨끗한 글\n"})
    assert (ws / "wiki" / "notes" / "token.md").read_text("utf-8").endswith("깨끗한 글\n")
    with daemon.client() as ui:
        ended = ui.call("job.finish", {"job": job["job"]}, timeout=300)
    stored = reports.read_report(ws, job["job"])
    assert stored is not None and stored["notes"] == "구매 단추가 옮겨졌다"
    rendered = (ws / ended["report"]).read_text("utf-8")
    assert "구매 단추가 옮겨졌다" in rendered
    for folder in ("knowledge", "wiki"):
        for path in (ws / folder).rglob("*"):
            if path.is_file():
                assert token not in path.read_text("utf-8", errors="replace"), path
    # 보고를 쓴 뒤 원문은 메모리에서도 지웠다
    assert token not in daemon.daemon.jobs.secret_values()


def test_budget_exhausted_refuses_and_notifies() -> None:
    jobs = JobRegistry("ws")
    seen: list[str] = []
    jobs.on_budget = lambda job: seen.append(job.id)
    job, _ = jobs.begin("triage", budget={"runs": 2}, owner=1)
    jobs.take_run(job.id)
    jobs.take_run(job.id)
    for _ in range(2):
        with pytest.raises(RequestFailed) as caught:
            jobs.take_run(job.id)
        assert caught.value.code == "job_budget_exhausted"
    assert job.runs == 2 and seen == [job.id]  # 알림은 한 번
    # 끝나는 중인 작업은 새 실행을 받지 않는다
    jobs = JobRegistry("ws2")  # 워크스페이스당 끝나지 않은 작업은 하나 (다른 표에서)
    other, _ = jobs.begin("triage", budget={"runs": 9}, owner=1)
    assert jobs.start_ending(other) is True and jobs.start_ending(other) is False
    with pytest.raises(RequestFailed) as caught:
        jobs.take_run(other.id)
    assert caught.value.code == "job_token_invalid"


class _StubManager:
    """RunVerifier가 쓰는 실행 관리자 대역: 검증 실행은 취소될 때까지 끝나지 않는다."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancelled: list[str] = []
        self._stop = threading.Event()

    def begin_verification(self) -> int:
        return 0

    def end_verification(self) -> None:
        pass

    def input_epoch(self) -> int:
        return 0

    def start_verify(self, graph: str, **_: Any) -> str:
        self.started.set()
        return "r-20261110-000000-0001"

    def wait_outcome(self, run_id: str, timeout: float) -> Any:
        self._stop.wait(timeout)
        return None

    def cancel(self, run_id: str) -> None:
        self.cancelled.append(run_id)
        self._stop.set()


def test_budget_counts_verify_runs(tmp_path: Path) -> None:
    """조율자 결정: 작업이 낸 채택의 검증 실행도 실행 예산에 센다. 다 쓰면 job_budget_exhausted로
    거부하고 게시하지 않는다."""
    ws = copy_example_workspace(tmp_path)
    change_id = setup(ws)
    before = {p: (ws / p).read_bytes() for p in (TARGET, TEST)}
    jobs = JobRegistry(str(ws))
    job, _ = jobs.begin("repair", budget={"runs": 0}, owner=1)

    class Budgeted(FakeVerifier):
        def __init__(self, job_id: str) -> None:
            super().__init__()
            self.job_id = job_id

        def run(self, graph: str, overlay: Any, **kwargs: Any) -> VerifyOutcome:
            try:
                jobs.take_run(self.job_id)
            except RequestFailed as exc:
                return VerifyOutcome(None, error=exc.code)
            return super().run(graph, overlay, **kwargs)

    result = Adopter(ws, Budgeted(job.id), job=job.id).request(CASE, change_id)
    assert result["adopted"] is False and result["failed"]["code"] == "job_budget_exhausted"
    assert {p: (ws / p).read_bytes() for p in before} == before and adoptions(ws) == []
    # RunVerifier 본체: 예산이 없으면 검증 실행을 시작하지 않는다
    manager = _StubManager()
    verifier = RunVerifier(manager, budget=lambda: jobs.take_run(job.id))  # type: ignore[arg-type]
    out = verifier.run(TEST, {}, profile=None, basis={})
    verifier.close()
    assert out.error == "job_budget_exhausted" and not manager.started.is_set()
    # 양성 대조: 예산이 남으면 채택된다 (센 실행 수 = 검증 실행 수)
    jobs = JobRegistry(str(ws))  # 앞 작업은 끝나지 않았다 — 새 daemon 표에서
    roomy, _ = jobs.begin("repair", budget={"runs": 10}, owner=1)
    done = Adopter(ws, Budgeted(roomy.id), job=roomy.id).request(CASE, change_id)
    assert done["adopted"] is True and roomy.runs == len(done["runs"]) >= 1


def test_job_end_cancels_adopt_verify(tmp_path: Path) -> None:
    """R8: 작업이 끝나면 그 작업이 낸 채택 요청의 도는 검증 실행을 취소하고 `adopt_cancelled`로
    둔다."""
    ws = copy_example_workspace(tmp_path)
    change_id = setup(ws)
    before = {p: (ws / p).read_bytes() for p in (TARGET, TEST)}
    adopts = JobAdopts()
    cancelled = threading.Event()
    pending = adopts.add("j-20261110-000000-abcd", cancelled)
    manager = _StubManager()
    box: dict[str, Any] = {}

    def work() -> None:
        verifier = RunVerifier(manager)  # type: ignore[arg-type]
        try:
            adopts.attach(pending, verifier)
            adopter = Adopter(ws, verifier, cancelled=cancelled, job="j-20261110-000000-abcd")
            box["result"] = adopter.request(CASE, change_id)
        finally:
            verifier.close()
            adopts.finish(pending)

    thread = threading.Thread(target=work)
    thread.start()
    assert manager.started.wait(60)
    assert adopts.cancel("j-20261110-000000-abcd") == ["r-20261110-000000-0001"]
    assert adopts.wait("j-20261110-000000-abcd", 60)
    thread.join(10)
    assert manager.cancelled == ["r-20261110-000000-0001"]
    assert box["result"]["failed"]["code"] == CANCELLED
    assert {p: (ws / p).read_bytes() for p in before} == before and adoptions(ws) == []
    assert case_doc(ws)["state"] == "open"
    log = [json.loads(x) for x in (ws / "knowledge" / "log.jsonl").read_text("utf-8").splitlines()]
    assert any(x.get("code") == CANCELLED and x.get("job") == "j-20261110-000000-abcd" for x in log)
