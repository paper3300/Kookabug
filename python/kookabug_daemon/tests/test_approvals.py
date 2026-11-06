"""사람 확인 (M5 계획 D4·3.6, B3).

에이전트 연결의 ask 판정은 ui 연결에 `approval.requested`로 묻고 답을 기다린다. 기다리는 동안·거부·
시간 초과에는 파일이 바이트 그대로이고, 승인 대기 중 UI가 저장하면 승인 뒤 쓰기가 늦은 쪽으로
거부된다. 답·미리보기·권한 설정은 사람만 한다. "항상 허용"은 그 도구·인자 하나에만 맞는 규칙을
`.kookabug/local.json`에 쓴다(다른 키·순서 보존).
"""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon, copy_sample_workspace
from kookabug_daemon import permission_files
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(120)]

GRAPH = "tests/inventory_open.graph.json"
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-7", "attended": True}


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return copy_sample_workspace(tmp_path / "ws")


@pytest.fixture
def environ(tmp_path: Path) -> dict[str, str]:
    return {"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")}


def rev(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_params(ws: Path, rel: str = GRAPH, title: str = "에이전트") -> dict[str, Any]:
    return {
        "path": rel,
        "base_revision": rev(ws / rel),
        "ops": [{"op": "set_meta", "title": title}],
    }


def notification(client: DaemonClient, method: str, timeout: float = 15) -> dict[str, Any]:
    """그 이름의 다음 알림 params (다른 알림은 버린다)."""
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise AssertionError(f"{timeout}초 안에 {method} 알림이 오지 않았다")
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            continue
        if message.get("method") == method:
            return message["params"]


def error_of(future: Future[Any], timeout: float = 30) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        future.result(timeout)
    return caught.value


def write_local(ws: Path, data: dict[str, Any]) -> Path:
    path = ws / ".kookabug" / "local.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_ask_waits_for_ui_then_applies(ws: Path, environ: dict[str, str]) -> None:
    graph = ws / GRAPH
    with ThreadDaemon(ws, environ=environ) as d, d.client() as ui, d.client(AGENT) as agent:
        pending = agent.request("graph.patch", patch_params(ws))
        asked = notification(ui, "approval.requested")
        assert asked["tool"] == "kb_graph_patch" and asked["arg"] == GRAPH
        assert asked["agent"] == {"id": "agent-7", "name": "mcp"}
        assert asked["method"] == "graph.patch" and asked["previewable"] is True
        assert asked["always_rule"] == f"kb_graph_patch({GRAPH})"
        assert any("set_meta 1" in line for line in asked["summary"])
        # 기다리는 동안 파일은 그대로, 목록에 보인다
        assert not pending.done()
        assert [r["id"] for r in ui.call("approval.list")["requests"]] == [asked["id"]]
        preview = ui.call("approval.preview", {"id": asked["id"]})
        assert preview["value"]["meta"]["title"] == "에이전트"
        assert json.loads(graph.read_text(encoding="utf-8"))["meta"]["title"] != "에이전트"
        ui.call("approval.respond", {"id": asked["id"], "verdict": "allow_once"})
        result = pending.result(30)
        assert result["revision"] == rev(graph)
        assert json.loads(graph.read_text(encoding="utf-8"))["meta"]["title"] == "에이전트"
        resolved = notification(ui, "approval.resolved")
        assert resolved == {"id": asked["id"], "verdict": "allow_once", "by": resolved["by"]}
        assert resolved["by"].startswith("ui:")
        assert ui.call("approval.list")["requests"] == []
        # 한 번 허용은 규칙을 남기지 않는다: 다음 요청도 다시 묻는다
        again = agent.request("graph.patch", patch_params(ws, title="두 번째"))
        asked = notification(ui, "approval.requested")
        ui.call("approval.respond", {"id": asked["id"], "verdict": "deny"})
        assert error_of(again).kind == "approval_denied"
    assert not (ws / ".kookabug" / "local.json").exists()


def test_deny_and_timeout_leave_file_bytes(ws: Path, environ: dict[str, str]) -> None:
    graph = ws / GRAPH
    before = graph.read_bytes()
    with (
        ThreadDaemon(ws, environ=environ, approval_timeout_s=1.5) as d,
        d.client() as ui,
        d.client(AGENT) as agent,
    ):
        # 거부
        pending = agent.request("graph.patch", patch_params(ws))
        asked = notification(ui, "approval.requested")
        ui.call("approval.respond", {"id": asked["id"], "verdict": "deny"})
        error = error_of(pending)
        assert error.kind == "approval_denied"
        assert error.data["decision"]["final"] == "ask"
        assert graph.read_bytes() == before
        # 시간 초과: 답이 없으면 거부, 카드는 닫히고 늦은 답은 not_found
        pending = agent.request("graph.create", {"path": "tests/new.graph.json", "kind": "test"})
        asked = notification(ui, "approval.requested")
        assert error_of(pending).kind == "approval_timeout"
        resolved = notification(ui, "approval.resolved")
        assert (resolved["id"], resolved["verdict"], resolved["by"]) == (
            asked["id"], "timeout", "daemon",
        )  # fmt: skip
        with pytest.raises(DaemonError) as late:
            ui.call("approval.respond", {"id": asked["id"], "verdict": "allow_once"})
        assert late.value.kind == "not_found"
        assert not (ws / "tests/new.graph.json").exists()
        # 요청한 연결이 끊기면 취소 (카드 닫힘, 아무것도 안 씀)
        with d.client(AGENT) as gone:
            gone.request("graph.patch", patch_params(ws))
            asked = notification(ui, "approval.requested")
        resolved = notification(ui, "approval.resolved")
        assert (resolved["id"], resolved["verdict"]) == (asked["id"], "cancelled")
        assert ui.call("approval.list")["requests"] == []
    assert graph.read_bytes() == before


def test_no_ui_connection_no_approver(ws: Path, environ: dict[str, str]) -> None:
    graph = ws / GRAPH
    before = graph.read_bytes()
    with ThreadDaemon(ws, environ=environ) as d, d.client(AGENT) as agent:
        with pytest.raises(DaemonError) as caught:
            agent.call("graph.patch", patch_params(ws))
        assert caught.value.kind == "approval_required"
        assert caught.value.data["reason"] == "no_approver"
        # 사람 없는 에이전트는 ui가 있어도 묻지 않고 deny (unattended_ask)
        with d.client() as ui, d.client({**AGENT, "attended": False}) as night:
            with pytest.raises(DaemonError) as denied:
                night.call("graph.patch", patch_params(ws))
            assert denied.value.kind == "permission_denied"
            assert denied.value.data["decision"]["reason"] == "unattended_ask"
            assert ui.call("approval.list")["requests"] == []
    assert graph.read_bytes() == before


def test_ui_edit_during_wait_late_agent_rejected(ws: Path, environ: dict[str, str]) -> None:
    graph = ws / GRAPH
    with ThreadDaemon(ws, environ=environ) as d, d.client() as ui, d.client(AGENT) as agent:
        pending = agent.request("graph.patch", patch_params(ws))
        asked = notification(ui, "approval.requested")
        # 기다리는 동안 UI가 저장한다 (경로 잠금을 쥐고 있지 않으므로 바로 된다)
        opened = ui.call("graph.open", {"path": GRAPH})
        value = opened["value"]
        value["meta"]["title"] = "사람"
        ui.call(
            "graph.save",
            {"doc_id": opened["doc_id"], "value": value, "base_revision": opened["revision"]},
        )
        human = graph.read_bytes()
        ui.call("approval.respond", {"id": asked["id"], "verdict": "allow_once"})
        error = error_of(pending)
        assert error.kind == "revision_conflict"
        assert graph.read_bytes() == human


def test_agent_cannot_respond_or_set_permissions(ws: Path, environ: dict[str, str]) -> None:
    graph = ws / GRAPH
    before = graph.read_bytes()
    with (
        ThreadDaemon(ws, environ=environ) as d,
        d.client() as ui,
        d.client(AGENT) as agent,
        d.client({**AGENT, "id": "agent-8"}) as other,
    ):
        pending = agent.request("graph.patch", patch_params(ws))
        asked = notification(ui, "approval.requested")
        attempts: list[tuple[str, dict[str, Any]]] = [
            ("approval.respond", {"id": asked["id"], "verdict": "allow_always"}),
            ("approval.respond", {"id": asked["id"], "verdict": "allow_once"}),
            ("approval.preview", {"id": asked["id"]}),
            ("approval.list", {}),
            (
                "permissions.set",
                {"layer": "project", "permissions": {"preset": "full"}, "base_revision": None},
            ),
            (
                "permissions.set",
                {"layer": "user", "permissions": {"preset": "full"}, "base_revision": None},
            ),
        ]
        for client in (agent, other):  # 자기 요청도, 다른 연결의 요청도
            for method, params in attempts:
                with pytest.raises(DaemonError) as caught:
                    client.call(method, params)
                assert caught.value.kind == "permission_denied", (method, caught.value)
        # 에이전트는 확인 요청 알림을 받지 않는다
        with pytest.raises(queue.Empty):
            while True:
                message = agent.notifications.get(timeout=0.3)
                assert not str(message.get("method")).startswith("approval."), message
        # 요청은 그대로 기다리고 있다 — 사람만 닫는다
        assert not pending.done()
        ui.call("approval.respond", {"id": asked["id"], "verdict": "deny"})
        assert error_of(pending).kind == "approval_denied"
        # 자기 판정 요약은 볼 수 있다 (계층 파일 값은 없음)
        mine = agent.call("permissions.get")
        assert "layers" not in mine and mine["principal"]["id"] == "agent-7"
        patch = next(t for t in mine["tools"] if t["tool"] == "kb_graph_patch")
        assert patch["final"] == "ask"
    assert graph.read_bytes() == before
    assert not (ws / ".kookabug" / "local.json").exists()
    assert not (Path(environ["KOOKABUG_USER_CONFIG_DIR"]) / "settings.json").exists()


def test_allow_always_writes_project_rule_preserving_file(
    ws: Path, environ: dict[str, str]
) -> None:
    graph = ws / GRAPH
    local = write_local(
        ws,
        {
            "settings": {"game.executable": "C:/x/python.exe", "game.cwd": "C:/games/sample"},
            "format": "kookabug.local/0",
        },
    )
    with ThreadDaemon(ws, environ=environ) as d, d.client() as ui, d.client(AGENT) as agent:
        pending = agent.request("graph.patch", patch_params(ws))
        asked = notification(ui, "approval.requested")
        ui.call("approval.respond", {"id": asked["id"], "verdict": "allow_always"})
        pending.result(30)
        data = json.loads(local.read_text(encoding="utf-8"))
        # 다른 키·순서 보존, permissions만 끝에 더함
        assert list(data) == ["settings", "format", "permissions"]
        assert list(data["settings"].items()) == [
            ("game.executable", "C:/x/python.exe"),
            ("game.cwd", "C:/games/sample"),
        ]
        assert data["permissions"] == {
            "rules": [{"rule": f"kb_graph_patch({GRAPH})", "verdict": "allow"}]
        }
        # 다음 요청은 묻지 않는다
        agent.call("graph.patch", patch_params(ws, title="두 번째"))
        assert ui.call("approval.list")["requests"] == []
        assert json.loads(graph.read_text(encoding="utf-8"))["meta"]["title"] == "두 번째"
        # 팀 deny 규칙이 이긴다
        team = json.loads((ws / "kookabug.json").read_text(encoding="utf-8"))
        team["permissions"] = {"rules": [{"rule": "kb_graph_patch", "verdict": "deny"}]}
        (ws / "kookabug.json").write_text(json.dumps(team), encoding="utf-8")
        before = graph.read_bytes()
        with pytest.raises(DaemonError) as caught:
            agent.call("graph.patch", patch_params(ws, title="세 번째"))
        assert caught.value.kind == "permission_denied"
        assert caught.value.data["decision"]["layer"] == "team"
        assert graph.read_bytes() == before


def test_control_tool_rejects_allow_always(ws: Path, environ: dict[str, str]) -> None:
    write_local(ws, {"format": "kookabug.local/0", "permissions": {"preset": "runner"}})
    local_before = (ws / ".kookabug" / "local.json").read_bytes()
    with ThreadDaemon(ws, environ=environ) as d, d.client() as ui, d.client(AGENT) as agent:
        pending = agent.request("control.key", {"window": "SampleRPG", "keys": "a"})
        asked = notification(ui, "approval.requested")
        assert asked["tool"] == "kb_input_key" and asked["arg"] == "SampleRPG"
        assert asked["always_rule"] is None
        with pytest.raises(DaemonError) as caught:
            ui.call("approval.respond", {"id": asked["id"], "verdict": "allow_always"})
        assert caught.value.kind == "always_not_allowed"
        # 요청은 그대로 남아 다른 답을 받을 수 있다
        assert [r["id"] for r in ui.call("approval.list")["requests"]] == [asked["id"]]
        ui.call("approval.respond", {"id": asked["id"], "verdict": "deny"})
        assert error_of(pending).kind == "approval_denied"
    assert (ws / ".kookabug" / "local.json").read_bytes() == local_before
    assert not (ws / "runs").exists()


def test_allow_always_exact_for_glob_chars(ws: Path, environ: dict[str, str]) -> None:
    glob_rel, a_rel, b_rel = "tests/[ab].graph.json", "tests/a.graph.json", "tests/b.graph.json"
    with ThreadDaemon(ws, environ=environ) as d:
        with d.client() as ui, d.client(AGENT) as agent:
            for rel in (glob_rel, a_rel, b_rel):
                opened = ui.call("graph.create", {"path": rel, "kind": "test"})
                ui.call("graph.close", {"doc_id": opened["doc_id"]})
            pending = agent.request("graph.patch", patch_params(ws, glob_rel))
            asked = notification(ui, "approval.requested")
            assert asked["always_rule"] == "kb_graph_patch(tests/[[]ab].graph.json)"
            ui.call("approval.respond", {"id": asked["id"], "verdict": "allow_always"})
            pending.result(30)
            # 같은 파일은 묻지 않는다
            agent.call("graph.patch", patch_params(ws, glob_rel, "다시"))
            assert ui.call("approval.list")["requests"] == []
        # a·b는 여전히 ask: 사람이 없으면 no_approver, 파일 그대로
        with d.client(AGENT) as agent:
            for rel in (a_rel, b_rel):
                before = (ws / rel).read_bytes()
                with pytest.raises(DaemonError) as caught:
                    agent.call("graph.patch", patch_params(ws, rel))
                assert caught.value.kind == "approval_required", rel
                assert (ws / rel).read_bytes() == before
            agent.call("graph.patch", patch_params(ws, glob_rel, "세 번째"))
    rules = json.loads((ws / ".kookabug" / "local.json").read_text(encoding="utf-8"))
    assert rules["permissions"]["rules"] == [
        {"rule": "kb_graph_patch(tests/[[]ab].graph.json)", "verdict": "allow"}
    ]


TIMEOUT_S = 2.0
RESOLVED = {"timeout": "timeout", "disconnect": "cancelled", "deny": "deny"}


@pytest.mark.parametrize("ending", ["timeout", "disconnect", "deny"])
def test_no_rule_write_after_request_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    """B3 검수 H2. ① 끝난(시간 초과·연결 끊김·거부) 요청에는 '항상 허용' 쓰기를 시작하지 못한다
    (파일 바이트 그대로). ② 쓰기를 시작한(resolving) 요청은 그 사이 시간 초과·끊김·다른 응답이
    끝내지 못하고, 쓰기 결과로 끝난다."""
    ws = copy_sample_workspace(tmp_path / "ws")
    local = write_local(ws, {"format": "kookabug.local/0", "settings": {"review": "keep"}})
    before = local.read_bytes()
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")}
    entered, release = threading.Event(), threading.Event()
    calls: list[str] = []
    with ThreadDaemon(ws, environ=environ, approval_timeout_s=TIMEOUT_S) as d:
        original = d.daemon.permission_files.add_rule

        def slow(layer: Any, rule: str) -> str:
            calls.append(rule)
            entered.set()
            assert release.wait(30)
            return original(layer, rule)

        monkeypatch.setattr(d.daemon.permission_files, "add_rule", slow)
        with d.client() as ui, d.client() as ui2:
            # ① 먼저 끝난 요청
            with d.client(AGENT) as agent:
                request = agent.request("graph.patch", patch_params(ws))
                asked = notification(ui, "approval.requested")
                if ending == "timeout":
                    assert error_of(request).kind == "approval_timeout"
                elif ending == "disconnect":
                    agent.close()
                else:
                    ui2.call("approval.respond", {"id": asked["id"], "verdict": "deny"})
                    assert error_of(request).kind == "approval_denied"
            assert notification(ui, "approval.resolved")["verdict"] == RESOLVED[ending]
            with pytest.raises(DaemonError) as late:
                ui.call("approval.respond", {"id": asked["id"], "verdict": "allow_always"})
            assert late.value.kind == "not_found"
            assert calls == [] and local.read_bytes() == before

            # ② 쓰기를 시작한 요청
            graph_before = (ws / GRAPH).read_bytes()
            agent = d.client(AGENT)
            try:
                request = agent.request("graph.patch", patch_params(ws))
                asked = notification(ui, "approval.requested")
                response = ui.request(
                    "approval.respond", {"id": asked["id"], "verdict": "allow_always"}
                )
                assert entered.wait(15)
                if ending == "timeout":
                    time.sleep(TIMEOUT_S + 1)  # 기한이 지나도 끝나지 않는다
                    assert not request.done()
                elif ending == "disconnect":
                    agent.close()
                else:
                    with pytest.raises(DaemonError) as other:
                        ui2.call("approval.respond", {"id": asked["id"], "verdict": "deny"})
                    assert other.value.kind == "not_found"
                assert local.read_bytes() == before  # 아직 쓰지 않았다
                release.set()
                assert response.result(30) == {}
                resolved = notification(ui, "approval.resolved")
                assert (resolved["id"], resolved["verdict"]) == (asked["id"], "allow_always")
                rules = json.loads(local.read_text(encoding="utf-8"))["permissions"]["rules"]
                assert rules == [{"rule": f"kb_graph_patch({GRAPH})", "verdict": "allow"}]
                if ending == "disconnect":
                    assert (ws / GRAPH).read_bytes() == graph_before  # 요청한 호출은 사라졌다
                else:
                    request.result(30)
                    assert (
                        json.loads((ws / GRAPH).read_text("utf-8"))["meta"]["title"] == "에이전트"
                    )
            finally:
                release.set()
                agent.close()


def test_rule_write_failure_ends_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ws: Path
) -> None:
    """'항상 허용' 규칙을 쓰지 못하면(그 사이 외부 수정) 요청은 그 오류로 끝나고 파일은 그대로."""
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")}
    local = write_local(ws, {"format": "kookabug.local/0"})
    external = b'{"format": "kookabug.local/0", "settings": {"x": 1}}'
    graph_before = (ws / GRAPH).read_bytes()
    original = permission_files.check_shape

    def edited(value: Any, kind: Any, **kwargs: Any) -> Any:
        # 파일을 읽은 뒤(원본 형식 검사 때) daemon 밖에서 먼저 저장한다
        if kwargs.get("file") == str(local) and local.read_bytes() != external:
            local.write_bytes(external)
        return original(value, kind, **kwargs)

    monkeypatch.setattr(permission_files, "check_shape", edited)
    with ThreadDaemon(ws, environ=environ) as d, d.client() as ui, d.client(AGENT) as agent:
        pending = agent.request("graph.patch", patch_params(ws))
        asked = notification(ui, "approval.requested")
        with pytest.raises(DaemonError) as caught:
            ui.call("approval.respond", {"id": asked["id"], "verdict": "allow_always"})
        assert caught.value.kind == "revision_conflict"
        assert error_of(pending).kind == "revision_conflict"
        resolved = notification(ui, "approval.resolved")
        assert (resolved["verdict"], resolved["by"]) == ("cancelled", "daemon")
    assert local.read_bytes() == external
    assert (ws / GRAPH).read_bytes() == graph_before
