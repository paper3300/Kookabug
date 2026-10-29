"""`kookabug-sdk` 명령이 콘솔 인코딩과 무관하게 한국어를 출력한다 (영문 Windows cp1252)."""

import io
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from kb_testing.console import run_legacy_console
from kookabug_sdk.console import utf8_stdio

NODES = """
from kookabug_sdk import Context, Exit, Result, node


@node(type="{id}.flow.noop", version=1, title="아무것도 안 함", exits=[Exit("done", "ok")])
def noop(ctx: Context) -> Result:
    return Result.ok("done")
"""


def write_project(root: Path, plugin_id: str) -> Path:
    project = root / "kbt_console"
    package = project / "src" / "kbt_console"
    package.mkdir(parents=True)
    (package / "__init__.py").touch()
    (package / "nodes.py").write_text(NODES.format(id=plugin_id), encoding="utf-8")
    (project / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "kbt-console"
            version = "0.1.0"

            [tool.kookabug]
            id = "{plugin_id}"
            modules = ["kbt_console.nodes"]
            """
        ),
        encoding="utf-8",
    )
    return project


def sdk(*args: str | Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return run_legacy_console([sys.executable, "-m", "kookabug_sdk.cli", *args], cwd=cwd)


def test_build_prints_korean_on_cp1252_console(tmp_path: Path) -> None:
    project = write_project(tmp_path, "sample")
    proc = sdk("build", project, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "(1개 노드)" in proc.stdout


def test_build_errors_print_korean_on_cp1252_console(tmp_path: Path) -> None:
    project = write_project(tmp_path, "Bad-Id")
    proc = sdk("build", project, cwd=tmp_path)
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert proc.stderr.startswith("오류: ")


def test_help_prints_korean_on_cp1252_console(tmp_path: Path) -> None:
    proc = sdk("--help", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "Kookabug 노드 SDK" in proc.stdout


def test_utf8_stdio_skips_missing_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    # pythonw에는 stdout이 없고, 바꿔 끼운 스트림에는 reconfigure가 없을 수 있다
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    utf8_stdio()
