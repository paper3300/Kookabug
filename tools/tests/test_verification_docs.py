"""M1 사람 검증 문서 (구현 계획 M1 2.14, T14): 실제 게임 검증 워크스페이스 틀이 검증을 통과하고,
절차서·결과 양식·Sandbox 설정이 2.14 사람 칸과 실제 게임 필수 항목을 빠짐없이 덮는가.

워크스페이스 틀의 target 이미지는 사람이 실제 게임 화면에서 자른다. 여기서는 예제 게임 화면 PNG를
대신 넣고 사람마다 다른 설정(`.kookabug/local.json`)을 채워 실행 전 검증만 본다.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.graphs import check, link, make_workspace, target
from helpers.m1 import START, ScenePlatform, StubEngines, clicks, run_on, write_target
from helpers.run import tk

from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.canonical import is_canonical
from kookabug_core.registry import default_registry
from kookabug_core.workspace import RunOptions, Workspace
from kookabug_sdk.types import Rect

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
VERIFY_DIR: Final = REPO_ROOT / "Docs" / "verification"
TEMPLATE: Final = VERIFY_DIR / "m1-real-game"
MANUAL: Final = VERIFY_DIR / "m1-manual.md"
RESULT: Final = VERIFY_DIR / "m1-result-template.md"
SANDBOX: Final = VERIFY_DIR / "m1-sandbox.wsb"
GRAPHS: Final = sorted(p.relative_to(TEMPLATE).as_posix() for p in TEMPLATE.glob("tests/*.json"))
TARGETS: Final = ("anchor", "label", "field")
LOCAL: Final = {
    "check.text": "확인",
    "game.title": "M1 Real Game",
    "korean.region": [10, 10, 300, 40],
}
# 결과 양식의 항목 ID (절차서 절과 일대일)
RESULT_IDS: Final = [
    *(f"D{i}" for i in range(1, 8)),
    *(f"S{i}" for i in range(1, 7)),
    *(f"G{i}" for i in range(13)),
]


def git_like_copy(source: Path, dest: Path) -> None:
    """Git 체크아웃처럼 파일만 옮긴다 (빈 폴더는 따라가지 않는다)."""
    skip = {"runs", ".kookabug", "__pycache__"}
    for path in source.rglob("*"):
        rel = path.relative_to(source)
        if path.is_file() and not skip.intersection(rel.parts):
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest / rel)


def template_copy(tmp_path: Path) -> Workspace:
    ws = tmp_path / "real-game"
    git_like_copy(TEMPLATE, ws)
    (ws / "targets").mkdir(parents=True, exist_ok=True)  # 절차서 G0과 같이
    for name in TARGETS:
        shutil.copyfile(FRAMES_DIR / "title.png", ws / "targets" / f"{name}.png")
        body = {"format": "kookabug.target/0", "image": f"{name}.png"}
        (ws / "targets" / f"{name}.target.json").write_text(json.dumps(body), encoding="utf-8")
    return Workspace.open(ws)


def test_template_folders_survive_git_checkout(tmp_path: Path) -> None:
    """Git은 빈 폴더를 저장하지 않는다: 틀의 폴더마다 파일이 있어 새 체크아웃에도 그대로 온다
    (T14 검수 1 — `targets/`가 빈 폴더라 새 체크아웃에서 검사·G0이 깨졌다)."""
    folders = [p for p in TEMPLATE.rglob("*") if p.is_dir() and "__pycache__" not in p.parts]
    assert sorted(p.relative_to(TEMPLATE).as_posix() for p in folders) == ["targets", "tests"]
    for folder in folders:
        assert any(f.is_file() for f in folder.rglob("*")), folder
    checkout = tmp_path / "checkout"
    git_like_copy(TEMPLATE, checkout)
    assert (checkout / "targets" / "README.md").is_file()
    assert "New-Item -ItemType Directory -Force .kookabug, targets" in MANUAL.read_text(
        encoding="utf-8"
    )


def test_template_graphs_cover_manual_scenarios() -> None:
    assert list(GRAPHS) == [
        f"tests/{name}.graph.json"
        for name in (
            "capture",
            "dpi_check",
            "focus_loss",
            "hold_key",
            "korean_input",
            "move_click",
            "resize_click",
        )
    ]
    manual = MANUAL.read_text(encoding="utf-8")
    for rel in GRAPHS:
        assert rel in manual, rel
    for path in [TEMPLATE / "kookabug.json", *TEMPLATE.glob("tests/*.json")]:
        assert is_canonical(path.read_text(encoding="utf-8")), path


@pytest.mark.parametrize("graph", GRAPHS)
def test_template_graph_validates_with_local_settings(tmp_path: Path, graph: str) -> None:
    ws = template_copy(tmp_path)
    diags = check(ws, graph, registry=default_registry(), options=RunOptions(settings=LOCAL))
    assert diags == [], graph


def test_template_needs_per_person_settings(tmp_path: Path) -> None:
    """게임 창 제목·확인 글자·한글 읽을 영역은 사람마다 `.kookabug/local.json`에 적는다."""
    ws = template_copy(tmp_path)
    pointers: dict[str, list[tuple[str, str | None]]] = {}
    for graph in GRAPHS:
        diags = check(ws, graph, registry=default_registry())
        pointers[graph] = sorted((d.code, d.pointer) for d in diags)
    assert {d for found in pointers.values() for d in found} == {
        ("setting_null", "/nodes/n_attach/in/title"),
        ("setting_null", "/nodes/n_read/in/contains"),
        ("setting_null", "/nodes/n_read/in/region"),
    }
    assert ("setting_null", "/nodes/n_read/in/region") in pointers["tests/korean_input.graph.json"]


def section_ids(text: str) -> list[str]:
    return re.findall(r"^#{2,4} ([DSG]\d+)\b", text, re.MULTILINE)


def test_manual_and_result_template_cover_every_item() -> None:
    manual = MANUAL.read_text(encoding="utf-8")
    result = RESULT.read_text(encoding="utf-8")
    assert section_ids(manual) == RESULT_IDS
    for item in RESULT_IDS:
        assert re.search(rf"^\| {item} \|", result, re.MULTILINE), item
    # 2.14 실제 게임 필수 항목·사람 칸의 핵심 낱말이 절차서에 있다
    for words in (
        "DPI 100%",
        "150%",
        "200%",
        "창 이동",
        "크기 변경",
        "stale_observation",
        "window_not_foreground",
        "테두리 없는 전체화면",
        "독점 전체화면",
        "capture_timeout",
        "target_elevated",
        "input_desktop_unavailable",
        "truth.jsonl",
        "--m1-real-game",
        "Ctrl+C",
        "오른쪽 Ctrl",
        "오른쪽 Alt",
        "Windows Sandbox",
        "m1-sandbox.wsb",
        "doctor --json",
        "KOOKABUG_DESKTOP_TESTS",
        "KOOKABUG_SOAK",
        "manual_result.md",
    ):
        assert words in manual, words
    # 결과 양식은 항목마다 증거 경로·통과 여부 칸과 OCR 수치 칸이 있다
    assert "| 항목 | 내용 | 결과 값 | 증거 경로 | 통과 |" in result
    for field in ("문자 정확도", "한국어 문자 정확도", "지연 중앙값", "지연 p95", "기준 PC"):
        assert field in result, field


def test_sandbox_config_maps_setup_folder_read_only() -> None:
    root = ET.fromstring(SANDBOX.read_text(encoding="utf-8"))
    assert root.tag == "Configuration"
    folders: list[dict[str, Any]] = [
        {child.tag: child.text for child in folder} for folder in root.iter("MappedFolder")
    ]
    by_sandbox = {f["SandboxFolder"]: f for f in folders}
    setup = by_sandbox["C:\\Users\\WDAGUtilityAccount\\Desktop\\kookabug-in"]
    assert setup["ReadOnly"] == "true"
    out = by_sandbox["C:\\Users\\WDAGUtilityAccount\\Desktop\\kookabug-out"]
    assert out["ReadOnly"] == "false"
    # 네트워크 없이 설치·실행된다 (OCR 모델을 실행 중 받지 않음)
    assert root.findtext("Networking") == "Disable"
    assert root.findtext("VGpu") == "Enable"


# ---------------------------------------------------------------- 절차서 명령 실행 (T14 검수 2·3)

G5_MARK: Final = "# G5 판정"
TARGET: Final = "targets/start.target.json"


def manual_block_after(marker: str) -> str:
    """절차서에서 `marker` 줄 다음부터 그 코드 블록 끝까지."""
    text = MANUAL.read_text(encoding="utf-8")
    start = text.index(marker) + len(marker)
    return text[start : text.index("\n```", start)].strip("\n")


def resize_then_click(tmp_path: Path, answers: list[Rect | None]) -> dict[str, Any]:
    """찾은 뒤 창 크기가 바뀌고 그 찾은 결과로 누르는 실행 (실제 실행기·입력 서비스, 장면 표).
    `kb run --json`의 필드(`verdict`·`code`·`reason`·`failure_step`·`run_dir`)와 `events.jsonl`."""
    ws = make_workspace(tmp_path / "ws")
    write_target(ws, TARGET)
    engines = StubEngines({TARGET: answers})
    platform = ScenePlatform.sample(engines)
    engines.after_find.append(lambda: platform.resize((2048, 1280)))
    graph = (
        tk()
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_find"})
        .node(
            "n_find",
            "testkit.m1.find",
            inputs={"target": target(TARGET)},
            next={"found": "n_click"},
        )
        .node(
            "n_click",
            "testkit.m1.click",
            inputs={"at": link("n_find.match")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run_on(ws, graph, platform)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    lines = [json.dumps(e, ensure_ascii=False) for e in ran.events]
    (run_dir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = ran.result
    return {
        "clicks": clicks(platform),
        "code": result.code,
        "failure_step": result.failure_step,
        "reason": result.reason,
        "run_dir": str(run_dir),
        "verdict": result.verdict,
    }


def run_g5_judgment(tmp_path: Path, run: dict[str, Any]) -> str:
    """절차서 G5 판정 블록을 그대로 PowerShell로 돌린다 (`$r` = `kb run --json` 결과)."""
    r_file = tmp_path / "r.json"
    r_file.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    script = tmp_path / "g5.ps1"
    body = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n"
        f"$r = Get-Content -Raw -Encoding UTF8 '{r_file}' | ConvertFrom-Json\n"
        f"{manual_block_after(G5_MARK)}\n"
    )
    script.write_text(body, encoding="utf-8-sig")  # PowerShell 5.1은 BOM으로 UTF-8을 안다
    done = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script,
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip().splitlines()[-1]


@pytest.mark.process
def test_g5_judgment_accepts_stale_observation_from_step_message(tmp_path: Path) -> None:
    """다시 찾지 못하면 입력하지 않고 fail. `stale_observation`은 최상위 `reason`이 아니라 실패
    스텝의 `step.end` 메시지에 있다 — 절차서 판정이 그것을 통과 ②로 본다 (T14 검수 2)."""
    run = resize_then_click(tmp_path, [START, None])
    assert (run["verdict"], run["code"], run["clicks"]) == ("fail", "unhandled_fail", [])
    assert "stale_observation" not in run["reason"]
    assert run_g5_judgment(tmp_path, run).startswith("G5 통과 ② stale_observation: ")


@pytest.mark.process
def test_g5_judgment_accepts_rematch_and_rejects_other_failures(tmp_path: Path) -> None:
    moved = Rect(START.x * 2, START.y * 2, START.width * 2, START.height * 2)
    rematched = resize_then_click(tmp_path / "rematch", [START, moved])
    assert rematched["verdict"] == "pass" and len(rematched["clicks"]) == 1
    line = run_g5_judgment(tmp_path / "rematch", rematched)
    assert line.startswith("G5 통과 ① 재검증: ") and "다시 찾아" in line
    # 찾지도 못한 실패(다른 사유)는 통과가 아니다
    other = resize_then_click(tmp_path / "other", [None])
    assert other["verdict"] == "fail"
    assert run_g5_judgment(tmp_path / "other", other).startswith("G5 실패: verdict=fail")


_CD: Final = re.compile(r"(?:^|;)\s*(?:cd|Set-Location)\s+(\S+)")
_PUSH: Final = re.compile(r"\bPush-Location\s+(\S+)")
_POP: Final = re.compile(r"\bPop-Location\b")


def test_manual_g_commands_run_in_the_right_folder() -> None:
    """같은 PowerShell 창으로 G0~G12를 따라가면 그래프·증거 명령은 실제 게임 워크스페이스(`$ws`),
    OCR 계산은 레포(`$repo`)에서 돈다 (T14 검수 3 — G9의 `cd $repo` 뒤 G10이 그래프를 못 찾았다)."""
    text = MANUAL.read_text(encoding="utf-8")
    g_part = text[text.index("### G0 ") : text.index("## 4. ")]
    cwd, stack = "$repo", []  # 0절 블록이 레포로 옮겨 둔 상태에서 시작
    checked = {"$ws": 0, "$repo": 0, "after_ocr": 0}
    for block in re.findall(r"^```powershell\n(.*?)^```", g_part, re.MULTILINE | re.DOTALL):
        for line in block.splitlines():
            if m := _PUSH.search(line):
                stack.append(cwd)
                cwd = m.group(1)
            for m in _CD.finditer(line):
                cwd = m.group(1)
            if re.search(r"\bkb (run|target test) |Keep-Run|Last-Run", line):
                assert cwd == "$ws", line
                checked["$ws"] += 1
                checked["after_ocr"] += checked["$repo"]
            if "tools/ocr_bench.py" in line:
                assert cwd == "$repo", line
                checked["$repo"] += 1
            if _POP.search(line):
                cwd = stack.pop()
    assert cwd == "$ws" and not stack
    # OCR 계산(G9) 뒤 G10~G12의 그래프 명령(hold_key 4줄, dpi_check·focus_loss)도 $ws에서 봤다
    assert checked["$repo"] == 1 and checked["after_ocr"] == 6 and checked["$ws"] >= 14, checked
