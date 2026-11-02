"""tools 스크립트가 콘솔 인코딩과 무관하게 한국어를 출력한다 (영문 Windows cp1252)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import license_pipeline as lp
from kb_testing import packaging as pk
from kb_testing.audit_fixtures import ALLOWLIST, WIN_314, scan_item
from kb_testing.console import run_legacy_console

TOOLS = pk.REPO_ROOT / "tools"


def tool(
    script: str, *args: str | Path, cwd: Path = pk.REPO_ROOT
) -> subprocess.CompletedProcess[str]:
    return run_legacy_console([sys.executable, TOOLS / script, *args], cwd=cwd)


@pytest.mark.parametrize(
    ("script", "description"),
    [
        ("gen_schema.py", "메타스키마 → Python 생성물"),
        ("fmt_json.py", "JSON을 canonical 형식으로"),
        ("license_audit.py", "Kookabug 라이선스 감사 판정"),
        ("license_pipeline.py", "Kookabug 라이선스 감사 파이프라인"),
    ],
)
def test_help_on_cp1252_console(script: str, description: str) -> None:
    proc = tool(script, "--help")
    assert proc.returncode == 0, proc.stderr
    assert description in proc.stdout


def test_desktop_probe_help_on_cp1252_console() -> None:
    # `python -m kb_testing.desktop`: argparse 도움말(한국어)이 utf8_stdio보다 먼저 나가면 죽었다
    env = {**os.environ, "PYTHONPATH": str(TOOLS)}
    cmd = [sys.executable, "-m", "kb_testing.desktop", "--help"]
    proc = run_legacy_console(cmd, cwd=pk.REPO_ROOT, env=env)
    assert proc.returncode == 0, proc.stderr
    assert "대화형 데스크톱 탐지" in proc.stdout


PYTEST_PRINT_PROBE = """\
from pathlib import Path

from installer.smoke import SmokeReport


def test_smoke_step_prints_korean() -> None:
    assert SmokeReport(Path(".")).step("setup.variant", lambda: (True, "설치 폴더 공백 한글")).ok
"""


def test_pytest_s_prints_korean_on_cp1252_console(tmp_path: Path) -> None:
    # CI installer 잡은 `pytest -s`로 설치 스모크를 돌린다. 단계 출력이 cp1252 stdout에 바로 써진다
    probe = tmp_path / "test_probe.py"
    probe.write_text(PYTEST_PRINT_PROBE, encoding="utf-8")
    cmd = [sys.executable, "-m", "pytest", "-s", "-q", "-p", "no:cacheprovider"]
    cmd += ["-p", "kb_testing.pytest_plugin", str(probe)]
    env = {**os.environ, "PYTHONPATH": str(TOOLS)}
    proc = run_legacy_console(cmd, cwd=tmp_path, env=env)
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "[통과] setup.variant" in proc.stdout
    assert "설치 폴더 공백 한글" in proc.stdout


def test_check_commands_on_cp1252_console() -> None:
    for script in ("gen_schema.py", "fmt_json.py"):
        proc = tool(script, "--check")
        assert proc.returncode == 0, f"{script}\n{proc.stdout}\n{proc.stderr}"


def test_license_audit_reports_on_cp1252_console(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.txt"
    env_file = tmp_path / "env.json"
    py_json = tmp_path / "py.json"
    runtime.write_text("alpha==1.0\n", encoding="utf-8")
    env_file.write_text(json.dumps(WIN_314), encoding="utf-8")
    args = [
        "--runtime",
        runtime,
        "--marker-env",
        env_file,
        "--python",
        py_json,
        "--allowlist",
        ALLOWLIST,
        "--notices-out",
        tmp_path / "NOTICES.txt",
    ]

    py_json.write_text(json.dumps([scan_item("alpha", "1.0")]), encoding="utf-8")
    proc = tool("license_audit.py", *args, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "Python 런타임 패키지 1개, JS 패키지 0개" in proc.stdout
    assert "라이선스 감사 통과" in proc.stdout

    py_json.write_text(json.dumps([scan_item("alpha", "1.0", "GPL-3.0")]), encoding="utf-8")
    proc = tool("license_audit.py", *args, cwd=tmp_path)
    assert proc.returncode == 1
    assert "라이선스 감사 실패" in proc.stderr


FIXTURE_PYPROJECT = """\
[project]
name = "audit-fixture"
version = "0.0.0"
requires-python = ">=3.14"
dependencies = ["prettytable"]
"""


@pytest.mark.packaging
def test_license_pipeline_on_cp1252_console(tmp_path: Path) -> None:
    # CI licenses 잡과 같은 진입점(license_pipeline.py)을 작은 프로젝트로 끝까지 돌린다
    project = tmp_path / "fixture"
    project.mkdir()
    (project / "pyproject.toml").write_text(FIXTURE_PYPROJECT, encoding="utf-8")
    pk.run([pk.uv_exe(), "lock", "--quiet"], cwd=project)

    build = tmp_path / "audit"
    proc = tool(
        "license_pipeline.py",
        "--project",
        project,
        "--build-dir",
        build,
        "--no-js",
        cwd=tmp_path,
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "라이선스 감사 통과" in proc.stdout
    assert (build / lp.BUILD_MARKER).exists()
