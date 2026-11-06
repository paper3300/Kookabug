"""daemon `plugins.*` (M6 계획 3.8·B4): 미리보기 → 설치, 실패, 에이전트 거부, 잠금 변경 알림, 준비.

실제 uv·venv·로컬 인덱스(`helpers.plugins`)와 같은 프로세스 daemon(`ThreadDaemon`). daemon의
플러그인 작업은 세션의 임시 uv 캐시·SDK wheel 환경(`plugin_environ`)을 쓴다.
"""

from __future__ import annotations

import json
import queue
import shutil
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.graphs import GraphBuilder, link
from helpers.plugins import Rig, plugin_world, rig, tree_hashes

from kb_testing.daemon import ThreadDaemon
from kb_testing.plugin_fixtures import sdk_wheel
from kookabug_core.plugins import SDK_WHEEL_ENV, PluginOps
from kookabug_core.plugins.lockfile import lock_sha256, revision_of
from kookabug_daemon.client import DaemonClient, DaemonError

__all__ = ["plugin_world", "rig"]

pytestmark = [pytest.mark.packaging, pytest.mark.process, pytest.mark.timeout(900)]

AGENT: Final = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-7", "attended": True}
GRAPH: Final = "tests/p.graph.json"
DONE_WAIT_S: Final = 300.0


@pytest.fixture
def daemon(rig: Rig) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(
        rig.root,
        plugin_environ=rig.world.environ,
        agent_toolsets=("core",),
        watch_interval_s=0.2,
    ) as d:
        yield d


def notification(
    client: DaemonClient, method: str, timeout: float = DONE_WAIT_S, **match: Any
) -> dict[str, Any]:
    """`method` 알림 중 `match`(params 키 = 값)에 맞는 첫째. 그 앞의 다른 알림은 버린다."""
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise AssertionError(f"{timeout}초 안에 {method} {match} 알림이 오지 않았다")
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            continue
        params = message.get("params", {})
        if message.get("method") == method and all(params.get(k) == v for k, v in match.items()):
            return params


def drain(client: DaemonClient) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    while True:
        try:
            out.append(client.notifications.get_nowait())
        except queue.Empty:
            return out


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params)
    return caught.value


def sample_graph(rig: Rig) -> dict[str, Any]:
    """예제 플러그인 순수 노드를 쓰는 그래프 값 (디스크에도 쓴다)."""
    g = GraphBuilder(plugins={"sample": "0.1.0"})
    g.entry("n_cmp")
    g.node("n_rev", "sample.text.reverse", inputs={"text": "abc"})
    g.node(
        "n_cmp",
        "core.assert.compare",
        inputs={"a": link("n_rev.text"), "op": "==", "b": "cba"},
        next={"ok": "n_pass"},
    )
    g.node("n_pass", "core.test.pass")
    g.write(rig.root, GRAPH)
    return json.loads((rig.root / GRAPH).read_text(encoding="utf-8"))


def plugin_state(rig: Rig) -> dict[str, Any]:
    """잠금 바이트·환경 폴더 파일 전체·커밋된 wheel 폴더 (작업이 바꾸면 안 되는 것)."""
    envs = rig.envs
    wheels = rig.root / "plugins"
    return {
        "lock": rig.lock_bytes(),
        "envs": {p.name: tree_hashes(p) for p in sorted(envs.iterdir()) if p.is_dir()}
        if envs.is_dir()
        else {},
        "wheels": tree_hashes(wheels) if wheels.is_dir() else {},
    }


def node_types(client: DaemonClient) -> set[str]:
    return {n["type"] for s in client.call("nodes.list")["schemas"] for n in s["nodes"]}


def test_preview_then_install_flow(rig: Rig, daemon: ThreadDaemon) -> None:
    """미리보기(①② — 코드 실행·환경 없음) → 취소면 아무것도 안 생김. 다시 미리보기 → 승인 →
    진행·끝·잠금 변경 알림, 레지스트리 재생성(팔레트·사전 검증), 목록에 준비됨."""
    wheel = str(rig.world.wheel("sample"))
    with daemon.client() as ui:
        # 1) 미리보기 → 취소: 잠금·환경 없음
        shown = ui.call("plugins.preview", {"source": wheel})
        assert shown["id"] == "sample" and shown["permissions"] == ["capture"]
        assert shown["untrusted"] == [] and shown["replaces"] is None
        assert shown["expires_in_s"] == 300
        busy = ui.call("plugins.list")["busy"]
        assert busy == {"op_id": shown["op_id"], "kind": "install", "stage": "manifest",
                        "waiting": True}  # fmt: skip
        assert ui.call("plugins.cancel", {"op_id": shown["op_id"]}) == {}
        done = notification(ui, "plugins.done", op_id=shown["op_id"])
        assert done["ok"] is False and done["error"]["code"] == "cancelled"
        assert done["error"]["stage"] == "confirm"
        assert rig.lock_bytes() is None and not rig.envs.exists()
        assert refused(ui, "plugins.install", {"op_id": shown["op_id"]}).kind == "op_not_found"

        # 2) 미리보기 → 승인
        sample_graph(rig)
        assert "sample.text.reverse" not in node_types(ui)
        shown = ui.call("plugins.preview", {"source": wheel})
        op_id = shown["op_id"]
        assert ui.call("plugins.install", {"op_id": op_id}) == {"op_id": op_id}
        stages: list[str] = []
        changed: dict[str, Any] | None = None  # 감시가 먼저 볼 수도 있다 (순서 무관)
        while True:
            message = ui.notifications.get(timeout=DONE_WAIT_S)
            params = message.get("params", {})
            if message["method"] == "plugins.changed":
                changed = params
            if message["method"] == "plugins.progress" and params["op_id"] == op_id:
                stages.append(params["stage"])
                assert params["message"]
            if message["method"] == "plugins.done" and params["op_id"] == op_id:
                done = params
                break
        assert done["ok"] is True, done
        assert done["kind"] == "install" and done["result"]["plugin"]["id"] == "sample"
        assert stages[0] == "confirmed" and stages[-1] == "committed"
        assert {"resolved", "env_complete", "archived"} <= set(stages)
        changed = changed or notification(ui, "plugins.changed", timeout=30)
        assert changed["revision"] == revision_of(rig.lock_bytes())
        time.sleep(1.0)  # 감시 주기 몇 번: 같은 revision은 다시 알리지 않는다
        assert "plugins.changed" not in {m.get("method") for m in drain(ui)}
        # 작업 로그 이름 = 작업 ID
        assert (rig.root / ".kookabug/plugins/logs" / f"{op_id}.log").is_file()
        # 같은 미리보기를 다시 승인할 수 없다
        assert refused(ui, "plugins.install", {"op_id": op_id}).kind == "op_not_found"

        listed = ui.call("plugins.list")
        (plugin,) = listed["plugins"]
        assert plugin["id"] == "sample" and plugin["env_status"] == "ready"
        assert {n["type"] for n in plugin["nodes"]} >= {"sample.text.reverse"}
        assert listed["busy"] is None and listed["trusted"] is True
        assert listed["lock_sha256"] == lock_sha256(rig.lock())
        # 레지스트리를 다시 만들었다: 팔레트·편집기 검증에 새 노드 (daemon 재시작 없음)
        assert "sample.text.reverse" in node_types(ui)
        opened = ui.call("graph.open", {"path": GRAPH})
        codes = {d["code"] for d in opened["diagnostics"]}
        assert not codes & {"unknown_node_type", "plugin_env_missing", "plugin_not_installed"}
        summary = ui.call("nodes.list")["plugins"]
        assert summary == [
            {"id": "sample", "title": "Sample", "version": "0.1.0", "permissions": ["capture"],
             "env": plugin["env"], "env_status": "ready"}
        ]  # fmt: skip


def test_install_failure_reports_stage_and_keeps_list(rig: Rig, daemon: ThreadDaemon) -> None:
    """설치 실패(검증 import 실패): 끝 알림에 단계·코드, 잠금·기존 환경·wheel·목록 그대로."""
    with daemon.client() as ui:
        rig.add("sample")  # 공유 환경에 기존 플러그인 (broken_import는 그 공유에 붙으려다 실패)
        notification(ui, "plugins.changed", timeout=30)  # 밖에서 바뀐 잠금
        before_list = ui.call("plugins.list")
        before = plugin_state(rig)
        shown = ui.call("plugins.preview", {"source": str(rig.world.wheel("broken_import"))})
        assert shown["untrusted"] == []
        ui.call("plugins.install", {"op_id": shown["op_id"]})
        done = notification(ui, "plugins.done", op_id=shown["op_id"])
        assert done["ok"] is False
        assert done["error"]["code"] == "verify_failed" and done["error"]["stage"] == "verify"
        assert "result" not in done
        after_list = ui.call("plugins.list")
        assert after_list["plugins"] == before_list["plugins"]
        assert after_list["environments"] == before_list["environments"]
        assert after_list["revision"] == before_list["revision"]
        after = plugin_state(rig)
        assert after["lock"] == before["lock"] and after["wheels"] == before["wheels"]
        for name, files in before["envs"].items():
            assert after["envs"][name] == files  # 기존 환경 파일 전체 그대로
        # 원천 받기 단계 실패는 미리보기 요청의 오류 (작업 알림 없음)
        error = refused(ui, "plugins.preview", {"source": str(rig.root / "없는.whl")})
        assert error.kind == "plugin_failed"
        assert error.data["plugin_error"]["code"] in ("source_unavailable", "manifest_invalid")
        assert ui.call("plugins.list")["busy"] is None


def test_plugin_methods_agent_denied(rig: Rig, daemon: ThreadDaemon) -> None:
    """에이전트 연결: 모든 변경 메서드가 판정 전 `permission_denied`, 잠금·폴더 그대로. 목록은 된다.
    작업 진행·끝 알림은 ui 연결에만."""
    rig.add("sample")
    lock = rig.lock()
    revision = revision_of(rig.lock_bytes())
    with daemon.client(AGENT) as agent, daemon.client() as ui:
        before = plugin_state(rig)
        calls: dict[str, dict[str, Any]] = {
            "plugins.preview": {"source": str(rig.world.wheel("compatible_c"))},
            "plugins.install": {"op_id": "0" * 32},
            "plugins.upgrade": {"id": "sample"},
            "plugins.remove": {"id": "sample", "base_revision": revision},
            "plugins.sync": {"lock_sha256": lock_sha256(lock)},
            "plugins.relock": {"lock_sha256": lock_sha256(lock)},
            "plugins.gc": {"candidates": {"envs": [], "wheels": [], "staging": []}},
            "plugins.cancel": {"op_id": "0" * 32},
        }
        for method, params in calls.items():
            error = refused(agent, method, params)
            assert error.kind == "permission_denied", method
        # 사람의 미리보기를 에이전트가 승인·취소하지 못한다
        shown = ui.call("plugins.preview", {"source": str(rig.world.wheel("compatible_c"))})
        for method in ("plugins.install", "plugins.cancel"):
            assert refused(agent, method, {"op_id": shown["op_id"]}).kind == "permission_denied"
        ui.call("plugins.cancel", {"op_id": shown["op_id"]})
        notification(ui, "plugins.done", op_id=shown["op_id"])
        # 목록은 에이전트도 (core 툴셋, kb_project_info)
        listed = agent.call("plugins.list")
        assert [p["id"] for p in listed["plugins"]] == ["sample"]
        assert listed["plugins"][0]["env_status"] == "ready"
        assert plugin_state(rig) == before
        seen = {m.get("method") for m in drain(agent)}
        assert not seen & {"plugins.progress", "plugins.done"}


def test_list_widget_host_only_when_ready(rig: Rig, daemon: ThreadDaemon) -> None:
    """위젯 호스트 (M6 3.10): 머리에 ui가 있고 환경이 준비된 플러그인만 `ui {host, path, widgets}`.
    호스트는 CSP 문법에 맞게 '_' 없음, 경로는 워크스페이스 기준 환경 안 ui 폴더.
    노드에는 config → 위젯."""
    rig.add("sample")
    with daemon.client() as ui:
        entry = ui.call("plugins.list")["plugins"][0]
        fp = rig.lock()["environments"][entry["env"]]["fingerprint"]
        assert entry["ui"]["host"] == f"sample-{fp[:12]}"
        assert entry["ui"]["widgets"] == ["sample.color"]
        path = entry["ui"]["path"]
        assert path.startswith(".kookabug/plugins/envs/") and ":" not in path
        assert (rig.root / path / "index.js").is_file()
        assert (rig.root / path).resolve().is_relative_to(rig.env_dir(entry["env"]).resolve())
        nodes = {n["type"]: n for n in entry["nodes"]}
        assert nodes["sample.color.pick"]["ui"] == {"color": "sample.color"}
        assert "ui" not in nodes["sample.text.reverse"]
        # 환경이 없으면 위젯 호스트도 없다 (기본 편집기)
        shutil.rmtree(rig.envs)
        entry = ui.call("plugins.list")["plugins"][0]
        assert entry["env_status"] == "missing"
        assert "ui" not in entry


def test_env_broken_without_lock_change_notifies(rig: Rig, daemon: ThreadDaemon) -> None:
    """잠금은 그대로인데 환경이 깨짐이 되면(밖의 verify) `plugins.changed {같은 revision}` — 화면이
    목록을 다시 읽어 위젯을 내린다 (M6 B6 검수 High). 잠금 밖 새 환경 폴더만으로는 알리지 않는다."""
    rig.add("sample")
    revision = revision_of(rig.lock_bytes())
    with daemon.client() as ui:
        # 설치(잠금 변경) 알림을 먼저 받는다
        notification(ui, "plugins.changed", timeout=30, revision=revision)
        assert ui.call("plugins.list")["plugins"][0]["env_status"] == "ready"
        time.sleep(0.5)
        drain(ui)
        # 잠금이 가리키지 않는 폴더가 생겨도 알림 없음
        (rig.envs / "shared-000000000000-deadbeef").mkdir()
        time.sleep(1.0)
        assert not [m for m in drain(ui) if m.get("method") == "plugins.changed"]
        env = rig.env_dir("shared")
        (env / "Lib" / "site-packages" / "kookabug_plugin_sample" / "ui" / "late.mjs").write_text(
            "export const x = 1;", encoding="utf-8"
        )
        assert rig.ops().verify()["ok"] is False
        assert notification(ui, "plugins.changed", timeout=30)["revision"] == revision
        entry = ui.call("plugins.list")["plugins"][0]
        assert entry["env_status"] == "broken"
        assert "ui" not in entry


def test_external_lock_change_notifies(rig: Rig, daemon: ThreadDaemon) -> None:
    """잠금을 밖(CLI 같은 다른 작업)에서 바꿔도 모든 연결에 `plugins.changed`, 레지스트리 재생성.
    환경이 없어지면 편집기 사전 검증에 `plugin_env_missing`."""
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        value = sample_graph(rig)
        assert "sample.text.reverse" not in node_types(ui)
        rig.add("sample")
        revision = revision_of(rig.lock_bytes())
        assert notification(ui, "plugins.changed", timeout=30)["revision"] == revision
        assert notification(agent, "plugins.changed", timeout=30)["revision"] == revision
        assert "sample.text.reverse" in node_types(ui)
        checked = ui.call("graph.check", {"path": GRAPH, "value": value})
        assert not [d for d in checked["diagnostics"] if d["code"].startswith("plugin_")]
        # 환경 폴더가 없어짐 (다른 PC에 클론한 것과 같다): 편집기에 준비 필요
        shutil.rmtree(rig.envs)
        checked = ui.call("graph.check", {"path": GRAPH, "value": value})
        missing = [d for d in checked["diagnostics"] if d["code"] == "plugin_env_missing"]
        assert missing and missing[0]["node"] == "n_rev"
        assert ui.call("plugins.list")["plugins"][0]["env_status"] == "missing"
        # 밖에서 제거
        rig.ops().remove("sample", confirm=lambda _: True)
        changed = notification(ui, "plugins.changed", timeout=30)
        assert changed["revision"] == revision_of(rig.lock_bytes())
        assert "sample.text.reverse" not in node_types(ui)
        checked = ui.call("graph.check", {"path": GRAPH, "value": value})
        assert "plugin_not_installed" in {d["code"] for d in checked["diagnostics"]}


def test_sync_requires_confirmed_lock_hash(rig: Rig, daemon: ThreadDaemon) -> None:
    """준비(sync)는 사람이 확인한 정규 잠금 해시일 때만: 다르면 `revision_conflict`, 아무것도 안
    만든다. 맞으면 환경을 만들고 목록이 준비됨."""
    rig.add("sample")
    shutil.rmtree(rig.envs)  # 클론한 PC: 잠금·wheel만 있다
    with daemon.client() as ui:
        listed = ui.call("plugins.list")
        assert listed["plugins"][0]["env_status"] == "missing"
        assert listed["environments"]["shared"]["status"] == "missing"
        started = ui.call("plugins.sync", {"lock_sha256": "0" * 64})
        done = notification(ui, "plugins.done", op_id=started["op_id"])
        assert done["ok"] is False and done["error"]["code"] == "revision_conflict"
        assert not rig.envs.exists() or not any(rig.envs.iterdir())
        started = ui.call("plugins.sync", {"lock_sha256": listed["lock_sha256"]})
        done = notification(ui, "plugins.done", op_id=started["op_id"])
        assert done["ok"] is True and done["result"]["created"] == ["shared"], done
        assert ui.call("plugins.list")["plugins"][0]["env_status"] == "ready"
        # 제거는 본 잠금 revision일 때만
        stale = ui.call("plugins.remove", {"id": "sample", "base_revision": "0" * 64})
        done = notification(ui, "plugins.done", op_id=stale["op_id"])
        assert done["ok"] is False and done["error"]["code"] == "revision_conflict"
        assert rig.lock()["plugins"][0]["id"] == "sample"
        removed = ui.call("plugins.remove", {"id": "sample", "base_revision": listed["revision"]})
        done = notification(ui, "plugins.done", op_id=removed["op_id"])
        assert done["ok"] is True and rig.lock()["plugins"] == []
        # 정리: 안 쓰는 환경·wheel (목록의 후보 = gc가 지운 것)
        candidates = ui.call("plugins.list")["gc_candidates"]
        assert candidates["envs"] and candidates["wheels"]
        started = ui.call("plugins.gc", {"candidates": candidates})
        done = notification(ui, "plugins.done", op_id=started["op_id"])
        assert done["ok"] is True
        assert done["result"]["removed"]["envs"] == candidates["envs"]
        assert done["result"]["removed"]["wheels"] == candidates["wheels"]


def _untrusted_stale(rig: Rig, tmp_path: Path) -> dict[str, str]:
    """sample만 든 잠금, 환경·신뢰 기억 없음, 앱 SDK 0.1.1 (조건 다름 → 다시 잠그기 카드)."""
    rig.add("sample")
    shutil.rmtree(rig.envs)
    local = rig.root / ".kookabug/local.json"
    data = json.loads(local.read_text(encoding="utf-8-sig"))
    data.pop("plugin_trust", None)
    local.write_text(json.dumps(data), encoding="utf-8")
    next_sdk = sdk_wheel(tmp_path / "next-sdk", version="0.1.1")
    return {**rig.world.environ, SDK_WHEEL_ENV: str(next_sdk)}


@pytest.mark.parametrize("change", ["added_plugin", "permissions"])
def test_relock_requires_confirmed_lock_hash(rig: Rig, tmp_path: Path, change: str) -> None:
    """다시 잠그기는 카드가 본 잠금(정규 해시)일 때만 (B5 검수 H 재현): 카드를 본 뒤 잠금이 바뀌면
    (플러그인 추가·권한 변경) `revision_conflict` — 환경·잠금·신뢰 그대로. 다시 본 해시로는 진행."""
    environ = _untrusted_stale(rig, tmp_path)
    lock_path = rig.root / "kookabug.lock"
    with (
        ThreadDaemon(rig.root, plugin_environ=environ, watch_interval_s=0.1) as d,
        d.client() as ui,
    ):
        card = ui.call("plugins.list")
        assert [p["id"] for p in card["plugins"]] == ["sample"] and card["stale_reason"]
        if change == "added_plugin":
            # 밖에서 받은 새 잠금: 카드에 없던 플러그인이 들었다 (같은 PC의 다른 거래로 만든다)
            PluginOps(rig.root, environ=rig.world.environ).add(
                str(rig.world.wheel("compatible_c")), confirm=lambda _: True
            )
            shutil.rmtree(rig.envs)
        else:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["plugins"][0]["manifest"]["permissions"] = ["capture", "network"]
            lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True), encoding="utf-8")
        local = rig.root / ".kookabug/local.json"
        data = json.loads(local.read_text(encoding="utf-8-sig"))
        data.pop("plugin_trust", None)
        local.write_text(json.dumps(data), encoding="utf-8")
        before = plugin_state(rig)
        current = ui.call("plugins.list")
        assert current["lock_sha256"] != card["lock_sha256"] and current["trusted"] is False
        started = ui.call("plugins.relock", {"lock_sha256": card["lock_sha256"]})
        done = notification(ui, "plugins.done", op_id=started["op_id"])
        assert done["ok"] is False and done["error"]["code"] == "revision_conflict", done
        assert plugin_state(rig) == before
        assert ui.call("plugins.list")["trusted"] is False
        # 다시 본 카드의 해시로는 진행한다
        started = ui.call("plugins.relock", {"lock_sha256": current["lock_sha256"]})
        done = notification(ui, "plugins.done", op_id=started["op_id"])
        assert done["ok"] is True, done
        after = ui.call("plugins.list")
        assert after["stale_reason"] is None and after["trusted"] is True
        assert all(p["env_status"] == "ready" for p in after["plugins"])


def test_gc_removes_only_confirmed_candidates(rig: Rig, daemon: ThreadDaemon) -> None:
    """정리는 카드에서 본 후보 안의 것만 지운다: 카드에 없던 후보(그 사이 생긴 것)는 남는다."""
    rig.add("sample")
    with daemon.client() as ui:
        listed = ui.call("plugins.list")
        removed = ui.call("plugins.remove", {"id": "sample", "base_revision": listed["revision"]})
        assert notification(ui, "plugins.done", op_id=removed["op_id"])["ok"] is True
        candidates = ui.call("plugins.list")["gc_candidates"]
        assert candidates["envs"] and candidates["wheels"]
        shown = {"envs": [], "wheels": candidates["wheels"], "staging": []}
        started = ui.call("plugins.gc", {"candidates": shown})
        done = notification(ui, "plugins.done", op_id=started["op_id"])
        assert done["ok"] is True
        assert done["result"]["removed"]["wheels"] == candidates["wheels"]
        assert done["result"]["removed"]["envs"] == []
        assert all((rig.envs / name).is_dir() for name in candidates["envs"])
        assert ui.call("plugins.list")["gc_candidates"]["envs"] == candidates["envs"]


def _staging_empty(rig: Rig) -> bool:
    staging = rig.root / ".kookabug/plugins/staging"
    return not staging.exists() or not any(staging.iterdir())


def test_preview_cancelled_when_connection_closes(rig: Rig) -> None:
    """미리보기를 연 연결이 끊기면 승인 대기를 ③에서 취소한다 (busy.lock을 5분 쥐지 않음):
    잠금·환경·staging 없음, 다음 작업이 곧바로 된다."""
    with ThreadDaemon(rig.root, plugin_environ=rig.world.environ) as d:
        with d.client() as ui:
            shown = ui.call("plugins.preview", {"source": str(rig.world.wheel("sample"))})
            assert d.daemon.plugin_jobs.active()
        deadline = time.monotonic() + 30
        while d.daemon.plugin_jobs.active():
            assert time.monotonic() < deadline, "연결이 끊긴 뒤에도 미리보기가 남았다"
            time.sleep(0.05)
        assert rig.lock_bytes() is None and not rig.envs.exists() and _staging_empty(rig)
        with d.client() as later:  # 연결이 끊긴 미리보기는 누구도 승인할 수 없다
            assert refused(later, "plugins.install", {"op_id": shown["op_id"]}).kind == (
                "op_not_found"
            )
        assert rig.ops().gc(confirm=lambda _: True)["failed"] == []  # busy.lock이 풀렸다


def test_other_ui_cannot_approve_owned_preview(rig: Rig) -> None:
    """미리보기는 연 연결만 승인·취소한다 (신뢰 확인을 본 화면 = 승인하는 화면). 다른 UI·에이전트의
    요청은 거부되고 미리보기는 그대로 기다린다 → 소유자 승인으로 설치. 다른 연결의 목록에는 대기
    미리보기의 op_id가 없다. 만료 뒤에는 소유자도 승인할 수 없다 (검수 B4-1 High 1)."""
    wheel = str(rig.world.wheel("sample"))
    with (
        ThreadDaemon(rig.root, plugin_environ=rig.world.environ) as d,
        d.client() as owner,
        d.client() as other,
        d.client(AGENT) as agent,
    ):
        shown = owner.call("plugins.preview", {"source": wheel})
        op_id = shown["op_id"]
        busy = other.call("plugins.list")["busy"]
        assert busy["op_id"] is None and busy["waiting"] is True
        assert owner.call("plugins.list")["busy"]["op_id"] == op_id
        for method in ("plugins.install", "plugins.cancel"):
            assert refused(other, method, {"op_id": op_id}).kind == "permission_denied", method
            assert refused(agent, method, {"op_id": op_id}).kind == "permission_denied", method
        error = refused(other, "plugins.preview", {"source": wheel})  # 바쁨: ID를 내놓지 않는다
        assert error.data["plugin_error"]["code"] == "plugin_busy"
        assert "op_id" not in error.data["plugin_error"]
        assert rig.lock_bytes() is None
        assert owner.call("plugins.list")["busy"]["waiting"] is True  # 그대로 기다린다
        assert owner.call("plugins.install", {"op_id": op_id}) == {"op_id": op_id}
        done = notification(owner, "plugins.done", op_id=op_id)
        assert done["ok"] is True and rig.lock()["plugins"][0]["id"] == "sample"
        # 만료: 소유자의 승인도 op_not_found, 아무것도 바뀌지 않는다
        d.daemon.plugin_jobs.preview_ttl_s = 0.3
        before = plugin_state(rig)
        shown = owner.call("plugins.upgrade", {"id": "sample"})
        done = notification(owner, "plugins.done", op_id=shown["op_id"])
        assert done["ok"] is False and done["error"]["code"] == "cancelled"
        assert refused(owner, "plugins.install", {"op_id": shown["op_id"]}).kind == "op_not_found"
        assert plugin_state(rig) == before


def test_null_revision_cannot_remove_newly_appeared_lock(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`base_revision: null`(확인할 때 잠금 없음) 뒤 거래 전에 잠금이 생기면 `revision_conflict` —
    null도 거래 안에서 읽은 revision과 비교한다 (검수 B4-1 High 2). 생기는 시점은 거래 직전."""
    rig.add("sample")
    saved = rig.lock_bytes()
    assert saved is not None
    path = rig.root / "kookabug.lock"
    path.unlink()
    original = PluginOps.remove

    def appeared(self: PluginOps, plugin_id: str, **kwargs: Any) -> dict[str, Any]:
        path.write_bytes(saved)  # 다른 프로세스가 잠금을 만들었다
        return original(self, plugin_id, **kwargs)

    monkeypatch.setattr(PluginOps, "remove", appeared)
    with ThreadDaemon(rig.root, plugin_environ=rig.world.environ) as d, d.client() as ui:
        assert ui.call("plugins.list")["revision"] is None
        started = ui.call("plugins.remove", {"id": "sample", "base_revision": None})
        done = notification(ui, "plugins.done", op_id=started["op_id"])
        assert done["ok"] is False and done["error"]["code"] == "revision_conflict"
    assert path.read_bytes() == saved


def test_daemon_shutdown_during_install_keeps_lock(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """승인 뒤 진행 중(⑦ 새 환경 완성 뒤·⑧ 전)에 daemon이 끝나면 거래를 취소한다: 잠금·기존 환경
    그대로, staging 정리. 새로 만든 환경은 잠금이 가리키지 않아 아무도 쓰지 않는다 (gc 몫)."""
    rig.add("conflict_a")
    before = plugin_state(rig)
    reached = threading.Event()
    original = PluginOps._archive  # pyright: ignore[reportPrivateUsage]

    def archive(self: PluginOps, built: Path, rel: str, sha: str) -> None:
        reached.set()
        while not self._cancel.is_set():  # pyright: ignore[reportPrivateUsage]
            time.sleep(0.02)  # daemon 종료가 취소할 때까지 ⑧ 앞에서 기다린다
        original(self, built, rel, sha)

    monkeypatch.setattr(PluginOps, "_archive", archive)
    d = ThreadDaemon(rig.root, plugin_environ=rig.world.environ)
    with d, d.client() as ui:
        shown = ui.call("plugins.preview", {"source": str(rig.world.wheel("compatible_c"))})
        ui.call("plugins.install", {"op_id": shown["op_id"]})
        assert reached.wait(DONE_WAIT_S)
        d.daemon.stop("test")
        d._thread.join(120)  # pyright: ignore[reportPrivateUsage]
    assert not d.daemon.plugin_jobs.active()
    after = plugin_state(rig)
    assert after["lock"] == before["lock"]
    assert before["wheels"].items() <= after["wheels"].items()  # 기존 커밋 wheel 그대로
    for name, files in before["envs"].items():
        assert after["envs"][name] == files
    assert _staging_empty(rig)
    assert [p["id"] for p in rig.lock()["plugins"]] == ["conflict_a"]
    # 취소된 거래가 남긴 새 환경·보관 wheel은 잠금이 가리키지 않는다 → gc가 지운다
    removed = rig.ops().gc(confirm=lambda _: True)["removed"]
    assert set(after["envs"]) - set(before["envs"]) == set(removed["envs"])
    assert plugin_state(rig) == before
