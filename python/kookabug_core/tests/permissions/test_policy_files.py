import json
from pathlib import Path
from typing import Any

import pytest

from kookabug_core.permissions import (
    USER_SETTINGS_FILE,
    LayerPolicy,
    load_policy,
    parse_rule,
    user_config_dir,
)


def write(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def workspace(root: Path, permissions: dict[str, Any] | None = None, **extra: Any) -> Path:
    data: dict[str, Any] = {"format": "kookabug.workspace/0", **extra}
    if permissions is not None:
        data["permissions"] = permissions
    write(root / "kookabug.json", data)
    return root


def local(root: Path, permissions: Any) -> None:
    write(
        root / ".kookabug" / "local.json",
        {"format": "kookabug.local/0", "permissions": permissions},
    )


def user(folder: Path, permissions: Any) -> Path:
    data = {"format": "kookabug.user-settings/0", "permissions": permissions}
    write(folder / USER_SETTINGS_FILE, data)
    return folder


def test_reads_three_layers(tmp_path: Path) -> None:
    root = workspace(tmp_path / "ws", {"preset": "runner", "toolsets": {"control": "ask"}})
    local(root, {"rules": [{"rule": "kb_run_start(tests/*)", "verdict": "deny"}]})
    user_dir = user(tmp_path / "user", {"preset": "full", "toolsets": {"run": "allow"}})

    p = load_policy(root, user_dir)
    assert p.team == LayerPolicy("team", "kookabug.json", "runner", {"control": "ask"})
    assert p.project == LayerPolicy(
        "project", ".kookabug/local.json", rules=(parse_rule("kb_run_start(tests/*)", "deny"),)
    )
    assert p.user == LayerPolicy(
        "user", str(user_dir / USER_SETTINGS_FILE), "full", {"run": "allow"}
    )
    assert not p.invalid and p.diagnostics == ()


def test_user_config_dir_env_override(tmp_path: Path) -> None:
    custom = tmp_path / "custom"
    assert user_config_dir({"KOOKABUG_USER_CONFIG_DIR": str(custom), "APPDATA": "C:/x"}) == custom
    assert user_config_dir({"APPDATA": str(tmp_path)}) == tmp_path / "Kookabug"
    assert user_config_dir({}) is None

    root = workspace(tmp_path / "ws")
    user(custom, {"preset": "read_only"})
    user(tmp_path / "Kookabug", {"preset": "full"})
    env = {"KOOKABUG_USER_CONFIG_DIR": str(custom), "APPDATA": str(tmp_path)}
    assert load_policy(root, user_config_dir(env)).user.preset == "read_only"
    assert load_policy(root, user_config_dir({"APPDATA": str(tmp_path)})).user.preset == "full"


def test_missing_files_mean_empty_layers(tmp_path: Path) -> None:
    root = workspace(tmp_path / "ws")
    for user_dir in (None, tmp_path / "nowhere"):
        p = load_policy(root, user_dir)
        assert p.user == LayerPolicy("user")
        assert p.project == LayerPolicy("project")
        assert p.team == LayerPolicy("team", "kookabug.json")
        assert not p.invalid
    # 사용자 폴더 위의 폴더들도 없으면 그냥 없는 파일
    assert load_policy(root, tmp_path / "a" / "b" / "c").user == LayerPolicy("user")


def test_missing_workspace_file_is_invalid(tmp_path: Path) -> None:
    # kookabug.json은 워크스페이스에 반드시 있다. 지워서 팀 상한을 없앨 수 없다
    p = load_policy(tmp_path / "empty", None)
    assert p.invalid
    assert codes(p.team) == [("json_invalid", "kookabug.json", None)]


def _policy_path(root: Path, user_dir: Path, which: str) -> Path:
    return {
        "user": user_dir / USER_SETTINGS_FILE,
        "project": root / ".kookabug" / "local.json",
        "team": root / "kookabug.json",
    }[which]


@pytest.mark.parametrize("which", ["user", "project", "team"])
def test_directory_in_place_of_policy_file_is_invalid(tmp_path: Path, which: str) -> None:
    root = workspace(tmp_path / "ws", {"preset": "full"})
    user_dir = tmp_path / "user"
    path = _policy_path(root, user_dir, which)
    if path.exists():
        path.unlink()
    path.mkdir(parents=True)
    layer = getattr(load_policy(root, user_dir), which)
    assert layer.invalid
    assert [d.code for d in layer.diagnostics] == ["json_invalid"]


@pytest.mark.parametrize("which", ["user", "project"])
def test_parent_is_file_is_invalid(tmp_path: Path, which: str) -> None:
    root = workspace(tmp_path / "ws")
    user_dir = tmp_path / "user"
    path = _policy_path(root, user_dir, which)
    write(path.parent, "not a folder")  # 설정 폴더 자리에 파일
    layer = getattr(load_policy(root, user_dir), which)
    assert [d.code for d in layer.diagnostics] == ["json_invalid"]


@pytest.mark.parametrize("which", ["user", "project", "team"])
def test_read_error_is_invalid(tmp_path: Path, which: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # 접근 거부 등 I/O 오류는 "없음"이 아니다
    root = workspace(tmp_path / "ws")
    user_dir = tmp_path / "user"
    local(root, {"preset": "full"})
    user(user_dir, {"preset": "full"})
    target = _policy_path(root, user_dir, which)
    real = Path.read_text

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == target:
            raise PermissionError(13, "접근 거부", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    p = load_policy(root, user_dir)
    layer = getattr(p, which)
    assert [d.code for d in layer.diagnostics] == ["json_invalid"]
    assert p.invalid


def codes(layer: LayerPolicy) -> list[tuple[str, str | None, str | None]]:
    return [(d.code, d.file, d.pointer) for d in layer.diagnostics]


def test_invalid_permissions_shape_is_diagnostic(tmp_path: Path) -> None:
    root = workspace(
        tmp_path / "ws",
        {"preset": "admin", "toolsets": {"shell": "allow", "run": "yes"}, "rules": [{"rule": "X"}]},
    )
    local(root, {"rules": [{"rule": "kb_run_start(", "verdict": "deny"}]})
    user_dir = write(tmp_path / "user" / USER_SETTINGS_FILE, "{not json").parent

    p = load_policy(root, user_dir)
    assert p.invalid
    assert codes(p.team) == [
        ("invalid_value", "kookabug.json", "/permissions/preset"),
        ("missing_field", "kookabug.json", "/permissions/rules/0"),
        ("pattern_mismatch", "kookabug.json", "/permissions/rules/0/rule"),
        ("invalid_value", "kookabug.json", "/permissions/toolsets/run"),
        ("invalid_key", "kookabug.json", "/permissions/toolsets/shell"),
    ]
    assert (p.team.preset, p.team.toolsets, p.team.rules) == (None, {}, ())
    assert codes(p.project) == [
        ("pattern_mismatch", ".kookabug/local.json", "/permissions/rules/0/rule")
    ]
    assert [d.code for d in p.user.diagnostics] == ["json_invalid"]
    assert p.diagnostics == p.team.diagnostics + p.project.diagnostics + p.user.diagnostics


def test_permissions_checked_apart_from_rest_of_file(tmp_path: Path) -> None:
    # 다른 필드가 틀려도 권한은 읽는다 (팀 상한이 조용히 사라지지 않게)
    root = workspace(tmp_path / "ws", {"preset": "read_only"}, settings={"bad..key": 1})
    assert load_policy(root, None).team.preset == "read_only"
    # permissions가 null·객체가 아님도 오류
    write(root / ".kookabug" / "local.json", {"format": "kookabug.local/0", "permissions": None})
    assert codes(load_policy(root, None).project) == [
        ("wrong_type", ".kookabug/local.json", "/permissions")
    ]
    write(root / ".kookabug" / "local.json", "[]")
    assert [d.code for d in load_policy(root, None).project.diagnostics] == ["wrong_type"]
