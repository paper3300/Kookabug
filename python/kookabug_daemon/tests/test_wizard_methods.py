"""마법사 메서드 (M8 계획 3.17, B7): 진행 저장·팀/이 PC 설정 쓰기·보기 탭 읽기 범위.

- `wizard.json`에는 단계 상태만 들어간다(스키마가 다른 키를 거부)
- `project.setup.set`은 `kookabug.json` sha가 다르면 아무것도 쓰지 않는다
- `local.settings.set`은 `local.json`의 다른 키(권한 등)를 보존한다
- Agent 연결은 네 메서드 모두 판정 전에 거부된다(`test_human_only_m8`이 표 전수로도 본다)
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import copy_example_workspace
from kookabug_daemon.client import DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "panel", "attended": True}
STATE = {"format": "kookabug.wizard/0", "step": 3, "done": [1, 2, 2], "skipped": [], "warnings": []}


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return copy_example_workspace(tmp_path)


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws) as d:
        yield d


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_wizard_state_roundtrip_and_team_setup(ws: Path, daemon: ThreadDaemon) -> None:
    with daemon.client() as ui:
        first = ui.call("wizard.get", {})
        assert first["wizard"] is None and first["team_setup"] is False
        assert first["config_sha256"] == sha(ws / "kookabug.json")
        assert first["game"]["title"] == "SampleRPG"
        saved = ui.call("wizard.set", {"wizard": STATE})["wizard"]
        assert saved["done"] == [1, 2]  # 중복은 하나로
        (ws / "wiki").mkdir(exist_ok=True)
        (ws / "wiki" / "index.md").write_text("# 위키\n", encoding="utf-8")
        again = ui.call("wizard.get", {})
        assert again["wizard"] == saved and again["team_setup"] is True
        # 단계 상태 밖의 값(입력 값·비밀값 자리)은 계약이 거부한다 — 파일은 그대로
        before = (ws / ".kookabug" / "wizard.json").read_bytes()
        # (검사 클라이언트도 같은 계약으로 먼저 거부한다 — 어느 쪽이든 쓰기는 없다)
        with pytest.raises((DaemonError, ValueError), match="password"):
            ui.call("wizard.set", {"wizard": {**STATE, "password": "x"}})
        with pytest.raises((DaemonError, ValueError)):
            ui.call("wizard.set", {"wizard": {**STATE, "step": 12}})
        assert (ws / ".kookabug" / "wizard.json").read_bytes() == before
    stored = json.loads((ws / ".kookabug" / "wizard.json").read_text("utf-8"))
    assert set(stored) == {"format", "step", "done", "skipped", "warnings"}


def test_broken_wizard_file_reads_as_none(ws: Path, daemon: ThreadDaemon) -> None:
    (ws / ".kookabug").mkdir(exist_ok=True)
    (ws / ".kookabug" / "wizard.json").write_text("{깨짐", encoding="utf-8")
    with daemon.client() as ui:
        assert ui.call("wizard.get", {})["wizard"] is None


@pytest.mark.parametrize(
    "broken",
    [
        {"warnings": [{"code": "x"}]},  # step 없음
        {"warnings": [{"step": "3", "code": "x"}]},  # 문자열 step
        {"warnings": [{"step": 12, "code": "x"}]},  # 범위 밖
        {"warnings": [{"step": 3, "code": "Bad Code"}]},  # code 형식
        {"warnings": "x"},  # 잘못된 컨테이너
        {"warnings": {"step": 3}},
        {"done": {"1": True}},
        {"skipped": [1, "2"]},
        {"step": True},
        {"extra": "x"},  # 단계 상태 밖 키
    ],
)
def test_review_wizard_bad_structure_reads_as_none(
    ws: Path, daemon: ThreadDaemon, broken: dict[str, object]
) -> None:
    """B7 검수 M7: JSON 문법은 맞아도 `Kb8WizardState` 구조가 틀리면 내부 오류가 아니라 없음."""
    (ws / ".kookabug").mkdir(exist_ok=True)
    (ws / ".kookabug" / "wizard.json").write_text(json.dumps({**STATE, **broken}), "utf-8")
    with daemon.client() as ui:
        assert ui.call("wizard.get", {})["wizard"] is None
        # 양성 대조: 맞는 상태는 읽는다
        (ws / ".kookabug" / "wizard.json").write_text(json.dumps(STATE), "utf-8")
        assert ui.call("wizard.get", {})["wizard"]["done"] == [1, 2]


def _junction_kookabug(tmp_path: Path) -> tuple[Path, Path]:
    """`.kookabug`가 워크스페이스 밖 빈 폴더를 가리키는 정션인 예제 워크스페이스 (검수 재현과 같다 —
    외부에 local.json이 이미 있으면 권한 정책 읽기가 먼저 `policy_path`로 막는다)."""
    import _winapi

    ws = copy_example_workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "marker.txt").write_bytes(b"outside")
    shutil.rmtree(ws / ".kookabug")
    _winapi.CreateJunction(str(outside), str(ws / ".kookabug"))
    return ws, outside


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 정션")
def test_review_kookabug_junction_writes_refused(tmp_path: Path) -> None:
    """B7 검수 H2: 사람 전용 쓰기도 쓰기 직전에 경로 경계(filetx.plain)를 지난다 — 정션 밖에
    쓰지 않는다."""
    ws, outside = _junction_kookabug(tmp_path / "a")
    before = {p.name: p.read_bytes() for p in outside.iterdir() if p.is_file()}
    with ThreadDaemon(ws) as d, d.client() as ui:
        with pytest.raises(DaemonError) as wizard_err:
            ui.call("wizard.set", {"wizard": STATE})
        assert wizard_err.value.kind == "path_outside_workspace"
        with pytest.raises(DaemonError) as local_err:
            ui.call("local.settings.set", {"settings": {"game.args": ["review-marker"]}})
        assert local_err.value.kind == "path_outside_workspace"
        # 같은 local.json 쓰기 경로(권한 파일)도
        layers = ui.call("permissions.get", {})["layers"]
        project = next(layer for layer in layers if layer["layer"] == "project")
        with pytest.raises(DaemonError) as perm_err:
            ui.call(
                "permissions.set",
                {
                    "layer": "project",
                    "base_revision": project["revision"],
                    "permissions": {"preset": "runner"},
                },
            )
        assert perm_err.value.kind == "path_outside_workspace"
    assert not (outside / "wizard.json").exists()
    assert not (outside / "local.json").exists()
    # 이미 있던 외부 바이트는 그대로 (daemon 자체 잠금 파일 daemon.lock·screens.lock은 B7 이전 동작)
    assert {name: (outside / name).read_bytes() for name in before} == before
    # 양성 대조: 정상 워크스페이스에서는 두 쓰기가 된다
    plain = copy_example_workspace(tmp_path / "b")
    with ThreadDaemon(plain) as d, d.client() as ui:
        assert ui.call("wizard.set", {"wizard": STATE})["wizard"]["step"] == 3
        ui.call("local.settings.set", {"settings": {"game.args": ["review-marker"]}})
    assert (plain / ".kookabug" / "wizard.json").is_file()
    local = json.loads((plain / ".kookabug" / "local.json").read_text("utf-8"))
    assert local["settings"]["game.args"] == ["review-marker"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 파일 공유 규칙")
def test_review_local_settings_retry_rechecks_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B7 검수 H3: 첫 교체가 공유 위반이고 그사이 외부 작성자가 바꾸면, 재시도도 교체 직전에 충돌
    검사를 다시 해 `revision_conflict`로 끝난다 — 외부 변경 보존, 임시 파일 없음."""
    from kookabug_core import documents
    from kookabug_core.service import WorkspaceService
    from kookabug_daemon.permission_files import PermissionFiles
    from kookabug_daemon.protocol import RequestFailed

    ws = copy_example_workspace(tmp_path)
    local = ws / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body.setdefault("settings", {})["game.args"] = ["old"]
    local.write_text(json.dumps(body), "utf-8")
    cwd_before = body["settings"].get("game.cwd")
    service = WorkspaceService(ws, environ={"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "u")})
    files = PermissionFiles(ws, service)
    real_replace = documents.os.replace
    calls: list[str] = []

    def flaky(src: str, dst: str | Path) -> None:
        calls.append(str(dst))
        if len(calls) == 1:
            # 첫 교체: 다른 프로세스가 읽는 중 → 그사이 외부 작성자가 대상을 바꾼다
            external = json.loads(local.read_text("utf-8"))
            external["settings"]["game.args"] = ["external-new"]
            local.write_text(json.dumps(external), "utf-8")
            raise PermissionError(32, "공유 위반 (검사 주입)")
        real_replace(src, dst)

    monkeypatch.setattr(documents.os, "replace", flaky)
    with pytest.raises(RequestFailed) as conflict:
        files.set_local_settings({"game.cwd": "C:/review"})
    assert conflict.value.code == "revision_conflict"
    assert len(calls) == 1  # 충돌을 알았으면 다시 교체하지 않는다
    final = json.loads(local.read_text("utf-8"))
    assert final["settings"]["game.args"] == ["external-new"]  # 외부 변경 보존
    assert final["settings"].get("game.cwd") == cwd_before != "C:/review"
    assert [p.name for p in local.parent.iterdir() if p.name.endswith(".tmp")] == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 정션·파일 공유 규칙")
@pytest.mark.parametrize("which", ["wizard", "local", "job"])
def test_review_retry_rejects_kookabug_junction_swapped_after_first_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    """B7-2 검수 H1: 첫 교체가 공유 위반이고 그사이 `.kookabug`가 밖을 가리키는 정션으로 바뀌면,
    재시도는 교체 직전에 경계를 다시 봐 `path_outside_workspace`로 끝난다 — 외부 바이트 그대로,
    임시 파일 없음."""
    import _winapi
    from types import SimpleNamespace

    from kookabug_core import documents, filetx
    from kookabug_core.agent_job import jobdir
    from kookabug_core.service import WorkspaceService
    from kookabug_daemon.methods import wizard
    from kookabug_daemon.permission_files import PermissionFiles
    from kookabug_daemon.protocol import RequestFailed

    ws = copy_example_workspace(tmp_path / "ws")
    inner = ws / ".kookabug"
    inner.mkdir(exist_ok=True)
    (inner / "wizard.json").write_text(json.dumps({**STATE, "step": 2}), "utf-8")
    moved = tmp_path / "moved-outside"
    real_replace = documents.os.replace
    calls: list[str] = []

    def flaky(src: str, dst: str | Path) -> None:
        calls.append(str(dst))
        if len(calls) == 1:
            # 첫 교체: 공유 위반. 그사이 `.kookabug`를 밖으로 옮기고 그 자리에 정션을 만든다
            # (임시 파일도 같이 옮겨지므로 다음 교체는 실제로 성공할 수 있다)
            inner.rename(moved)
            _winapi.CreateJunction(str(moved), str(inner))
            raise PermissionError(32, "공유 위반 (검사 주입)")
        real_replace(src, dst)

    before: dict[str, bytes] = {}
    job_id = "j-20261110-000000-abcd"
    job_file = f"jobs/{job_id}/job.json"
    if which == "job":
        (inner / "jobs" / job_id).mkdir(parents=True)
        (inner / job_file).write_text(json.dumps({"id": job_id, "state": "running"}), "utf-8")
    monkeypatch.setattr(documents.os, "replace", flaky)
    with pytest.raises((RequestFailed, filetx.TxError)) as err:
        if which == "job":
            # 같은 모양 (반대 검수): agent-job CLI의 job.json 쓰기
            before = {job_file: (inner / job_file).read_bytes()}
            jobdir.write_job(ws, {"id": job_id, "state": "done"})
        elif which == "wizard":
            call = SimpleNamespace(
                daemon=SimpleNamespace(root=ws), params={"wizard": {**STATE, "step": 7}}
            )
            before = {"wizard.json": (inner / "wizard.json").read_bytes()}
            wizard._guarded(wizard._set_sync, call)
        else:
            service = WorkspaceService(
                ws, environ={"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "u")}
            )
            before = {"local.json": (inner / "local.json").read_bytes()}
            PermissionFiles(ws, service).set_local_settings({"game.args": ["review-outside-write"]})
    monkeypatch.undo()
    assert getattr(err.value, "code", None) == "path_outside_workspace"
    assert len(calls) == 1  # 경계가 바뀐 걸 알았으면 다시 교체하지 않는다
    assert {name: (moved / name).read_bytes() for name in before} == before
    assert [p.name for p in moved.rglob("*.tmp")] == []


def test_setup_set_writes_blocks_and_refuses_stale_sha(ws: Path, daemon: ThreadDaemon) -> None:
    config = ws / "kookabug.json"
    with daemon.client() as ui:
        base = ui.call("wizard.get", {})["config_sha256"]
        done = ui.call(
            "project.setup.set",
            {
                "base_sha256": base,
                "record": {"screenshots": "on", "video": "failed_only"},
                "retention": {"passed_days": 14, "failed_days": 60},
                "settings": {"game.client_size": [1280, 720]},
            },
        )
        assert done["sha256"] == sha(config)
        body = json.loads(config.read_text("utf-8"))
        assert body["record"]["video"] == "failed_only" and body["retention"]["failed_days"] == 60
        assert body["settings"]["game.client_size"] == [1280, 720]
        assert body["settings"]["game.title"] == "SampleRPG"  # 다른 설정 키는 그대로
        after = config.read_bytes()
        with pytest.raises(DaemonError) as stale:
            ui.call("project.setup.set", {"base_sha256": base, "record": {"video": "off"}})
        assert stale.value.kind == "revision_conflict"
        assert config.read_bytes() == after  # 양성 대조: 위에서는 실제로 바뀌었다
        with pytest.raises(DaemonError) as bad:
            ui.call("project.setup.set", {"base_sha256": done["sha256"], "record": {"video": "x"}})
        assert bad.value.kind == "validation_failed"
        assert config.read_bytes() == after


def test_local_settings_keep_other_keys(ws: Path, daemon: ThreadDaemon) -> None:
    local = ws / ".kookabug" / "local.json"
    before = json.loads(local.read_text("utf-8"))
    with daemon.client() as ui:
        ui.call(
            "local.settings.set",
            {"settings": {"game.executable": "C:/Games/Sample/game.exe", "game.args": ["-w"]}},
        )
        body = json.loads(local.read_text("utf-8"))
        assert body["settings"]["game.executable"] == "C:/Games/Sample/game.exe"
        for key, value in before.items():
            if key != "settings":
                assert body[key] == value
        assert ui.call("wizard.get", {})["game"]["executable"] == "C:/Games/Sample/game.exe"
        ui.call("local.settings.set", {"settings": {"game.args": None}})
        assert "game.args" not in json.loads(local.read_text("utf-8"))["settings"]
        # 6단계 이 PC 원본 경로 (local 원본 — sources.check가 이 경로를 본다)
        ui.call("local.settings.set", {"sources": {"game_code": "C:/Src/Game"}})
        body = json.loads(local.read_text("utf-8"))
        assert body["sources"]["game_code"] == {"path": "C:/Src/Game"}
        assert body["settings"]["game.executable"] == "C:/Games/Sample/game.exe"  # 다른 키 보존
        with pytest.raises(DaemonError):
            ui.call("local.settings.set", {"sources": {"Bad Id": "C:/x"}})
        # 게임 실행 키 밖(권한 등)은 계약이 거부한다
        with pytest.raises((DaemonError, ValueError), match="permissions"):
            ui.call("local.settings.set", {"settings": {"permissions": "x"}})


def test_get_local_sources_and_base_revision(ws: Path, daemon: ThreadDaemon) -> None:
    """6단계 화면 채우기(B7 검수 H4·H5): `wizard.get`이 팀 원본·이 PC 경로·local revision을 한 번에
    주고, `local.settings.set`은 그 revision과 대조한다."""
    local = ws / ".kookabug" / "local.json"
    with daemon.client() as ui:
        ui.call("local.settings.set", {"sources": {"game_code": "C:/Src/Game"}})
        got = ui.call("wizard.get", {})
        assert got["local_sources"] == {"game_code": "C:/Src/Game"}
        assert got["local_revision"] == sha(local)
        team = json.loads((ws / "kookabug.json").read_text("utf-8"))["sources"]
        assert got["sources"] == team and team  # 빈 목록끼리 같아서 통과하지 않게
        # 화면을 채운 뒤 밖에서 바뀌면 거부하고 파일은 그대로
        local.write_text(local.read_text("utf-8").replace("C:/Src/Game", "C:/Other"), "utf-8")
        after = local.read_bytes()
        with pytest.raises(DaemonError) as err:
            ui.call(
                "local.settings.set",
                {"base_revision": got["local_revision"], "sources": {"game_code": None}},
            )
        assert err.value.kind == "revision_conflict"
        assert local.read_bytes() == after
        # 양성 대조: 다시 읽은 revision이면 된다
        fresh = ui.call("wizard.get", {})["local_revision"]
        ui.call("local.settings.set", {"base_revision": fresh, "sources": {"game_code": None}})
        assert "game_code" not in json.loads(local.read_text("utf-8")).get("sources", {})


def test_agent_denied_wizard_methods(ws: Path, daemon: ThreadDaemon) -> None:
    calls = {
        "wizard.get": {},
        "wizard.set": {"wizard": STATE},
        "project.setup.set": {"base_sha256": "0" * 64, "record": {}},
        "local.settings.set": {"settings": {"game.cwd": "C:/x"}},
    }
    with daemon.client(AGENT) as agent:
        for method, params in calls.items():
            with pytest.raises(DaemonError) as denied:
                agent.call(method, params)
            assert denied.value.kind == "permission_denied", method
    assert not (ws / ".kookabug" / "wizard.json").exists()


def test_read_scope_knowledge_and_wiki_not_private(ws: Path, daemon: ThreadDaemon) -> None:
    (ws / "wiki").mkdir(exist_ok=True)
    (ws / "wiki" / "index.md").write_bytes("# 위키\n".encode())
    with daemon.client() as ui:
        assert ui.call("workspace.read", {"path": "wiki/index.md"})["text"] == "# 위키\n"
        assert ui.call("workspace.read", {"path": "knowledge/features/shop.json"})["bytes"] > 0
        for path in (".kookabug/local.json", "runs/x.json", "knowledge/../.kookabug/local.json"):
            with pytest.raises(DaemonError):
                ui.call("workspace.read", {"path": path})
        # 탐색기 목록은 그대로 (보기 탭으로만 읽는다)
        tree = ui.call("workspace.tree", {})["entries"]
        assert not [e for e in tree if e["path"].startswith(("wiki", "knowledge"))]
