"""기록 읽기 메서드 (M3 계획 2.7, T7): `run.list` 확장·`run.index`·`run.children`·`run.step`·
`run.file`·`run.export`, `graph.open`의 실행 폴더 읽기 전용, 진행 중 실행 색인 늘리기.

daemon은 같은 프로세스의 다른 스레드(`ThreadDaemon`), runner는 실제 프로세스, 플랫폼은 가짜다. 목록·
스텝 검사는 실행 폴더를 직접 심는다(예전 실행 기록 복사본·합성 이벤트): daemon이 띄우지 않은 끝난
실행이다.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest
from helpers.daemon_runs import TEST, EventLog, RunRig
from helpers.graphs import GraphBuilder
from helpers.run import tk

from kb_testing.proc import wait_until
from kookabug_core.record.index import index_cache_file
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.protocol import INVALID_PARAMS

pytestmark = [pytest.mark.process, pytest.mark.timeout(180)]

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "run-history"
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-7"}


# ---------------------------------------------------------------- 도움


def plant_fixture(rig: RunRig, name: str, folder: str, **run_json: Any) -> tuple[str, Path]:
    """예전 실행 기록을 `runs/<folder>_<run_id>`로 심는다. `run_json`은 run.json에 더할 필드."""
    source = FIXTURES / name
    data = json.loads((source / "run.json").read_text(encoding="utf-8"))
    run_id = data["run_id"]
    target = rig.root / "runs" / f"{folder}_{run_id}"
    shutil.copytree(source, target)
    if run_json:
        data.update(run_json)
        (target / "run.json").write_text(json.dumps(data), encoding="utf-8")
    return run_id, target


def plant_events(
    rig: RunRig, run_id: str, events: Iterable[Mapping[str, Any]], **run_json: Any
) -> Path:
    """합성 이벤트로 끝난 실행 폴더를 심는다 (`seq`·`t`·`run`을 붙인다)."""
    folder = rig.root / "runs" / f"2026-11-02T01-00-00_t_{run_id}"
    folder.mkdir(parents=True)
    lines = []
    for i, event in enumerate(events, start=1):
        line = {"t": f"2026-11-02T01:00:{i // 1000:02d}.{i % 1000:03d}Z", **event}
        lines.append(json.dumps({**line, "seq": i, "run": run_id}, ensure_ascii=False))
    (folder / "events.jsonl").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    data = {
        "format": "kookabug.run/0",
        "graph": TEST,
        "run_id": run_id,
        "started_at": "2026-11-02T01:00:00.001Z",
        "ended_at": "2026-11-02T01:00:00.500Z",
        "status": "finished",
        **run_json,
    }
    (folder / "run.json").write_text(json.dumps(data), encoding="utf-8")
    return folder


def wait_ended(client: DaemonClient, run_id: str) -> dict[str, Any]:
    return wait_until(
        lambda: (s := client.call("run.status", {"run_id": run_id}))["state"] == "ended" and s,
        timeout=60,
        interval=0.1,
    )


def gate_graph(signal: Path) -> GraphBuilder:
    return (
        tk()
        .entry("n_log")
        .node("n_log", "core.log.message", inputs={"text": "앞"}, next={"done": "n_gate"})
        .node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_after"})
        .node("n_after", "core.log.message", inputs={"text": "뒤"}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def loop_graph(times: int) -> GraphBuilder:
    return (
        tk()
        .entry("n_loop")
        .node(
            "n_loop",
            "core.flow.repeat",
            inputs={"times": times},
            next={"body": "n_log", "done": "n_pass"},
        )
        .node("n_log", "core.log.message", inputs={"text": "본문"})
        .node("n_pass", "core.test.pass")
    )


def step_of(index: Mapping[str, Any], node: str) -> dict[str, Any]:
    return next(s for s in index["steps"] if s["node"] == node)


# ---------------------------------------------------------------- run.list


def test_run_list_summary_badges_and_paging(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, tk().entry("n_pass").node("n_pass", "core.test.pass"))
    planted = {
        "pass": plant_fixture(
            rig, "m2-inventory-pass", "2026-11-01T09-01-00_inventory_open", retried_steps=1
        ),
        "fail": plant_fixture(
            rig,
            "m2-login-fail",
            "2026-11-01T09-02-00_inventory_open",
            debug_intervened=True,
            retried_steps=0,
        ),
        # 같은 초의 두 실행: started_at(밀리초)로 정렬한다
        "skip": plant_fixture(
            rig,
            "m2-maintenance-skip",
            "2026-11-01T09-03-00_inventory_open",
            started_at="2026-11-01T09:03:00.100Z",
            retried_steps=1,
        ),
        "timeout": plant_fixture(
            rig,
            "m2-swapped-target-timeout",
            "2026-11-01T09-03-00_swapped_target",
            started_at="2026-11-01T09:03:00.900Z",
            code="no_assertion",
        ),
    }
    ids = {key: run_id for key, (run_id, _) in planted.items()}
    with rig.daemon() as d, d.client() as client:
        whole = client.call("run.list", {})
        order = [r["run_id"] for r in whole["runs"]]
        assert order == [ids["timeout"], ids["skip"], ids["fail"], ids["pass"]]
        assert whole["next"] is None and whole["runs_bytes"] > 0
        runs = {r["run_id"]: r for r in whole["runs"]}

        # 배지·결과 필드 (run.json에서)
        passed = runs[ids["pass"]]
        assert passed["flaky"] is True  # 재시도 끝에 성공한 스텝이 있는 pass
        assert passed["outcome"]["verdict"] == "pass" and passed["duration_ms"] > 0
        assert passed["failure_path"] is None and "failure_title" not in passed
        failed = runs[ids["fail"]]
        assert failed["debug_intervened"] is True and failed["flaky"] is False
        assert failed["failure_path"] == ["n_enter_world"]
        # 스냅샷이 없는 예전 실행은 노드 ID를 제목으로 쓴다
        assert failed["failure_title"] == "n_enter_world"
        assert failed["profile"] == "login_fail" and failed["game_build"] is None
        assert runs[ids["skip"]]["flaky"] is False  # skipped는 불안정이 아니다
        assert runs[ids["timeout"]]["code"] == "no_assertion"
        assert "flaky" not in runs[ids["timeout"]]  # retried_steps가 없는 예전 기록
        # 끝난 실행의 last_seq는 파일 끝까지
        for run_id, folder in planted.values():
            lines = (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()
            assert runs[run_id]["last_seq"] == json.loads(lines[-1])["seq"]

        # 쪽 넘김: 같은 순서를 2개씩
        pages: list[str] = []
        before: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 2}
            if before is not None:
                params["before"] = before
            page = client.call("run.list", params)
            pages.extend(r["run_id"] for r in page["runs"])
            before = page["next"]
            if before is None:
                break
        assert pages == order

        # 거르기
        fails = client.call("run.list", {"verdict": "fail"})["runs"]
        verdicts = {r["run_id"]: r["outcome"]["verdict"] for r in whole["runs"]}
        assert {r["run_id"] for r in fails} == {k for k, v in verdicts.items() if v == "fail"}
        swapped = client.call("run.list", {"graph": "tests/broken/swapped_target.graph.json"})
        assert [r["run_id"] for r in swapped["runs"]] == [ids["timeout"]]
        with pytest.raises(DaemonError) as caught:
            client.call("run.list", {"before": "x"})
        assert caught.value.code == INVALID_PARAMS


# ---------------------------------------------------------------- run.index·run.children


def test_run_children_pages_iteration(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, loop_graph(5))
    with rig.daemon() as d, d.client() as client:
        started = client.call("run.start", {"path": TEST})
        run_id = started["run_id"]
        wait_ended(client, run_id)
        index = client.call("run.index", {"run_id": run_id})
        assert index["state"] == "ended" and index["run"]["status"] == "finished"
        assert index["run_dir"] == f"runs/{Path(started['run_dir']).name}"
        loop = step_of(index, "n_loop")
        assert [i["iteration"] for i in loop["iterations"]] == [0, 1, 2, 3, 4]
        assert all(i["steps"] == 2 and i["status"] == "success" for i in loop["iterations"])
        assert loop["children"] == 10

        first = client.call(
            "run.children",
            {"run_id": run_id, "parent": loop["step"], "iteration": 2, "offset": 0, "limit": 1},
        )
        assert first["total"] == 2 and first["offset"] == 0
        assert [(s["node"], s["iteration"]) for s in first["steps"]] == [("n_log", 2)]
        second = client.call(
            "run.children",
            {"run_id": run_id, "parent": loop["step"], "iteration": 2, "offset": 1, "limit": 1},
        )
        assert [(s["node"], s["exit"]) for s in second["steps"]] == [("n_loop", "body")]
        every = client.call(
            "run.children", {"run_id": run_id, "parent": loop["step"], "offset": 0, "limit": 500}
        )
        assert every["total"] == 10 and every["steps"][-1]["exit"] == "done"

        # 캐시에 남고, 없는 스텝·실행은 거부
        assert index_cache_file(rig.root, run_id).is_file()
        with pytest.raises(DaemonError) as caught:
            client.call(
                "run.children", {"run_id": run_id, "parent": "s999", "offset": 0, "limit": 10}
            )
        assert caught.value.code == INVALID_PARAMS
        with pytest.raises(DaemonError) as caught:
            client.call("run.index", {"run_id": "zzzzzzzz"})
        assert caught.value.kind == "run_not_found"


# ---------------------------------------------------------------- run.step·run.file


def test_run_step_returns_logs_attempts_artifacts(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path)
    attempt = {"duration_ms": 5, "exit": "timeout", "outputs": {}, "status": "fail"}
    folder = plant_events(
        rig,
        "step0001",
        [
            {"event": "run.start", "graph": TEST, "protocol": 1, "runner": {"pid": 1}},
            {
                "event": "step.start",
                "attempt": 1,
                "node": "n_w",
                "parent": None,
                "path": ["n_w"],
                "step": "s1",
            },
            {"event": "log", "level": "info", "message": "한 번째", "node": "n_w", "step": "s1"},
            {"event": "attempt.end", "attempt": 1, "step": "s1", **attempt},
            {"event": "log", "level": "warn", "message": "두 번째", "node": "n_w", "step": "s1"},
            {"event": "log", "level": "info", "message": "다른 스텝", "node": None, "step": None},
            {
                "event": "step.end",
                "attempt": 2,
                "duration_ms": 12,
                "exit": "timeout",
                "outputs": {},
                "status": "fail",
                "step": "s1",
                "artifacts": ["steps/s1_fail.png", "steps/s1_ocr.txt"],
                "evidence": {
                    "last": "steps/s1_fail.png",
                    "mid": None,
                    "mid_missing": "no_sample_near_mid",
                },
            },
            {
                "event": "run.end",
                "verdict": "fail",
                "code": "unhandled_fail",
                "reason": "",
                "failure_step": "s1",
                "failure_path": ["n_w"],
                "finalized_by": "runner",
                "duration_ms": 20,
            },
        ],
        verdict="fail",
        code="unhandled_fail",
    )
    (folder / "steps").mkdir()
    (folder / "steps" / "s1_ocr.txt").write_text("점검 중", encoding="utf-8")
    (folder / "steps" / "s1_fail.png").write_bytes(b"png")
    (folder / "thumbs").mkdir()
    (folder / "thumbs" / "s1.jpg").write_bytes(b"jpg")
    with rig.daemon() as d, d.client() as client:
        got = client.call("run.step", {"run_id": "step0001", "step": "s1"})
        assert [e["event"] for e in got["events"]] == [
            "step.start",
            "log",
            "attempt.end",
            "log",
            "step.end",
        ]
        assert [e["seq"] for e in got["events"]] == sorted(e["seq"] for e in got["events"])
        node = got["step"]
        assert node["attempt"] == 2 and node["status"] == "fail" and node["evidence"] is True
        assert node["artifacts"] == ["steps/s1_fail.png", "steps/s1_ocr.txt"]
        assert node["thumbnail"] is True and got["thumbnail"] == "thumbs/s1.jpg"
        assert got["ocr_text"] == "점검 중"
        assert got["run_dir"] == f"runs/{folder.name}"

        index = client.call("run.index", {"run_id": "step0001"})
        assert index["failure_chain"] == ["s1"]

        # run.file: run.json 원문, events.jsonl 끝 (1 MiB까지)
        run_json = client.call("run.file", {"run_id": "step0001", "name": "run.json"})
        assert json.loads(run_json["text"])["run_id"] == "step0001"
        assert run_json["truncated"] is False
        tail = client.call("run.file", {"run_id": "step0001", "name": "events_tail"})
        assert tail["text"] == (folder / "events.jsonl").read_bytes().decode("utf-8")

        # 큰 events.jsonl은 끝 1 MiB의 완전한 줄만
        with (folder / "events.jsonl").open("ab") as f:
            for i in range(12_000):
                line = json.dumps({"event": "log", "seq": 100 + i, "pad": "x" * 100}) + "\n"
                f.write(line.encode("utf-8"))
        big = client.call("run.file", {"run_id": "step0001", "name": "events_tail"})
        assert big["truncated"] is True and big["bytes"] > 1024 * 1024
        assert len(big["text"].encode("utf-8")) <= 1024 * 1024
        lines = big["text"].splitlines()
        assert json.loads(lines[0])["event"] == "log" and json.loads(lines[-1])["seq"] == 12_099

        with pytest.raises(DaemonError) as caught:
            client.call("run.step", {"run_id": "step0001", "step": "s77"})
        assert caught.value.code == INVALID_PARAMS


# ---------------------------------------------------------------- run.export


def test_run_export_zip_ui_only_and_refuses_active(tmp_path: Path) -> None:
    signal = tmp_path / "go"
    rig = RunRig.make(tmp_path, gate_graph(signal))
    out = tmp_path / "out"
    out.mkdir()
    dest = out / "run.zip"
    with rig.daemon() as d, d.client() as client:
        started = client.call("run.start", {"path": TEST})
        run_id = started["run_id"]
        client.call("run.subscribe", {"run_id": run_id, "after_seq": 0})
        log = EventLog(client, run_id)
        log.until_event(lambda e: e.get("event") == "step.start" and e.get("node") == "n_gate")
        with pytest.raises(DaemonError) as caught:
            client.call("run.export", {"run_id": run_id, "dest": str(dest)})
        assert caught.value.kind == "run_active"
        assert list(out.iterdir()) == []
        signal.write_text("go", encoding="utf-8")
        log.until_ended()
        wait_ended(client, run_id)

        result = client.call("run.export", {"run_id": run_id, "dest": str(dest)})
        assert result == {"path": str(dest), "bytes": dest.stat().st_size}
        # 임시 파일이 남지 않는다
        assert [p.name for p in out.iterdir()] == ["run.zip"]
        folder = Path(started["run_dir"])
        with zipfile.ZipFile(dest) as archive:
            names = set(archive.namelist())
            assert f"{folder.name}/events.jsonl" in names
            assert f"{folder.name}/run.json" in names
            assert f"{folder.name}/snapshot/{TEST}" in names
            body = archive.read(f"{folder.name}/events.jsonl")
        assert body == (folder / "events.jsonl").read_bytes()

        # 다시 내보내면 덮어쓴다 (replace)
        again = client.call("run.export", {"run_id": run_id, "dest": str(dest)})
        assert again["bytes"] == dest.stat().st_size
        assert [p.name for p in out.iterdir()] == ["run.zip"]
        # 상대 경로·없는 폴더는 거부
        with pytest.raises(DaemonError) as caught:
            client.call("run.export", {"run_id": run_id, "dest": "run.zip"})
        assert caught.value.code == INVALID_PARAMS
        with pytest.raises(DaemonError) as caught:
            client.call("run.export", {"run_id": run_id, "dest": str(out / "no" / "a.zip")})
        assert caught.value.kind == "io_error"


def test_run_export_agent_denied_creates_nothing_at_dest(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path)
    plant_fixture(rig, "m2-login-fail", "2026-11-01T09-02-00_inventory_open")
    run_id = json.loads((FIXTURES / "m2-login-fail" / "run.json").read_text(encoding="utf-8"))[
        "run_id"
    ]
    out = tmp_path / "agent-out"
    out.mkdir()
    dest = out / "stolen.zip"
    path = rig.root / ".kookabug" / "local.json"
    path.parent.mkdir(exist_ok=True)
    # 에이전트에게 모든 도구를 허용해도 내보내기는 판정 전에 거부된다
    body = {"format": "kookabug.local/0", "permissions": {"toolsets": {"run": "allow"}}}
    path.write_text(json.dumps(body), encoding="utf-8")
    with rig.daemon() as d, d.client(AGENT) as agent:
        # 읽기 메서드는 에이전트도 쓴다 (kb_run_events)
        assert agent.call("run.index", {"run_id": run_id})["run_id"] == run_id
        with pytest.raises(DaemonError) as caught:
            agent.call("run.export", {"run_id": run_id, "dest": str(dest)})
        assert caught.value.kind == "permission_denied"
    assert list(out.iterdir()) == []


# ---------------------------------------------------------------- graph.open 읽기 전용


def test_graph_open_runs_path_read_only_save_refused(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, tk().entry("n_pass").node("n_pass", "core.test.pass"))
    with rig.daemon() as d, d.client() as client:
        started = client.call("run.start", {"path": TEST})
        wait_ended(client, started["run_id"])
        folder = Path(started["run_dir"])
        snap = f"runs/{folder.name}/snapshot/{TEST}"
        opened = client.call("graph.open", {"path": snap})
        assert opened["read_only"] is True
        before = (folder / "snapshot" / TEST).read_bytes()
        value = dict(opened["value"])
        value["nodes"] = {**value["nodes"]}
        with pytest.raises(DaemonError) as caught:
            client.call(
                "graph.save",
                {
                    "doc_id": opened["doc_id"],
                    "value": value,
                    "base_revision": opened["revision"],
                    "force": True,
                },
            )
        assert caught.value.kind == "read_only"
        assert caught.value.data["path"] == snap
        assert (folder / "snapshot" / TEST).read_bytes() == before
        with pytest.raises(DaemonError) as caught:
            client.call(
                "graph.create", {"path": f"runs/{folder.name}/new.graph.json", "kind": "test"}
            )
        assert caught.value.kind == "read_only"
        assert not (folder / "new.graph.json").exists()
        # 워크스페이스 그래프는 그대로 편집 가능
        normal = client.call("graph.open", {"path": TEST})
        assert "read_only" not in normal


# ---------------------------------------------------------------- 진행 중 실행


def test_live_run_index_grows_with_events(tmp_path: Path) -> None:
    signal = tmp_path / "go"
    rig = RunRig.make(tmp_path, gate_graph(signal))
    with rig.daemon() as d, d.client() as client:
        started = client.call("run.start", {"path": TEST})
        run_id = started["run_id"]
        client.call("run.subscribe", {"run_id": run_id, "after_seq": 0})
        log = EventLog(client, run_id)
        log.until_event(lambda e: e.get("event") == "step.start" and e.get("node") == "n_gate")
        live = wait_until(
            lambda: (
                (i := client.call("run.index", {"run_id": run_id}))["last_seq"]
                >= log.events[-1]["seq"]
                and i
            ),
            timeout=30,
            interval=0.05,
        )
        assert live["state"] == "running" and live["run"]["status"] == "running"
        gate = step_of(live, "n_gate")
        assert gate["status"] == "running" and gate["t_end"] is None
        assert [s["node"] for s in live["steps"]] == ["n_entry", "n_log", "n_gate"]
        assert not index_cache_file(rig.root, run_id).exists()
        step = client.call("run.step", {"run_id": run_id, "step": gate["step"]})
        kinds = [e["event"] for e in step["events"]]
        assert kinds[0] == "step.start" and "step.end" not in kinds

        signal.write_text("go", encoding="utf-8")
        log.until_ended()
        wait_ended(client, run_id)
        done = client.call("run.index", {"run_id": run_id})
        assert done["state"] == "ended" and done["last_seq"] == log.events[-1]["seq"]
        assert step_of(done, "n_gate")["status"] == "success"
        assert [s["node"] for s in done["steps"]] == [
            "n_entry",
            "n_log",
            "n_gate",
            "n_after",
            "n_pass",
        ]
        # 끝나면 색인 캐시로 옮긴다
        assert index_cache_file(rig.root, run_id).is_file()
