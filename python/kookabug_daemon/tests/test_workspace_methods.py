"""`workspace.info`·`workspace.tree`·`workspace.changed` (M2 계획 2.4, T4)."""

from __future__ import annotations

import _winapi
import json
import platform
import queue
import time
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon, copy_sample_workspace
from kookabug_daemon.client import DaemonClient

pytestmark = pytest.mark.process


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return copy_sample_workspace(tmp_path / "ws")


def by_path(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {e["path"]: e for e in entries}


def test_tree_lists_kinds_and_marks_broken(ws: Path) -> None:
    (ws / "tests" / "broken_json.graph.json").write_text('{"kind": ', encoding="utf-8")
    (ws / "tests" / "wrong_kind.graph.json").write_text('{"kind": "x"}', encoding="utf-8")
    (ws / "tests" / "notes.txt").write_text("메모", encoding="utf-8")
    (ws / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
    (ws / "kookabug.lock").write_text("{}", encoding="utf-8")
    (ws / "README.md").write_text("루트의 다른 파일은 보이지 않는다", encoding="utf-8")
    (ws / "tests" / "empty").mkdir()
    with ThreadDaemon(ws) as d, d.client() as client:
        entries = client.call("workspace.tree")["entries"]
    paths = [e["path"] for e in entries]
    assert paths == sorted(paths)
    tree = by_path(entries)
    assert tree["kookabug.json"] == {"path": "kookabug.json", "type": "file", "kind": "workspace"}
    assert tree["kookabug.lock"]["kind"] == "lock"
    assert tree["AGENTS.md"]["kind"] == "agents"
    assert "README.md" not in tree and "fake-platform.json" not in tree
    for folder in ("tests", "subgraphs", "targets", "screens", "tests/empty", "targets/login"):
        assert tree[folder] == {"path": folder, "type": "dir"}
    assert tree["tests/inventory_open.graph.json"]["graph_kind"] == "test"
    assert tree["subgraphs/enter_world.graph.json"] == {
        "path": "subgraphs/enter_world.graph.json",
        "type": "file",
        "kind": "graph",
        "graph_kind": "subgraph",
    }
    assert tree["targets/login/login_button.target.json"]["kind"] == "target"
    assert tree["targets/login/login_button.png"]["kind"] == "other"
    assert tree["screens/lobby.screen.json"]["kind"] == "screen"
    assert tree["tests/notes.txt"]["kind"] == "other"
    broken = tree["tests/broken_json.graph.json"]
    assert broken["kind"] == "graph" and "graph_kind" not in broken
    assert "(1:" in broken["problem"]
    wrong = tree["tests/wrong_kind.graph.json"]
    assert "kind" in wrong["problem"] and "graph_kind" not in wrong


def test_runs_and_private_names_only(ws: Path, tmp_path: Path) -> None:
    (ws / "runs" / "20261031-a").mkdir(parents=True)
    (ws / "runs" / "20261031-a" / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (ws / ".kookabug").mkdir(exist_ok=True)
    (ws / ".kookabug" / "local.json").write_text('{"format": "kookabug.local/0"}', "utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.graph.json").write_text("{}", encoding="utf-8")
    _winapi.CreateJunction(str(outside), str(ws / "tests" / "link_out"))
    _winapi.CreateJunction(str(ws / ".kookabug"), str(ws / "tests" / "link_private"))
    _winapi.CreateJunction(str(ws / "subgraphs"), str(ws / "tests" / "link_inside"))
    with ThreadDaemon(ws) as d, d.client() as client:
        tree = by_path(client.call("workspace.tree")["entries"])
    for name in ("runs", ".kookabug"):
        assert tree[name] == {"path": name, "type": "dir", "name_only": True, "git_ignored": True}
    assert not [p for p in tree if p.startswith(("runs/", ".kookabug/"))]
    # 루트 밖·.kookabug/를 가리키는 링크는 건너뛰고, 루트 안 폴더 링크는 안으로 들어가지 않는다
    assert not [p for p in tree if p.startswith(("tests/link_out", "tests/link_private"))]
    assert tree["tests/link_inside"] == {"path": "tests/link_inside", "type": "dir"}
    assert not [p for p in tree if p.startswith("tests/link_inside/")]


def wait_changed(client: DaemonClient, path: str, timeout: float) -> float:
    started = time.monotonic()
    while (left := timeout - (time.monotonic() - started)) > 0:
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            break
        if message["method"] == "workspace.changed" and path in message["params"]["paths"]:
            return time.monotonic() - started
    raise AssertionError(f"{timeout}초 안에 {path}의 workspace.changed가 오지 않았다")


def test_changed_notification_within_2s(ws: Path) -> None:
    with ThreadDaemon(ws) as d, d.client() as client:
        time.sleep(1.5)  # 첫 목록(기준)을 잡을 시간
        new = ws / "tests" / "new.graph.json"
        new.write_text('{"kind": "test"}', encoding="utf-8")
        assert wait_changed(client, "tests/new.graph.json", 5.0) < 2.0
        new.write_text('{"kind": "subgraph"}', encoding="utf-8")
        assert wait_changed(client, "tests/new.graph.json", 5.0) < 2.0
        new.unlink()
        assert wait_changed(client, "tests/new.graph.json", 5.0) < 2.0
        # 이름만 보이는 폴더 안은 알리지 않는다
        (ws / "runs").mkdir()
        (ws / "runs" / "r.txt").write_text("x", encoding="utf-8")
        (ws / "kookabug.json").write_text(
            (ws / "kookabug.json").read_text(encoding="utf-8") + "\n", encoding="utf-8"
        )
        seen: list[str] = []
        deadline = time.monotonic() + 3
        while (left := deadline - time.monotonic()) > 0:
            try:
                message = client.notifications.get(timeout=left)
            except queue.Empty:
                break
            if message["method"] == "workspace.changed":
                seen += message["params"]["paths"]
                if "kookabug.json" in seen:
                    break
        assert "kookabug.json" in seen
        assert not [p for p in seen if p.startswith("runs")]


def test_info_deadline_from_workspace_run(ws: Path) -> None:
    # 툴바 기한 "기본"에 보일 값: kookabug.json run.deadline_ms, 없으면 30분 (G11)
    config = json.loads((ws / "kookabug.json").read_text(encoding="utf-8-sig"))
    config["run"] = {**config.get("run", {}), "deadline_ms": 5_400_000}
    (ws / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
    with ThreadDaemon(ws) as d, d.client() as client:
        assert client.call("workspace.info")["deadline_ms"] == 5_400_000
    del config["run"]["deadline_ms"]
    (ws / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
    with ThreadDaemon(ws) as d, d.client() as client:
        assert client.call("workspace.info")["deadline_ms"] == 30 * 60 * 1000


def test_info_profiles_and_status_fields(ws: Path, tmp_path: Path) -> None:
    with ThreadDaemon(ws) as d, d.client() as client:
        info = client.call("workspace.info")
    assert info["root"] == str(ws)
    assert info["profiles"] == ["login_fail", "maintenance"]
    # 보관 정책 (기록 뷰어 상태 바, M3 T11): 없는 값은 기본값
    assert info["retention"] == {"passed_days": 14, "failed_days": 60, "keep_last": 50}
    # 실행 기한 기본값 (툴바 "기본", G11): 예제 워크스페이스의 run.deadline_ms (5분)
    assert info["deadline_ms"] == 300_000
    assert info["diagnostics"] == []
    core = [p for p in info["plugins"] if p["id"] == "core"]
    assert len(core) == 1 and core[0]["version"]
    runtime = info["runtime"]
    assert runtime["python"] == platform.python_version()
    assert (runtime["platform"], runtime["capture"]) == ("windows", "wgc")
    assert runtime["ocr"] is None or isinstance(runtime["ocr"], str)

    # 가짜 플랫폼 daemon, 형식이 틀린 local.json은 진단으로
    (ws / ".kookabug").mkdir(exist_ok=True)
    (ws / ".kookabug" / "local.json").write_text(json.dumps({"format": 1}), encoding="utf-8")
    fake = ws / "fake-platform.json"
    with ThreadDaemon(ws, platform_fake=fake) as d, d.client() as client:
        info = client.call("workspace.info")
    assert (info["runtime"]["platform"], info["runtime"]["capture"]) == ("fake", "fake")
    assert info["diagnostics"] and all(
        d["file"] == ".kookabug/local.json" for d in info["diagnostics"]
    )
