"""예제 워크스페이스(`workspace/`)가 검증을 통과하고 장면 표(`FakeScenario`)로 헤드리스 실행되는가
(구현 계획 M1 T12, 2.14 #1·#2).

헤드리스 실행은 제품 CLI(`kookabug run --platform-fake fake-platform.json`)를 하위 프로세스로
띄운다. 워크스페이스와 화면 PNG는 임시 폴더로 복사해 쓴다(실행 기록 `runs/`가 레포에 생기지 않게).
사람마다 다른 값(`game.executable`·`game.cwd`)은 사용자처럼 `.kookabug/local.json`에 넣는다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.cli import cli_env, run_cli
from helpers.graphs import check

from kb_testing.doc_examples import json_blocks
from kb_testing.sample_game import (
    EXAMPLE_LOCAL,
    EXAMPLE_SECRET_ENV,
    EXAMPLE_SECRETS,
    FRAMES_DIR,
    GAME_DIR,
    WORKSPACE_DIR,
    copy_example_workspace,
)
from kookabug_core.canonical import is_canonical
from kookabug_core.record import read_run
from kookabug_core.registry import default_registry
from kookabug_core.screens import read_screen_file, screen_index
from kookabug_core.workspace import RunOptions, Workspace
from kookabug_platform.frames import decode_image
from kookabug_platform.screens import evaluate_screen
from kookabug_platform.vision import FrameMeta, Vision, load_target_file
from kookabug_sdk.types import Target

WORKSPACE: Final = WORKSPACE_DIR
SECRETS: Final = EXAMPLE_SECRETS
LOCAL: Final = EXAMPLE_LOCAL
INVENTORY_OPEN: Final = "tests/inventory_open.graph.json"
SWAPPED: Final = "tests/broken/swapped_target.graph.json"
SMOKE: Final = "tests/smoke_headless.graph.json"
ENTER_WORLD: Final = "subgraphs/enter_world.graph.json"
GRAPHS: Final = (
    INVENTORY_OPEN,
    SWAPPED,
    SMOKE,
    ENTER_WORLD,
    "subgraphs/broken/enter_world_swapped_target.graph.json",
)
# 화면 PNG → 맞아야 하는 화면 ID (나머지 화면은 전부 아니어야 한다)
SCREEN_OF: Final = {
    "title": "title",
    "maintenance": "maintenance",
    "login": "login",
    "login_error": "login_error",
    "lobby": "lobby",
    "lobby_server1": "lobby",
    "lobby_server2": "lobby",
    "loading": "loading",
    "world": "world_field",
    "inventory": "inventory",
}


def run_headless(
    tmp_path: Path, ocr_models: Path, graph: str, *args: str
) -> tuple[int, dict[str, Any]]:
    ws = copy_example_workspace(tmp_path)
    env = cli_env(tmp_path, None, **EXAMPLE_SECRET_ENV, KOOKABUG_OCR_MODELS=str(ocr_models))
    done = run_cli(
        ["run", graph, "--platform-fake", "fake-platform.json", "--json", *args],
        cwd=ws,
        env=env,
        timeout=180,
    )
    assert done.stdout.strip(), done.stderr
    return done.returncode, json.loads(done.stdout)


def step_ends(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """노드 ID → 그 노드의 마지막 `step.end` (스텝 ID는 `step`)."""
    events = read_run(out["run_dir"]).events
    nodes = {e["step"]: e["node"] for e in events if e["event"] == "step.start"}
    return {nodes[e["step"]]: e for e in events if e["event"] == "step.end"}


def load_target(ws: Path, rel: str) -> Target:
    target = load_target_file(ws / rel)
    return Target(name=rel, path=target.path, spec=target.spec)


def found(ws: Path, target: str, png: Path) -> bool:
    pixels = decode_image(png.read_bytes())
    result = Vision().find(pixels, FrameMeta.of_image(pixels), load_target(ws, target))
    return result.match is not None


def exit_screen(ws: Path, exit_name: str, graph: str = ENTER_WORLD) -> str:
    """서브그래프가 그 출구에 선언한 도착 화면 ID (`interface.exits.<출구>.screen`)."""
    body = json.loads((ws / graph).read_text(encoding="utf-8"))
    return body["interface"]["exits"][exit_name]["screen"]


def screen_matches(ws: Path, screen_id: str, png: Path) -> bool:
    """그 화면 판정 파일(`screens/<ID>.screen.json`)의 조건이 PNG에서 맞는가."""
    rel = f"screens/{screen_id}.screen.json"
    screen = read_screen_file(ws / rel, rel)
    pixels = decode_image(png.read_bytes())
    meta = FrameMeta.of_image(pixels)
    return evaluate_screen(screen, lambda t: load_target(ws, t), pixels, meta, Vision()).matched


# ---------------------------------------------------------------- 파일·검증


def test_workspace_validates_no_errors_no_warnings() -> None:
    ws = Workspace.open(WORKSPACE)
    registry = default_registry()
    for profile in (None, "login_fail", "maintenance"):
        options = RunOptions(settings=LOCAL, profile=profile)
        for graph in GRAPHS:
            assert check(ws, graph, registry=registry, options=options, secrets=SECRETS) == [], (
                profile,
                graph,
            )


def test_per_person_settings_are_null_in_team_config() -> None:
    """게임 실행 경로와 작업 폴더는 사람마다 `.kookabug/local.json`에 넣는다 (팀 설정은 `null`)."""
    diags = check(Workspace.open(WORKSPACE), INVENTORY_OPEN, secrets=SECRETS)
    assert sorted((d.code, d.pointer) for d in diags) == [
        ("setting_null", "/nodes/n_launch/in/cwd"),
        ("setting_null", "/nodes/n_launch/in/path"),
    ]
    # 비밀값이 없으면 실행 전 검증 오류 (예제는 KOOKABUG_SECRET_* 환경 변수로 넣는다)
    diags = check(Workspace.open(WORKSPACE), INVENTORY_OPEN, options=RunOptions(settings=LOCAL))
    assert [d.code for d in diags] == ["secret_missing"], diags


def test_workspace_files_canonical() -> None:
    files = [p for p in WORKSPACE.rglob("*.json") if "runs" not in p.relative_to(WORKSPACE).parts]
    assert len(files) > 20
    for path in files:
        assert is_canonical(path.read_text(encoding="utf-8")), path


def test_example_graphs_follow_design_doc() -> None:
    """예제 그래프는 스키마 v0 1장·3장 예시 그대로다. 게임 실행 노드만 설정값(`game.*`)으로
    띄운다."""

    def doc(kind: str) -> dict[str, Any]:
        (block,) = [
            b.data
            for b in json_blocks()
            if b.data.get("format") == "kookabug.graph/0" and b.data.get("kind") == kind
        ]
        return block

    def read(rel: str) -> dict[str, Any]:
        return json.loads((WORKSPACE / rel).read_text(encoding="utf-8"))

    assert read(INVENTORY_OPEN) == doc("test")
    subgraph, expected = read(ENTER_WORLD), doc("subgraph")
    launch = subgraph["nodes"]["n_launch"]["in"]
    assert launch == {
        "args": {"$setting": "game.args"},
        "cwd": {"$setting": "game.cwd"},
        "path": {"$setting": "game.executable"},
        "timeout_ms": 30000,
        "window_title": {"$setting": "game.title"},
    }
    subgraph["nodes"]["n_launch"]["in"] = expected["nodes"]["n_launch"]["in"]
    assert subgraph == expected
    # 깨뜨린 변형은 타이틀 대기 target·기한과 설명만 다르다
    broken = read("subgraphs/broken/enter_world_swapped_target.graph.json")
    assert broken["nodes"]["n_wait_title"]["in"] == {
        "target": {"$target": "targets/broken/start_button_swapped.target.json"},
        "timeout_ms": 3000,
    }
    broken["nodes"]["n_wait_title"]["in"] = read(ENTER_WORLD)["nodes"]["n_wait_title"]["in"]
    assert {**broken, "meta": None} == {**read(ENTER_WORLD), "meta": None}
    swapped_test = read(SWAPPED)
    call = swapped_test["nodes"]["n_enter_world"]
    assert call["config"]["graph"] == "subgraphs/broken/enter_world_swapped_target.graph.json"
    call["config"]["graph"] = ENTER_WORLD
    assert {**swapped_test, "meta": None} == {**read(INVENTORY_OPEN), "meta": None}


def test_targets_recorded_metadata_present() -> None:
    targets = sorted(WORKSPACE.rglob("*.target.json"))
    assert len(targets) == 13
    for path in targets:
        body = json.loads(path.read_text(encoding="utf-8"))
        assert body["recorded"] == {"client_size": [1024, 640], "dpi": 96}, path
        assert (path.parent / body["image"]).is_file(), path
        load_target_file(path)  # 이미지까지 읽힌다


def test_targets_cut_from_committed_frames() -> None:
    """target PNG는 화면 PNG를 `tools/cut_targets.py` 표대로 자른 것이다 (화면을 다시 찍었으면
    그 스크립트로 다시 만든다)."""
    spec = importlib.util.spec_from_file_location(
        "cut_targets", GAME_DIR / "tools" / "cut_targets.py"
    )
    assert spec is not None and spec.loader is not None
    cut_targets = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = cut_targets  # dataclass가 자기 모듈을 찾는다
    try:
        spec.loader.exec_module(cut_targets)
    finally:
        del sys.modules[spec.name]
    assert cut_targets.stale(cut_targets.outputs()) == []
    committed = {p.relative_to(WORKSPACE).as_posix() for p in WORKSPACE.rglob("*.target.json")}
    assert committed == set(cut_targets.TARGETS)


def test_screens_detect_each_committed_frame() -> None:
    """화면 PNG마다 그 화면 판정만 맞는다 (로비는 서버를 고른 두 장면도)."""
    ws = Workspace.open(WORKSPACE)
    index = screen_index(ws)
    assert sorted(index) == sorted(set(SCREEN_OF.values()))
    screens = {}
    for screen_id, (rel,) in index.items():
        path = ws.resolve(rel)
        assert path is not None
        screens[screen_id] = read_screen_file(path, rel)
    vision = Vision()
    pngs = sorted(FRAMES_DIR.glob("*.png"))
    assert sorted(p.stem for p in pngs) == sorted(SCREEN_OF)
    for png in pngs:
        pixels = decode_image(png.read_bytes())
        meta = FrameMeta.of_image(pixels)
        matched = [
            screen_id
            for screen_id, screen in screens.items()
            if evaluate_screen(
                screen, lambda rel: load_target(WORKSPACE, rel), pixels, meta, vision
            ).matched
        ]
        assert matched == [SCREEN_OF[png.stem]], png.name


def test_exit_screens_match_arrival_frames() -> None:
    """출구의 `screen`은 그 출구로 나갈 때 도착한 화면이다 (스키마 1장 "화면 선언"). 출구마다
    도착 장면 PNG에서 선언한 화면 판정이 맞아야 한다 (변형 서브그래프도 같다)."""
    arrival = {"login_failed": "login_error", "maintenance": "maintenance", "success": "world"}
    for graph in (ENTER_WORLD, "subgraphs/broken/enter_world_swapped_target.graph.json"):
        body = json.loads((WORKSPACE / graph).read_text(encoding="utf-8"))
        assert sorted(body["interface"]["exits"]) == sorted(arrival)
        for exit_name, scene in arrival.items():
            declared = exit_screen(WORKSPACE, exit_name, graph)
            png = FRAMES_DIR / f"{scene}.png"
            assert screen_matches(WORKSPACE, declared, png), (graph, exit_name, declared)


# ---------------------------------------------------------------- 헤드리스 실행


@pytest.mark.process
def test_inventory_open_pass_headless(tmp_path: Path, ocr_models: Path) -> None:
    code, out = run_headless(tmp_path, ocr_models, INVENTORY_OPEN)
    assert (code, out["verdict"], out["code"]) == (0, "pass", "assertion_passed"), out
    ends = step_ends(out)
    assert ends["n_enter_world"]["exit"] == "success"
    assert ends["n_check_inventory"]["exit"] == "ok"
    # 서버 선택은 OCR로 "Server 1" 글자 상자를 찾아 그 가운데를 눌렀다 (로비 Server 1 줄 안)
    match = ends["n_select_server"]["outputs"]["match"]
    box = match["rect"]
    x, y = box["x"] + box["width"] // 2, box["y"] + box["height"] // 2
    assert match["method"] == "ocr" and 262 <= x < 762 and 200 <= y < 264, match
    # 비밀번호는 기록에 남지 않는다
    text = (Path(out["run_dir"]) / "events.jsonl").read_text(encoding="utf-8")
    assert SECRETS["accounts.qa_tester_01"] not in text


@pytest.mark.process
def test_login_fail_profile_fail_headless(tmp_path: Path, ocr_models: Path) -> None:
    code, out = run_headless(tmp_path, ocr_models, INVENTORY_OPEN, "--profile", "login_fail")
    assert (code, out["verdict"], out["code"]) == (1, "fail", "unhandled_fail"), out
    # 실패 위치: 월드 접속 (연결하지 않은 login_failed 출구)
    assert out["failure_titles"] == ["월드 접속"]
    ends = step_ends(out)
    call = ends["n_enter_world"]
    assert (call["step"], call["exit"]) == (out["failure_step"], "login_failed")
    assert "올바르지 않습니다" in call["outputs"]["message"]
    assert ends["n_wait_lobby"]["exit"] == "error"
    # 호출 스텝의 실패 증거: 호출 노드가 비밀값(password)을 받아도 막지 않는다(스키마 6장). 안쪽
    # 마지막 프레임(오류 문구 읽기)에 오류 팝업이 보인다 — 오류 팝업 target으로 다시 찾으면 찾는다
    steps = Path(out["run_dir"]) / "steps"
    shot = steps / f"{call['step']}_fail.png"
    assert call["artifacts"] == [f"steps/{shot.name}"] and "omitted" not in call
    ws = Path(out["run_dir"]).parents[1]
    assert found(ws, "targets/login/error_popup.target.json", shot)
    assert not found(ws, "targets/lobby/server_list.target.json", shot)
    # 그 출구(login_failed)가 선언한 도착 화면의 판정이 실패 증거에서 맞는다
    declared = exit_screen(ws, "login_failed")
    assert screen_matches(ws, declared, shot), declared
    assert not screen_matches(ws, "login", shot)
    ocr = steps / f"{ends['n_read_error']['step']}_ocr.txt"
    assert "올바르지 않습니다" in ocr.read_text(encoding="utf-8")
    # 비밀번호를 직접 받은 안쪽 스텝(비밀번호 입력)은 여전히 스크린샷을 남기지 않는다
    typed = ends["n_type_password"]
    assert typed.get("artifacts") is None
    assert SECRETS["accounts.qa_tester_01"] not in (steps.parent / "events.jsonl").read_text(
        encoding="utf-8"
    )


@pytest.mark.process
def test_maintenance_profile_skipped_headless(tmp_path: Path, ocr_models: Path) -> None:
    code, out = run_headless(tmp_path, ocr_models, INVENTORY_OPEN, "--profile", "maintenance")
    assert (code, out["verdict"], out["reason"]) == (3, "skipped", "서버 점검 중"), out
    # 호출 스텝은 fail 출구 maintenance로 나가 증거를 남긴다. 그 출구가 선언한 도착 화면이 맞는다
    call = step_ends(out)["n_enter_world"]
    assert call["exit"] == "maintenance"
    shot = Path(out["run_dir"]) / "steps" / f"{call['step']}_fail.png"
    ws = Path(out["run_dir"]).parents[1]
    declared = exit_screen(ws, "maintenance")
    assert screen_matches(ws, declared, shot), declared
    assert not screen_matches(ws, "title", shot)


@pytest.mark.process
def test_swapped_target_fail_headless(tmp_path: Path, ocr_models: Path) -> None:
    code, out = run_headless(tmp_path, ocr_models, SWAPPED)
    assert (code, out["verdict"], out["code"]) == (1, "fail", "unhandled_fail"), out
    assert out["failure_titles"] == ["월드 접속", "타이틀 대기"]
    ends = step_ends(out)
    wait = ends["n_wait_title"]
    assert (wait["step"], wait["exit"]) == (out["failure_step"], "timeout")
    # 대기 노드의 timeout 증거: 바꿔치기한 target으로는 못 찾고, 원래 target으로는 찾는다
    shot = Path(out["run_dir"]) / "steps" / f"{wait['step']}_timeout.png"
    ws = Path(out["run_dir"]).parents[1]
    assert not found(ws, "targets/broken/start_button_swapped.target.json", shot)
    assert found(ws, "targets/title/start_button.target.json", shot)
    # 실패 위치에도 실행기의 실패 증거가 있다
    assert (shot.parent / f"{wait['step']}_fail.png").is_file()


@pytest.mark.process
def test_smoke_headless_graph_pass(tmp_path: Path, ocr_models: Path) -> None:
    code, out = run_headless(tmp_path, ocr_models, SMOKE)
    assert (code, out["verdict"]) == (0, "pass"), out
    ends = step_ends(out)
    assert ends["n_check_title"]["outputs"]["text"] == "SampleRPG"
    assert ends["n_check_login"]["exit"] == "ok"
