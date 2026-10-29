import json
import textwrap
import zipfile
from pathlib import Path

import pytest

from kb_testing import packaging as pk
from kb_testing.console import run_legacy_console

SDK = pk.REPO_ROOT / "python" / "kookabug_sdk"
MODULES = [
    "__init__",
    "build",
    "cli",
    "console",
    "context",
    "decorators",
    "pure",
    "result",
    "schema",
    "testing",
    "types",
]

PLUGIN_NODES = """
from kookabug_sdk import Context, Exit, Result, node


@node(type="sample.flow.noop", version=1, title="아무것도 안 함", exits=[Exit("done", "ok")])
def noop(ctx: Context) -> Result:
    return Result.ok("done")
"""

LOAD = """\
import json
import kookabug_sdk
from kookabug_sdk.schema import load_installed
print(json.dumps({"sdk": kookabug_sdk.__file__, "schema": load_installed("kb_sample_plugin")}))
"""


def write_plugin(root: Path) -> Path:
    project = root / "kb-sample-plugin"
    package = project / "src" / "kb_sample_plugin"
    package.mkdir(parents=True)
    (package / "__init__.py").touch()
    (package / "nodes.py").write_text(PLUGIN_NODES, encoding="utf-8")
    (project / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "kb-sample-plugin"
            version = "0.1.0"
            requires-python = ">=3.14"
            dependencies = ["kookabug-sdk"]

            [tool.kookabug]
            id = "sample"
            modules = ["kb_sample_plugin.nodes"]

            [build-system]
            requires = ["uv_build>=0.13.6,<0.14"]
            build-backend = "uv_build"
            """
        ),
        encoding="utf-8",
    )
    return project


@pytest.mark.packaging
def test_sdk_wheel_and_sdist_build_and_license_file_included(tmp_path: Path) -> None:
    sdk = pk.build_dists(SDK, tmp_path / "dist-sdk")

    wheel_files = sdk.wheel_files()
    assert [f for f in wheel_files if f.endswith(".dist-info/licenses/LICENSE")]
    for module in MODULES:
        assert f"kookabug_sdk/{module}.py" in wheel_files
    assert not [f for f in wheel_files if "__pycache__" in f or "/tests/" in f]
    assert [f for f in sdk.sdist_files() if f.endswith("/LICENSE")]

    metadata = next(f for f in wheel_files if f.endswith(".dist-info/METADATA"))
    with zipfile.ZipFile(sdk.wheel) as zf:
        meta = zf.read(metadata).decode("utf-8")
        entry_points = zf.read(metadata.replace("METADATA", "entry_points.txt")).decode("utf-8")
    assert "License-Expression: MIT" in meta
    assert "Requires-Dist" not in meta
    assert "kookabug-sdk = kookabug_sdk.cli:main" in entry_points

    # 깨끗한 venv에 SDK만 설치 → 설치된 명령으로 플러그인 build → 플러그인 wheel에 스키마가 들어가고
    # 설치 후 load_installed로 읽힌다 (uv_build가 모듈 안 JSON을 wheel에 넣는다, G22)
    py = pk.make_clean_venv(tmp_path / "venv")
    pk.install(py, sdk.wheel)
    project = write_plugin(tmp_path)
    cli = py.parent / ("kookabug-sdk.exe" if py.suffix == ".exe" else "kookabug-sdk")
    # 영문 Windows 콘솔(cp1252)에서도 설치된 명령이 한국어 결과를 출력한다
    proc = run_legacy_console([cli, "build", project], cwd=tmp_path, env=pk.clean_env())
    assert proc.returncode == 0, proc.stderr
    assert "(1개 노드)" in proc.stdout
    schema_file = project / "src" / "kb_sample_plugin" / "kookabug.schema.json"
    built = json.loads(schema_file.read_text(encoding="utf-8"))
    assert [n["type"] for n in built["nodes"]] == ["sample.flow.noop"]

    plugin = pk.build_dists(project, tmp_path / "dist-plugin")
    assert "kb_sample_plugin/kookabug.schema.json" in plugin.wheel_files()
    pk.install(py, sdk.wheel, plugin.wheel)
    out = json.loads(pk.run_isolated(py, LOAD, cwd=tmp_path).stdout)
    assert Path(out["sdk"]).resolve().is_relative_to((tmp_path / "venv").resolve())
    assert out["schema"] == built
