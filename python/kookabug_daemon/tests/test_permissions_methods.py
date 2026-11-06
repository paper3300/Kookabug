"""`permissions.get/set` (M5 계획 3.5·3.6, B3): 권한 파일 안전 쓰기.

revision(파일 바이트 sha256)이 다르면 `revision_conflict`이고 파일은 그대로다. `permissions`만
바꾸고 다른 키·순서는 보존한다. JSON이 아닌 파일·형식이 틀린 결과는 고치지 않고 `settings_invalid`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon, copy_sample_workspace
from kookabug_core import documents
from kookabug_daemon import permission_files
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.protocol import RequestFailed

pytestmark = [pytest.mark.process, pytest.mark.timeout(120)]


def layer_file(ws: Path, user: Path, name: str) -> tuple[Path, str]:
    if name == "project":
        return ws / ".kookabug" / "local.json", "kookabug.local/0"
    return user / "settings.json", "kookabug.user-settings/0"


@pytest.mark.parametrize("name", ["project", "user"])
@pytest.mark.parametrize("bad_permissions", [{"preset": "invalid"}, ["do-not-replace"]])
def test_invalid_existing_permissions_preserved(
    ws: Path, user_dir: Path, name: str, bad_permissions: Any
) -> None:
    """B3 검수 H3: 기존 permissions가 틀린 파일은 바꾸기 전에 거부하고 바이트를 그대로 둔다."""
    path, fmt = layer_file(ws, user_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps({"format": fmt, "permissions": bad_permissions}).encode()
    path.write_bytes(raw)
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(user_dir)}
    with ThreadDaemon(ws, environ=environ) as d, d.client() as ui:
        error = refused(
            ui,
            {
                "layer": name,
                "permissions": {"preset": "full"},
                "base_revision": hashlib.sha256(raw).hexdigest(),
            },
        )
        assert error.kind == "settings_invalid"
    assert path.read_bytes() == raw


@pytest.mark.parametrize("name", ["project", "user"])
def test_external_edit_during_validation_preserved(
    ws: Path, user_dir: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """B3 검수 H4: 읽은 뒤(형식 검사 중) daemon 밖에서 먼저 저장하면 교체 직전 다시 확인해
    `revision_conflict`, 외부 바이트를 덮어쓰지 않는다."""
    path, fmt = layer_file(ws, user_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps({"format": fmt, "permissions": {"preset": "read_only"}}).encode()
    external = json.dumps({"format": fmt, "permissions": {"preset": "runner"}}).encode()
    path.write_bytes(raw)
    original = permission_files.check_shape
    changed: list[bool] = []

    def concurrent_edit(value: Any, kind: Any, **kwargs: Any) -> Any:
        if kwargs.get("file") == str(path) and not changed:
            path.write_bytes(external)
            changed.append(True)
        return original(value, kind, **kwargs)

    environ = {"KOOKABUG_USER_CONFIG_DIR": str(user_dir)}
    with ThreadDaemon(ws, environ=environ) as d, d.client() as ui:
        monkeypatch.setattr(permission_files, "check_shape", concurrent_edit)
        error = refused(
            ui,
            {
                "layer": name,
                "permissions": {"preset": "full"},
                "base_revision": hashlib.sha256(raw).hexdigest(),
            },
        )
        assert error.kind == "revision_conflict"
        assert error.data["revision"] == hashlib.sha256(external).hexdigest()
    assert changed
    assert path.read_bytes() == external


@pytest.mark.parametrize("operation", ["project", "user", "add_rule"])
def test_edit_after_temp_fsync_before_replace_is_preserved(
    ws: Path, user_dir: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """B3 검수 H4 잔여: 임시 파일 fsync 뒤(교체 바로 앞) daemon 밖에서 먼저 저장해도 덮어쓰지 않고
    `revision_conflict`, 임시 파일도 남지 않는다 (`set`·"항상 허용"의 `add_rule` 둘 다)."""
    name = "user" if operation == "user" else "project"
    path, fmt = layer_file(ws, user_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    before = json.dumps({"format": fmt, "permissions": {"preset": "read_only"}}).encode()
    external = json.dumps({"format": fmt, "permissions": {"preset": "runner"}}).encode()
    path.write_bytes(before)
    original = documents.os.fsync
    injected: list[bool] = []

    def external_edit(fd: int) -> None:
        original(fd)
        if not injected:
            path.write_bytes(external)
            injected.append(True)

    environ = {"KOOKABUG_USER_CONFIG_DIR": str(user_dir)}
    with ThreadDaemon(ws, environ=environ) as d, d.client() as ui:
        monkeypatch.setattr(documents.os, "fsync", external_edit)
        if operation == "add_rule":
            with pytest.raises(RequestFailed) as caught:
                d.daemon.permission_files.add_rule("project", "kb_graph_patch(tests/x.graph.json)")
            kind = caught.value.code
        else:
            kind = refused(
                ui,
                {
                    "layer": name,
                    "permissions": {"preset": "full"},
                    "base_revision": hashlib.sha256(before).hexdigest(),
                },
            ).kind
        assert kind == "revision_conflict"
    assert injected
    assert path.read_bytes() == external
    assert [p.name for p in path.parent.iterdir() if p.suffix == ".tmp"] == []


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return copy_sample_workspace(tmp_path / "ws")


@pytest.fixture
def user_dir(tmp_path: Path) -> Path:
    return tmp_path / "user"


def layer(client: DaemonClient, name: str) -> dict[str, Any]:
    return next(x for x in client.call("permissions.get")["layers"] if x["layer"] == name)


def refused(client: DaemonClient, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call("permissions.set", params)
    return caught.value


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_set_user_and_project_revision_conflict(ws: Path, user_dir: Path) -> None:
    local = ws / ".kookabug" / "local.json"
    settings = user_dir / "settings.json"
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(user_dir)}
    with ThreadDaemon(ws, environ=environ) as d, d.client() as ui:
        got = ui.call("permissions.get")
        layers = {x["layer"]: x for x in got["layers"]}
        assert layers["project"]["revision"] is None and layers["project"]["editable"]
        assert layers["user"]["revision"] is None and layers["user"]["source"] == str(settings)
        assert layers["team"]["editable"] is False
        assert layers["team"]["revision"] == sha(ws / "kookabug.json")
        # 기본값(graph_author)의 사람이 지켜보는 에이전트 기준 판정
        tools = {t["tool"]: t for t in got["tools"]}
        assert tools["kb_graph_patch"]["final"] == "ask"
        assert tools["kb_run_start"]["final"] == "deny"

        for name, path, fmt in (
            ("project", local, "kookabug.local/0"),
            ("user", settings, "kookabug.user-settings/0"),
        ):
            # 새 파일 (기준 null)
            first = ui.call(
                "permissions.set",
                {"layer": name, "permissions": {"preset": "runner"}, "base_revision": None},
            )
            assert first["revision"] == sha(path) == layer(ui, name)["revision"]
            assert json.loads(path.read_text(encoding="utf-8")) == {
                "format": fmt,
                "permissions": {"preset": "runner"},
            }
            # 늦은 쪽: 옛 기준(null)으로 다시 쓰면 거부, 바이트 그대로
            before = path.read_bytes()
            error = refused(
                ui, {"layer": name, "permissions": {"preset": "full"}, "base_revision": None}
            )
            assert error.kind == "revision_conflict"
            assert error.data["revision"] == first["revision"]
            assert path.read_bytes() == before
            # 지금 기준이면 바뀐다
            second = ui.call(
                "permissions.set",
                {
                    "layer": name,
                    "permissions": {"preset": "full", "toolsets": {"control": "ask"}},
                    "base_revision": first["revision"],
                },
            )
            assert second["revision"] != first["revision"]
            # 형식이 틀린 permissions는 쓰지 않는다
            current = path.read_bytes()
            error = refused(
                ui,
                {
                    "layer": name,
                    "permissions": {"preset": "everything"},
                    "base_revision": second["revision"],
                },
            )
            assert error.kind == "validation_failed"
            assert path.read_bytes() == current
        # 정책에 반영 (다음 판정부터): 프로젝트 full + control ask
        tools = {t["tool"]: t for t in ui.call("permissions.get")["tools"]}
        assert tools["kb_run_start"]["final"] == "allow"
        assert tools["kb_input_click"]["final"] == "ask"


def test_project_set_preserves_other_keys_and_order(ws: Path, user_dir: Path) -> None:
    local = ws / ".kookabug" / "local.json"
    local.parent.mkdir()
    local.write_text(
        json.dumps(
            {
                "settings": {"game.executable": "C:/py.exe", "game.cwd": "C:/g"},
                "permissions": {"preset": "read_only"},
                "format": "kookabug.local/0",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(user_dir)}
    with ThreadDaemon(ws, environ=environ) as d, d.client() as ui:
        ui.call(
            "permissions.set",
            {
                "layer": "project",
                "permissions": {"preset": "full"},
                "base_revision": layer(ui, "project")["revision"],
            },
        )
    data = json.loads(local.read_text(encoding="utf-8"))
    assert list(data) == ["settings", "permissions", "format"]
    assert list(data["settings"]) == ["game.executable", "game.cwd"]
    assert data["permissions"] == {"preset": "full"}


def test_invalid_file_not_overwritten(ws: Path, user_dir: Path) -> None:
    local = ws / ".kookabug" / "local.json"
    local.parent.mkdir()
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(user_dir)}
    cases = [
        b'{"format": "kookabug.local/0", "permissions": ',  # JSON이 아님
        b'["format"]',  # 객체가 아님
        b'{"format": "kookabug.local/0", "unknown": 1}',  # 다른 부분 형식 오류
    ]
    with ThreadDaemon(ws, environ=environ) as d, d.client() as ui:
        for raw in cases:
            local.write_bytes(raw)
            current = hashlib.sha256(raw).hexdigest()
            assert layer(ui, "project")["revision"] == current
            error = refused(
                ui,
                {"layer": "project", "permissions": {"preset": "full"}, "base_revision": current},
            )
            assert error.kind == "settings_invalid", raw
            assert local.read_bytes() == raw
            if raw == cases[2]:
                continue  # 권한 밖 부분만 틀린 파일은 정책 자체는 읽힌다 (기존 규칙)
            # 권한 파일을 읽을 수 없으면 에이전트 요청은 전부 거부 (기존 규칙)
            agent = {"kind": "agent", "name": "t", "version": "0", "id": "a", "attended": True}
            with d.client(agent) as client, pytest.raises(DaemonError) as denied:
                client.call("permissions.get")
            assert denied.value.kind == "permission_denied"
            assert denied.value.data["decision"]["reason"] == "policy_invalid"
