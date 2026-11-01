"""`kookabug doctor` (구현 계획 M1 2.11, 계획 검수 8).

헤드리스 프로필은 데스크톱 없이 돈다(설치 스모크·CI). 데스크톱 항목은 여기서 바꿔 끼운 결과로
모양만 보고, 실제 확인은 `test_doctor_live.py`(`desktop`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kookabug_cli import main as cli
from kookabug_platform import doctor
from kookabug_platform.doctor import Check

HEADLESS_IDS = [
    "python",
    "import.numpy",
    "import.cv2",
    "import.onnxruntime",
    "import.windows_capture",
    "dll.origin",
    "ocr.models",
    "dpi",
    "smoke.fake",
    "video.encoder",
]
EXAMPLE_WORKSPACE = Path(__file__).resolve().parents[3] / "fixtures" / "sample-game" / "workspace"


@pytest.fixture(autouse=True)
def _models(ocr_models: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))


def run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = cli.main(argv)
    return code, capsys.readouterr().out


def run_json(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    code, out = run([*argv, "--json"], capsys)
    (line,) = out.splitlines()  # JSON 한 객체만
    return code, json.loads(line)


def by_id(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in body["checks"]}


def test_profile_headless_skips_desktop_checks(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_desktop() -> list[Check]:
        raise AssertionError("headless 프로필이 데스크톱 검사를 불렀다")

    monkeypatch.setattr(doctor, "_desktop_checks", no_desktop)
    code, body = run_json(["doctor", "--profile", "headless"], capsys)
    assert [c["id"] for c in body["checks"]] == HEADLESS_IDS
    assert {c["profile"] for c in body["checks"]} == {"headless"}
    assert (code, body["ok"], body["profile"]) == (0, True, "headless")


def test_json_items_have_profile(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 기본 프로필은 desktop = headless 항목 + desktop 항목 (데스크톱 결과는 바꿔 끼움)
    fake = [Check("desktop.capture", "desktop", False, "세션이 잠겨 있다")]
    monkeypatch.setattr(doctor, "_desktop_checks", lambda: fake)
    code, body = run_json(["doctor"], capsys)
    assert body["profile"] == "desktop"
    for item in body["checks"]:
        assert set(item) == {"detail", "id", "ok", "profile"}
        assert item["profile"] in ("headless", "desktop") and isinstance(item["ok"], bool)
    assert [c["id"] for c in body["checks"]] == [*HEADLESS_IDS, "desktop.capture"]
    # 고른 프로필에 실패가 하나라도 있으면 1
    assert (code, body["ok"]) == (1, False)


def test_text_output_lines(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out = run(["doctor", "--profile", "headless"], capsys)
    lines = out.splitlines()
    assert code == 0
    assert lines[0].startswith("[통과] python (headless): ")
    assert lines[-1] == f"doctor (headless): 검사 {len(HEADLESS_IDS)}개, 전부 통과"


def test_dll_origin_reported(capsys: pytest.CaptureFixture[str]) -> None:
    _, body = run_json(["doctor", "--profile", "headless"], capsys)
    detail = by_id(body)["dll.origin"]["detail"]
    for name in doctor.DLLS:
        assert f"{name}=" in detail
    # opencv를 읽었으므로 msvcp140.dll은 어딘가에서 읽혔다
    msvcp = detail.split("msvcp140.dll=")[1].split(";")[0]
    assert msvcp.lower().endswith("msvcp140.dll")


def test_dll_outside_install_fails_when_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """설치본이면 `msvcp140.dll`은 설치 폴더(앱 로컬 VC++)에서 읽혀야 한다."""
    install = tmp_path / "Kookabug"
    monkeypatch.setattr(doctor, "installed", lambda: True)
    monkeypatch.setattr(doctor, "_install_root", lambda: install)
    monkeypatch.setattr(doctor, "loaded_dll", lambda name: Path("C:/Windows/System32") / name)
    ok, detail = doctor._dlls()
    assert not ok and "설치 폴더 밖" in detail
    monkeypatch.setattr(doctor, "loaded_dll", lambda name: install / "python" / name)
    assert doctor._dlls()[0]


def test_exit_1_when_model_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(tmp_path / "없는 폴더"))
    code, body = run_json(["doctor", "--profile", "headless"], capsys)
    models = by_id(body)["ocr.models"]
    assert (code, body["ok"], models["ok"]) == (1, False, False)
    assert models["detail"].startswith("ocr_model_missing:")
    # 다른 항목은 계속 본다 (스모크는 OCR이 없어 실패)
    assert by_id(body)["import.cv2"]["ok"] and not by_id(body)["smoke.fake"]["ok"]


def test_exit_1_when_model_corrupt(
    tmp_path: Path,
    ocr_models: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = tmp_path / "models"
    broken.mkdir()
    for path in ocr_models.iterdir():
        (broken / path.name).write_bytes(path.read_bytes())
    det = next(broken.glob("*det*.onnx"))
    det.write_bytes(det.read_bytes()[:-1] + b"\x00")
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(broken))
    code, body = run_json(["doctor", "--profile", "headless"], capsys)
    assert code == 1
    assert by_id(body)["ocr.models"]["detail"].startswith("ocr_model_corrupt:")


def test_headless_runs_fake_smoke_graph(capsys: pytest.CaptureFixture[str]) -> None:
    """가짜 플랫폼 스모크: `kookabug doctor`는 예제 게임 워크스페이스의 헤드리스 스모크 그래프를
    장면 표로 돌린다 (타이틀 버튼 찾기·게임 이름 OCR·클릭·로그인 화면 확인)."""
    _, body = run_json(["doctor", "--profile", "headless"], capsys)
    smoke = by_id(body)["smoke.fake"]
    assert smoke["ok"], smoke["detail"]
    expected = EXAMPLE_WORKSPACE / "tests" / "smoke_headless.graph.json"
    assert smoke["detail"].startswith(f"{expected}: pass ("), smoke["detail"]
    assert "OCR 'SampleRPG'" in smoke["detail"]


def test_builtin_smoke_graph_without_example() -> None:
    """예제 워크스페이스가 없는 개발 환경(wheel만 설치)의 내장 최소 그래프: 그린 화면에서 표식을
    찾고(실제 매칭) 수를 읽어(실제 OCR) 비교한다."""
    check = doctor._guard("smoke.fake", "headless", doctor._smoke(None))
    assert check.ok, check.detail
    assert "(내장)" in check.detail and "SCORE 12345" in check.detail


def test_example_smoke_found_in_repo_and_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = doctor.example_smoke()
    assert found is not None
    assert (found.workspace, found.graph) == (EXAMPLE_WORKSPACE, "tests/smoke_headless.graph.json")
    assert found.scenario == (EXAMPLE_WORKSPACE.parent / "frames" / "scenario.json").resolve()
    # 설치본은 <설치>/examples/sample-game/workspace. 없으면 스모크가 실패로 알린다
    # (내장으로 대신하지 않는다)
    install = tmp_path / "Kookabug"
    monkeypatch.setattr(doctor, "installed", lambda: True)
    monkeypatch.setattr(doctor, "_install_root", lambda: install)
    missing = doctor.example_smoke()
    assert missing is not None
    assert missing.workspace == install / "examples" / "sample-game" / "workspace"
    check = doctor._guard("smoke.fake", "headless", doctor._smoke(missing))
    assert not check.ok and "workspace" in check.detail.lower(), check.detail


def test_smoke_failure_reports_reason(tmp_path: Path) -> None:
    graph = doctor.smoke_workspace(tmp_path)
    # 표식 target을 다른 그림으로 바꾸면 대기가 timeout → 스모크 실패
    other = doctor._smoke_image()[200:280, 500:620]
    import cv2

    (tmp_path / "targets" / "marker.png").write_bytes(cv2.imencode(".png", other)[1].tobytes())
    result = doctor.run_smoke(graph)
    assert result.verdict == "fail"
    check = doctor._guard("smoke.fake", "headless", doctor._smoke(graph))
    assert not check.ok and "unhandled_fail" in check.detail


def test_unknown_profile_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["doctor", "--profile", "cloud"])
    assert exc.value.code == cli.EXIT_USAGE
    with pytest.raises(ValueError, match="프로필"):
        doctor.run_checks("cloud")  # type: ignore[arg-type]


def test_check_never_raises() -> None:
    def boom() -> tuple[bool, str]:
        raise RuntimeError("터짐")

    check = doctor._guard("x", "headless", boom)
    assert (check.ok, check.detail) == (False, "RuntimeError: 터짐")
