"""M8 완료 기준 (M8 계획 5장 Python 열) 인수 테스트.

끝에서 끝 경로: 실제 `kookabug agent-job run`(CLI 하위 프로세스) → 가짜 QA 에이전트 CLI
(`kb_testing.fake_qa_agent`, custom 프로필) → 실제 `kookabug mcp`(stdio) → daemon(`ThreadDaemon`) →
실제 runner → 예제 상점 가짜 게임(`make_fake_game(scenario="shop")`, 상태 파일을 runner·daemon이
같이 씀). 실제 모델·claude·codex·네트워크·실제 입력·실제 schtasks는 쓰지 않는다.

- 정상 수리(`shop_moved`)·은폐 방지(`shop_missing`)·Init(`init_sample`) 각본은
  `tools/kb_testing/qa_scripts/`에 있다. 각본은 단계마다 기대 결과를 스스로 단언하고, 이 검사는
  작업이 끝난 뒤 파일·보고·daemon 상태를 다시 단언한다
- 모든 "0·없음·그대로" 단언에는 같은 검사 안에 양성 대조가 있다
- 자세한 경우는 묶음별 근거 테스트(`kookabug_daemon/tests/test_adopt.py`·`test_cases.py`·
  `test_forbidden.py`·`test_qa_runner.py`·`test_job_supervision.py`, `kookabug_core/tests/
  agent_job/`·`knowledge/`)에 있다. 실제 창·실제 Agent CLI는 `Docs/verification/m8-manual.md`
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.cli import cli_env
from helpers.graphs import GraphBuilder

from kb_testing.daemon import ThreadDaemon
from kb_testing.fake_game import FakeGame, make_fake_game
from kb_testing.mcp_client import McpClient
from kb_testing.proc import TOOLS_DIR, VENV_PYTHON, Spawned, count_inputs, python_cmd
from kb_testing.sample_game import EXAMPLE_LOCAL
from kookabug_core.agent_job import jobdir
from kookabug_core.agent_job import report as reports
from kookabug_core.win import is_alive
from kookabug_core.win.process import identify

pytestmark = [pytest.mark.process, pytest.mark.timeout(1800)]

SHOP: Final = "SampleRPG 상점"
TEST: Final = "tests/shop/buy_potion.graph.json"
AFFECTED: Final = "tests/shop/buy_then_close.graph.json"
TARGET: Final = "targets/shop/buy.target.json"
IMAGE: Final = "targets/shop/buy.png"
ASSERTIONS: Final = ["n_assert_gold", "n_assert_item"]
SECRET: Final = "pw-M8-acceptance-7Qx"
"""검사 전용 비밀값 (워크스페이스 비밀값 `acc.pw`)."""
PASS_GRAPH: Final = "tests/pass.graph.json"
"""`budget_hog` 각본이 쓰는 그래프 (검사가 둔다)."""
SLOW_GRAPH: Final = "tests/slow.graph.json"
JOB_TIMEOUT_S: Final = 1200
"""agent-job 하나의 상한 (시나리오 각본 — 검증 실행 여러 번)."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def team_tree(root: Path) -> dict[str, str]:
    """팀 기준 파일 전부(tests·subgraphs·targets·screens·kookabug.json·주장)의 sha."""
    out = {"kookabug.json": sha((root / "kookabug.json").read_bytes())}
    for top in ("tests", "subgraphs", "targets", "screens", "knowledge/features"):
        base = root / top
        if base.is_dir():
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    out[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    return out


def read_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def tree_text(folder: Path) -> str:
    if not folder.exists():
        return ""
    return "\n".join(
        p.read_text("utf-8", errors="replace") for p in sorted(folder.rglob("*")) if p.is_file()
    )


@dataclass
class Job:
    """끝난 agent-job 하나 (CLI 출력·작업 폴더·가짜 CLI 결과)."""

    root: Path
    code: int
    out: dict[str, Any]
    stderr: str
    elapsed: float
    fake: dict[str, Any] = field(default_factory=dict[str, Any])

    @property
    def id(self) -> str:
        return str(self.out["job"])

    @property
    def folder(self) -> Path:
        return jobdir.job_path(self.root, self.id)

    @property
    def results(self) -> list[dict[str, Any]]:
        return list(self.fake.get("results", []))

    def step(self, label: str) -> dict[str, Any]:
        found = [r for r in self.results if r.get("label") == label]
        assert found, f"각본 단계 {label}이(가) 없다: {self.fake.get('failed')}"
        return found[-1]

    def report(self) -> dict[str, Any]:
        stored = reports.read_report(self.root, self.id)
        assert stored is not None, f"작업 {self.id}의 보고가 없다"
        return stored

    def items(self, kind: str) -> list[dict[str, Any]]:
        return [i for g in self.report()["groups"] for i in g["items"] if i["kind"] == kind]


@dataclass
class World:
    game: FakeGame
    daemon: ThreadDaemon
    tmp: Path
    env: dict[str, str]
    procs: list[subprocess.Popen[bytes]] = field(default_factory=list[subprocess.Popen[bytes]])
    """띄운 agent-job 프로세스 (검사가 중간에 실패해도 남기지 않는다)."""

    @property
    def root(self) -> Path:
        return self.game.root

    def cli(self, *args: str, timeout: float = 300) -> tuple[int, dict[str, Any]]:
        """사람 쪽 `kookabug ... --json` 하나 (종료 코드, 마지막 JSON 줄)."""
        done = subprocess.run(
            [*python_cmd("-m", "kookabug_cli"), *args],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        lines = [line for line in done.stdout.splitlines() if line.strip()]
        assert lines, f"출력이 없다 (종료 {done.returncode}): {done.stderr[-2000:]}"
        return done.returncode, json.loads(lines[-1])

    def start_job(self, script: str | Path, playbook: str = "repair", *args: str) -> Running:
        """실제 `kookabug agent-job run --json`을 하위 프로세스로 띄운다 (기다리지 않는다)."""
        # 가짜 CLI는 이 venv의 python(설치본처럼 site-packages를 찾는 실행 파일)으로 띄운다 —
        # agent-job 프로세스 안에서는 런처 변수가 이미 소비돼 자식에 넘어가지 않는다
        agent = f'"{VENV_PYTHON}" -m kb_testing.fake_qa_agent --script "{script}"'
        cmd = [
            *python_cmd("-m", "kookabug_cli"),
            "agent-job",
            "run",
            "--workspace",
            str(self.root),
            "--playbook",
            playbook,
            "--agent-command",
            agent,
            "--json",
            *args,
        ]
        folder = self.tmp / "agent-job"
        folder.mkdir(exist_ok=True)
        n = len(list(folder.glob("*.out")))
        out, err = folder / f"{n}.out", folder / f"{n}.err"
        with out.open("wb") as stdout, err.open("wb") as stderr:
            proc = subprocess.Popen(cmd, cwd=self.root, env=self.env, stdout=stdout, stderr=stderr)
        self.procs.append(proc)
        return Running(self, proc, out, err, time.monotonic())

    def job(
        self,
        script: str | Path,
        playbook: str = "repair",
        *args: str,
        timeout: float = JOB_TIMEOUT_S,
    ) -> Job:
        """실제 `kookabug agent-job run --json`을 끝까지 돌린다."""
        return self.start_job(script, playbook, *args).finish(timeout)

    def wait_active_job(self, timeout: float = 120) -> str:
        """daemon에 작업이 붙을 때까지 (작업 ID)."""
        deadline = time.monotonic() + timeout
        while (job := self.daemon.daemon.jobs.active_id()) is None:
            assert time.monotonic() < deadline, f"{timeout}초 안에 작업이 시작되지 않았다"
            time.sleep(0.1)
        return job

    def wait_active_run(self, timeout: float = 120) -> str:
        deadline = time.monotonic() + timeout
        while (run := self.daemon.daemon.run_manager.active_run()) is None:
            assert time.monotonic() < deadline, f"{timeout}초 안에 실행이 시작되지 않았다"
            time.sleep(0.1)
        return str(run)


@dataclass
class Running:
    world: World
    proc: subprocess.Popen[bytes]
    out: Path
    err: Path
    started: float

    def finish(self, timeout: float = JOB_TIMEOUT_S) -> Job:
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(30)
            raise AssertionError(f"agent-job이 {timeout}초 안에 끝나지 않았다") from None
        elapsed = time.monotonic() - self.started
        stdout = self.out.read_text("utf-8", errors="replace")
        stderr = self.err.read_text("utf-8", errors="replace")
        lines = [line for line in stdout.splitlines() if line.strip()]
        assert lines, f"agent-job 출력이 없다 (종료 {self.proc.returncode}): {stderr[-2000:]}"
        out = json.loads(lines[-1])
        root = self.world.root
        job = Job(root, self.proc.returncode, out, stderr, elapsed)
        if out.get("job"):
            fake = jobdir.job_path(root, job.id, "fake.json")
            if fake.exists():
                job.fake = read_json(fake)
        return job


def write_script(tmp: Path, name: str, steps: list[dict[str, Any]]) -> Path:
    """검사 전용 짧은 각본 (예제 각본 밖 — 기준 고정·잠금·취소처럼 한 가지만 보는 것)."""
    path = tmp / f"{name}.json"
    path.write_text(json.dumps({"steps": steps}, ensure_ascii=False), encoding="utf-8")
    return path


def write_graph(root: Path, rel: str, builder: GraphBuilder) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(builder.build()), encoding="utf-8")


def dead(pid: int) -> bool:
    ident = identify(pid)
    return ident is None or not is_alive(ident)


def wait_for(check: Any, what: str, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, f"{timeout}초 안에 {what}이(가) 보이지 않았다"
        time.sleep(0.1)


def keys_and_texts(game: FakeGame) -> tuple[int, int]:
    """게임에 실제로 간 콘솔 키(`)·글자 입력 수 (실제 기록 형식 — `count_inputs`)."""
    inputs = game.inputs()
    return count_inputs(inputs, "key", key="`"), count_inputs(inputs, "text")


def run_json(root: Path, run_id: str) -> dict[str, Any]:
    [folder] = list((root / "runs").glob(f"*_{run_id}"))
    return read_json(folder / "run.json")


def wait_run(client: Any, run_id: str, timeout: float = 300) -> None:
    deadline = time.monotonic() + timeout
    while client.call("run.status", {"run_id": run_id})["state"] != "ended":
        assert time.monotonic() < deadline, f"실행 {run_id}이(가) {timeout}초 안에 끝나지 않았다"
        time.sleep(0.2)


def human_run(w: World, graph: str) -> dict[str, Any]:
    """사람(UI 연결) 실행 하나를 끝까지 — run.json."""
    with w.daemon.client() as ui:
        run_id = str(ui.call("run.start", {"path": graph})["run_id"])
        wait_run(ui, run_id)
    return run_json(w.root, run_id)


@contextlib.contextmanager
def world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ocr_models: Path,
    *,
    variant: str | None,
    preset: str = "curator",
    adopt_cheat: bool = False,
) -> Iterator[World]:
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", SECRET)
    game = make_fake_game(
        tmp_path, scenario="shop", variant=variant, permissions={"preset": preset}
    )
    local = game.root / ".kookabug" / "local.json"
    body = read_json(local)
    body["settings"] = dict(EXAMPLE_LOCAL)  # 사람마다 다른 실행 설정 (가짜 플랫폼은 띄우지 않는다)
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    env = cli_env(tmp_path, None)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp_path / "user")
    env["KOOKABUG_OCR_MODELS"] = str(ocr_models)
    env["KOOKABUG_SECRET_ACC_PW"] = SECRET
    env["PYTHONPATH"] = str(TOOLS_DIR)
    w: World | None = None
    try:
        with game.daemon(env) as d:
            w = World(game, d, tmp_path, env)
            if adopt_cheat:
                # 사람이 준비한 팀 기준 (3.16): give_gold 채택, 분류 dev_safe(무인 허용)
                with d.client() as ui:
                    ui.call("cheats.adopt", {"id": "give_gold", "rev": 1, "category": "dev_safe"})
            yield w
            # 다음 검사가 깨끗한 상태에서 시작한다: 작업 잠금·입력 임대권·실행 슬롯이 남지 않았다
            assert jobdir.lock_free(game.root), "jobs.lock이 남았다"
            assert d.daemon.run_manager.active_run() is None, "실행이 남았다"
            assert d.daemon.input_busy() is None, "입력 임대권·녹화가 남았다"
            assert d.daemon.jobs.active_id() is None, "daemon 작업 슬롯이 남았다"
    finally:
        # 검사가 중간에 실패해도 agent-job을 남기지 않는다 (CLI 트리는 agent-job의 Job Object가
        # 같이 끝낸다)
        for proc in [] if w is None else w.procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait(60)


# ---------------------------------------------------------------- 정상 수리 (shop_moved)


def test_scenario_ui_change_auto_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    with world(tmp_path, monkeypatch, ocr_models, variant="moved") as w:
        root = w.root
        team_target = (root / TARGET).read_bytes()
        graphs = {rel: (root / rel).read_bytes() for rel in (TEST, AFFECTED)}
        assert not (root / "wiki" / "features" / "shop.md").exists()
        job = w.job("shop_moved", "repair")
        assert job.code == 0 and job.out["state"] == "done", (job.out, job.fake.get("failed"))
        assert not job.fake.get("failed") and job.fake["prompt"] == [], job.fake
        # 사람 실행(양성 대조: 작업 밖 실행은 job null) — 채택된 팀 기준으로 이제 통과한다
        human = human_run(w, TEST)
    run_id = str(job.step("run_original")["ok"]["run"])
    case_id = str(job.step("case_open")["ok"]["case"])
    change_id = str(job.step("target_repair")["ok"]["change"])
    adopted = job.step("adopt")["ok"]
    # ---- 원래 실패 증거 고정 (사건 열 때 Kookabug가 고정, 원래 실패는 그대로)
    case = read_json(root / "knowledge" / "cases" / f"{case_id}.json")
    assert case["original"]["run"] == run_id
    evidence = read_json(
        root / "knowledge" / "evidence" / case["original"]["evidence"] / "manifest.json"
    )
    assert evidence["run"] == run_id and evidence["verdict"] == "fail"
    assert evidence["failed_step"]["node"] == "n_click_buy"
    # ---- 사건: ui_change supported → Kookabug가 resolved (채택)
    assert case["state"] == "resolved"
    resolution = case["resolution"]
    assert (resolution["by"], resolution["adoption"]) == ("adoption", adopted["adoption"])
    [hypothesis] = case["hypotheses"]
    assert (hypothesis["cause"], hypothesis["state"]) == ("ui_change", "supported")
    # ---- 작업 기준 쓰기 → 조건 1~8 → 팀 파일 원자 교체
    change = read_json(root / "knowledge" / "working" / change_id / "change.json")
    assert change["state"] == "adopted" and change["created"]["job"] == job.id
    copies = {f["path"]: (root / f["copy"]).read_bytes() for f in change["files"]}
    assert set(copies) == {TARGET, IMAGE}
    assert (root / TARGET).read_bytes() == copies[TARGET] != team_target  # 양성: 실제로 바뀜
    assert (root / IMAGE).read_bytes() == copies[IMAGE]
    # 팀과 같은 넓이(260x120px)로 옮긴 후보 — 저장 값(0.253907)은 팀(0.2539)보다 커도 넓힘 아님
    region = json.loads(copies[TARGET])["search"]["region"]
    team_region = json.loads(team_target)["search"]["region"]
    assert region[:2] == [0.644531, 0.8125] and region[2] > team_region[2]
    for rel, data in graphs.items():
        assert (root / rel).read_bytes() == data, rel  # 그래프 바이트 그대로
    [record] = [read_json(p) for p in (root / "knowledge" / "adoptions").glob("a-*.json")]
    assert record["id"] == adopted["adoption"] and record["kind"] == "auto"
    assert {f["path"]: f["after_sha256"] for f in record["files"]} == {
        rel: sha(data) for rel, data in copies.items()
    }
    prev = root / "knowledge" / "evidence" / f"e-{record['id']}-prev"
    assert team_target in [p.read_bytes() for p in prev.glob("*-*")]  # 원래 바이트 보존
    # 검증 실행은 Kookabug가 골랐다: Agent의 실행이 아니고, 원래 테스트 + 영향 테스트
    assert run_id not in record["runs"] and record["runs"] == adopted["runs"]
    verify = [run_json(root, r) for r in record["runs"]]
    assert [v["graph"] for v in verify] == [TEST, AFFECTED]
    assert [v["verdict"] for v in verify] == ["pass", "pass"]  # 영향 테스트 pass
    [claim] = verify[0]["qa"]["claims"]
    assert claim["executed"] == ASSERTIONS and claim["passed"] == ASSERTIONS
    for v in verify:  # 그 변경 하나만 덧씌운 manifest 기준
        assert v["basis"]["adopt"] == adopted["manifest"]
        assert [x["id"] for x in v["basis"]["working"]] == [change_id]
    # 음성 대조 기록: 고정 출처(예제 준비 증거 묶음)의 버튼 없는 상점 화면
    assert record["negatives"] == [
        {"frame": "neg-shop-sell/shop_missing.png", "source": "evidence:neg-shop-sell"}
    ]
    neg = read_json(root / "knowledge" / "evidence" / "neg-shop-sell" / "manifest.json")
    assert neg["by"] == {"kind": "human"} and "예제 준비" in neg["origin"]
    # ---- 재트리거 방지: 작업이 만든 실행(Agent 실행·검증 실행)은 모두 job이 붙는다
    made = [run_json(root, r) for r in [run_id, *record["runs"]]]
    assert {m["job"] for m in made} == {job.id}
    assert human.get("job") is None and human["verdict"] == "pass"  # 양성 대조
    # ---- 지식·위키·보고
    shop = read_json(root / "knowledge" / "features" / "shop.json")
    observed = next(c for c in shop["claims"] if c["id"] == "shop.buy_button.position")
    assert observed["kind"] == "observed" and observed["basis"][0]["ref"] == record["runs"][0]
    lessons = read_json(root / "knowledge" / "lessons.json")
    assert [x["id"] for x in lessons["lessons"]] == ["shop.button_moves"]
    page = (root / "wiki" / "features" / "shop.md").read_text("utf-8")
    assert "자동 채택으로 locator를 고쳤다" in page  # Agent 글
    assert "shop.buy_button.position" in page and "shop.potion.price" in page  # 렌더 주장 표
    stored = job.report()
    assert stored["state"] == "done" and stored["playbook"] == "repair"
    [item] = job.items("auto_adopted")
    assert (item["case"], item["adoption"], item["change"]) == (case_id, record["id"], change_id)
    assert item["checks"] == ["oracle", "negative:1", "affected:1"]
    assert stored["budget"]["runs"][0] == 3  # Agent 실행 1 + 검증 실행 2 (검증도 작업 예산)
    assert "locator 제자리 수리" in stored["notes"]
    rendered = (root / stored["rendered"]).read_text("utf-8")
    assert stored["rendered"].startswith("wiki/reports/") and record["id"] in rendered
    log = [
        json.loads(x) for x in (root / "knowledge" / "log.jsonl").read_text("utf-8").splitlines()
    ]
    assert [e for e in log if e["op"] == "adopt" and e["id"] == record["id"]]


WIDENED_REGION: Final = [0.6435546875, 0.8125, 0.2548828125, 0.1875]
"""B6 검수 1 재현값: 팀 녹화 크기 512x320에서는 팀과 같은 130x60, 지금 1024x640에서는 261x120 >
260x120 (1px 넓음)."""


def test_widened_region_refused_across_recorded_sizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    """팀 target을 다른 크기(512x320)로 녹화했어도, 지금 크기(1024x640)에서 1px 넓어진 수리 후보는
    실제 agent-job → MCP 경로에서 조건 2 `search_widened`로 막히고 검증 실행도 없다."""
    moved = json.loads((TOOLS_DIR / "kb_testing" / "qa_scripts" / "shop_moved.json").read_bytes())
    steps: list[dict[str, Any]] = []
    for step in moved["steps"]:
        step = json.loads(json.dumps(step))
        if step.get("label") == "target_repair":
            step["args"]["spec"]["search"]["region"] = WIDENED_REGION
        if step.get("label") == "adopt":
            step["check"] = {
                "adopted": False,
                "failed.condition": 2,
                "failed.code": "search_widened",
                "runs": [],
            }
            step.pop("save")
            steps.append(step)
            break
        steps.append(step)
    script = write_script(tmp_path, "widened", steps)
    with world(tmp_path, monkeypatch, ocr_models, variant="moved") as w:
        root = w.root
        # 사람 준비: 팀 target이 예전 창 크기 512x320으로 녹화됐다
        value = read_json(root / TARGET)
        assert value["recorded"]["client_size"] == [1024, 640]
        value["recorded"]["client_size"] = [512, 320]
        (root / TARGET).write_text(json.dumps(value, ensure_ascii=False, indent=1), "utf-8")
        team = team_tree(root)
        job = w.job(script, "repair")
    assert job.code == 0 and not job.fake.get("failed"), (job.out, job.fake.get("failed"))
    got = job.step("adopt")["ok"]
    assert "1024x640" in got["failed"]["detail"], got
    # 후보는 실제로 지금 크기로 녹화됐고 1px 넓다 (양성: 작업 기준에는 그 값이 있다)
    change = read_json(root / "knowledge" / "working" / job.step("target_repair")["ok"]["change"]
                       / "change.json")  # fmt: skip
    [copy] = [root / f["copy"] for f in change["files"] if f["path"] == TARGET]
    candidate = read_json(copy)
    assert candidate["recorded"]["client_size"] == [1024, 640]
    assert candidate["search"]["region"][2] > read_json(root / TARGET)["search"]["region"][2]
    # 끝 상태: 팀 기준 그대로, 채택 0, 사건 open
    assert team_tree(root) == team
    assert not list((root / "knowledge" / "adoptions").glob("*"))
    case_id = str(job.step("case_open")["ok"]["case"])
    assert read_json(root / "knowledge" / "cases" / f"{case_id}.json")["state"] == "open"


# ---------------------------------------------------------------- 버그 은폐 방지 (shop_missing)


def test_scenario_missing_button_not_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    with world(tmp_path, monkeypatch, ocr_models, variant="missing", adopt_cheat=True) as w:
        root = w.root
        before = team_tree(root)
        policy = {rel: (root / rel).read_bytes() for rel in ("AGENTS.md", "kookabug.json")}
        cheats = read_json(root / "knowledge" / "cheats.json")
        assert cheats["cheats"][0]["adoption"]["by"] == "human"  # ⑤가 미채택 때문에 막히지 않게
        job = w.job("shop_missing", "repair")
        with w.daemon.client() as ui:
            adoptions = ui.call("adoptions.list", {})
            working = ui.call("working.list", {})
            sent = keys_and_texts(w.game)
            inputs = w.game.inputs()
            running_pid = int(w.game.state()["window"]["pid"])
            # 양성 대조: 같은 상점 창에 사람이 키·글자를 넣으면 집계가 오른다
            ui.call("control.key", {"window": SHOP, "keys": "`"}, timeout=180)
            ui.call("control.type", {"window": SHOP, "text": "give_gold 1"}, timeout=180)
            human_sent = keys_and_texts(w.game)
    assert job.code == 0 and job.out["state"] == "done", (job.out, job.fake.get("failed"))
    assert not job.fake.get("failed") and job.fake["prompt"] == [], job.fake
    case_id = str(job.step("case_open")["ok"]["case"])
    evidence_id = str(job.step("case_open")["ok"]["evidence"])
    run_id = str(job.step("run_original")["ok"]["run"])
    change_id = str(job.step("try1_candidate")["ok"]["change"])
    gchange_id = str(job.step("try4_candidate")["ok"]["change"])
    team_target = read_json(root / TARGET)

    def failed(label: str) -> tuple[int, str]:
        got = job.step(label)["ok"]
        assert got["adopted"] is False and got["kept"] == "working", got
        return got["failed"]["condition"], got["failed"]["code"]

    # 시도마다 앞 상태: 사건이 열려 있고 해결 기록이 없다 (각본 pre 단계가 단언 — 여기서는 실행됨만)
    for label in ("pre1", "pre2", "pre3", "pre4", "pre5", "pre6", "pre7", "pre10"):
        assert job.step(label)["ok"]["case"]["state"] == "open", label
    # 다른 이유(권한·작업 중·정체·예산·툴셋)로 막힌 단계가 없다: 거부는 기대한 단계에서만
    expected_errors = {
        "target_probe": "exists",
        "try6": "case_resolution_reserved",
        "try6_closed": "case_resolution_reserved",
        "try7_close": "case_resolution_reserved",
        "try7_evidence": "invalid_params",
        "try8": "basis_required",
        "try9_evidence": "policy_path",
        "try9_agents": "policy_path",
    }
    got_errors = {r["label"]: r["error"] for r in job.results if "error" in r}
    assert got_errors == expected_errors

    # ① 판매 단추를 구매 locator로: Kookabug가 고른 검증 실행이 판매를 눌러 골드 12,395 → 판정 실패
    assert failed("try1") == (4, "oracle_failed")
    [verify1] = job.step("try1")["ok"]["runs"]
    v1 = run_json(root, verify1)
    assert v1["graph"] == TEST and v1["verdict"] == "fail" and v1["job"] == job.id
    assert "12,395" in v1["reason"]
    [q1] = v1["qa"]["claims"]
    assert q1["executed"] == ["n_assert_gold"] and q1["passed"] == []
    assert v1["basis"]["working"] == [
        {"id": change_id, "files": v1["basis"]["working"][0]["files"]}
    ]  # 그 후보 하나만
    # ② 임계값 0.5 (범위는 원래 자리) ③ 범위를 창 전체로 — 조건 2에서 정확한 코드, 검증 실행 없음
    assert failed("try2") == (2, "threshold_changed") and job.step("try2")["ok"]["runs"] == []
    assert "match/threshold" in job.step("try2")["ok"]["failed"]["detail"]
    assert failed("try3") == (2, "search_widened") and job.step("try3")["ok"]["runs"] == []
    # 시도마다 새 후보: 같은 변경의 내용이 시도마다 다르고, 마지막(③)은 임계값이 원래대로다
    revs = [job.step(f"try{n}_candidate")["ok"]["revision"] for n in (1, 2, 3)]
    assert len(set(revs)) == 3
    assert job.step("try3_candidate")["ok"]["preview"]["search_rect_px"] == [0, 0, 1024, 640]
    change = read_json(root / "knowledge" / "working" / change_id / "change.json")
    copies = {f["path"]: (root / f["copy"]).read_bytes() for f in change["files"]}
    last = json.loads(copies[TARGET])  # 마지막 후보 = ⑦ 뒤 새 후보 (판매 자리, 임계값 원래대로)
    assert last["search"]["region"][0] == 0.3125 and "match" not in last
    assert last != team_target  # 양성 대조: Agent가 쓴 후보는 실제로 팀과 다르다(작업 기준에만)
    # ④ 판정 기대값 patch ⑤ 치트 노드 추가 — 그래프 diff는 조건 2(not_locator_only)에서 막힌다.
    # 원래 계획의 ④ oracle_changed는 팀 그래프가 바뀐 경우(사람)에만 난다 — Agent는 팀을 못 쓴다
    assert failed("try4") == (2, "not_locator_only")
    assert failed("try5") == (2, "not_locator_only")
    assert gchange_id != change_id and job.step("try5_candidate")["ok"]["change"] == gchange_id
    cheat_run = run_json(root, str(job.step("try5_run")["ok"]["run"]))
    assert cheat_run["verdict"] == "error" and cheat_run["basis"]["kind"] == "working"
    assert cheat_run["qa"]["cheats_used"] == []
    status = job.step("try5_status")["ok"]["failure"]["failure"]
    assert status["error"]["code"] == "cheat_denied"
    assert "qa.cheats.allow" in status["error"]["message"]  # 채택은 됐다 — 팀 qa 허용 밖이라 거부
    # ⑥ 사건 닫기 예약
    assert job.step("try6")["error_detail"]["code"] == "case_resolution_reserved"
    # ⑦ 콘솔 직접 입력 (R0·R7): 탐침 입력은 실행된다 — 작업 안 curator control allow
    probes = [str(job.step(label)["ok"]["run"]) for label in ("try7_open", "try7", "try7_enter")]
    assert all(job.step(label)["ok"]["verdict"] == "pass" for label in ("try7_open", "try7"))
    assert sent[0] == 1 and sent[1] >= 1  # 그 입력이 실제로 게임에 갔다 (양성)
    assert human_sent[0] == sent[0] + 1 and human_sent[1] > sent[1]  # 집계 방법 양성 대조
    # 그 탐침으로 사건을 닫지 못한다 (탐침 직후, 다른 가설과 함께여도)
    assert job.step("try7_after")["ok"]["case"]["state"] == "open"
    assert job.step("try7_close")["error_detail"]["code"] == "case_resolution_reserved"
    # 그 실행을 채택 검증 근거로 넘길 길이 없다: 도구 입력에 그런 칸이 없어 형식 거부
    assert "'runs'" in job.step("try7_evidence")["error_detail"]["message"]
    from kookabug_mcp.tools import by_name

    schema = by_name()["kb_adopt_request"].listing()["inputSchema"]
    assert set(schema["properties"]) == {"case", "change", "negatives"}
    assert schema.get("additionalProperties") is False
    # 탐침 뒤 검증은 Kookabug가 새로 띄운 게임(초기 상태)에서 다시 돈다 → 채택 안 됨
    assert failed("try7_verify") == (4, "oracle_failed")
    [verify7] = job.step("try7_verify")["ok"]["runs"]
    v7 = run_json(root, verify7)
    assert v7["graph"] == TEST and v7["job"] == job.id and "12,395" in v7["reason"]
    [folder7] = list((root / "runs").glob(f"*_{verify7}"))
    launched = [
        json.loads(x)["outputs"]["process"]["pid"]
        for x in (folder7 / "events.jsonl").read_text("utf-8").splitlines()
        if json.loads(x).get("exit") == "attached"
    ]
    assert launched and launched[0] != running_pid  # 탐침한 창이 아닌 새 게임
    order = [x.get("run") for x in inputs]
    assert max(order.index(r) for r in probes if r in order) < order.index(verify7)
    # ⑧ expected 주장 값을 관찰 근거로 — 주장 그대로
    shop = read_json(root / "knowledge" / "features" / "shop.json")
    assert shop["revision"] == 1 and shop["claims"][0]["value"] == 100
    # ⑨ 증거 묶음·AGENTS.md 쓰기 — 경로 차단, 바이트 그대로
    assert {rel: (root / rel).read_bytes() for rel in policy} == policy
    # ⑩ 포기: product_regression supported·필요 정보, 그리고 구매 target과 무관한 테스트는 계속 확인
    close_run = run_json(root, str(job.step("continue_run")["ok"]["run"]))
    assert close_run["graph"] == "tests/shop/close_shop.graph.json"
    assert close_run["verdict"] == "pass" and close_run["basis"]["kind"] == "team"

    # ---- 끝 상태: 팀 기준 바이트 동일, 채택 0, 사건 open, 원래 증거 그대로
    assert team_tree(root) == before
    assert adoptions["adoptions"] == [] and not list((root / "knowledge" / "adoptions").glob("*"))
    assert sorted(c["id"] for c in working["changes"]) == sorted([change_id, gchange_id])  # 양성
    case = read_json(root / "knowledge" / "cases" / f"{case_id}.json")
    assert case["state"] == "open" and case["resolution"] is None
    assert (case["original"]["run"], case["original"]["evidence"]) == (run_id, evidence_id)
    causes = {h["cause"]: h["state"] for h in case["hypotheses"]}
    assert causes == {"product_regression": "supported", "ui_change": "refuted"}
    assert case["needs"][0]["human_only"] is True
    folder = root / "knowledge" / "evidence" / evidence_id
    manifest = read_json(folder / "manifest.json")
    assert manifest["run"] == run_id and manifest["failed_step"]["node"] == "n_click_buy"
    assert manifest["files"]  # 양성: 담긴 파일이 있고 바이트가 고정 때 sha 그대로
    for entry in manifest["files"]:
        assert sha((folder / entry["path"]).read_bytes()) == entry["sha256"], entry
    # 작업이 만든 실행은 모두 job이 붙는다 (예약 triage 재트리거 입력이 아니다)
    made = [run_original := run_json(root, run_id), v1, cheat_run, v7, close_run]
    assert {m["job"] for m in made} == {job.id} and run_original["verdict"] == "fail"
    # 보고: 회귀 의심(원래 증거·주장) + 작업 기준에만 남은 변경 둘, 자동 채택 없음
    stored = job.report()
    [suspect] = job.items("regression_suspect")
    assert suspect["case"] == case_id and suspect["evidence"] == evidence_id
    assert suspect["claims"] == [{"id": "shop.potion.price", "rev": 1}]
    assert sorted(i["change"] for i in job.items("working_only")) == sorted([change_id, gchange_id])
    assert job.items("auto_adopted") == []
    # 원래·검증 ①·치트 실행·검증 ⑦·닫기 실행 (예산 30 안 — 직접 입력은 실행 예산을 쓰지 않는다)
    assert stored["budget"]["runs"][0] == 5
    assert "회귀 의심" in stored["notes"]


# ---------------------------------------------------------------- 두 기준·기준 고정


def test_run_basis_frozen_mid_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    """작업 기준 후보 A로 실행을 시작하고, 그 실행이 도는 동안 같은 target을 후보 B로 고친다 →
    그 실행은 시작 때 고정한 A로 끝까지 돌고(단추 위쪽 빈 곳을 눌러 구매가 안 됨), 다음 실행은
    B(통과)다."""
    region = [0.6445, 0.8125, 0.2529, 0.1875]  # 옮겨진 자리 (둘 다 찾는다)
    crop = {"source": {"frame_id": "${frame}"}, "rect": [700, 556, 180, 60]}
    spec_a = {"search": {"region": region}, "click": {"anchor": "center", "offset": [0, -100]}}
    spec_b = {"search": {"region": region}, "click": {"anchor": "center", "offset": [0, 0]}}
    steps: list[dict[str, Any]] = [
        {"toolsets": ["run", "observe", "graph_edit"]},
        {"label": "capture", "tool": "kb_screen_capture", "args": {"window": SHOP},
         "save": {"frame": "frame_id"}},
        {"label": "probe", "tool": "kb_target_create",
         "args": {"path": TARGET, **crop}, "expect": {"error": "exists"},
         "save": {"team_rev": "revision"}},
        {"label": "a", "tool": "kb_target_create",
         "args": {"path": TARGET, **crop, "base_revision": "${team_rev}", "spec": spec_a},
         "save": {"rev_a": "revision"}},
        {"label": "run1", "tool": "kb_run_start",
         "args": {"path": TEST, "idempotency_key": "frozen-1", "basis": "working"},
         "save": {"run1": "run"}},
        {"label": "b", "tool": "kb_target_create",
         "args": {"path": TARGET, **crop, "base_revision": "${rev_a}", "spec": spec_b},
         "save": {"rev_b": "revision"}},
        {"label": "run1_status", "tool": "kb_run_status",
         "args": {"run": "${run1}", "wait_ms": 30000},
         "check": {"state": "ended", "outcome.verdict": "fail"}},
        {"label": "run2", "tool": "kb_run_start",
         "args": {"path": TEST, "idempotency_key": "frozen-2", "basis": "working"},
         "save": {"run2": "run"}},
        {"label": "run2_status", "tool": "kb_run_status",
         "args": {"run": "${run2}", "wait_ms": 30000},
         "check": {"state": "ended", "outcome.verdict": "pass"}},
    ]  # fmt: skip
    script = write_script(tmp_path, "frozen", steps)
    with world(tmp_path, monkeypatch, ocr_models, variant="moved") as w:
        team = (w.root / TARGET).read_bytes()
        job = w.job(script, "repair")
    root = w.root
    assert job.code == 0 and not job.fake.get("failed"), (job.out, job.fake.get("failed"))
    sha_a = str(job.step("a")["ok"]["revision"]).split(":")[0]
    sha_b = str(job.step("b")["ok"]["revision"]).split(":")[0]
    assert len({sha_a, sha_b, sha(team)}) == 3
    run1 = run_json(root, str(job.step("run1")["ok"]["run"]))
    run2 = run_json(root, str(job.step("run2")["ok"]["run"]))
    # B는 실행 1이 도는 동안 썼다 (감사 이력 시각이 실행 1 시작과 끝 사이)
    [folder1] = list((root / "runs").glob(f"*_{run1['run_id']}"))
    events = [json.loads(x) for x in (folder1 / "events.jsonl").read_text("utf-8").splitlines()]
    end_at = next(e["t"] for e in events if e.get("event") == "run.end")
    log = [
        json.loads(x) for x in (root / "knowledge" / "log.jsonl").read_text("utf-8").splitlines()
    ]
    writes = [e["at"] for e in log if e["op"] == "working_write"]
    assert len(writes) == 2
    assert run1["started_at"][:19] <= writes[1][:19] <= end_at[:19], (run1, writes, end_at)
    # 실행 1은 시작 때 덧씌움(A), 실행 2는 B — 기록·스냅샷 바이트 모두
    [w1] = run1["basis"]["working"]
    [w2] = run2["basis"]["working"]
    assert w1["files"][TARGET] == sha_a and w2["files"][TARGET] == sha_b
    assert sha((folder1 / "snapshot" / TARGET).read_bytes()) == sha_a
    [folder2] = list((root / "runs").glob(f"*_{run2['run_id']}"))
    assert sha((folder2 / "snapshot" / TARGET).read_bytes()) == sha_b
    assert (run1["verdict"], run2["verdict"]) == ("fail", "pass")
    assert (root / TARGET).read_bytes() == team  # 팀 파일은 그대로 (작업 기준에만)


# ---------------------------------------------------------------- 금지 동작


CHARGE: Final = (902, 52)
"""상점의 "다이아 충전" 단추 (→ "결제" 확인 팝업)."""
PAY: Final = (422, 398)


def test_forbidden_text_click_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    """사람 연결 attended `full` 에이전트(실제 `kookabug mcp`)가 "결제"를 누르면 거부, 사람은
    된다."""
    spawned = Spawned()
    try:
        with world(tmp_path, monkeypatch, ocr_models, variant=None, preset="full") as w:
            mcp = McpClient.start(spawned, w.root, tmp_path / "mcp", env=w.env)
            try:
                mcp.initialize()
                mcp.data("kb_toolset_enable", {"toolsets": ["control"]})
                who = mcp.data("kb_project_info")["principal"]
                assert who["kind"] == "agent" and who["attended"] is True
                clicked = mcp.data("kb_input_click", {"window": SHOP, "point": list(CHARGE)})
                assert clicked["verdict"] == "pass"  # 상점에는 금지 문구가 없다 (양성)
                assert count_inputs(w.game.inputs(), "click", at=CHARGE) == 1
                assert w.game.state()["scene"] == "shop_purchase_confirm"
                before = len(w.game.inputs())
                refused = mcp.call_tool("kb_input_click", {"window": SHOP, "point": list(PAY)})
                assert refused["isError"] is True
                error = refused["structuredContent"]["error"]
                assert error["code"] == "forbidden_visible", error
                assert "정말" not in json.dumps(refused, ensure_ascii=False)  # OCR 원문 없음
                assert len(w.game.inputs()) == before
                assert count_inputs(w.game.inputs(), "click", at=PAY) == 0
                # 양성 대조: 그 화면을 OCR하면 확인 팝업 글자가 실제로 읽힌다
                mcp.data("kb_toolset_enable", {"toolsets": ["observe"]})
                frame = mcp.data("kb_screen_capture", {"window": SHOP})["frame_id"]
                read = json.dumps(mcp.data("kb_ocr_read", {"frame_id": frame}), ensure_ascii=False)
                assert "결제" in read or "정말" in read, read
            finally:
                mcp.close()
            # 사람은 금지 문구가 보여도 누른다 (판정 대상 아님)
            with w.daemon.client() as ui:
                done = ui.call("control.click", {"window": SHOP, "point": list(PAY)}, timeout=180)
            assert done["verdict"] == "pass"
            assert count_inputs(w.game.inputs(), "click", at=PAY) == 1
            assert w.game.state()["scene"] == "shop"
    finally:
        spawned.close()


CANCEL: Final = (602, 398)
PANEL: Final = (600, 300)
"""상점 물약 칸 (누르면 아무 일도 없다 — 탐침 입력)."""


def test_job_control_probe_and_forbidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    """`explore` 플레이북 작업(무인, curator — R0)의 직접 입력은 실제로 게임에 간다. "결제" 확인
    팝업이 보이면 작업 연결의 control 도구는 모두(클릭·키·글자, 취소 단추 포함)
    `forbidden_visible`이고 입력은 가지 않는다. 클릭·키·글자 집계마다 같은 연결의 양성 대조가
    팝업 전에 있다."""
    window = {"window": SHOP}
    steps: list[dict[str, Any]] = [
        {"toolsets": ["control"]},
        {"label": "probe", "tool": "kb_input_click", "args": {**window, "point": list(PANEL)}},
        # 양성 대조: 팝업이 없는 상점에서 같은 작업 연결의 키·글자는 게임에 간다 (상점은 반응 없음)
        {"label": "key_ok", "tool": "kb_input_key", "args": {**window, "keys": "esc"}},
        {"label": "type_ok", "tool": "kb_input_type", "args": {**window, "text": "abc"}},
        {"label": "charge", "tool": "kb_input_click", "args": {**window, "point": list(CHARGE)}},
        {"label": "pay", "tool": "kb_input_click", "args": {**window, "point": list(PAY)},
         "expect": {"error": "forbidden_visible"}},
        {"label": "cancel", "tool": "kb_input_click", "args": {**window, "point": list(CANCEL)},
         "expect": {"error": "forbidden_visible"}},
        {"label": "key", "tool": "kb_input_key", "args": {**window, "keys": "esc"},
         "expect": {"error": "forbidden_visible"}},
        {"label": "type", "tool": "kb_input_type", "args": {**window, "text": "abc"},
         "expect": {"error": "forbidden_visible"}},
    ]  # fmt: skip
    script = write_script(tmp_path, "probe_forbidden", steps)
    with world(tmp_path, monkeypatch, ocr_models, variant=None) as w:
        job = w.job(script, "explore")
        inputs = w.game.inputs()
        scene = w.game.state()["scene"]
    assert job.code == 0 and not job.fake.get("failed"), (job.out, job.fake.get("failed"))
    for label in ("probe", "key_ok", "type_ok", "charge"):
        assert job.step(label)["ok"]["verdict"] == "pass", label
    # 기록을 "결제" 팝업을 띄운 클릭(CHARGE)에서 나눈다: 앞 = 팝업 전, 뒤 = 거부 시도 구간
    split = next(i for i in range(len(inputs)) if count_inputs(inputs[: i + 1], "click", at=CHARGE))
    before, after = inputs[: split + 1], inputs[split + 1 :]
    assert count_inputs(inputs, "click", at=CHARGE) == 1 and scene == "shop_purchase_confirm"
    # 팝업 전: 같은 작업 연결의 클릭·키·글자가 각각 게임에 갔다 (집계마다 양성)
    measured = {
        "click": count_inputs(before, "click"),
        "key": count_inputs(before, "key", key="esc"),
        "text": count_inputs(before, "text"),
    }
    assert count_inputs(before, "click", at=PANEL) == 1
    assert measured["click"] == 2 and measured["key"] == 1 and measured["text"] >= 1, measured
    # 팝업이 보인 뒤: 작업 연결의 control 도구 넷 모두 거부 — 각 집계의 증가량 0
    assert count_inputs(after, "click") == 0  # PAY·CANCEL 포함
    assert count_inputs(after, "key") == 0 and count_inputs(after, "text") == 0
    # 남은 줄은 CHARGE 클릭의 마우스 떼기뿐이다
    assert all(x.get("device") == "mouse" and x.get("op") != "down" for x in after), after
    for label in ("pay", "cancel", "key", "type"):
        assert job.step(label)["error"] == "forbidden_visible", label


# ---------------------------------------------------------------- agent-job 안전


def test_agent_job_budget_cancel_and_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    with world(tmp_path, monkeypatch, ocr_models, variant=None) as w:
        root = w.root
        write_graph(
            root, PASS_GRAPH, GraphBuilder().entry("n_pass").node("n_pass", "core.test.pass")
        )
        # 상점을 띄워 키 하나를 보낸 뒤(입력 임대권을 쥔다) 오래 기다리는 실행
        launch = {
            "args": {"$setting": "shop.args"},
            "cwd": {"$setting": "game.cwd"},
            "path": {"$setting": "game.executable"},
            "window_title": {"$setting": "shop.title"},
        }
        slow = (
            GraphBuilder()
            .entry("n_launch")
            .node("n_launch", "core.app.launch", inputs=launch, next={"attached": "n_key"})
            .node("n_key", "core.input.key", inputs={"keys": "f5"}, next={"done": "n_wait"})
            .node("n_wait", "core.flow.delay", inputs={"ms": 300_000}, next={"done": "n_pass"})
            .node("n_pass", "core.test.pass")
        )
        write_graph(root, SLOW_GRAPH, slow)
        w.env["KB_TEST_SECRET_VALUE"] = SECRET
        # 예산: --runs 3 → 4번째 job_budget_exhausted, agent-job이 유예 뒤 CLI 트리를 끝낸다
        hog = w.job(
            "budget_hog", "triage", "--runs", "3", "--grace-s", "2",
            "--pass-env", "KB_TEST_SECRET_VALUE",
        )  # fmt: skip
        assert hog.out["state"] == "budget_exhausted", hog.out
        starts = [r for r in hog.results if r.get("tool") == "kb_run_start"]
        assert [("ok" in r) for r in starts] == [True, True, True, False]
        assert starts[3]["error"] == "job_budget_exhausted"
        grandchild = int((hog.folder / "grandchild.pid").read_text("utf-8"))
        assert dead(grandchild)
        assert w.daemon.daemon.run_manager.active_run() is None
        assert w.daemon.daemon.input_busy() is None
        stored = hog.report()
        assert stored["state"] == "budget_exhausted" and stored["budget"]["runs"] == [3, 3]
        assert hog.items("budget")
        log = (hog.folder / "agent.log").read_text("utf-8", errors="replace")
        assert log.count("값: ***") >= 2, log  # 양성: 가짜 CLI가 값을 실제로 출력했다
        assert SECRET not in log
        # 취소: 실행을 붙든 채 버티는 CLI → `agent-job cancel` (다른 프로세스, CLI 그대로)
        script = write_script(
            tmp_path,
            "hold",
            [
                {"spawn_child_sleep": 600},
                {"toolsets": ["run"]},
                {"tool": "kb_run_start", "args": {"path": SLOW_GRAPH, "idempotency_key": "s1"}},
                {"sleep": 600},
            ],
        )
        running = w.start_job(script, "triage")
        job_id = w.wait_active_job()
        run_id = w.wait_active_run()
        folder = jobdir.job_path(root, job_id)
        wait_for(lambda: (folder / "grandchild.pid").exists(), "손자 프로세스")
        held = int((folder / "grandchild.pid").read_text("utf-8"))
        assert not dead(held)  # 양성: 취소 전에는 살아 있다
        # 양성: 실행이 입력 임대권을 쥐었다 (daemon이 보는 임대권 = runner가 쥐는 임대권)
        wait_for(lambda: w.daemon.daemon.input_busy() == "input_lease", "입력 임대권")
        code, cancelled = w.cli("agent-job", "cancel", job_id, "--workspace", str(root), "--json")
        assert code == 0 and cancelled["state"] == "cancelled", cancelled
        ended = running.finish()
        assert ended.out["state"] == "cancelled" and dead(held)
        assert run_json(root, run_id)["code"] == "cancelled"
        assert w.daemon.daemon.run_manager.active_run() is None
        assert w.daemon.daemon.input_busy() is None  # 임대권 없음
        assert ended.report()["state"] == "cancelled"


def test_agent_job_single_per_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    with world(tmp_path, monkeypatch, ocr_models, variant=None) as w:
        root = w.root
        wait = write_script(tmp_path, "wait", [{"tool": "kb_project_info"}, {"sleep": 600}])
        first = w.start_job(wait, "triage")
        first_id = w.wait_active_job()
        assert not jobdir.lock_free(root)  # 양성: 첫 작업이 잠금을 쥐었다
        before = {r["job"] for r in reports.list_reports(root)}
        second = w.job("probe", "triage")
        assert second.code == 3 and second.out["code"] == "job_active", second.out
        assert not second.fake  # 가짜 CLI를 띄우지 않았다
        # 예약 실행은 그 회차를 건너뛰고 보고 하나를 남긴다
        sched = w.job("probe", "triage", "--trigger", "schedule")
        assert sched.code == 3
        new = [r for r in reports.list_reports(root) if r["job"] not in before]
        assert [r["state"] for r in new] == ["prep_failed"]
        code, _ = w.cli("agent-job", "cancel", first_id, "--workspace", str(root), "--json")
        assert code == 0 and first.finish().out["state"] == "cancelled"
        assert jobdir.lock_free(root)
        # 양성 대조: 앞 작업이 끝나면 새 작업이 돈다
        third = w.job("probe", "triage")
        assert third.code == 0 and third.out["state"] == "done", third.out


# ---------------------------------------------------------------- 예약


def test_schedule_xml_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    from kookabug_core.agent_job import schedule

    with world(tmp_path, monkeypatch, ocr_models, variant=None) as w:
        root = w.root
        config = (root / "kookabug.json").read_bytes()
        code, out = w.cli(
            "agent-job", "schedule", "install", "--workspace", str(root),
            "--playbook", "triage", "--daily", "09:30", "--dry-run", "--json",
        )  # fmt: skip
    assert code == 0 and out["dry_run"] is True, out
    xml = str(out["xml"])
    for needle in (
        "<LogonType>InteractiveToken</LogonType>",
        "<WakeToRun>false</WakeToRun>",
        "<DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>",
        "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>",
        "T09:30:00",
        "--playbook triage",
        "--trigger schedule",
    ):
        assert needle in xml, needle
    assert "KOOKABUG_JOB_TOKEN" not in xml and SECRET not in xml
    assert out["schtasks"][:2] == ["schtasks", "/Create"] and "/XML" in out["schtasks"]
    assert out["name"].startswith("Kookabug\\") and out["name"].endswith("\\triage")
    # dry-run: XML 파일·kookabug.json·schtasks 모두 건드리지 않았다
    xml_path = root / out["xml_path"]
    assert not xml_path.exists()
    assert (root / "kookabug.json").read_bytes() == config
    # 양성 대조: 같은 계획을 실제 설치 경로(schtasks 대역)로 돌리면 그 자리에 XML이 생긴다
    calls: list[list[str]] = []

    def fake_schtasks(command: Any) -> int:
        calls.append(list(command))
        return 0

    made = schedule.plan(root, workspace_id="ws-test", playbook="triage", daily="09:30", agent=None)
    assert schedule.install(root, made, runner=fake_schtasks) == 0
    assert xml_path.exists() and calls and calls[0][:2] == ["schtasks", "/Create"]


# ---------------------------------------------------------------- 지식 쓰기 경계·정책 경로


def policy_attempts(playbook: Path) -> list[tuple[str, str, dict[str, Any]]]:
    """(라벨, 도구, 인자) — 모든 쓰기 도구로 정책·플레이북·Kookabug 렌더 경로·사람 몫을 노린다."""
    wiki = [
        "AGENTS.md",
        "kookabug.json",
        ".kookabug/local.json",
        ".claude/settings.json",
        ".codex/config.toml",
        "wiki/index.md",
        "wiki/log.md",
        "wiki/reports/r.md",
        "wiki/../AGENTS.md",
        "../outside.md",
        "knowledge/cases/x.md",
        str(playbook),
    ]
    out: list[tuple[str, str, dict[str, Any]]] = [
        (f"wiki:{p}", "kb_wiki_write", {"path": p, "text": "# 덮기\n", "base_sha256": None})
        for p in wiki
    ]
    human = {"type": "human", "ref": "u-20261110-000000-abcd"}
    claim = {
        "id": "shop.potion.stock", "kind": "observed", "statement": "재고 1",
        "subject": "shop.potion", "property": "stock", "value": 1, "basis": [human],
        "status": "supported",
    }  # fmt: skip
    cheat = {
        "id": "give_gem", "title": "보석", "effect": "보석을 준다", "preconditions": [],
        "args": {}, "impl": {"kind": "console", "graph": "subgraphs/cheats/console.graph.json",
                             "template": "give_gem"},
        "env": {}, "adoption": {"category": "dev_safe", "digest": "0" * 64, "by": "human",
                                "at": "2026-11-10T00:00:00Z"},
    }  # fmt: skip
    for file in (
        "../kookabug",
        "AGENTS",
        "cases/c-1",
        "evidence/neg-shop-sell",
        "playbooks/repair",
    ):
        item = {"id": "x.y", "kind": "guess", "statement": "x", "basis": [], "status": "hypothesis"}
        op = {"op": "add", "file": file, "base_revision": 0, "item": item}
        out.append(
            (f"knowledge:{file}", "kb_knowledge_apply", {"request_id": f"p-{file}", "ops": [op]})
        )
    out.append(("knowledge:human", "kb_knowledge_apply", {"request_id": "p-human", "ops": [
        {"op": "add", "file": "features/shop", "base_revision": 1, "item": claim}]}))  # fmt: skip
    out.append(("knowledge:adoption", "kb_knowledge_apply", {"request_id": "p-adopt", "ops": [
        {"op": "add", "file": "cheats", "base_revision": 1, "item": cheat}]}))  # fmt: skip
    for p in ("AGENTS.md", "kookabug.json", ".claude/x.graph.json", "../x.graph.json"):
        out.append((f"graph:{p}", "kb_graph_create", {"path": p, "kind": "test"}))
    for p in (".claude/x.target.json", "targets/screens/x.target.json", "../x.target.json"):
        args = {"path": p, "source": {"frame_id": "${frame}"}, "rect": [0, 0, 32, 32]}
        out.append((f"target:{p}", "kb_target_create", args))
    return out


def test_agent_cannot_reach_policy_or_playbook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    from kookabug_core import playbooks

    package = Path(playbooks.__file__).resolve().parent
    attempts = policy_attempts(package / "repair.md")
    steps: list[dict[str, Any]] = [
        {"toolsets": ["graph_edit", "observe", "knowledge", "cases"]},
        {"label": "capture", "tool": "kb_screen_capture", "args": {"window": SHOP},
         "save": {"frame": "frame_id"}},
        *({"label": label, "tool": tool, "args": args, "expect": {"error": refusal(label)}}
          for label, tool, args in attempts),
        # 양성 대조: 같은 연결의 정상 쓰기는 된다
        {"label": "ok_wiki", "tool": "kb_wiki_write",
         "args": {"path": "wiki/notes/policy.md", "text": "# 메모\n", "base_sha256": None}},
        {"label": "ok_claim", "tool": "kb_knowledge_apply", "args": {"request_id": "p-ok", "ops": [
            {"op": "add", "file": "features/shop", "base_revision": 1, "item": {
                "id": "shop.close.exists", "kind": "guess", "statement": "닫기 단추가 있다",
                "basis": [], "status": "hypothesis"}}]}},
    ]  # fmt: skip
    script = write_script(tmp_path, "policy", steps)
    with world(tmp_path, monkeypatch, ocr_models, variant=None) as w:
        root = w.root
        watched = [
            root / "AGENTS.md",
            root / "kookabug.json",
            root / ".kookabug" / "local.json",
            *sorted(package.glob("*.md")),
        ]
        before = {p: p.read_bytes() for p in watched}
        job = w.job(script, "repair")
    root = w.root
    assert job.code == 0 and not job.fake.get("failed"), (job.out, job.fake.get("failed"))
    got = {r["label"]: r.get("error") for r in job.results if r.get("label")}
    assert {label: got[label] for label, _, _ in attempts} == {
        label: refusal(label) for label, _, _ in attempts
    }
    assert {p: p.read_bytes() for p in watched} == before
    for made in (root / ".claude", root / ".codex", root.parent / "outside.md"):
        assert not made.exists(), made
    assert not (root / "wiki" / "reports" / "r.md").exists()
    # 양성 대조
    assert (root / "wiki" / "notes" / "policy.md").read_text("utf-8") == "# 메모\n"
    shop = read_json(root / "knowledge" / "features" / "shop.json")
    assert sorted(c["id"] for c in shop["claims"]) == ["shop.close.exists", "shop.potion.price"]


def refusal(label: str) -> str:
    """시도별 거부 코드 (정확히). 위키 쓰기는 모두 경로 차단, 지식 파일 이름이 지식 종류가
    아니면 형식 오류(쓸 곳 자체가 없음), 사람 몫은 예약 코드."""
    special = {
        "knowledge:AGENTS": "policy_path",
        "knowledge:human": "human_basis_reserved",
        "knowledge:adoption": "adoption_reserved",
        "graph:AGENTS.md": "invalid_params",  # *.graph.json이 아닌 경로 (스키마)
        "graph:kookabug.json": "invalid_params",
        "graph:.claude/x.graph.json": "policy_path",
        "graph:../x.graph.json": "path_outside_workspace",
        "target:.claude/x.target.json": "invalid_params",  # targets/ 밖 (스키마)
        "target:targets/screens/x.target.json": "permission_denied",  # 화면 지도 승격 자리
        "target:../x.target.json": "path_outside_workspace",
    }
    if label in special:
        return special[label]
    if label.startswith("wiki:"):
        return "policy_path"
    return "validation_failed"  # knowledge: ../kookabug·cases/·evidence/·playbooks/


# ---------------------------------------------------------------- 치트·qa_runner


CHEAT_TESTS: Final = {
    "ok": ("give_gold", {"amount": 1000}),
    "unadopted": ("give_gem", {}),
    "digest": ("give_gold_copy", {"amount": 1000}),
    "manual": ("reset_shop", {}),
}
"""팀 테스트(사람이 작성) → (치트, 인자). 테스트마다 그 치트 하나만 `qa.cheats.allow`에 둔다."""


def cheat_test(cheat: str, args: dict[str, Any]) -> dict[str, Any]:
    launch = {
        "args": {"$setting": "shop.args"},
        "cwd": {"$setting": "game.cwd"},
        "path": {"$setting": "game.executable"},
        "window_title": {"$setting": "shop.title"},
        "timeout_ms": 30000,
    }
    gold = {"region": [140, 96, 220, 76], "timeout_ms": 5000}
    allow: dict[str, Any] = {"id": cheat, "max_calls": 1}
    if args:
        allow["args"] = {"amount": {"min": 1, "max": 5000}}
    return {
        "format": "kookabug.graph/0",
        "kind": "test",
        "plugins": {"core": "0.1.0"},
        "qa": {"format": "kookabug.qa/0", "cheats": {"allow": [allow]}},
        "nodes": {
            "n_entry": {"type": "core.graph.entry", "version": 1, "next": {"start": "n_launch"}},
            "n_launch": {"type": "core.app.launch", "version": 1, "in": launch,
                         "next": {"attached": "n_open"}},
            "n_open": {"type": "core.assert.text", "version": 1, "in": {**gold, "equals": "12,345"},
                       "next": {"ok": "n_cheat"}},
            "n_cheat": {"type": "core.qa.cheat", "version": 1,
                        "config": {"cheat": cheat, "args": args}, "next": {"done": "n_rich"}},
            "n_rich": {"type": "core.assert.text", "version": 1,
                       "in": {**gold, "equals": "13,345"}},
        },
    }  # fmt: skip


def prepare_cheats(w: World) -> None:
    """사람이 준비한 팀 기준: 치트 정의 4개(하나는 미채택), 분류 둘(무인 허용·불가), 채택 셋,
    채택 뒤 구현 서브그래프 바이트가 바뀐 치트 하나(digest 불일치), 팀 테스트 4개."""
    from kookabug_core.canonical import canonical_dumps

    root = w.root
    console = root / "subgraphs" / "cheats" / "console.graph.json"
    copy = root / "subgraphs" / "cheats" / "console_copy.graph.json"
    copy.write_bytes(console.read_bytes())
    doc = read_json(root / "knowledge" / "cheats.json")
    [gold] = doc["cheats"]

    def cheat(cid: str, template: str, graph: str, args: dict[str, Any]) -> dict[str, Any]:
        impl = {**gold["impl"], "graph": graph, "template": template}
        return {**gold, "id": cid, "title": cid, "impl": impl, "args": args}

    doc["cheats"] += [
        cheat("give_gem", "give_gem", "subgraphs/cheats/console.graph.json", {}),
        cheat("give_gold_copy", "give_gold {amount}", copy.relative_to(root).as_posix(),
              gold["args"]),
        cheat("reset_shop", "reset_shop", "subgraphs/cheats/console.graph.json", {}),
    ]  # fmt: skip
    doc["revision"] = 2
    (root / "knowledge" / "cheats.json").write_text(canonical_dumps(doc), encoding="utf-8")
    config = read_json(root / "kookabug.json")
    config["cheats"]["categories"].append(
        {"id": "manual", "title": "사람 확인", "description": "무인 실행 금지", "unattended": False}
    )
    (root / "kookabug.json").write_text(canonical_dumps(config), encoding="utf-8")
    with w.daemon.client() as ui:
        for cid, category in (
            ("give_gold", "dev_safe"),
            ("give_gold_copy", "dev_safe"),
            ("reset_shop", "manual"),
        ):
            ui.call("cheats.adopt", {"id": cid, "rev": 1, "category": category})
    # 채택 뒤 구현 폐포가 바뀌었다 (R2: digest에 서브그래프 바이트가 들어간다)
    body = read_json(copy)
    body["meta"]["title"] = "콘솔 치트 (고침)"
    copy.write_text(canonical_dumps(body), encoding="utf-8")
    for name, (cid, args) in CHEAT_TESTS.items():
        path = root / "tests" / "cheat" / f"{name}.graph.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cheat_test(cid, args)), encoding="utf-8")


def test_qa_runner_only_adopted_cheats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    steps: list[dict[str, Any]] = [{"toolsets": ["run"]}]
    for name in CHEAT_TESTS:
        steps += [
            {"label": f"run:{name}", "tool": "kb_run_start",
             "args": {"path": f"tests/cheat/{name}.graph.json", "idempotency_key": name},
             "save": {f"run_{name}": "run"}},
            {"label": f"status:{name}", "tool": "kb_run_status",
             "args": {"run": f"${{run_{name}}}", "wait_ms": 30000}, "check": {"state": "ended"}},
        ]  # fmt: skip
    steps += [
        {"label": "working", "tool": "kb_run_start",
         "args": {"path": "tests/cheat/ok.graph.json", "idempotency_key": "w", "basis": "working"},
         "expect": {"error": "basis_denied"}},
        {"label": "console", "tool": "kb_input_type",
         "args": {"window": SHOP, "text": "give_gold 9"}, "expect": {"error": "permission_denied"}},
        {"label": "patch", "tool": "kb_graph_patch",
         "args": {"path": "tests/cheat/ok.graph.json", "base_revision": "0" * 64,
                  "ops": [{"op": "set_meta", "title": "x"}]},
         "expect": {"error": "permission_denied"}},
    ]  # fmt: skip
    script = write_script(tmp_path, "qa_runner", steps)
    spawned = Spawned()
    try:
        with world(tmp_path, monkeypatch, ocr_models, variant=None, preset="qa_runner") as w:
            prepare_cheats(w)
            team = team_tree(w.root)
            job = w.job(script, "triage")
            # 작업 밖 사람 연결 qa_runner 에이전트도 콘솔에 직접 치지 못한다 (control deny)
            mcp = McpClient.start(spawned, w.root, tmp_path / "mcp", env=w.env)
            try:
                mcp.initialize()
                direct = mcp.call_tool("kb_input_type", {"window": SHOP, "text": "give_gold 9"})
                listed = mcp.tool_names()
            finally:
                mcp.close()
            texts = count_inputs(w.game.inputs(), "text")
    finally:
        spawned.close()
    root = w.root
    assert job.code == 0 and not job.fake.get("failed"), (job.out, job.fake.get("failed"))
    runs = {name: run_json(root, str(job.step(f"run:{name}")["ok"]["run"])) for name in CHEAT_TESTS}
    # 채택·분류 무인 허용·qa 허용 안 → 통과 (치트가 실제로 돌아 골드 13,345)
    ok = runs["ok"]
    assert ok["verdict"] == "pass" and ok["basis"]["kind"] == "team" and ok["job"] == job.id
    [used] = ok["qa"]["cheats_used"]
    assert used["cheat"] == "give_gold" and len(used["digest"]) == 64
    # 미채택·digest 불일치 → cheat_not_adopted, 무인 불가 분류 → cheat_denied (설정 오류로 드러냄)
    reasons = {
        "unadopted": ("cheat_not_adopted", "채택하지 않았다"),
        "digest": ("cheat_not_adopted", "digest 불일치"),
        "manual": ("cheat_denied", "무인 실행을 허용하지 않는다"),
    }
    for name, (code, why) in reasons.items():
        failure = job.step(f"status:{name}")["ok"]["failure"]["failure"]
        assert failure["node"] == "n_cheat" and runs[name]["verdict"] == "error", name
        assert runs[name]["qa"]["cheats_used"] == [], name
        assert failure["error"]["code"] == code and why in failure["error"]["message"], failure
    # 팀 기준만·직접 입력·그래프 편집 없음
    assert job.step("working")["error"] == "basis_denied"
    assert job.step("console")["error"] == "permission_denied"
    assert job.step("patch")["error_detail"]["decision"]["source"] == "preset:qa_runner"
    assert direct["isError"] is True
    error = direct["structuredContent"]["error"]
    assert error["code"] == "permission_denied", error
    assert error["decision"]["source"] == "preset:qa_runner"  # 프리셋 자체가 control deny
    assert "kb_input_type" not in listed or direct["isError"]
    # 콘솔에 직접 친 글자는 게임에 가지 않았다 — 양성: 통과한 치트 실행은 콘솔 서브그래프로 글자를
    # 보냈다(팀 테스트의 입력 노드는 막지 않는다, R3)
    sent = [x for x in w.game.inputs() if x.get("op") == "text"]
    assert texts == len(sent) and sent and {x.get("run") for x in sent} == {ok["run_id"]}
    assert team_tree(root) == team


# ---------------------------------------------------------------- Init


INIT_SOURCES: Final = [
    {"id": "item_table", "kind": "data", "title": "아이템 테이블", "path": "sources/items.csv"},
    {"id": "patch_notes", "kind": "patch_notes", "title": "패치 노트", "path": "sources/none.md"},
    {
        "id": "design_doc",
        "kind": "design_doc",
        "title": "기획 문서",
        "url": "https://example.com/d",
    },
    {"id": "game_folder", "kind": "other", "title": "게임 폴더", "path": "."},
]
"""예제 원본 (사람이 마법사 6단계에서 정한 것): 아이템 CSV(있음)·없는 경로·URL(받지 않음)·
워크스페이스를 품은 게임 폴더(그 안의 위키·지식 파생물은 근거가 아니다 — R5 자기 인용)."""


def test_init_collects_unknowns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    with world(tmp_path, monkeypatch, ocr_models, variant=None) as w:
        root = w.root
        config = root / "kookabug.json"
        with w.daemon.client() as ui:
            base = sha(config.read_bytes())
            ui.call("project.sources.set", {"base_sha256": base, "value": INIT_SOURCES})
        policy = {rel: (root / rel).read_bytes() for rel in ("kookabug.json", "AGENTS.md")}
        team = team_tree(root)
        job = w.job("init_sample", "init")
        with w.daemon.client() as ui:
            doc = ui.call("knowledge.get", {"file": "unknowns"})["doc"]
            [question] = [u for u in doc["unknowns"] if u["human_only"]]
            # 사람이 보고함에서 답한다 (사람 전용) — 답하지 않아도 작업은 끝났다(차단 조건 아님)
            answer = {"id": question["id"], "base_rev": question["rev"], "text": "옮겼다"}
            ui.call("unknowns.answer", answer)
    assert job.code == 0 and job.out["state"] == "done", (job.out, job.fake.get("failed"))
    assert not job.fake.get("failed") and job.fake["prompt"] == [], job.fake
    # 1 설정 확인: 읽지 못한 원본은 kb_project_info에 missing, URL은 받지 않음
    states = {s["id"]: s["state"] for s in job.step("info")["ok"]["sources"]}
    assert states == {
        "item_table": "ok",
        "patch_notes": "missing",
        "design_doc": "unchecked_url",
        "game_folder": "ok",
    }
    # 2 원본 수집: expected는 서비스가 해시를 확인한 원본 근거, 그 밖은 guess·hypothesis
    shop = {c["id"]: c for c in read_json(root / "knowledge" / "features" / "shop.json")["claims"]}
    blade = shop["shop.blade.price"]
    assert blade["kind"] == "expected" and blade["basis"][0]["verified"] is True
    assert blade["basis"][0]["hash"] == "sha256:" + sha(
        (root / "sources" / "items.csv").read_bytes()
    )
    assert (shop["shop.sell.ratio"]["kind"], shop["shop.sell.ratio"]["status"]) == (
        "guess",
        "hypothesis",
    )
    assert (
        job.step("hash_mismatch")["error"] == "basis_hash_mismatch"
    )  # Agent가 준 해시는 믿지 않는다
    assert "shop.close.label" not in shop
    # R5 자기 인용: 사람이 등록한 원본 폴더(게임 폴더 = 워크스페이스) 안의 위키 파생물은 파일이 있고
    # 해시·주장 형식이 맞아도 원본 근거가 아니다
    overview = root / "wiki" / "overview.md"
    assert overview.exists() and job.step("read_overview")["sha256_file"] is True
    assert job.step("self_cite")["error"] == "basis_derived"
    assert "shop.genre" not in shop
    # 양성 대조: 같은 연결·같은 원본 폴더의 외부 원본 파일은 서비스가 해시를 확인하고 받아들인다
    listed = shop["shop.blade.listed"]
    assert listed["basis"][0]["ref"] == "sources:game_folder#sources/items.csv"
    assert listed["basis"][0]["verified"] is True
    assert listed["basis"][0]["hash"] == blade["basis"][0]["hash"]
    # 미지수 형식: 읽지 못한 원본 → 사람만 답할 수 있는 질문(원본 표시), 하나는 Agent가 더 알아볼 것
    unknowns = read_json(root / "knowledge" / "unknowns.json")
    assert unknowns["format"] == "kookabug.unknowns/0"
    by_source = {u["source"]: u for u in unknowns["unknowns"]}
    patch = by_source["sources:patch_notes"]
    assert patch["human_only"] is True and patch["id"].startswith("u-") and patch["question"]
    assert patch["state"] == "answered" and patch["answer"]["by"] == "human"  # 사람 답 (양성)
    assert by_source["sources:design_doc"]["human_only"] is False
    cheats = {c["id"]: c for c in read_json(root / "knowledge" / "cheats.json")["cheats"]}
    assert cheats["give_potion"]["adoption"] is None  # 후보만 (채택은 사람)
    assert cheats["give_potion"]["origin"]["kind"] == "agent"
    # 위키: Agent 글 4쪽, Kookabug 렌더(index·reports)는 Agent가 못 쓴다
    for page in ("overview", "glossary", "roadmap", "environment"):
        assert (root / "wiki" / f"{page}.md").exists(), page
    assert "확인된 향후 일정 없음" in (root / "wiki" / "roadmap.md").read_text("utf-8")
    assert job.step("index_blocked")["error"] == "policy_path"
    assert job.step("reports_blocked")["error"] == "policy_path"
    assert not (root / "wiki" / "reports" / "x.md").exists()
    index = (root / "wiki" / "index.md").read_text("utf-8")
    assert index.startswith("# 위키 목차") and "overview.md" in index  # Kookabug 렌더 그대로
    # 경로 차단: 정책 파일·팀 기준은 그대로 (지식 주장 파일만 바뀜 — 양성)
    assert {rel: (root / rel).read_bytes() for rel in policy} == policy
    changed = {k for k in team_tree(root) if team_tree(root).get(k) != team.get(k)}
    assert changed == {"knowledge/features/shop.json"}
    # 5 보고: init_summary(결정적 요약) + 치트 후보 + 사람만 답할 수 있는 질문
    stored = job.report()
    assert stored["playbook"] == "init" and stored["state"] == "done"
    [summary] = job.items("init_summary")
    assert summary["summary"]["unknowns"] == 2 and summary["summary"]["cheat_candidates"] == 1
    assert [i["cheat"] for i in job.items("cheat_candidate")] == ["give_potion"]
    assert stored["unknowns"] == [patch["id"]]
    assert "미지수 2개" in stored["notes"]


# ---------------------------------------------------------------- 비밀값


SECRET_TEST: Final = "tests/secret/console_secret.graph.json"


def secret_test() -> dict[str, Any]:
    """사람이 작성한 팀 테스트: 떠 있는 상점 창에 붙어 콘솔에 비밀값(`acc.pw`)을 넣은 뒤 판정이
    실패한다 (떠 있는 가짜 게임은 상태 파일로 이어져 검사가 게임에 간 값을 볼 수 있다)."""
    gold = {"region": [140, 96, 220, 76], "timeout_ms": 3000}
    return {
        "format": "kookabug.graph/0",
        "kind": "test",
        "plugins": {"core": "0.1.0"},
        "nodes": {
            "n_entry": {"type": "core.graph.entry", "version": 1, "next": {"start": "n_attach"}},
            "n_attach": {"type": "core.window.attach", "version": 1, "in": {"title": SHOP},
                         "next": {"found": "n_open"}},
            "n_open": {"type": "core.assert.text", "version": 1, "in": {**gold, "equals": "12,345"},
                       "next": {"ok": "n_console"}},
            "n_console": {"type": "core.input.key", "version": 1, "in": {"keys": "`"},
                          "next": {"done": "n_type"}},
            "n_type": {"type": "core.input.type_text", "version": 1,
                       "in": {"text": {"$secret": "acc.pw"}}, "next": {"done": "n_check"}},
            "n_check": {"type": "core.assert.text", "version": 1,
                        "in": {"region": [24, 572, 976, 48], "equals": "없는 명령",
                               "timeout_ms": 3000}},
        },
    }  # fmt: skip


def test_no_secret_in_knowledge_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    steps: list[dict[str, Any]] = [
        {"print_env": "KB_TEST_SECRET_VALUE"},
        {"print_split_env": "KB_TEST_SECRET_VALUE"},
        {"toolsets": ["run", "observe", "cases", "knowledge"]},
        {"label": "run", "tool": "kb_run_start",
         "args": {"path": SECRET_TEST, "idempotency_key": "secret"}, "save": {"run": "run"}},
        {"label": "status", "tool": "kb_run_status", "args": {"run": "${run}", "wait_ms": 30000},
         "check": {"state": "ended", "outcome.verdict": "fail"}},
        {"label": "events", "tool": "kb_run_events", "args": {"run": "${run}"}},
        {"label": "search", "tool": "kb_log_search", "args": {"query": "콘솔"}},
        {"label": "case", "tool": "kb_case_open", "args": {"run": "${run}"},
         "save": {"case": "case", "evidence": "evidence"}},
        {"label": "pin", "tool": "kb_evidence_pin",
         "args": {"run": "${run}", "note": "콘솔 입력 뒤 실패"}},
        {"label": "signals", "tool": "kb_triage_signals", "args": {"case": "${case}"}},
        {"label": "case_get", "tool": "kb_case_get", "args": {"case": "${case}"}},
        {"label": "claim", "tool": "kb_knowledge_apply", "args": {"request_id": "s-1", "ops": [
            {"op": "add", "file": "features/shop", "base_revision": 1, "item": {
                "id": "shop.console.rejects", "kind": "observed",
                "statement": "콘솔은 모르는 명령을 거부한다",
                "subject": "shop.console", "property": "rejects", "value": True,
                "basis": [{"type": "run", "ref": "${run}"}], "status": "supported"}}]}},
        {"label": "wiki", "tool": "kb_wiki_write",
         "args": {"path": "wiki/notes/console.md", "text": "# 콘솔\n\n입력 뒤 실패를 보았다.\n",
                  "base_sha256": None}},
        {"label": "note", "tool": "kb_report_note",
         "args": {"text": "콘솔 입력 뒤 실패. 사건을 열었다."}},
    ]  # fmt: skip
    script = write_script(tmp_path, "secret", steps)
    with world(tmp_path, monkeypatch, ocr_models, variant=None) as w:
        root = w.root
        path = root / SECRET_TEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(secret_test()), encoding="utf-8")
        w.env["KB_TEST_SECRET_VALUE"] = SECRET
        job = w.job(script, "triage", "--pass-env", "KB_TEST_SECRET_VALUE")
        with w.daemon.client() as ui:
            case_id = str(job.step("case")["ok"]["case"])
            rpc = [
                ui.call("cases.get", {"id": case_id}),
                ui.call("reports.get", {"job": job.id}),
                ui.call("knowledge.get", {"file": "features/shop"}),
                ui.call("jobs.list", {}),
                ui.call("run.failure", {"run_id": str(job.step("run")["ok"]["run"])}),
            ]
        game_state = w.game.state()
    assert job.code == 0 and not job.fake.get("failed"), (job.out, job.fake.get("failed"))
    run_id = str(job.step("run")["ok"]["run"])
    [folder] = list((root / "runs").glob(f"*_{run_id}"))
    # 양성 대조: 비밀값은 실제로 게임에 갔고(게임 상태의 콘솔 칸 값), 원본 이벤트에는 그 스텝이
    # 비밀값 입력으로 표시돼 있다 — 아래 "값 0" 단언이 빈 검사가 아니다
    assert game_state["forms"]["console"]["values"]["command"] == SECRET
    events = [json.loads(x) for x in (folder / "events.jsonl").read_text("utf-8").splitlines()]
    assert [e["step"] for e in events if e.get("event") == "step.end" and e.get("secret")]
    assert job.fake["results"] and "값: ***" in (job.folder / "agent.log").read_text("utf-8")
    # 지식 출력 전부에서 값 0
    places = {
        "cases": tree_text(root / "knowledge" / "cases"),
        "evidence": tree_text(root / "knowledge" / "evidence"),
        "reports": tree_text(root / "knowledge" / "reports"),
        "log": (root / "knowledge" / "log.jsonl").read_text("utf-8"),
        "features": tree_text(root / "knowledge" / "features"),
        "wiki": tree_text(root / "wiki"),
        "job": tree_text(
            job.folder
        ),  # agent.log·job.json·prompt.md·mcp.json·가짜 CLI가 받은 MCP 응답
        "rpc": json.dumps(rpc, ensure_ascii=False),
        "cli": json.dumps(job.out, ensure_ascii=False) + job.stderr,
    }
    assert {k: SECRET in v for k, v in places.items()} == dict.fromkeys(places, False)
    for k, v in places.items():
        assert v, k  # 빈 출처가 아니다
    for half in (SECRET[: len(SECRET) // 2], SECRET[len(SECRET) // 2 :]):
        assert half not in places["job"]  # 나뉜 출력도 가렸다
    # 증거 묶음 둘(사건 열기 자동 고정·Agent 고정) 모두 그 실행의 묶음이고 파일이 있다
    pinned = [str(job.step("case")["ok"]["evidence"]), str(job.step("pin")["ok"]["id"])]
    for bundle in pinned:
        manifest = read_json(root / "knowledge" / "evidence" / bundle / "manifest.json")
        assert manifest["run"] == run_id and manifest["files"], bundle
    # 가짜 CLI가 받은 응답 중 실행 이벤트·기록 찾기도 비밀값 스텝을 가렸다 (응답 자체는 있다)
    assert job.step("events")["ok"]["events"] and "ok" in job.step("search")
