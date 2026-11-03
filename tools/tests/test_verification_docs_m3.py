"""M3 사람 확인 문서 (M3 계획 T12): 절차서·결과 양식의 항목이 서로 맞고, 절차서가 가리키는 검사
파일·비교 화면·인수 테스트 수가 레포와 같은가 (문서가 코드와 어긋나면 사람이 따라 할 수 없다).
절차서의 PowerShell 블록(사본 만들기·영상 끄기 넣기·되돌리기)은 그대로 돌려 결과 파일을 제품
규칙으로 읽는다."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import pytest

from kookabug_core.loader import load_program
from kookabug_core.workspace import MemorySecrets, Workspace

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
VERIFY_DIR: Final = REPO_ROOT / "Docs" / "verification"
MANUAL: Final = VERIFY_DIR / "m3-manual.md"
RESULT: Final = VERIFY_DIR / "m3-result-template.md"
COMPARE: Final = REPO_ROOT / "tools" / "design-ref" / "compare.mjs"
CI: Final = REPO_ROOT / ".github" / "workflows" / "ci.yml"
ACCEPTANCE: Final = REPO_ROOT / "python" / "kookabug_core" / "tests" / "acceptance" / "test_m3.py"
APP_ACCEPTANCE: Final = REPO_ROOT / "apps" / "desktop" / "e2e" / "acceptance.m3.spec.ts"

M3_SCREENS: Final = [
    "main-debug",
    "main-debug-paused",
    "runviewer",
    "runviewer-compare",
    "runviewer-stats",
    "runviewer-comparetab",
]
"""M3 비교 화면 (M3 계획 T9~T11, `compare.mjs` SCREENS 순서)."""
SECTION_IDS: Final = [
    *(f"D{i}" for i in range(1, 7)),
    *(f"R{i}" for i in range(1, 5)),
    *(f"B{i}" for i in range(1, 6)),
    *(f"W{i}" for i in range(1, 5)),
    *(f"S{i}" for i in range(1, 6)),
    "P1",
]
"""절차서 `###` 절 (V·U는 표의 행이다)."""
V_IDS: Final = [f"V{i}" for i in range(1, 7)]
U_IDS: Final = [f"U{i}" for i in range(1, 14)]


def manual() -> str:
    return MANUAL.read_text(encoding="utf-8")


def test_sections_and_result_rows_match() -> None:
    text = manual()
    result = RESULT.read_text(encoding="utf-8")
    assert re.findall(r"^### ([DRBWSP]\d+)\b", text, re.MULTILINE) == SECTION_IDS
    for item in [*SECTION_IDS, *V_IDS, *U_IDS]:
        assert re.search(rf"^\| {item} \|", result, re.MULTILINE), item
    for item in [*V_IDS, *U_IDS]:
        assert re.search(rf"^\| {item} \|", text, re.MULTILINE), item
    assert "| 항목 | 내용 | 결과 값 | 증거 경로 | 통과 |" in result


def test_compare_set_same_in_manual_ci_and_tool() -> None:
    text = COMPARE.read_text(encoding="utf-8")
    body = text[text.index("export const SCREENS = {") : text.index("};", text.index("SCREENS"))]
    ids = re.findall(r'^\s{2}"?([a-z-]+)"?:', body, re.MULTILINE)
    assert [i for i in ids if i in M3_SCREENS] == M3_SCREENS
    command = f"node tools/design-ref/compare.mjs {' '.join(M3_SCREENS)}"
    assert command in manual()
    assert command in CI.read_text(encoding="utf-8")
    in_table = re.findall(r"^\| V\d+ \| [^|]*\(`([a-z-]+)`\)", manual(), re.MULTILINE)
    assert in_table == M3_SCREENS
    assert f"마지막 줄 `{2 * len(M3_SCREENS)}`" in manual()


def test_referenced_files_exist() -> None:
    text = manual()
    pattern = r"(?<![\w/])((?:python|fixtures|tools|Docs)/[\w./-]+\.(?:py|md|wsb|txt|json))"
    paths = set(re.findall(pattern, text))
    specs = set(re.findall(r"\b(e2e/[\w./-]+\.(?:spec\.ts|json))", text))
    assert len(paths) >= 5 and len(specs) >= 4, (paths, specs)
    for rel in paths:
        assert (REPO_ROOT / rel).is_file(), rel
    for rel in specs:
        assert (REPO_ROOT / "apps" / "desktop" / rel).is_file(), rel
    sample = REPO_ROOT / "fixtures" / "sample-game" / "workspace"
    for rel in re.findall(r"`(tests/[\w/]+\.graph\.json)`", text):
        if rel.startswith("tests/manual_") or "m3_" in rel:
            continue
        assert (sample / rel).is_file(), rel


@pytest.mark.process
def test_acceptance_counts_match_manual() -> None:
    """D2의 "N passed"가 `test_m3.py`에서 모은 검사 수와 같다. 앱 인수 검사 5개도 그대로다."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            ACCEPTANCE,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    collected = [line for line in proc.stdout.splitlines() if "::test_" in line]
    d2 = text_between(manual(), "### D2 ", "### D3 ")
    assert f"마지막 줄 `{len(collected)} passed`" in d2, len(collected)
    media = [line for line in collected if "real_mp4" in line or "decoded_mp4" in line]
    assert len(media) == 3
    app = re.findall(r'^test\("(test_\w+)"', APP_ACCEPTANCE.read_text(encoding="utf-8"), re.M)
    assert len(app) == 5 and "`acceptance.m3.spec.ts` 5개" in manual()


def text_between(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end)]


def test_user_reported_items_present() -> None:
    """STATE의 M3 사용자 보고 항목과 사람 확인 2.13 다섯 항목, 검수 M9(설치 트리 영상 사용 불가·
    N 판), M1 D7 미실행, 포그라운드 주의가 절차서에 있다."""
    text = manual()
    for words in (
        "KOOKABUG_MEDIA_TESTS",
        "KOOKABUG_DESKTOP_TESTS",
        "test_video_live.py",
        "test_m3.py",
        "acceptance.m3.spec.ts",
        "SuperTuxKart",
        "Windows N",
        "mf_missing",
        "opencv_videoio_ffmpeg",
        "KOOKABUG_VIDEO_TEST",
        "D7",
        "한 번도 실행하지 않았다",
        "window_not_foreground",
        "실행 전 포그라운드",
        "failed_only",
        "비밀값 입력",
        "stale_observation",
        "manual_result.md",
    ):
        assert words in text, words


# ---------------------------------------------------------------- 절차를 따라가면

COPY_MARK: Final = "# M3 사본 만들기"
R2_GRAPH_MARK: Final = "# M3 R2 그래프 만들기"
REDACT_ON_MARK: Final = "# M3 R2 가림 켜기"
REDACT_BACK_MARK: Final = "# M3 R2 가림 되돌리기"
INVENTORY: Final = "tests/inventory_open.graph.json"
R2_GRAPH: Final = "tests/m3_r2_video.graph.json"
SWAPPED: Final = "tests/broken/swapped_target.graph.json"
SWAPPED_SUB: Final = "subgraphs/broken/enter_world_swapped_target.graph.json"


def manual_block_after(marker: str) -> str:
    text = manual()
    start = text.index(marker) + len(marker)
    return text[start : text.index("\n```", start)].strip("\n")


def run_powershell(tmp_path: Path, marker: str) -> None:
    """절차서 블록을 그대로 돌린다. `$repo`는 이 레포, `%TEMP%`는 `tmp_path`(사본은 `kb-m3`)."""
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


@pytest.mark.process
def test_manual_blocks_make_valid_workspace_and_graph(tmp_path: Path) -> None:
    """사본의 영상 정책이 failed_only이고 다른 설정은 그대로이며(비밀값 가림은 기본 = 꺼짐),
    R2 그래프 블록이 만든 그래프가 제품 로더로 읽히고 `inventory_open`과 두 곳만 다르다
    (`n_press_i` 영상 끔, 마지막 검증이 로그인 단추를 3초 기다림). 가림 켜기 블록은
    `record.redact_secrets: true`만 더하고 되돌리기 블록은 바이트를 되돌린다
    (다듬기 P1-B: P1-A의 기본 가림 없음에 맞춤)."""
    run_powershell(tmp_path, COPY_MARK)
    root = tmp_path / "kb-m3" / "sample-rpg"
    sample = REPO_ROOT / "fixtures" / "sample-game" / "workspace"
    raw = (root / "kookabug.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    copied = json.loads(raw)
    original = json.loads((sample / "kookabug.json").read_text(encoding="utf-8"))
    assert copied["record"] == {**original["record"], "video": "failed_only"}
    assert {k: v for k, v in copied.items() if k != "record"} == {
        k: v for k, v in original.items() if k != "record"
    }
    ws = Workspace.open(root)
    assert ws.root == root
    local = json.loads((root / ".kookabug" / "local.json").read_bytes())
    assert local["format"] == "kookabug.local/0"

    assert "redact_secrets" not in copied["record"]

    run_powershell(tmp_path, R2_GRAPH_MARK)
    edited = json.loads((root / R2_GRAPH).read_bytes())
    source = json.loads((root / INVENTORY).read_bytes())
    assert edited["nodes"]["n_press_i"]["record"] == {"video": "off"}
    check = edited["nodes"]["n_check_inventory"]["in"]
    assert check["target"] == {"$target": "targets/login/login_button.target.json"}
    assert check["timeout_ms"] == 3000
    del edited["nodes"]["n_press_i"]["record"]
    edited["nodes"]["n_check_inventory"]["in"] = source["nodes"]["n_check_inventory"]["in"]
    assert edited == source
    program = load_program(
        ws, R2_GRAPH, secrets=MemorySecrets({"accounts.qa_tester_01": "sample-pass-01"})
    )
    errors = [d for d in program.diagnostics if d.severity == "error"]
    assert errors == [], errors

    before = (root / "kookabug.json").read_bytes()
    run_powershell(tmp_path, REDACT_ON_MARK)
    redacted = json.loads((root / "kookabug.json").read_bytes())
    assert redacted["record"] == {**copied["record"], "redact_secrets": True}
    assert {k: v for k, v in redacted.items() if k != "record"} == {
        k: v for k, v in copied.items() if k != "record"
    }
    assert Workspace.open(root).diagnostics == []
    run_powershell(tmp_path, REDACT_BACK_MARK)
    assert (root / "kookabug.json").read_bytes() == before


def test_r1_names_where_swapped_target_fails() -> None:
    """R1은 바꿔치기 그래프가 실제로 실패하는 곳(서브그래프 '월드 접속 > 타이틀 대기')을 적는다.
    그 실행은 로그인·I 키에 닿지 않으므로 R2는 따로 만든 그래프를 쓴다
    (다듬기 P1-B, 조율자 실측)."""
    sample = REPO_ROOT / "fixtures" / "sample-game" / "workspace"
    test = json.loads((sample / SWAPPED).read_text(encoding="utf-8"))
    sub = json.loads((sample / SWAPPED_SUB).read_text(encoding="utf-8"))
    assert test["nodes"]["n_enter_world"]["config"]["graph"] == SWAPPED_SUB
    where = f"{test['nodes']['n_enter_world']['title']} > {sub['nodes']['n_wait_title']['title']}"
    assert where in test["meta"]["description"]
    r1 = text_between(manual(), "### R1 ", "### R2 ")
    assert where in r1 and SWAPPED_SUB in r1 and "`n_wait_title`" in r1
    assert "n_press_i" not in r1 and "인벤토리" not in r1
    r2 = text_between(manual(), "### R2 ", "### R3 ")
    assert SWAPPED not in r2 and R2_GRAPH in r2
    # 기본은 가리지 않고, 가림은 설정으로 켠다 (2026-11-03 사용자 결정 D3)
    for words in ("가리지 않는다", "record.redact_secrets: true", "비밀값 입력", "기록 끔"):
        assert words in r2, words


# ---------------------------------------------------------------- S3: daemon 수명 (T12 검수 3)

S2_MARK: Final = "# M3 S2 설치본 사본"
S3_MARK: Final = "# M3 S3 영상 사용 불가 사본"
MF_MISSING: Final = '{"encoder": "msmf", "msmf": {"mf_dlls": ["kb-missing-mfplat.dll"]}}'
FAKE_ENCODER: Final = '{"encoder": "fake"}'
"""S2 흐름의 영상 쓰기 (실제 인코더 대신, 계획 2.5 "CI는 가짜 인코더")."""


def copy_target(block: str) -> str:
    """블록의 `Copy-Item … "$HOME\\Documents\\<폴더>"` 폴더 이름."""
    (name,) = re.findall(
        r'Copy-Item -Recurse "\$app\\examples\\sample-game" "\$HOME\\Documents\\([^"\\]+)"', block
    )
    return name


def test_s3_uses_fresh_workspace_copy_not_s2_daemon() -> None:
    """S3은 S2와 다른 새 사본을 열고(그래야 주입한 환경을 가진 새 daemon이 뜬다), 검사 설정은 앱을
    띄우기 전에 넣으며, 재사용 daemon·설정 제거 뒤 남는 환경을 경고한다."""
    s2, s3 = manual_block_after(S2_MARK), manual_block_after(S3_MARK)
    fresh = copy_target(s3)
    assert copy_target(s2) != fresh
    assert s3.index("$env:KOOKABUG_VIDEO_TEST") < s3.index('& "$app\\Kookabug.exe"')
    assert f"Documents\\{fresh}\\workspace\\fake-platform.json" in s3
    section = text_between(manual(), "### S3 ", "### S4 ")
    for words in (f"`문서\\{fresh}\\workspace`", "daemon은 남고", "다시 쓰지 않는다", "daemon"):
        assert words in section, words


@pytest.mark.process
def test_s3_env_flow_on_pc_without_media(
    tmp_path: Path, spawned: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T12 검수 2라운드 반례: Media Foundation이 없는 PC(바탕 환경에 MF DLL 부재)에서도 같은 흐름
    검사가 통과한다 — 실제 인코더에 기대지 않는다."""
    from kb_testing import proc

    original = proc.direct_env

    def without_media(base: Any = None) -> dict[str, str]:
        return {**original(base), "KOOKABUG_VIDEO_TEST": MF_MISSING}

    monkeypatch.setattr(proc, "direct_env", without_media)
    test_s3_env_reaches_runs_only_in_fresh_workspace_daemon(tmp_path, spawned)


@pytest.mark.process
def test_s3_env_reaches_runs_only_in_fresh_workspace_daemon(tmp_path: Path, spawned: Any) -> None:
    """S2 → S3 흐름을 실제 daemon으로: S2 사본의 daemon은 UI가 끊긴 뒤에도 남아 다시 붙으면 그
    daemon(주입 전 환경, 가짜 인코더)이 실행을 띄운다 → 영상 recorded. S3의 새 사본은 주입한
    환경으로 새 daemon이 떠 실행이 unavailable(mf_missing)이다."""
    from installer import build, smoke
    from kb_testing.proc import direct_env, isolated_env, python_cmd, wait_until
    from kookabug_daemon.client import DaemonClient, attach

    def prepare(name: str) -> Path:
        build.copy_examples(REPO_ROOT / "fixtures" / "sample-game", tmp_path / name)
        ws = tmp_path / name / "workspace"
        config = json.loads((ws / "kookabug.json").read_text(encoding="utf-8"))
        config["record"]["video"] = "failed_only"
        (ws / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
        (ws / smoke.VIDEO_GRAPH).write_text(json.dumps(smoke.VIDEO_SMOKE), encoding="utf-8")
        return ws

    s2 = prepare(copy_target(manual_block_after(S2_MARK)))
    s3 = prepare(copy_target(manual_block_after(S3_MARK)))
    # 목적은 daemon 환경 전달이라 실제 인코더에 기대지 않는다(인코더 없는 PC·CI에서도 같다):
    # S2 환경은 가짜 인코더, S3 환경만 MF DLL 부재로 덮어쓴다 (T12 검수 2라운드)
    env = {**direct_env(isolated_env(tmp_path)), "KOOKABUG_VIDEO_TEST": FAKE_ENCODER}
    spawns: list[Path] = []

    def spawner(environ: dict[str, str]) -> Any:
        def spawn(root: Path) -> None:
            spawns.append(root)
            cmd = python_cmd("-m", "kookabug_cli", "daemon", "--workspace", root)
            cmd += ["--platform-fake", str(root / "fake-platform.json")]
            spawned.popen(cmd, env=environ, creationflags=0x08000000)

        return spawn

    def video_of(root: Path, environ: dict[str, str]) -> tuple[str, dict[str, Any]]:
        info = attach(root, spawn=spawner(environ))
        assert info is not None
        with DaemonClient.from_session(info) as client:
            started = client.call("run.start", {"path": smoke.VIDEO_GRAPH})

            def ended() -> bool:
                status = client.call("run.status", {"run_id": started["run_id"]})
                return status["state"] == "ended"

            wait_until(ended, timeout=60)
        run_json = Path(started["run_dir"]) / "run.json"
        return info.start_id, json.loads(run_json.read_text(encoding="utf-8"))["video"]

    first, video = video_of(s2, env)  # S2: 영상을 쓰는 환경 (가짜 인코더)
    assert video["status"] == "recorded", video
    injected = {**env, "KOOKABUG_VIDEO_TEST": MF_MISSING}
    again, video = video_of(s2, injected)  # 같은 사본을 다시 열면 남은 daemon에 붙는다
    assert again == first and spawns == [s2]
    assert video["status"] == "recorded", video
    _, video = video_of(s3, injected)  # S3: 새 사본 → 새 daemon이 주입 환경을 받는다
    assert spawns == [s2, s3]
    assert (video["status"], video.get("reason")) == ("unavailable", "mf_missing"), video
    for root in (s2, s3):
        info = attach(root, spawn=lambda _root: None)
        assert info is not None
        with DaemonClient.from_session(info) as client:
            client.call("daemon.shutdown", {"force": True})
