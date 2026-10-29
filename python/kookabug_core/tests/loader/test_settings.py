"""`$setting` 탐색: 실행 옵션 → local.json → 선택한 프로필 → kookabug.json 기본값.

처음으로 키를 가진 계층의 값을 쓰고, 그 값이 null이면 오류 (워크스페이스 구조 "설정")."""

from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder, check_program, make_workspace, only, setting

from kookabug_core.ir import Unresolved
from kookabug_core.workspace import RunOptions, Workspace

KEY = "game.server"
GRAPH = "tests/setting.graph.json"


def graph_with_setting(ws: Workspace, key: str = KEY) -> str:
    return (
        GraphBuilder()
        .entry("n_set")
        .node("n_set", "core.var.set", inputs={"name": "v", "value": setting(key)})
        .write(ws, GRAPH)
    )


def resolved(ws: Workspace, options: RunOptions | None = None) -> tuple[Any, list[str]]:
    program, diags = check_program(ws, graph_with_setting(ws), options=options)
    value = program.graphs[GRAPH].nodes["n_set"].inputs["value"]
    return value, [d.code for d in diags if d.code.startswith("setting_")]


ALL_LAYERS = ("options", "local", "profile", "workspace")


@pytest.mark.parametrize(
    ("layers", "expected"),
    [
        (ALL_LAYERS, "options"),
        (("local", "profile", "workspace"), "local"),
        (("profile", "workspace"), "profile"),
        (("workspace",), "workspace"),
    ],
    ids=["all→options", "no-options→local", "no-local→profile", "no-profile→workspace"],
)
def test_setting_lookup_order(tmp_path: Path, layers: tuple[str, ...], expected: str) -> None:
    ws = make_workspace(
        tmp_path,
        settings={KEY: "workspace"} if "workspace" in layers else {},
        profiles={"qa": {KEY: "profile"} if "profile" in layers else {}},
        local={KEY: "local"} if "local" in layers else {},
    )
    options = RunOptions(settings={KEY: "options"} if "options" in layers else {}, profile="qa")

    assert ws.lookup_setting(KEY, options).layer == expected
    value, problems = resolved(ws, options)
    assert (value, problems) == (expected, [])


def test_setting_lookup_is_not_merged_per_layer(tmp_path: Path) -> None:
    # 위 계층에 다른 키만 있으면 그 키는 아래 계층에서 찾는다
    ws = make_workspace(tmp_path, settings={KEY: "workspace"}, local={"other": 1})
    assert resolved(ws) == ("workspace", [])


def test_setting_profile_not_selected_is_ignored(tmp_path: Path) -> None:
    ws = make_workspace(
        tmp_path, settings={KEY: "workspace"}, profiles={"qa": {KEY: "qa"}, "dev": {KEY: "dev"}}
    )
    assert resolved(ws) == ("workspace", [])
    assert resolved(ws, RunOptions(profile="dev")) == ("dev", [])


def test_setting_selected_null_reports_local_json_path_and_key(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path, settings={"game.executable": None})
    program, diags = check_program(ws, graph_with_setting(ws, "game.executable"))

    (d,) = only(diags, "setting_null")
    assert d.severity == "error"
    assert (d.file, d.node, d.pointer) == (GRAPH, "n_set", "/nodes/n_set/in/value")
    local_json = str(tmp_path.resolve() / ".kookabug" / "local.json")
    assert local_json in d.message
    assert '"game.executable"' in d.message
    value = program.graphs[GRAPH].nodes["n_set"].inputs["value"]
    assert value == Unresolved("$setting", "game.executable")


def test_setting_null_in_local_is_not_skipped(tmp_path: Path) -> None:
    # local에 명시한 null도 선택된 값이다. 아래 계층(기본값 "x")으로 내려가지 않는다
    ws = make_workspace(tmp_path, settings={KEY: "x"}, local={KEY: None})
    value, problems = resolved(ws)
    assert problems == ["setting_null"]
    assert isinstance(value, Unresolved)

    _, diags = check_program(ws, GRAPH)
    (d,) = only(diags, "setting_null")
    assert str(ws.local_path) in d.message


def test_setting_null_in_options_is_not_skipped(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path, settings={KEY: "x"})
    assert resolved(ws, RunOptions(settings={KEY: None}))[1] == ["setting_null"]


def test_setting_missing_everywhere(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path, settings={"a": 1}, profiles={"qa": {"b": 2}}, local={"c": 3})
    _, diags = check_program(ws, graph_with_setting(ws, "nope"), options=RunOptions(profile="qa"))
    (d,) = only(diags, "setting_missing")
    assert d.severity == "error"
    assert "'nope'" in d.message
    assert d.pointer == "/nodes/n_set/in/value"


def test_setting_value_keeps_json_type(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path, settings={KEY: {"list": [1, 2]}})
    assert resolved(ws) == ({"list": [1, 2]}, [])


def test_unknown_profile_is_error(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path, settings={KEY: "x"}, profiles={"qa": {}})
    _, diags = check_program(ws, graph_with_setting(ws), options=RunOptions(profile="prod"))
    (d,) = only(diags, "profile_missing")
    assert d.file == "kookabug.json"
    assert "qa" in d.message


def test_workspace_find_walks_up(tmp_path: Path) -> None:
    make_workspace(tmp_path)
    (tmp_path / "tests" / "deep").mkdir(parents=True)
    assert Workspace.find(tmp_path / "tests" / "deep").root == tmp_path.resolve()


def test_invalid_local_json_is_reported(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path, settings={KEY: "x"})
    ws.local_path.parent.mkdir(parents=True, exist_ok=True)
    ws.local_path.write_text('{"format": "kookabug.local/0", "settings": {"bad key": 1}}', "utf-8")
    ws = Workspace.open(tmp_path)
    assert [(d.code, d.file) for d in ws.diagnostics] == [("invalid_key", ".kookabug/local.json")]
    assert ws.local is None
