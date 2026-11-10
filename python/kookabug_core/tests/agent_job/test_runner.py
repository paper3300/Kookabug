"""`agent-job` 감독 본체 (M8 계획 3.9, 9장 R8·R9) — 엄격: 입력 안전·비밀값.

실제 daemon(`ThreadDaemon`)·실제 `kookabug mcp`·실제 runner와 가짜 QA 에이전트 CLI
(`kb_testing.fake_qa_agent`, custom 프로필)로 돈다. 실제 claude·codex는 띄우지 않는다.
"""

from __future__ import annotations

import io
import json
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder

from kb_testing.daemon import ThreadDaemon, daemon_env
from kb_testing.proc import DIRECT_PYTHON, TOOLS_DIR, wait_until
from kb_testing.sample_game import copy_example_workspace
from kookabug_cli import agent_job_cmd
from kookabug_cli.agent_job_cmd import connect_daemon
from kookabug_cli.main import build_parser
from kookabug_core.agent_job import jobdir, profiles
from kookabug_core.agent_job import report as reports
from kookabug_core.agent_job.runner import (
    EXIT_ACTIVE,
    EXIT_PREP,
    JobOptions,
    JobOutcome,
    Redactor,
    run_job,
)
from kookabug_core.win import is_alive
from kookabug_core.win.process import identify

pytestmark = [pytest.mark.process, pytest.mark.timeout(600)]

SECRET = "pw-Zq81-unique-secret"
SLOW = "tests/slow.graph.json"
PASS = "tests/pass.graph.json"
HELD = "tests/held.graph.json"
"""게임을 띄워 키 하나를 보낸 뒤(입력 임대권을 쥔다) 오래 기다리는 실행."""


def graphs(root: Path) -> None:
    passing = GraphBuilder().entry("n_pass").node("n_pass", "core.test.pass").build()
    slow = (
        GraphBuilder()
        .entry("n_wait")
        .node("n_wait", "core.flow.delay", inputs={"ms": 300_000}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
        .build()
    )
    launch = {
        "args": {"$setting": "game.args"},
        "cwd": {"$setting": "game.cwd"},
        "path": {"$setting": "game.executable"},
        "window_title": {"$setting": "game.title"},
    }
    held = (
        GraphBuilder()
        .entry("n_launch")
        .node("n_launch", "core.app.launch", inputs=launch, next={"attached": "n_key"})
        .node("n_key", "core.input.key", inputs={"keys": "f5"}, next={"done": "n_wait"})
        .node("n_wait", "core.flow.delay", inputs={"ms": 300_000}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
        .build()
    )
    (root / PASS).write_text(json.dumps(passing), encoding="utf-8")
    (root / SLOW).write_text(json.dumps(slow), encoding="utf-8")
    (root / HELD).write_text(json.dumps(held), encoding="utf-8")
    local = root / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["permissions"] = {"preset": "curator"}
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def env_for(tmp: Path) -> dict[str, str]:
    env = daemon_env(tmp)
    env["PYTHONPATH"] = str(TOOLS_DIR)
    env["KB_TEST_SECRET_VALUE"] = SECRET
    env["KOOKABUG_SECRET_ACCOUNTS_QA_TESTER"] = SECRET  # 워크스페이스 비밀값 공급자 (가림 대상)
    return env


def command(script: str | Path) -> str:
    return f'"{DIRECT_PYTHON}" -m kb_testing.fake_qa_agent --script "{script}"'


def write_script(tmp: Path, name: str, steps: list[dict[str, Any]]) -> Path:
    path = tmp / f"{name}.json"
    path.write_text(json.dumps({"steps": steps}, ensure_ascii=False), encoding="utf-8")
    return path


@dataclass
class Ran:
    root: Path
    outcome: JobOutcome
    out: str
    fake: dict[str, Any]
    pid: int | None

    @property
    def folder(self) -> Path:
        assert self.outcome.job is not None
        return jobdir.job_path(self.root, self.outcome.job)

    def text(self, name: str) -> str:
        return (self.folder / name).read_text("utf-8", errors="replace")


def start(
    root: Path,
    env: dict[str, str],
    script: str | Path,
    *,
    playbook: str = "triage",
    secrets: Any = None,
    pass_env: tuple[str, ...] = ("KB_TEST_SECRET_VALUE",),
    **extra: Any,
) -> tuple[threading.Thread, dict[str, Any]]:
    box: dict[str, Any] = {"started": threading.Event()}

    def started(job: str, pid: int) -> None:
        box["job"], box["pid"] = job, pid
        box["started"].set()

    options = JobOptions(
        root=root,
        playbook=playbook,
        agent="custom",
        agent_command=command(script),
        pass_env=list(pass_env),
        on_started=started,
        **extra,
    )
    out = io.StringIO()

    def work() -> None:
        box["outcome"] = run_job(
            options, out=out, connect=connect_daemon, environ=env, secrets=secrets
        )
        box["out"] = out.getvalue()

    thread = threading.Thread(target=work, name="agent-job-test")
    thread.start()
    return thread, box


def finish(root: Path, thread: threading.Thread, box: dict[str, Any], timeout: float = 300) -> Ran:
    thread.join(timeout)
    assert not thread.is_alive(), "agent-job이 끝나지 않았다"
    outcome: JobOutcome = box["outcome"]
    fake: dict[str, Any] = {}
    jobs = root / ".kookabug" / "jobs"
    if outcome.job is not None and not jobs.is_junction():
        path = jobdir.job_path(root, outcome.job, "fake.json")
        if path.exists():
            fake = json.loads(path.read_text("utf-8"))
    return Ran(root, outcome, box.get("out", ""), fake, box.get("pid"))


def run_sync(root: Path, env: dict[str, str], script: str | Path, **extra: Any) -> Ran:
    thread, box = start(root, env, script, **extra)
    return finish(root, thread, box)


def dead(pid: int | None) -> bool:
    if pid is None:
        return True
    ident = identify(pid)
    return ident is None or not is_alive(ident)


def tree_text(folder: Path) -> str:
    return "\n".join(
        p.read_text("utf-8", errors="replace") for p in folder.rglob("*") if p.is_file()
    )


# ---------------------------------------------------------------- 예산 먹보 (한 번 돌려 여러 단언)


TOKENS: list[str] = []
"""예산 먹보 작업이 받은 토큰 원문 (검사가 job.begin을 감싸 기록 — 어디에도 남지 않아야 한다)."""


@pytest.fixture(scope="module")
def hog(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Ran, ThreadDaemon]]:
    tmp = tmp_path_factory.mktemp("hog")
    root = copy_example_workspace(tmp)
    graphs(root)
    env = env_for(tmp)
    with ThreadDaemon(root, platform_fake=root / "fake-platform.json") as d:
        begin = d.daemon.jobs.begin

        def recorded(*args: Any, **kwargs: Any) -> Any:
            job, token = begin(*args, **kwargs)
            TOKENS.append(token)
            return job, token

        d.daemon.jobs.begin = recorded  # type: ignore[method-assign]
        ran = run_sync(root, env, "budget_hog", runs=3, grace_s=2.0)
        yield ran, d


def test_budget_runs_exhausted_stops_cli(hog: tuple[Ran, ThreadDaemon]) -> None:
    ran, d = hog
    assert ran.outcome.state == "budget_exhausted", ran.out
    results = [r for r in ran.fake.get("results", []) if r.get("tool") == "kb_run_start"]
    # 3번 성공, 4번째는 job_budget_exhausted (daemon이 작업 토큰으로 집계·강제)
    assert [("ok" in r) for r in results[:3]] == [True, True, True]
    assert results[3]["error"] == "job_budget_exhausted" and len(results) == 4
    # 가짜 CLI는 버텼다(sleep 600) → agent-job이 유예 뒤 트리를 끝냈다 (CLI·손자 모두)
    assert dead(ran.pid)
    grandchild = int((ran.folder / "grandchild.pid").read_text("utf-8"))
    assert dead(grandchild)
    # 남은 실행 없음·보고 budget
    assert d.daemon.run_manager.active_run() is None
    stored = reports.read_report(ran.root, str(ran.outcome.job))
    assert stored is not None and stored["state"] == "budget_exhausted"
    assert stored["budget"]["runs"] == [3, 3]
    assert "budget" in {i["kind"] for g in stored["groups"] for i in g["items"]}
    job = jobdir.read_job(ran.root, str(ran.outcome.job))
    assert job is not None and job["state"] == "budget_exhausted" and job["used"]["runs"] == 3
    assert job["agent"]["command"] == os.path.basename(DIRECT_PYTHON)


def test_agent_log_redacts_secret(hog: tuple[Ran, ThreadDaemon]) -> None:
    ran, _ = hog
    log = ran.text("agent.log")
    # 양성 대조: 가짜 CLI는 값을 실제로 출력했다 (출력 줄이 있고 그 자리가 가려졌다)
    assert log.count("값: ***") >= 2, log
    assert SECRET not in log


def test_job_token_never_logged(hog: tuple[Ran, ThreadDaemon]) -> None:
    ran, _ = hog
    assert len(TOKENS) == 1 and len(TOKENS[0]) >= 32
    token = TOKENS[0]
    log = ran.text("agent.log")
    # 양성 대조: 가짜 CLI가 토큰을 출력했다 (그 줄은 있고 값 자리가 가려졌다)
    assert log.count("값: ***") >= 2
    # 작업 폴더(job.json·prompt.md·mcp.json·agent.log·가짜 CLI 결과), 출력, 보고, 감사 이력 어디에도
    # 토큰 원문이 없다
    assert token not in tree_text(ran.folder)
    assert token not in ran.out
    assert token not in tree_text(ran.root / "knowledge") + tree_text(ran.root / "wiki")
    job = jobdir.read_job(ran.root, str(ran.outcome.job))
    assert job is not None and "token" not in json.dumps(job)


def test_secret_split_across_output_chunks(hog: tuple[Ran, ThreadDaemon]) -> None:
    ran, _ = hog
    log = ran.text("agent.log")
    # 값을 둘로 나눠 사이에 flush·쉼 (청크 경계를 넘는 값) → 앞뒤 글자와 함께 가려졌다
    assert log.count("앞 *** 뒤") >= 2 or log.count("앞 ***") >= 2, log
    half = SECRET[: len(SECRET) // 2]
    assert half + SECRET[len(SECRET) // 2 :] not in log
    # 단위: 경계가 어디든 가린다 (한 바이트씩도)
    for size in (1, 2, 3, 7):
        redactor = Redactor([SECRET, "tok"])
        data = f"a {SECRET} b tok c".encode()
        chunks = [data[i : i + size] for i in range(0, len(data), size)]
        joined = b"".join(redactor.feed(c) for c in chunks) + redactor.flush()
        assert joined == b"a *** b *** c"


def test_child_env_and_argv_secret_boundary(hog: tuple[Ran, ThreadDaemon]) -> None:
    ran, _ = hog
    names = set(ran.fake["env_names"])
    # 양성 대조: 작업 토큰·작업 변수·사람이 고른 이름은 자식에 있다
    assert {
        profiles.TOKEN_ENV,
        profiles.JOB_ENV,
        profiles.MCP_CONFIG_ENV,
        "KB_TEST_SECRET_VALUE",
    } <= names
    # 게임 비밀값·허용 목록 밖 이름은 없다
    assert not [n for n in names if n.upper().startswith("KOOKABUG_SECRET")]
    assert ran.fake["argv_has_token"] is False
    config = json.loads(ran.text("mcp.json"))
    assert config["mcpServers"]["kookabug"]["env"] == {}
    assert "--job-token-env" in config["mcpServers"]["kookabug"]["args"]


# ---------------------------------------------------------------- 그 밖


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = copy_example_workspace(tmp_path)
    graphs(root)
    return root


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws, platform_fake=ws / "fake-platform.json") as d:
        yield d


def test_prompt_has_playbook_no_wiki(ws: Path, daemon: ThreadDaemon, tmp_path: Path) -> None:
    sentinel = "위키에만 있는 문장 — 프롬프트에 들어가면 안 된다 7f3a"
    (ws / "wiki").mkdir(exist_ok=True)
    (ws / "wiki" / "overview.md").write_text(f"# 개요\n\n{sentinel}\n", encoding="utf-8")
    ran = run_sync(ws, env_for(tmp_path), "probe", playbook="probe", runs=1, minutes=1)
    assert ran.outcome.state == "done", ran.out
    prompt = ran.text("prompt.md")
    assert prompt.startswith("<!-- kookabug:job -->") and f"작업 ID: {ran.outcome.job}" in prompt
    assert "`kb_project_info`를 한 번 부르고" in prompt  # 플레이북 본문
    assert sentinel not in prompt
    assert ran.fake["prompt"] == []  # 가짜 CLI의 단언도 통과 (머리말 있음·위키 없음)


def test_probe_success_by_observed_call(ws: Path, daemon: ThreadDaemon, tmp_path: Path) -> None:
    env = env_for(tmp_path)
    ok = run_sync(ws, env, "probe", playbook="probe", runs=1, minutes=1)
    assert ok.outcome.extra["probe_ok"] is True
    # kb_project_info가 플레이북 판·원본 상태·자동화 정책·작업 예산을 준다 (B4 인계)
    info = ok.fake["results"][0]["ok"]
    assert info["playbooks"]["repair"] >= 1 and info["playbooks"]["probe"] >= 1
    assert info["sources"] and all(
        s["state"] in ("ok", "missing", "unreadable", "unchecked_url") for s in info["sources"]
    )
    assert info["automation"]["forbidden"] and info["job"]["job"] == ok.outcome.job
    assert info["job"]["budget"] == {"minutes": 1, "runs": 1}
    # 음성 대조: 도구를 부르지 않고 "성공"이라 출력해도 성공이 아니다 (모델 출력을 해석하지 않는다)
    quiet = write_script(tmp_path, "quiet", [{"print": "kb_project_info 불렀음, 성공"}])
    bad = run_sync(ws, env, quiet, playbook="probe", runs=1, minutes=1)
    assert bad.outcome.state == "done" and bad.outcome.extra["probe_ok"] is False


def test_time_budget_cancels_runs_and_releases_input(
    ws: Path, daemon: ThreadDaemon, tmp_path: Path
) -> None:
    script = write_script(
        tmp_path,
        "slow",
        [
            {"toolsets": ["run"]},
            {"tool": "kb_run_start", "args": {"path": HELD, "idempotency_key": "s1"}},
            {"sleep": 600},
        ],
    )
    thread, box = start(ws, env_for(tmp_path), script, deadline_s=10.0)
    assert box["started"].wait(120)
    wait_until(lambda: daemon.daemon.run_manager.active_run() is not None, timeout=120)
    run_id = daemon.daemon.run_manager.active_run()
    # 양성 대조: 실행이 입력 임대권을 쥐었다 (아래 "임대권 없음"이 빈 검사가 아니다)
    wait_until(lambda: daemon.daemon.input_busy() == "input_lease", timeout=60)
    ran = finish(ws, thread, box)
    assert ran.outcome.state == "budget_exhausted"
    assert dead(ran.pid)
    # 시간 초과 → 같은 종료 경로: 그 작업의 실행 취소·마무리 완료, 임대권 없음
    assert daemon.daemon.run_manager.active_run() is None
    with daemon.client() as ui:
        status = ui.call("run.status", {"run_id": run_id})
    run_json = json.loads((Path(status["run_dir"]) / "run.json").read_text("utf-8"))
    assert run_json["code"] == "cancelled" and run_json["job"] == ran.outcome.job
    assert daemon.daemon.input_busy() is None


def test_cancel_kills_tree_and_runs(
    ws: Path, daemon: ThreadDaemon, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = write_script(
        tmp_path,
        "tree",
        [
            {"spawn_child_sleep": 600},
            {"toolsets": ["run"]},
            {"tool": "kb_run_start", "args": {"path": SLOW, "idempotency_key": "s1"}},
            {"sleep": 600},
        ],
    )
    thread, box = start(ws, env_for(tmp_path), script)
    assert box["started"].wait(120)
    wait_until(lambda: daemon.daemon.run_manager.active_run() is not None, timeout=120)
    run_id = daemon.daemon.run_manager.active_run()
    folder = jobdir.job_path(ws, box["job"])
    wait_until(lambda: (folder / "grandchild.pid").exists(), timeout=60)
    grandchild = int((folder / "grandchild.pid").read_text("utf-8"))
    assert not dead(grandchild) and not dead(box["pid"])  # 양성 대조: 취소 전에는 살아 있다
    # 다른 프로세스의 `agent-job cancel JOB`과 같은 길 (CLI 명령 그대로)
    args = build_parser().parse_args(
        ["agent-job", "cancel", box["job"], "--workspace", str(ws), "--json"]
    )
    assert agent_job_cmd.run(args, *_streams()) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "cancelled"
    ran = finish(ws, thread, box)
    assert ran.outcome.state == "cancelled"
    assert dead(ran.pid) and dead(grandchild)
    with daemon.client() as ui:
        status = ui.call("run.status", {"run_id": run_id})
    assert (
        json.loads((Path(status["run_dir"]) / "run.json").read_text("utf-8"))["code"] == "cancelled"
    )
    stored = reports.read_report(ws, box["job"])
    assert stored is not None and stored["state"] == "cancelled"


def test_daemon_restart_marks_interrupted(ws: Path, tmp_path: Path) -> None:
    script = write_script(tmp_path, "idle", [{"tool": "kb_project_info"}, {"sleep": 600}])
    with ThreadDaemon(ws, platform_fake=ws / "fake-platform.json") as d:
        thread, box = start(ws, env_for(tmp_path), script)
        assert box["started"].wait(120)
        wait_until(lambda: d.daemon.jobs.get(box["job"]) is not None, timeout=60)
        time.sleep(1.0)
    # daemon이 끝나며 같은 종료 경로(입력 복구 확인 → 보고)를 지났다. agent-job은 연결을 잃었고 그
    # daemon 프로세스(이 검사 프로세스)는 살아 있어 직접 확인할 수 없지만, daemon이 확인 뒤 쓴 끝
    # 보고를 따른다
    ran = finish(ws, thread, box)
    assert ran.outcome.state == "interrupted" and dead(ran.pid)
    job = jobdir.read_job(ws, box["job"])
    assert job is not None and job["state"] == "interrupted"
    stored = reports.read_report(ws, box["job"])
    assert stored is not None and stored["state"] == "interrupted"
    # 확인하지 못한 채 남은 작업(recovery_unconfirmed)도 다음 daemon 시작이 이어받는다
    pending = {**job, "id": "j-20261110-010203-abce", "state": jobdir.UNCONFIRMED, "report": None}
    pending.pop("format", None)
    jobdir.write_job(ws, pending)
    with ThreadDaemon(ws):
        pass
    resumed = jobdir.read_job(ws, pending["id"])
    assert resumed is not None and resumed["state"] == "interrupted"
    assert reports.read_report(ws, pending["id"])["state"] == "interrupted"  # type: ignore[index]
    # agent-job도 죽은 경우: 다음 daemon 시작이 남은 running 작업을 interrupted로 끝낸다
    stale = {**job, "id": "j-20261110-010203-abcd", "state": "running", "report": None}
    stale.pop("format", None)
    jobdir.write_job(ws, stale)
    with jobdir.JobLock(ws):
        # 양성 대조: agent-job이 살아 있으면(잠금을 쥐고 있으면) 건드리지 않는다
        with ThreadDaemon(ws):
            pass
        assert jobdir.read_job(ws, stale["id"])["state"] == "running"  # type: ignore[index]
    with ThreadDaemon(ws):
        pass
    after = jobdir.read_job(ws, stale["id"])
    assert after is not None and after["state"] == "interrupted"
    assert reports.read_report(ws, stale["id"])["state"] == "interrupted"  # type: ignore[index]


class _LostLink:
    """연결을 잃은 소유 연결 대역: `gone`은 daemon 프로세스가 없어졌는지."""

    def __init__(self, gone: bool) -> None:
        self._gone = gone
        self.asked: list[float] = []

    def gone(self, timeout: float) -> bool:
        self.asked.append(timeout)
        return self._gone


def test_lost_daemon_reports_only_after_input_settled(ws: Path) -> None:
    """R8 연결 유실 경로: ① daemon 프로세스가 없어졌고 ② 입력 해제를 확인한 뒤에만 보고를 쓴다.
    아니면 `recovery_unconfirmed`만 (보고 없음)."""
    from kookabug_core.agent_job.runner import _write_interrupted

    def doc(n: int) -> dict[str, Any]:
        return {
            "id": f"j-20261110-0102{n:02d}-abcd",
            "playbook": "triage",
            "trigger": "manual",
            "agent": {"profile": "custom"},
            "started_at": "2026-11-10T01:02:00Z",
            "budget": {"minutes": 60, "runs": 3},
            "used": {"runs": 0, "tool_calls": 0, "minutes": 0},
        }

    seen: list[Path] = []

    def settled(ok: bool) -> Any:
        def check(root: Path, env: Any) -> bool:
            seen.append(root)
            return ok

        return check

    cases = [
        (doc(1), _LostLink(gone=False), True),  # daemon 살아 있음 → 확인 못 함
        (doc(2), _LostLink(gone=True), False),  # daemon은 없지만 입력 해제를 확인 못 함
    ]
    for d, link, ok in cases:
        options = JobOptions(root=ws, playbook="triage", gone_wait_s=0.1, input_settled=settled(ok))
        out = _write_interrupted(ws, d, link, {}, options)  # type: ignore[arg-type]
        assert out == {"state": jobdir.UNCONFIRMED, "report": None}
        assert reports.read_report(ws, d["id"]) is None
    assert len(seen) == 1  # daemon이 살아 있으면 입력 확인까지 가지 않는다
    # 양성 대조: 둘 다 확인되면 interrupted 보고
    options = JobOptions(root=ws, playbook="triage", input_settled=settled(True))
    out = _write_interrupted(ws, doc(3), _LostLink(gone=True), {}, options)  # type: ignore[arg-type]
    assert out["state"] == "interrupted" and out["report"]
    assert reports.read_report(ws, doc(3)["id"])["state"] == "interrupted"  # type: ignore[index]


@pytest.mark.parametrize("profile_auth", ["OPENAI_API_KEY"])
def test_pass_env_value_redacted(
    ws: Path, daemon: ThreadDaemon, tmp_path: Path, profile_auth: str
) -> None:
    """High 4: custom 프로필이 `--pass-env`로 넘긴 인증 값(이름을 바꾼 것 포함)은 가짜 CLI가 일부러
    출력해도 `agent.log`에 원문이 0이다. 6자 미만 값은 가리지 않는다(양성 대조)."""
    auth = "review-auth-only-custom-4c7e"
    renamed = "renamed-auth-value-91xq"
    env = {**env_for(tmp_path), profile_auth: auth, "KB_TEST_RENAMED": renamed, "KB_SHORT": "abc12"}
    script = write_script(
        tmp_path,
        "leak_auth",
        [
            {"print_env": profile_auth},
            {"print_env": "KB_TEST_RENAMED"},
            {"print_split_env": "KB_TEST_RENAMED"},
            {"print_env": "KB_SHORT"},
        ],
    )
    ran = run_sync(ws, env, script, pass_env=(profile_auth, "KB_TEST_RENAMED", "KB_SHORT"))
    assert ran.outcome.state == "done", ran.out
    log = ran.text("agent.log")
    # 양성 대조: 출력 줄은 있다(값 자리가 가려졌다), 짧은 값은 그대로
    assert log.count("값: ***") >= 2 and "abc12" in log, log
    assert auth not in log and renamed not in log
    assert set(ran.fake["env_names"]) >= {profile_auth, "KB_TEST_RENAMED"}  # 실제로 넘겼다


def test_input_busy_prep_failed(ws: Path, daemon: ThreadDaemon, tmp_path: Path) -> None:
    reservation = daemon.daemon.run_manager.reserve_recording()
    try:
        ran = run_sync(ws, env_for(tmp_path), "probe", playbook="probe", runs=1, minutes=1)
    finally:
        reservation.release()
    assert ran.outcome.exit_code == EXIT_PREP and ran.outcome.state == "prep_failed"
    assert ran.pid is None  # CLI를 띄우지 않았다
    job = jobdir.read_job(ws, str(ran.outcome.job))
    assert job is not None and job["state"] == "prep_failed" and "token" not in json.dumps(job)
    stored = reports.read_report(ws, str(ran.outcome.job))
    assert stored is not None and stored["state"] == "prep_failed"


def test_second_job_refused_job_active(ws: Path, daemon: ThreadDaemon, tmp_path: Path) -> None:
    env = env_for(tmp_path)
    with jobdir.JobLock(ws):
        ran = run_sync(ws, env, "probe", playbook="probe", runs=1, minutes=1)
        assert ran.outcome.exit_code == EXIT_ACTIVE and ran.outcome.extra["code"] == "job_active"
        assert ran.pid is None
        before = {r["job"] for r in reports.list_reports(ws)}
        # 예약 실행은 그 회차를 건너뛰고 보고 하나를 남긴다
        sched = run_sync(ws, env, "probe", playbook="probe", runs=1, minutes=1, trigger="schedule")
        assert sched.outcome.exit_code == EXIT_ACTIVE
        new = [r for r in reports.list_reports(ws) if r["job"] not in before]
        assert len(new) == 1 and new[0]["state"] == "prep_failed"
    # 실제 작업 둘이 겹치면 두 번째가 job_active (잠금은 프로세스 공통 바이트 잠금)
    script = write_script(tmp_path, "wait", [{"sleep": 600}])
    thread, box = start(ws, env, script)
    assert box["started"].wait(120)
    second = run_sync(ws, env, "probe", playbook="probe", runs=1, minutes=1)
    assert second.outcome.exit_code == EXIT_ACTIVE
    with daemon.client() as ui:
        ui.call("job.end", {"job": box["job"], "reason": "cancelled"}, timeout=300)
    assert finish(ws, thread, box).outcome.state == "cancelled"
    # 끝난 뒤에는 잠금이 풀린다
    assert jobdir.lock_free(ws)


def test_secret_provider_failure_suppresses_log(
    ws: Path, daemon: ThreadDaemon, tmp_path: Path
) -> None:
    script = write_script(
        tmp_path,
        "leak",
        [{"print_env": "KOOKABUG_JOB_TOKEN"}, {"print_env": "KB_TEST_SECRET_VALUE"}],
    )

    def broken() -> list[str]:
        raise OSError("자격 증명 관리자를 읽지 못했다")

    ran = run_sync(ws, env_for(tmp_path), script, secrets=broken)
    assert ran.outcome.state == "done"
    log = ran.text("agent.log")
    assert "가림 불가로 생략" in log
    assert SECRET not in log and "값:" not in log  # 원문을 하나도 남기지 않았다
    # 양성 대조: 공급이 되면 출력 줄은 남는다(가려서)
    ok = run_sync(ws, env_for(tmp_path), script)
    assert "값: ***" in ok.text("agent.log")


def test_job_dir_junction_refused(ws: Path, daemon: ThreadDaemon, tmp_path: Path) -> None:
    """작업 폴더(`.kookabug/jobs`)가 정션이면 워크스페이스 밖에 쓰지 않고 준비 실패로 끝낸다."""
    import subprocess

    outside = tmp_path / "outside"
    outside.mkdir()
    jobs = ws / ".kookabug" / "jobs"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(jobs), str(outside)], check=True, capture_output=True
    )
    try:
        ran = run_sync(ws, env_for(tmp_path), "probe", playbook="probe", runs=1, minutes=1)
    finally:
        os.rmdir(jobs)  # 정션만 지운다 (대상 폴더는 그대로)
    assert ran.outcome.state == "prep_failed" and ran.pid is None
    assert list(outside.iterdir()) == []  # 밖에 prompt·mcp·agent.log·job.json 없음
    stored = reports.read_report(ws, str(ran.outcome.job))
    assert stored is not None and "job_dir_unsafe" in json.dumps(stored, ensure_ascii=False)


def test_agent_env_exit5(
    ws: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KOOKABUG_AGENT", "panel")
    for argv in (
        [
            "agent-job",
            "run",
            "--workspace",
            str(ws),
            "--playbook",
            "triage",
            "--agent-command",
            "x",
        ],
        ["agent-job", "playbooks"],
        ["agent-job", "cancel", "j-20261110-000000-abcd", "--workspace", str(ws)],
        [
            "agent-job",
            "schedule",
            "install",
            "--workspace",
            str(ws),
            "--playbook",
            "triage",
            "--dry-run",
        ],
    ):
        args = build_parser().parse_args(argv)
        assert agent_job_cmd.run(args, *_streams()) == 5, argv
    assert not (ws / ".kookabug" / "jobs").exists()
    capsys.readouterr()
    # 양성 대조: KOOKABUG_AGENT가 없으면 사람 명령은 돈다
    monkeypatch.delenv("KOOKABUG_AGENT")
    assert (
        agent_job_cmd.run(
            build_parser().parse_args(["agent-job", "playbooks", "--json"]), *_streams()
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["playbooks"]["repair"] >= 1


def _streams() -> tuple[Any, Any]:
    import sys

    return sys.stdout, sys.stderr
