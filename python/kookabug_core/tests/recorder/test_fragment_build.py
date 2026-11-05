"""녹화 스텝 → 커밋 조각 → 그래프 (M4 계획 2.7 "조각의 맨 앞·끝", 2.9, 검수 M4, T6).

조각은 스키마 모양·의미 검사를 지나고, 새 테스트(틀 + 조각)와 서브그래프 삽입(틀의 entry 뒤) 둘 다
실행 전 검증 오류가 없어야 한다 — 삽입에 종료 노드가 없어 `terminal_in_subgraph`가 나지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers.graphs import make_workspace, write_json, write_target

from kookabug_core import documents
from kookabug_core.recorder.build import (
    FragmentError,
    apply_fragment,
    attach_draft,
    build_fragment,
    check_visible_draft,
    click_drafts,
    drag_drafts,
    key_draft,
    launch_draft,
    text_draft,
    wait_draft,
)
from kookabug_core.schema import check_shape
from kookabug_core.validate import check_graph
from kookabug_core.workspace import MemorySecrets

LOGIN = "targets/rec/login/01_login.target.json"
FIELD = "targets/rec/login/02_field.target.json"
LOBBY = "targets/rec/login/03_lobby.target.json"
SECRET = {"$secret": "accounts.qa_password"}


def login_steps(*, check: bool = True) -> list[list]:
    steps = [
        click_drafts(FIELD, "계정"),
        [text_draft("qa_tester_01", clear=False)],
        [key_draft("tab")],
        [text_draft(SECRET, clear=True)],
        click_drafts(LOGIN, "로그인", timeout_ms=12000),
        [wait_draft(LOBBY, "서버 선택", 10000)],
    ]
    if check:
        steps.append([check_visible_draft(LOBBY, "서버 선택")])
    return steps


def workspace(tmp_path: Path):
    settings = {"game.executable": "game.exe", "game.args": [], "game.cwd": "", "game.title": "S"}
    ws = make_workspace(tmp_path / "ws", settings=settings)
    for rel in (LOGIN, FIELD, LOBBY):
        write_target(ws, rel, recorded={"client_size": [1024, 640], "dpi": 96})
    return ws


def errors(ws, rel: str, value: dict) -> list[str]:
    write_json(ws, rel, value)
    _, diags = check_graph(ws, rel, secrets=MemorySecrets({"accounts.qa_password": "x"}))
    return [f"{d.code}: {d.message}" for d in diags if d.severity == "error"]


def test_new_test_fragment_starts_with_launch_or_attach() -> None:
    launched = build_fragment(login_steps(), mode="new_test", start=launch_draft())
    first = launched["nodes"][0]
    assert first["type"] == "core.app.launch" and launched["first_window_node"] == "r1"
    assert first["in"]["path"] == {"$setting": "game.executable"}
    assert first["next"] == {"attached": "r2"}
    attached = build_fragment(login_steps(), mode="new_test", start=attach_draft("SampleRPG"))
    assert attached["nodes"][0]["type"] == "core.window.attach"
    assert attached["nodes"][0]["in"] == {"title": "SampleRPG"}
    assert [w["code"] for w in attached["warnings"]] == ["attach_start"]
    with pytest.raises(FragmentError):
        build_fragment(login_steps(), mode="new_test")
    for fragment in (launched, attached):
        assert check_shape(fragment, "recorder-fragment") == []


def test_new_test_appends_test_pass_without_assertions() -> None:
    plain = build_fragment(login_steps(check=False), mode="new_test", start=launch_draft())
    last = plain["nodes"][-1]
    assert last["type"] == "core.test.pass" and "next" not in last
    assert [w["code"] for w in plain["warnings"]] == ["no_assertion"]
    checked = build_fragment(login_steps(), mode="new_test", start=launch_draft())
    assert checked["nodes"][-1]["type"] == "core.assert.visible"
    assert all(n["type"] != "core.test.pass" for n in checked["nodes"])
    assert checked["warnings"] == []


def test_insert_fragment_no_window_node_no_terminal_open_end() -> None:
    fragment = build_fragment(login_steps(check=False), mode="insert")
    types = [n["type"] for n in fragment["nodes"]]
    assert "core.app.launch" not in types and "core.window.attach" not in types
    assert "core.test.pass" not in types
    assert "first_window_node" not in fragment
    assert fragment["open_end"] == {"node": fragment["chain"][-1], "exit": "found"}
    assert check_shape(fragment, "recorder-fragment") == []


def test_fragment_links_use_local_ids() -> None:
    fragment = build_fragment(
        [click_drafts(FIELD, "칸"), drag_drafts(LOBBY, "목록", (300, 400), 250, 10000)],
        mode="insert",
    )
    drag = fragment["nodes"][-1]
    assert drag["type"] == "core.input.drag"
    assert drag["in"]["start"] == {"$link": "r2.match"}  # 바로 앞 image.wait
    assert drag["in"]["end"] == [300, 400]
    assert check_shape(fragment, "recorder-fragment") == []
    with pytest.raises(FragmentError):  # 첫 노드가 앞 노드를 가리킬 수는 없다
        build_fragment([drag_drafts(LOBBY, "목록", (1, 1), 1, 1)[1:]], mode="insert")


def test_secret_text_only_as_secret_reference() -> None:
    fragment = build_fragment(login_steps(), mode="new_test", start=launch_draft())
    texts = [n for n in fragment["nodes"] if n["type"] == "core.input.type_text"]
    assert texts[1]["in"] == {"text": SECRET, "clear": True}
    assert texts[1]["title"] == "비밀값 입력"
    assert "qa_tester_01" not in texts[0]["title"]  # 제목에는 글자를 넣지 않는다


def test_fragment_validates_against_schema_and_node_specs(tmp_path: Path) -> None:
    ws = workspace(tmp_path)
    # 새 테스트: 틀 + 조각 (entry 뒤)
    new = build_fragment(login_steps(), mode="new_test", start=launch_draft())
    graph = apply_fragment(documents.template("test"), new, after=("n_entry", "start"))
    assert check_shape(graph, "graph") == []
    assert errors(ws, "tests/recorded.graph.json", graph) == []
    # 검증 없는 새 테스트 (test.pass로 끝남)
    plain = build_fragment(login_steps(check=False), mode="new_test", start=attach_draft("S"))
    graph = apply_fragment(documents.template("test"), plain, after=("n_entry", "start"))
    assert errors(ws, "tests/plain.graph.json", graph) == []
    # 서브그래프 삽입: entry → (조각) → 원래 다음(exit)
    insert = build_fragment(login_steps(check=False), mode="insert")
    sub = apply_fragment(documents.template("subgraph"), insert, after=("n_entry", "start"))
    nodes = sub["nodes"]
    last_id = next(i for i, n in nodes.items() if n.get("next", {}).get("found") == "n_exit")
    assert nodes[last_id]["type"] == "core.image.wait"
    problems = errors(ws, "subgraphs/recorded.graph.json", sub)
    assert problems == [] and not any("terminal_in_subgraph" in p for p in problems)
    # 노드 ID는 렌더러와 같은 모양, 원문 없음
    assert all(i == "n_entry" or i == "n_exit" or i.startswith("n_") for i in nodes)
    assert "hunter" not in json.dumps(sub, ensure_ascii=False)


def test_apply_refuses_after_terminal_node() -> None:
    graph = documents.template("test")
    graph["nodes"]["n_pass"] = {"type": "core.test.pass", "version": 1}
    fragment = build_fragment([[key_draft("f5")]], mode="insert")
    with pytest.raises(FragmentError):
        apply_fragment(graph, fragment, after=("n_pass", "done"))
