"""UX1 (2026-11-11 사람 첫 툴 테스트 묶음) daemon 쪽.

- U3 `jobs.activity`: 작업 토큰 연결의 `kb_*` 도구 호출이 작업 폴더 `activity.jsonl`에 남고
  (값·비밀값·긴 인자 없음), 사람 전용 읽기로 이어 읽기·agent.log 꼬리를 준다. 작업 ID·경계 검사
- T2 `app.launch`: 사람(ui) 연결도 부른다 (마법사 2단계 띄우기). 가짜 플랫폼 `launch_fake`면 장면
  가짜 게임이 떠 `windows.list`에 그 PID 창이 보인다
- U4 `project.qa_info`: 같은 종류 원본이 여럿이어도 각각 종류·이름·위치를 준다 (Agent가 모두 읽게)
"""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.packaging import REPO_ROOT
from kb_testing.proc import wait_until
from kb_testing.sample_game import copy_example_workspace
from kookabug_core.agent_job import activity, jobdir
from kookabug_daemon.client import DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

SECRET_TEXT = "ux1-top-secret-body-4711"


def agent(agent_id: str, token: str) -> dict[str, Any]:
    return {"kind": "agent", "name": "mcp", "version": "0", "id": agent_id, "job_token": token}


def set_local(ws: Path, **fields: Any) -> None:
    local = ws / ".kookabug" / "local.json"
    body = (
        json.loads(local.read_text("utf-8")) if local.exists() else {"format": "kookabug.local/0"}
    )
    body.update(fields)
    local.parent.mkdir(exist_ok=True)
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = copy_example_workspace(tmp_path)
    set_local(root, permissions={"preset": "curator"})
    return root


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws) as d:
        yield d


def test_short_target_keeps_only_short_identifiers() -> None:
    assert activity.short_target(
        "wiki.write", {"path": "wiki/overview.md", "text": SECRET_TEXT}
    ) == ("wiki/overview.md")
    assert activity.short_target("knowledge.get", {"file": "claims", "id": "c1"}) == "claims"
    assert activity.short_target("control.type", {"window": "SampleRPG", "text": SECRET_TEXT}) == (
        "SampleRPG"
    )
    assert activity.short_target("control.type", {"window": "W", "secret": "acc.pw"}) == "W"
    # 글 값·연산 묶음·긴 값·줄바꿈은 남기지 않는다
    assert activity.short_target("job.note", {"text": SECRET_TEXT}) == ""
    assert activity.short_target("knowledge.search", {"query": SECRET_TEXT}) == ""
    assert activity.short_target("knowledge.apply", {"ops": [{"x": 1}], "request_id": "r"}) == ""
    assert activity.short_target("graph.create", {"path": "a" * 121}) == ""
    assert activity.short_target("graph.create", {"path": "a\nb"}) == ""


def test_jobs_activity_records_agent_tool_calls(daemon: ThreadDaemon, ws: Path) -> None:
    job = daemon.begin_job({"playbook": "init"})
    folder = ws / jobdir.JOBS_DIR / job["job"]
    folder.mkdir(parents=True)
    log_lines = [f"agent line {i}" for i in range(250)]
    (folder / "agent.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    with daemon.client(agent(job["agent_id"], job["token"])) as conn:
        assert conn.call("workspace.info")["root"]
        conn.call("knowledge.get", {"file": "unknowns"})
        # 실패한 호출도 결과 코드로 남는다. 글 값(text)은 남지 않는다
        with pytest.raises(DaemonError):
            conn.call(
                "wiki.write",
                {"path": "wiki/overview.md", "text": SECRET_TEXT, "base_sha256": "0" * 64},
            )
        with daemon.client() as ui:
            wait_until(
                lambda: len(ui.call("jobs.activity", {"job": job["job"]})["entries"]) >= 3,
                timeout=15,
            )
            got = ui.call("jobs.activity", {"job": job["job"]})
            tools = [(e["tool"], e["result"], e["target"]) for e in got["entries"]]
            assert tools[0] == ("kb_project_info", "ok", "")
            assert ("kb_knowledge_get", "ok", "unknowns") in tools
            wiki = next(t for t in tools if t[0] == "kb_wiki_write")
            assert wiki[1] != "ok" and wiki[2] == "wiki/overview.md"
            assert [e["seq"] for e in got["entries"]] == list(range(1, len(got["entries"]) + 1))
            assert got["state"] == "running"
            assert got["used"]["tool_calls"] >= 3
            # agent.log 꼬리: 마지막 200줄 그대로
            assert got["log_tail"] == log_lines[-200:]
            # 이어 읽기
            after = ui.call("jobs.activity", {"job": job["job"], "after": 1})["entries"]
            assert [e["seq"] for e in after] == [e["seq"] for e in got["entries"][1:]]
            # 모르는 작업
            with pytest.raises(DaemonError) as caught:
                ui.call("jobs.activity", {"job": "j-20260101-000000-abcd"})
            assert caught.value.kind == "not_found"
        # 사람 전용: 작업 Agent는 부르지 못한다
        with pytest.raises(DaemonError) as caught:
            conn.call("jobs.activity", {"job": job["job"]})
        assert caught.value.kind == "permission_denied"
    raw = (folder / activity.ACTIVITY_FILE).read_text(encoding="utf-8")
    assert SECRET_TEXT not in raw
    assert job["token"] not in raw


def test_mask_target_hides_known_secrets() -> None:
    assert activity.mask_target("wiki/a.md", ["tok-123456"]) == "wiki/a.md"
    assert activity.mask_target("wiki/tok-123456.md", ["tok-123456"]) == activity.MASKED
    # 비교는 공백·대소문자를 무시한다 (글자 검사기와 같은 규칙)
    assert activity.mask_target("Game - TOK 123456", ["tok123456"]) == activity.MASKED
    assert activity.mask_target("wiki/a.md", []) == "wiki/a.md"
    # 가림 값을 확인하지 못하면 대상을 비운다
    assert activity.mask_target("wiki/a.md", None) == ""
    assert activity.mask_target("", ["x"]) == ""


FW_BACKSLASH = chr(0xFF3C)  # 전각 역슬래시 — NFKC가 `\`로 바꾼다


def test_mask_target_decodes_and_unifies_paths() -> None:
    secret = "review-credential-7a9c"
    secret_path = "review/path-7a9c"
    fw_percent, fw_plus = chr(0xFF05), chr(0xFF0B)
    # `+`·경로 구분자 표현은 같은 비밀값으로 본다 (UX1_2 H1)
    assert activity.mask_target("q=a+b-secret-31", ["a b-secret-31"]) == activity.MASKED
    assert activity.mask_target("wiki/review/path.md", [r"review\path"]) == activity.MASKED
    assert activity.mask_target(r"wiki\review\path.md", ["review/path"]) == activity.MASKED
    assert activity.mask_target("wiki/review/path.md", [f"review{FW_BACKSLASH}path"]) == (
        activity.MASKED
    )
    # 퍼센트 인코딩·NFKC로 바뀌는 글자가 섞인 대상은 비운다 (UX1_2~5 검수 재현 전부)
    for target, value in [
        ("wiki/%72eview-credential-7a9c.md", secret),
        ("wiki/%2572eview-credential-7a9c.md", secret),
        ("wiki/%25252572eview-credential-7a9c", secret),
        ("Game+%52EVIEW-credential-7a9c", "game review-credential"),
        ("wiki%5Creview%5Cpath.md", "review/path"),
        (f"wiki/review{FW_BACKSLASH}path.md", "review/path"),
        ("wiki/review%EF%BC%BCpath.md", "review/path"),
        (f"wiki/{fw_percent}72eview/path-7a9c.md", secret_path),
        ("wiki/%EF%BC%8572eview/path-7a9c.md", secret_path),
        (f"wiki/review%2Bpath{fw_plus}secret-7a9c.md", "review+path secret-7a9c"),
        ("wiki/review%252Bpath%2Bsecret-7a9c.md", "review+path secret-7a9c"),
        ("wiki/review%252Bpath%EF%BC%8Bsecret-7a9c.md", "review+path secret-7a9c"),
        ("wiki/a%20b.md", secret),
        (f"wiki/{chr(0xFF21)}BC.md", secret),
    ]:
        assert activity.mask_target(target, [value]) == "", target
    # 비밀값과 상관없는 일반 대상은 원문 그대로
    assert activity.mask_target("wiki/a+b.md", [secret]) == "wiki/a+b.md"
    assert activity.mask_target("wiki/상점.md", [secret]) == "wiki/상점.md"


ENV_SECRET = "ux1-env-secret-9137"
REVIEW_SECRET = "review-credential-7a9c"
PATH_SECRET = "ux1vault\\ux1-path-secret-5521"


def _activity_texts(
    daemon: ThreadDaemon, folder: Path, job_id: str, count: int
) -> tuple[list[dict[str, Any]], str, str]:
    """활동 줄이 `count`개 쌓일 때까지 기다린 뒤 (RPC 줄, RPC 글, 파일 글)."""
    with daemon.client() as ui:
        wait_until(
            lambda: len(ui.call("jobs.activity", {"job": job_id})["entries"]) >= count,
            timeout=15,
        )
        got = ui.call("jobs.activity", {"job": job_id})
    raw = (folder / activity.ACTIVITY_FILE).read_text(encoding="utf-8")
    return got["entries"], json.dumps(got, ensure_ascii=False), raw


def _assert_hidden(texts: Iterable[str], secrets: Iterable[str]) -> None:
    """원문·퍼센트 디코딩·구분자 통일 어느 표현에도 비밀값이 없다."""
    for text in texts:
        forms = {text}
        for _ in range(4):
            forms |= {unquote(f) for f in forms} | {f.replace("+", " ") for f in forms}
        folded = [f.replace("\\", "/").casefold() for f in forms]
        for secret in secrets:
            want = secret.replace("\\", "/").casefold()
            assert not any(want in f for f in folded)


def test_activity_target_masks_encoded_and_path_forms(
    daemon: ThreadDaemon, ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 검수 재현(UX1_2 H1): 인코딩·경로 표현의 알려진 비밀값 → 성공·실패 호출 모두 파일·RPC에 없음
    monkeypatch.setenv("KOOKABUG_SECRET_REVIEW", REVIEW_SECRET)
    monkeypatch.setenv("KOOKABUG_SECRET_UX1_PATH", PATH_SECRET)
    job = daemon.begin_job({"playbook": "init"})
    folder = ws / jobdir.JOBS_DIR / job["job"]
    folder.mkdir(parents=True)
    wiki = ws / "wiki"
    wiki.mkdir(exist_ok=True)
    (wiki / "%72eview-credential-7a9c.md").write_text("# ok\n", encoding="utf-8")
    nested = wiki / "ux1vault"
    nested.mkdir()
    (nested / "ux1-path-secret-5521.md").write_text("# ok\n", encoding="utf-8")
    with daemon.client(agent(job["agent_id"], job["token"])) as conn:
        # 성공 호출 (실제 파일: 이름 그대로의 인코딩 글, 구분자가 다른 경로)
        conn.call("workspace.read", {"path": "wiki/%72eview-credential-7a9c.md"})
        conn.call("workspace.read", {"path": "wiki/ux1vault/ux1-path-secret-5521.md"})
        # 실패 호출 (없는 파일)
        with pytest.raises(DaemonError):
            conn.call("workspace.read", {"path": "wiki/missing-%2572eview-credential-7a9c.md"})
        with pytest.raises(DaemonError):
            conn.call("workspace.read", {"path": "wiki/ux1vault/ux1-path-secret-5521+x.md"})
    entries, rpc, raw = _activity_texts(daemon, folder, job["job"], 4)
    _assert_hidden([rpc, raw], [REVIEW_SECRET, PATH_SECRET])
    assert len(entries) == 4
    # 퍼센트 인코딩 대상은 비우고(UX1 검수 5), 구분자가 다른 경로는 가린다
    assert sorted(e["target"] for e in entries) == ["", "", activity.MASKED, activity.MASKED]
    assert sorted(e["result"] == "ok" for e in entries) == [False, False, True, True]


def test_activity_target_dropped_after_finish_on_old_connection(
    daemon: ThreadDaemon, ws: Path
) -> None:
    # 검수 재현(UX1_2 H2): finish 뒤 기존 연결로 토큰 경로 호출 → 거부, 활동 대상은 비움
    job = daemon.begin_job({"playbook": "init"})
    token = job["token"]
    folder = ws / jobdir.JOBS_DIR / job["job"]
    folder.mkdir(parents=True)
    with daemon.client(agent(job["agent_id"], token)) as conn:
        with daemon.client() as ui:
            ui.call("job.finish", {"job": job["job"]}, timeout=300)
        with pytest.raises(DaemonError) as caught:
            conn.call("workspace.read", {"path": f"wiki/{token}.md"})
        assert caught.value.kind == "job_token_invalid"
    entries, rpc, raw = _activity_texts(daemon, folder, job["job"], 1)
    _assert_hidden([rpc, raw], [token])
    assert [(e["result"], e["target"]) for e in entries] == [("job_token_invalid", "")]


def test_activity_target_dropped_when_record_runs_after_finish(
    daemon: ThreadDaemon, ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 검수 재현(UX1_2 H2): 종료 직전 성공 호출의 기록이 종료 뒤 실행 → 가림 자료가 없어 대상 비움
    from kookabug_daemon.jobs import JobRegistry

    gate = threading.Event()
    original = JobRegistry.record_activity

    def delayed(self: JobRegistry, job_id: str, tool: str, result: str, target: str) -> None:
        gate.wait(60)
        original(self, job_id, tool, result, target)

    monkeypatch.setattr(JobRegistry, "record_activity", delayed)
    job = daemon.begin_job({"playbook": "init"})
    token = job["token"]
    folder = ws / jobdir.JOBS_DIR / job["job"]
    folder.mkdir(parents=True)
    (ws / "wiki").mkdir(exist_ok=True)
    (ws / "wiki" / f"{token}.md").write_text("# ok\n", encoding="utf-8")
    with daemon.client(agent(job["agent_id"], token)) as conn:
        conn.call("workspace.read", {"path": f"wiki/{token}.md"})
        with daemon.client() as ui:
            ui.call("job.finish", {"job": job["job"]}, timeout=300)
        gate.set()
    entries, rpc, raw = _activity_texts(daemon, folder, job["job"], 1)
    _assert_hidden([rpc, raw], [token])
    assert [(e["result"], e["target"]) for e in entries] == [("ok", "")]


def test_activity_target_masks_token_and_workspace_secret(
    daemon: ThreadDaemon, ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 검수 재현(H1): 경로·창 제목에 작업 토큰·워크스페이스 비밀값 → 파일·RPC 어디에도 원문 없음
    monkeypatch.setenv("KOOKABUG_SECRET_UX1_PROBE", ENV_SECRET)
    job = daemon.begin_job({"playbook": "init"})
    token = job["token"]
    folder = ws / jobdir.JOBS_DIR / job["job"]
    folder.mkdir(parents=True)
    wiki = ws / "wiki"
    wiki.mkdir(exist_ok=True)
    (wiki / f"{token}.md").write_text("# ok\n", encoding="utf-8")
    (wiki / f"{ENV_SECRET}.md").write_text("# ok\n", encoding="utf-8")
    with daemon.client(agent(job["agent_id"], token)) as conn:
        # 성공 호출 (실제 파일)
        conn.call("workspace.read", {"path": f"wiki/{token}.md"})
        conn.call("workspace.read", {"path": f"wiki/{ENV_SECRET}.md"})
        # 실패 호출 (없는 파일·창)
        with pytest.raises(DaemonError):
            conn.call("workspace.read", {"path": f"wiki/missing-{token}.md"})
        # 창 제목: 인자가 틀린 호출(실패)과 받아들여진 호출(그런 창이 없어 입력 없이 끝나는 실행)
        with pytest.raises(DaemonError):
            conn.call("control.type", {"window": f"Game {token}"})
        conn.call("control.type", {"window": f"Game {ENV_SECRET}", "text": "x"})
        with daemon.client() as ui:
            wait_until(
                lambda: len(ui.call("jobs.activity", {"job": job["job"]})["entries"]) >= 5,
                timeout=15,
            )
            got = ui.call("jobs.activity", {"job": job["job"]})
    rpc = json.dumps(got, ensure_ascii=False)
    raw = (folder / activity.ACTIVITY_FILE).read_text(encoding="utf-8")
    for text in (rpc, raw):
        assert token not in text
        assert ENV_SECRET not in text
    entries = got["entries"]
    assert len(entries) == 5
    assert all(e["target"] == activity.MASKED for e in entries)
    # 기록은 실행기 스레드라 순서가 바뀔 수 있다 — 성공 3·실패 2, 창 제목 호출 2
    assert sorted(e["result"] == "ok" for e in entries) == [False, False, True, True, True]
    assert [e["tool"] for e in entries].count("kb_input_type") == 2


def test_activity_target_dropped_when_secrets_unreadable(
    daemon: ThreadDaemon, ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kookabug_core.agent_job.runner as runner

    def broken(root: Path, environ: Any) -> list[str]:
        raise OSError("자격 증명 관리자를 읽지 못함")

    monkeypatch.setattr(runner, "known_secrets", broken)
    job = daemon.begin_job({"playbook": "init"})
    folder = ws / jobdir.JOBS_DIR / job["job"]
    folder.mkdir(parents=True)
    with daemon.client(agent(job["agent_id"], job["token"])) as conn:
        conn.call("knowledge.get", {"file": "unknowns"})
        with daemon.client() as ui:
            wait_until(
                lambda: len(ui.call("jobs.activity", {"job": job["job"]})["entries"]) >= 1,
                timeout=15,
            )
            got = ui.call("jobs.activity", {"job": job["job"]})
    assert [(e["tool"], e["result"], e["target"]) for e in got["entries"]] == [
        ("kb_knowledge_get", "ok", "")
    ]


def test_activity_not_written_outside_job_folder(daemon: ThreadDaemon, ws: Path) -> None:
    # 작업 폴더가 없으면(agent-job이 만들지 않았으면) 남기지 않는다 — 폴더를 새로 만들지 않는다
    job = daemon.begin_job({"playbook": "init"})
    with daemon.client(agent(job["agent_id"], job["token"])) as conn:
        conn.call("workspace.info")
    folder = ws / jobdir.JOBS_DIR / job["job"]
    assert not (folder / activity.ACTIVITY_FILE).exists()
    with daemon.client() as ui:
        got = ui.call("jobs.activity", {"job": job["job"]})
    assert got["entries"] == [] and got["log_tail"] == []


def test_qa_info_lists_every_source_of_a_kind(
    daemon: ThreadDaemon, ws: Path, tmp_path: Path
) -> None:
    docs = tmp_path / "planning"
    docs.mkdir()
    (docs / "a.md").write_text("# a\n", encoding="utf-8")
    config = json.loads((ws / "kookabug.json").read_text(encoding="utf-8"))
    config["sources"] = [
        {"id": "design_doc", "kind": "design_doc", "title": "기획 문서", "path": "sources"},
        {"id": "design_doc_2", "kind": "design_doc", "title": "기획 문서 2", "local": True},
        {
            "id": "design_doc_3",
            "kind": "design_doc",
            "title": "기획 문서 3",
            "url": "https://example.invalid/d",
        },
    ]
    (ws / "kookabug.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    set_local(ws, sources={"design_doc_2": {"path": str(docs)}})
    with daemon.client() as ui:
        sources = {s["id"]: s for s in ui.call("project.qa_info")["sources"]}
    assert set(sources) == {"design_doc", "design_doc_2", "design_doc_3"}
    assert all(s["kind"] == "design_doc" for s in sources.values())
    assert sources["design_doc_2"]["path"] == str(docs)
    assert sources["design_doc_2"]["state"] == "ok"
    assert sources["design_doc_3"]["url"] == "https://example.invalid/d"
    assert sources["design_doc"]["path"] == str(ws / "sources")


def test_ui_app_launch_fake_game_window(tmp_path: Path) -> None:
    root = copy_example_workspace(tmp_path)
    frames = tmp_path / "frames"
    shutil.copytree(REPO_ROOT / "fixtures" / "sample-game" / "frames", frames)
    spec = tmp_path / "platform.json"
    spec.write_text(
        json.dumps({"scenario": str(frames / "scenario.json"), "launch_fake": True}),
        encoding="utf-8",
    )
    with ThreadDaemon(root, platform_fake=spec) as d, d.client() as ui:
        assert ui.call("windows.list")["windows"] == []  # running: false — 떠 있는 게임 없음
        set_local(
            root, settings={"game.executable": "C:/Games/Sample/Game.exe", "game.args": ["-a b"]}
        )
        pid = ui.call("app.launch", {})["pid"]
        windows = ui.call("windows.list")["windows"]
        assert [w["pid"] for w in windows] == [pid]
        # 다시 띄우면 창이 하나 더 (읽을 때마다 같은 HWND·PID)
        second = ui.call("app.launch", {})["pid"]
        again = ui.call("windows.list")["windows"]
        assert [w["pid"] for w in again] == [pid, second]
        assert again[0]["handle"] == windows[0]["handle"]
        frame = ui.call("target.capture", {"window": windows[0]["handle"]})
        assert frame["width"] > 0


def test_ui_app_launch_refused_while_job_running(tmp_path: Path) -> None:
    # 검수 재현(M2): 무인 작업이 도는 중 사람 app.launch → job_active (가짜 게임을 띄우지 않는다)
    root = copy_example_workspace(tmp_path)
    frames = tmp_path / "frames"
    shutil.copytree(REPO_ROOT / "fixtures" / "sample-game" / "frames", frames)
    spec = tmp_path / "platform.json"
    spec.write_text(
        json.dumps({"scenario": str(frames / "scenario.json"), "launch_fake": True}),
        encoding="utf-8",
    )
    set_local(root, settings={"game.executable": "C:/Games/Sample/Game.exe"})
    with ThreadDaemon(root, platform_fake=spec) as d, d.client() as ui:
        job = d.begin_job({"playbook": "init"})
        assert [j["state"] for j in ui.call("jobs.list")["jobs"]] == ["running"]
        with pytest.raises(DaemonError) as caught:
            ui.call("app.launch", {})
        assert caught.value.kind == "job_active"
        assert ui.call("windows.list")["windows"] == []
        # 작업이 끝나면 다시 띄운다
        ui.call("job.finish", {"job": job["job"]}, timeout=300)
        assert ui.call("app.launch", {})["pid"] > 0
