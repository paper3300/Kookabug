"""M2 사람 확인 문서 (M2 계획 T14): 절차서·결과 양식의 항목이 서로 맞고, 절차서가 가리키는
검사 파일·비교 화면이 레포에 실제로 있는가 (문서가 코드와 어긋나면 사람이 따라 할 수 없다).
절차를 따라가면 정상 제품이 통과로 판정되는지도 본다: 사본·복구 블록은 PowerShell로 그대로 돌리고,
T1의 임계값 기대 결과는 실제 daemon 미리보기와 대조한다 (T14 검수 1)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.cli import cli_env, run_cli
from helpers.daemon_targets import START_BUTTON, Editor

from kb_testing.daemon import ThreadDaemon

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
VERIFY_DIR: Final = REPO_ROOT / "Docs" / "verification"
MANUAL: Final = VERIFY_DIR / "m2-manual.md"
RESULT: Final = VERIFY_DIR / "m2-result-template.md"
COMPARE: Final = REPO_ROOT / "tools" / "design-ref" / "compare.mjs"
CI: Final = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SHOTS: Final = REPO_ROOT / "apps" / "desktop" / "e2e" / "shots"

SECTION_IDS: Final = [
    *(f"D{i}" for i in range(1, 7)),
    *(f"E{i}" for i in range(1, 10)),
    "T1",
    "T2",
    *(f"S{i}" for i in range(1, 7)),
]
"""절차서 `###` 절 (V·U는 표의 행이다)."""
V_IDS: Final = [f"V{i}" for i in range(1, 12)]
U_IDS: Final = [f"U{i}" for i in range(1, 16)]


def manual() -> str:
    return MANUAL.read_text(encoding="utf-8")


M3_SCREENS: Final = frozenset(
    {
        "main-debug",
        "main-debug-paused",
        "runviewer",
        "runviewer-compare",
        "runviewer-stats",
        "runviewer-comparetab",
    }
)
"""M3에서 늘린 비교 화면 (M3 계획 T9~T11). M2 절차서가 아니라 M3 절차서(T12)가 맡는다."""
M4_SCREENS: Final = frozenset(
    {"recorder", "recorder-idle", "recorder-paused", "recorder-stopped", "recorder-error"}
    | {"target-ext"}
)
"""M4에서 늘린 비교 화면 (M4 계획 2.14). M4 절차서(T13)가 맡는다."""
M5_SCREENS: Final = frozenset(
    {"panel-empty", "panel-chat", "panel-approval", "panel-acp-permission", "agent-judge"}
    | {"runviewer-analyze"}
)
"""M5에서 늘린 비교 화면 (M5 계획 B4·B5). M5 절차서 D3가 맡는다."""
M7_SCREENS: Final = frozenset({"screenmap", "screenmap-promote", "screenmap-protected"})
"""M7에서 늘린 비교 화면 (M7 계획 B5). M7 절차서 H3가 맡는다."""
M8_SCREENS: Final = frozenset({*(f"wizard{i}" for i in range(10)), "wizard9-noagent"})
"""M8에서 늘린 비교 화면 (마법사, M8 계획 B7). M8 절차서 H6이 맡는다."""


NO_DESIGN_SHOTS: Final = frozenset({"plugins.spec.ts", "plugin-widget.spec.ts"})
"""비교할 시안 PNG가 없는 샷 시나리오 (M6 U1 — 확정 시안 없음). 이 파일들만 `compare.mjs` 머리
규칙에서 뺀다 — 다른 샷은 문구와 무관하게 머리 검사를 그대로 받는다 (B7 검수 M1)."""


def compare_screens(shots: Path | None = None) -> list[str]:
    """`compare.mjs`의 SCREENS 중 앱 스크린샷 시나리오가 있는 M2 화면 id, SCREENS 순서.
    시나리오(`shots/*.spec.ts`)는 머리 주석에 `compare.mjs <id…>`를 적는다."""
    text = COMPARE.read_text(encoding="utf-8")
    body = text[text.index("export const SCREENS = {") : text.index("};", text.index("SCREENS"))]
    ids = re.findall(r'^\s{2}"?([a-z0-9-]+)"?:', body, re.MULTILINE)
    shot: set[str] = set()
    for spec in (SHOTS if shots is None else shots).glob("*.spec.ts"):
        if spec.name in NO_DESIGN_SHOTS:  # 확정 시안이 없는 화면 (M6 플러그인 — 사람이 본다)
            continue
        found = re.search(r"compare\.mjs ([a-z0-9 -]+)$", spec.read_text(encoding="utf-8"), re.M)
        assert found is not None, spec
        shot.update(found.group(1).split())
    assert shot <= set(ids), shot - set(ids)
    later = M3_SCREENS | M4_SCREENS | M5_SCREENS | M7_SCREENS | M8_SCREENS
    return [i for i in ids if i in shot and i not in later]


def test_sections_and_result_rows_match() -> None:
    text = manual()
    result = RESULT.read_text(encoding="utf-8")
    assert re.findall(r"^### ([DETS]\d+)\b", text, re.MULTILINE) == SECTION_IDS
    for item in [*SECTION_IDS, *V_IDS]:
        assert re.search(rf"^\| {item} \|", result, re.MULTILINE), item
    for item in [*V_IDS, *U_IDS]:
        assert re.search(rf"^\| {item} \|", text, re.MULTILINE), item
    for item in U_IDS:
        assert re.search(rf"^\| {item} \|", result, re.MULTILINE), item
    assert "| 항목 | 내용 | 결과 값 | 증거 경로 | 통과 |" in result


def test_compare_set_same_in_manual_ci_and_tool() -> None:
    screens = compare_screens()
    assert len(screens) == 11, screens
    command = f"node tools/design-ref/compare.mjs {' '.join(screens)}"
    assert command in manual()
    assert command in CI.read_text(encoding="utf-8")
    # V 표의 화면 id가 비교 화면 전부다
    in_table = re.findall(r"^\| V\d+ \| [^|]*\(`([a-z-]+)`\)", manual(), re.MULTILINE)
    assert in_table == screens
    assert f"마지막 줄 `{2 * len(screens)}`" in manual()


def test_no_design_exemption_only_for_named_shots(tmp_path: Path) -> None:
    """시안 없음 예외는 M6 플러그인 샷 두 파일 이름에만. 다른 샷이 머리를 잃으면 "시안 없음" 문구를
    더해도 실패한다 (B7 검수 M1 재현)."""
    import shutil

    shots = tmp_path / "shots"
    shutil.copytree(SHOTS, shots)
    assert {p.name for p in shots.glob("plugin*.spec.ts")} == NO_DESIGN_SHOTS
    compare_screens(shots)  # 지금 그대로는 통과
    target = shots / "agent-judge.spec.ts"
    body = "\n".join(
        line
        for line in target.read_text(encoding="utf-8").splitlines()
        if "compare.mjs agent-judge" not in line
    )
    target.write_text(body, encoding="utf-8")
    with pytest.raises(AssertionError):
        compare_screens(shots)
    target.write_text("// 비교할 시안 PNG 없음\n" + body, encoding="utf-8")
    with pytest.raises(AssertionError):
        compare_screens(shots)


def test_referenced_files_exist() -> None:
    text = manual()
    pattern = r"\b((?:python|fixtures|tools|Docs)/[\w./-]+\.(?:py|md|wsb|txt))"
    paths = set(re.findall(pattern, text))
    specs = set(re.findall(r"\b(e2e/[\w.]+\.spec\.ts)", text))
    assert len(paths) >= 6 and len(specs) >= 2, (paths, specs)
    for rel in paths:
        assert (REPO_ROOT / rel).is_file(), rel
    for rel in specs:
        assert (REPO_ROOT / "apps" / "desktop" / rel).is_file(), rel


def test_user_reported_items_present() -> None:
    """STATE의 M2 사용자 보고 항목(U1~U9, 정지 버튼, 설치 파일 묶음, 바탕 화면 바로 가기,
    ffmpeg 소스 약속)과 잠금 해제 검사가 절차서에 있다."""
    text = manual()
    for words in (
        "KOOKABUG_DESKTOP_TESTS",
        "test_m2.py",
        "acceptance.spec.ts",
        "target.live.spec.ts",
        "test_target_live.py",
        "정지 ■",
        "zip",
        "7z",
        "바탕 화면",
        "ffmpeg-SOURCE.txt",
        "3년",
        "m1-sandbox.wsb",
        "manual_result.md",
        "SmartScreen",
        "UAC",
    ):
        assert words in text, words


# ---------------------------------------------------------------- 절차를 따라가면 (T14 검수 1)

COPY_MARK: Final = "# M2 사본 만들기"
RESTORE_MARK: Final = "# M2 실행 그래프 복구"
SAMPLE: Final = REPO_ROOT / "fixtures" / "sample-game" / "workspace"
INVENTORY: Final = "tests/inventory_open.graph.json"
ENTER_WORLD: Final = "subgraphs/enter_world.graph.json"
MANUAL_EDIT: Final = "tests/manual_edit.graph.json"
ACCOUNT_FIELD: Final = "targets/login/account_field.target.json"


def manual_block_after(marker: str) -> str:
    """절차서에서 `marker` 줄 다음부터 그 코드 블록 끝까지."""
    text = manual()
    start = text.index(marker) + len(marker)
    return text[start : text.index("\n```", start)].strip("\n")


def run_powershell(tmp_path: Path, marker: str) -> None:
    """절차서 블록을 그대로 돌린다. `$repo`는 이 레포, `%TEMP%`는 `tmp_path`(사본은 `kb-m2`)."""
    script = tmp_path / f"block-{abs(hash(marker))}.ps1"
    body = f"$repo = '{REPO_ROOT}'\n$env:TEMP = '{tmp_path}'\n{manual_block_after(marker)}\n"
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
        timeout=120,
        check=False,
    )
    assert done.returncode == 0 and "Exception" not in done.stderr, done.stderr


def manual_copy(tmp_path: Path) -> Path:
    run_powershell(tmp_path, COPY_MARK)
    return tmp_path / "kb-m2" / "sample-rpg"


def section(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end)]


def break_flow(path: Path) -> None:
    """E3·E4처럼 "I 키" 다음을 새 노드로 바꿨다가 그 노드를 지운 상태 (인벤토리 확인 안 감)."""
    value = json.loads(path.read_text(encoding="utf-8"))
    value["nodes"]["n_press_i"].pop("next", None)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def test_edit_sections_use_copy_and_e7_restores_before_run() -> None:
    text = manual()
    edits = section(text, "### E3 ", "### E7 ")
    assert MANUAL_EDIT in edits and "inventory_open.graph.json" not in edits
    e7 = section(text, "### E7 ", "### E8 ")
    assert e7.index(RESTORE_MARK) < e7.index("1. `inventory_open`")
    assert COPY_MARK in section(text, "### 예제 워크스페이스 사본", "## 1. ")


@pytest.mark.process
def test_manual_copy_then_broken_edits_restored_run_passes(tmp_path: Path) -> None:
    """검수 반례: E3·E4 편집이 저장된 뒤에도 E7 실행이 pass다. 편집은 사본 그래프에만 닿고,
    실행 그래프가 망가져 있어도(실수로 저장·T1 대상 교체) E7 앞 복구 블록이 원본으로 되돌린다."""
    ws = manual_copy(tmp_path)
    original = (SAMPLE / INVENTORY).read_bytes()
    assert (ws / MANUAL_EDIT).read_bytes() == original
    for name in ("title.png", "login.png"):
        assert (ws / "captures" / name).is_file()
    local = (ws / ".kookabug" / "local.json").read_bytes()
    assert not local.startswith(b"\xef\xbb\xbf")
    assert json.loads(local)["format"] == "kookabug.local/0"

    env = cli_env(tmp_path, KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01="sample-pass-01")
    args = ["run", INVENTORY, "--json", "--platform-fake", str(ws / "fake-platform.json")]
    break_flow(ws / MANUAL_EDIT)
    for rel in (INVENTORY, ENTER_WORLD):
        (ws / rel).write_text("{}", encoding="utf-8")  # 실행 그래프가 망가진 최악의 경우
    broken = run_cli(args, cwd=ws, env=env, timeout=180)
    assert broken.returncode != 0

    run_powershell(tmp_path, RESTORE_MARK)
    assert (ws / INVENTORY).read_bytes() == original
    assert (ws / ENTER_WORLD).read_bytes() == (SAMPLE / ENTER_WORLD).read_bytes()
    done = run_cli(args, cwd=ws, env=env, timeout=180)
    out: dict[str, Any] = json.loads(done.stdout)
    assert (done.returncode, out["verdict"]) == (0, "pass"), done.stdout + done.stderr


@pytest.mark.process
def test_t1_threshold_expectations_match_daemon_preview(tmp_path: Path) -> None:
    """검수 반례: 같은 정지 화면에서 자른 영역은 점수 1.00이라 어느 임계값에서도 찾음이다.
    찾음·못 찾음 전환은 다른 화면의 대상(계정 칸, 타이틀 화면에서 점수 0.6대)으로 본다."""
    t1 = section(manual(), "### T1 ", "### T2 ")
    for words in (ACCOUNT_FIELD, "captures/title.png", "0.6", "어느 임계값에서도", "0.85"):
        assert words in t1, words
    ws = manual_copy(tmp_path)
    with ThreadDaemon(ws) as d, d.client() as client:
        ed = Editor(client)
        frame = ed.load("captures/title.png")
        spec = ed.open(ACCOUNT_FIELD)["spec"]

        def other(threshold: float | None) -> dict[str, Any]:
            match = {} if threshold is None else {"match": {"threshold": threshold}}
            return ed.preview(frame, {**spec, **match}, image=spec["image"], base=ACCOUNT_FIELD)

        start = other(None)
        assert (start["found"], start["threshold"]) == (False, 0.85), start
        assert 0.6 <= start["best"]["score"] < 0.7, start
        assert other(0.50)["found"] is True and other(0.99)["found"] is False
        # 새 대상의 기본 임계값과 같은 정지 화면 자르기
        for threshold in (None, 0.50, 0.99):
            spec_new = {} if threshold is None else {"match": {"threshold": threshold}}
            same = ed.preview(frame, spec_new, crop=(frame, START_BUTTON))
            assert same["found"] is True and same["match"]["score"] >= 0.99, same
            if threshold is None:
                assert same["threshold"] == 0.85
