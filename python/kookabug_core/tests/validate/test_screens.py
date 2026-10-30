"""화면 검사: 출구 `screen`이 `screens/`의 화면 하나를 가리키는지 (구현 계획 M1 2.10)."""

from pathlib import Path
from typing import Any

from helpers.graphs import GraphBuilder, check, make_workspace, write_json, write_target

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.loader import load_program
from kookabug_core.screens import screen_index
from kookabug_core.workspace import Workspace

SUB = "subgraphs/s.graph.json"
POINTER = "/interface/exits/done/screen"


def subgraph(ws: Workspace, screen: str = "lobby") -> str:
    interface = {"exits": {"done": {"kind": "ok", "screen": screen}}}
    g = GraphBuilder("subgraph", interface=interface).entry("n_exit").exit("n_exit", "done")
    return g.write(ws, SUB)


def write_screen(ws: Workspace, rel: str, **detect: Any) -> None:
    detect = detect or {"all": [{"$target": "targets/a.target.json"}]}
    write_json(ws, rel, {"detect": detect, "format": "kookabug.screen/0", "title": "로비"})


def screen_diags(diags: list[Diagnostic]) -> list[Diagnostic]:
    return [d for d in diags if d.code.startswith("screen_")]


def test_unknown_screen_warning(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    (diag,) = screen_diags(check(ws, subgraph(ws)))
    assert (diag.code, diag.severity, diag.file, diag.pointer) == (
        "screen_unknown",
        "warning",
        SUB,
        POINTER,
    )
    assert "'lobby'" in diag.message
    # 경고뿐이라 오류는 없다 (실행을 막지 않는다)
    assert [d for d in check(ws, SUB) if d.severity == "error"] == []


def test_ambiguous_screen_error(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_target(ws, "targets/a.target.json")
    write_screen(ws, "screens/a/lobby.screen.json")
    write_screen(ws, "screens/b/lobby.screen.json")
    (diag,) = screen_diags(check(ws, subgraph(ws)))
    assert (diag.code, diag.severity, diag.pointer) == ("screen_ambiguous", "error", POINTER)
    assert "screens/a/lobby.screen.json" in diag.message
    assert "screens/b/lobby.screen.json" in diag.message


def test_unreferenced_duplicate_screen_ids_not_checked(tmp_path: Path) -> None:
    # 범위 (T6 검수 4, 설계 문서 4장): 중복은 검증하는 그래프의 출구가 가리킨 ID에서만 오류다
    ws = make_workspace(tmp_path)
    write_target(ws, "targets/a.target.json")
    write_screen(ws, "screens/lobby.screen.json")
    write_screen(ws, "screens/a/unused.screen.json")
    write_screen(ws, "screens/b/unused.screen.json")
    assert screen_diags(check(ws, subgraph(ws))) == []
    assert screen_index(ws)["unused"] == [
        "screens/a/unused.screen.json",
        "screens/b/unused.screen.json",
    ]
    # 같은 중복 ID를 출구가 가리키면 오류
    assert [d.code for d in screen_diags(check(ws, subgraph(ws, "unused")))] == ["screen_ambiguous"]


def test_explored_folder_ignored(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_target(ws, "targets/a.target.json")
    write_screen(ws, "screens/_explored/lobby.screen.json")
    assert [d.code for d in screen_diags(check(ws, subgraph(ws)))] == ["screen_unknown"]
    # 탐색 결과와 같은 ID가 screens/에 있어도 모호하지 않다
    write_screen(ws, "screens/lobby.screen.json")
    assert screen_diags(check(ws, SUB)) == []
    assert screen_index(ws) == {"lobby": ["screens/lobby.screen.json"]}


def test_valid_screen_loaded_with_its_targets(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_target(ws, "targets/a.target.json")
    write_target(ws, "targets/loading.target.json")
    write_screen(
        ws,
        "screens/lobby.screen.json",
        all=[{"$target": "targets/a.target.json"}],
        none=[{"$target": "targets/loading.target.json"}],
    )
    assert screen_diags(check(ws, subgraph(ws))) == []
    program = load_program(ws, SUB)
    found = program.screens["lobby"]
    assert found.status == "ok" and found.screen is not None
    assert (found.screen.all, found.screen.none) == (
        ("targets/a.target.json",),
        ("targets/loading.target.json",),
    )
    assert program.references.screens == {"screens/lobby.screen.json"}
    assert {"targets/a.target.json", "targets/loading.png"} <= set(program.references.all())


def test_invalid_screen_warning(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_screen(ws, "screens/lobby.screen.json", all=[{"$target": "targets/none.target.json"}])
    (diag,) = screen_diags(check(ws, subgraph(ws)))
    assert (diag.code, diag.severity) == ("screen_invalid", "warning")
    assert "targets/none.target.json" in diag.message
    write_json(ws, "screens/lobby.screen.json", {"detect": {}, "format": "kookabug.screen/0"})
    (diag,) = screen_diags(check(ws, SUB))
    assert diag.code == "screen_invalid" and "형식" in diag.message
