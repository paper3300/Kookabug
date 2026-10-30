"""데스크톱 검사 실행 조건과 탐지 보고 (구현 계획 M1 2.13)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kb_testing import desktop as dk

FAILED = dk.ProbeReport(
    ok=False,
    checks=(
        dk.ProbeCheck("window_station", True, "WinSta0, 대화형", 0),
        dk.ProbeCheck("wgc_frame", False, "5초 안에 WGC 프레임이 오지 않았다", 5000),
    ),
    elapsed_ms=5001,
    python="3.14.10",
    windows="10.0.26200",
    session_id=1,
)
PASSED = dk.ProbeReport(
    ok=True,
    checks=(dk.ProbeCheck("window_station", True, "WinSta0, 대화형", 0),),
    elapsed_ms=1,
    python="3.14.10",
    windows="10.0.26200",
    session_id=1,
)


class _Probe:
    def __init__(self, report: dk.ProbeReport) -> None:
        self.report = report
        self.calls = 0

    def __call__(self) -> dk.ProbeReport:
        self.calls += 1
        return self.report


def test_mode_off_skips_with_reason() -> None:
    probe = _Probe(PASSED)
    for markers in ({"desktop"}, {"desktop_input"}, {"soak"}):
        env = {dk.MODE_ENV: "off", dk.INPUT_ENV: "1", dk.SOAK_ENV: "1"}
        decision = dk.decide(markers, env, probe)
        assert decision == dk.Decision("skip", f"데스크톱 검사 끔 ({dk.MODE_ENV}=off)")
    assert probe.calls == 0
    # 표시 없는 검사는 모드와 무관하게 돈다
    assert dk.decide({"process"}, {dk.MODE_ENV: "off"}, probe).action == "run"
    assert probe.calls == 0


def test_mode_require_fails_when_probe_fails() -> None:
    require = dk.decide({"desktop"}, {dk.MODE_ENV: "require"}, _Probe(FAILED))
    assert require.action == "fail"
    assert "wgc_frame: 5초 안에 WGC 프레임이 오지 않았다" in require.reason
    assert f"{dk.MODE_ENV}=require" in require.reason

    # auto(기본)는 같은 이유로 건너뛴다
    for env in ({dk.MODE_ENV: "auto"}, {}):
        auto = dk.decide({"desktop"}, env, _Probe(FAILED))
        assert auto.action == "skip"
        assert auto.reason == f"대화형 데스크톱 탐지 실패 — {FAILED.reason}"

    assert dk.decide({"desktop"}, {dk.MODE_ENV: "require"}, _Probe(PASSED)).action == "run"
    with pytest.raises(ValueError, match="off·auto·require"):
        dk.decide({"desktop"}, {dk.MODE_ENV: "always"}, _Probe(PASSED))


def test_desktop_input_and_soak_need_opt_in() -> None:
    for marker, flag in (("desktop_input", dk.INPUT_ENV), ("soak", dk.SOAK_ENV)):
        probe = _Probe(PASSED)
        # require여도 옵트인 없이는 돌지 않는다 (탐지도 하지 않는다)
        no_opt_in = dk.decide({"desktop", marker}, {dk.MODE_ENV: "require"}, probe)
        assert no_opt_in.action == "skip"
        assert f"{flag}=1" in no_opt_in.reason
        assert probe.calls == 0
        assert dk.decide({marker}, {dk.MODE_ENV: "require", flag: "0"}, probe).action == "skip"

        opted = dk.decide({"desktop", marker}, {dk.MODE_ENV: "require", flag: "1"}, probe)
        assert opted.action == "run"
        assert probe.calls == 1
        # 옵트인해도 탐지 실패면 require는 실패
        failed = dk.decide({marker}, {dk.MODE_ENV: "require", flag: "1"}, _Probe(FAILED))
        assert failed.action == "fail"
    # 둘 다 붙은 검사는 둘 다 켜야 한다
    both = {"desktop_input", "soak"}
    assert dk.decide(both, {dk.INPUT_ENV: "1"}, _Probe(PASSED)).action == "skip"
    assert dk.decide(both, {dk.INPUT_ENV: "1", dk.SOAK_ENV: "1"}, _Probe(PASSED)).action == "run"


@pytest.mark.process
def test_probe_report_json_fields(tmp_path: Path) -> None:
    out = tmp_path / "probe.json"
    env = {**os.environ, "PYTHONPATH": str(dk.TOOLS_DIR), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [sys.executable, "-m", "kb_testing.desktop", "--json", str(out), "--no-fail"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=dk.PROBE_TIMEOUT_S,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(out.read_text("utf-8"))
    assert set(data) == {"ok", "checks", "elapsed_ms", "python", "windows", "session_id"}
    assert isinstance(data["ok"], bool)
    assert [c["id"] for c in data["checks"]] == list(dk.CHECK_IDS)
    for check in data["checks"]:
        assert set(check) == {"id", "ok", "detail", "elapsed_ms"}
        assert isinstance(check["ok"], bool)
        assert check["detail"]
    assert data["ok"] == all(c["ok"] for c in data["checks"])
    assert dk.ProbeReport.from_dict(data).to_dict() == data
    # 사람이 읽는 요약도 같이 나온다
    assert "### 데스크톱 탐지" in proc.stdout

    # 플러그인이 쓰는 경로(표준 출력 JSON)도 같은 보고를 준다
    report = dk.probe_in_subprocess()
    assert [c.id for c in report.checks] == list(dk.CHECK_IDS)


@pytest.mark.process
def test_plugin_applies_mode_to_marked_tests(tmp_path: Path) -> None:
    (tmp_path / "test_marked.py").write_text(
        "import pytest\n\n"
        "@pytest.mark.desktop\n"
        "def test_needs_desktop():\n"
        "    pass\n\n"
        "@pytest.mark.desktop_input\n"
        "def test_needs_input():\n"
        "    pass\n\n"
        "def test_plain():\n"
        "    pass\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(dk.TOOLS_DIR),
        "PYTHONIOENCODING": "utf-8",
        dk.MODE_ENV: "off",
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "kb_testing.pytest_plugin",
            "--strict-markers",
            "-rs",
            "-q",
            "-o",
            "addopts=",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed, 2 skipped" in proc.stdout
    assert f"데스크톱 검사 끔 ({dk.MODE_ENV}=off)" in proc.stdout
    assert "건너뜀 2개" in proc.stdout
