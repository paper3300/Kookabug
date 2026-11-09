"""작업 기준 쓰기 경계 (M8 계획 E3·C7·9장 R4, B3) — 엄격: Agent 권한.

- `curator`·`qa_runner` 프리셋 Agent와 작업 토큰이 붙은 Agent 연결(프리셋 무관, `full` 포함)의
  그래프·target 쓰기는 팀 파일 대신 작업 기준으로 간다. 팀 파일 쓰기 경로(`graph.save`)가 없다
- 기존 프리셋(작업 밖)은 지금처럼 팀 파일에 쓴다 (회귀 없음)
- Agent 연결은 그래프·target 도구로 `knowledge/`·`wiki/` 아래를 쓰지 못한다

B4부터 실제 정책의 프리셋(`curator`)과 실제 작업 토큰(`job.begin` → hello `job_token`)으로 검사한다.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import copy_example_workspace
from kookabug_core import basis
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

TEST = "tests/shop/buy_potion.graph.json"
TARGET = "targets/shop/buy.target.json"
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-w", "attended": True}


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = copy_example_workspace(tmp_path)
    local = root / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["permissions"] = {"preset": "full"}
    local.write_text(json.dumps(body), encoding="utf-8")
    (root / "captures").mkdir()
    shutil.copyfile(root.parent / "frames" / "shop" / "shop_moved.png", root / "captures" / "m.png")
    return root


def team_tree(ws: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for top in ("tests", "subgraphs", "targets", "screens"):
        for path in sorted((ws / top).rglob("*")):
            if path.is_file():
                out[path.relative_to(ws).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def patch_title(client: DaemonClient, title: str) -> dict[str, Any]:
    opened = client.call("graph.open", {"path": TEST})
    client.call("graph.close", {"doc_id": opened["doc_id"]})
    return client.call(
        "graph.patch",
        {
            "path": TEST,
            "base_revision": opened["revision"],
            "ops": [{"op": "set_meta", "title": title}],
        },
    )


def save_target(client: DaemonClient) -> dict[str, Any]:
    frame = client.call("target.load_image", {"path": "captures/m.png"})
    opened = client.call("target.open", {"path": TARGET})
    return client.call(
        "target.save",
        {
            "path": TARGET,
            "base_revision": opened["revision"],
            "spec": {
                "click": {"anchor": "center", "offset": [0, 0]},
                "search": {"region": [0.6445, 0.8125, 0.2539, 0.1875]},
            },
            "crop": {"frame_id": frame["frame_id"], "rect": [700, 556, 180, 60]},
        },
    )


@pytest.fixture
def curator(ws: Path) -> Iterator[None]:
    """B4: 실제 정책에 등록된 프리셋 `curator` (B3는 프리셋 이름을 바꿔 끼워 검사했다)."""
    local = ws / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["permissions"] = {"preset": "curator"}
    local.write_text(json.dumps(body), encoding="utf-8")
    yield


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=60)
    return caught.value


def check_working_only(ws: Path, client: DaemonClient) -> None:
    before = team_tree(ws)
    patched = patch_title(client, "작업 기준 제목")
    assert patched["basis"] == "working" and patched["wrote"] is True
    # 작업 연결은 자기 작업 사본을 보고 그 revision으로 다시 고친다
    again = client.call("graph.open", {"path": TEST})
    assert again["basis"] == "working" and again["change"] == patched["change"]
    assert again["value"]["meta"]["title"] == "작업 기준 제목"
    client.call("graph.close", {"doc_id": again["doc_id"]})
    patch_title(client, "두 번째")
    # graph.save(문서 표 저장)는 팀 파일 쓰기 경로라 없다
    opened = client.call("graph.open", {"path": "tests/shop/buy_then_close.graph.json"})
    error = refused(
        client,
        "graph.save",
        {"doc_id": opened["doc_id"], "value": opened["value"], "base_revision": opened["revision"]},
    )
    assert error.kind == "permission_denied"
    created = client.call("graph.create", {"path": "tests/shop/new.graph.json", "kind": "test"})
    assert created["basis"] == "working"
    saved = save_target(client)
    assert saved["basis"] == "working" and saved["image"] == "targets/shop/buy.png"
    # target.open도 자기 작업 사본을 보여 준다 (B4) — 그 revision으로 다시 저장할 수 있다
    reopened = client.call("target.open", {"path": TARGET})
    region = reopened["spec"]["search"]["region"]
    assert region == pytest.approx([0.6445, 0.8125, 0.2539, 0.1875], abs=1e-3)  # 팀은 0.0781…
    assert reopened["revision"] == saved["revision"]
    assert save_target(client)["basis"] == "working"
    # knowledge/·wiki/ 아래는 그래프·target 도구로 쓰지 않는다
    for path in (f"knowledge/working/{patched['change']}/files/{TEST}", "wiki/x.graph.json"):
        assert refused(client, "graph.create", {"path": path, "kind": "test"}).kind == "policy_path"
    assert team_tree(ws) == before
    assert not (ws / "tests" / "shop" / "new.graph.json").exists()
    changes = basis.load_changes(ws)
    paths = sorted(p for c in changes for p in c.paths())
    assert paths == sorted([TEST, "tests/shop/new.graph.json", TARGET, "targets/shop/buy.png"]), (
        paths
    )


def test_curator_never_writes_team_files(ws: Path, curator: None) -> None:
    with ThreadDaemon(ws) as d, d.client(AGENT) as agent:
        check_working_only(ws, agent)
    changes = basis.load_changes(ws)
    assert {c.agent for c in changes} == {"agent-w"} and {c.job for c in changes} == {None}


def test_full_job_cannot_write_team(ws: Path) -> None:
    """R4: 작업 토큰이 붙은 연결은 `full` 프리셋이어도 작업 기준으로만 쓴다 (B4: 실제 토큰 경로)."""
    with ThreadDaemon(ws) as d:
        with d.client() as ui:
            job = ui.call("job.begin", {"playbook": "repair"})
        info = {**AGENT, "id": job["agent_id"], "job_token": job["token"]}
        with d.client(info) as agent:
            check_working_only(ws, agent)
    assert {c.job for c in basis.load_changes(ws)} == {job["job"]}
    assert {c.agent for c in basis.load_changes(ws)} == {job["agent_id"]}


def test_legacy_presets_still_write_team(ws: Path) -> None:
    """회귀: 작업 밖 기존 프리셋(full)은 지금처럼 팀 파일에 쓰고 작업 기준을 만들지 않는다."""
    before = (ws / TEST).read_bytes()
    with ThreadDaemon(ws) as d, d.client(AGENT) as agent:
        patched = patch_title(agent, "팀 제목")
        assert "basis" not in patched and patched["wrote"] is True
        saved = save_target(agent)
        assert "basis" not in saved
    assert (ws / TEST).read_bytes() != before
    assert json.loads((ws / TEST).read_text("utf-8"))["meta"]["title"] == "팀 제목"
    assert basis.load_changes(ws) == []
    # 사람 연결도 그대로
    with ThreadDaemon(ws) as d, d.client() as ui:
        assert "basis" not in patch_title(ui, "사람 제목")
