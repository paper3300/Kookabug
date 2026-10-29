"""라이선스 감사 파이프라인을 실제 uv·pip-licenses로 끝까지 돌린다."""

import json
from pathlib import Path

import pytest

import license_audit as la
import license_pipeline as lp
from kb_testing import packaging as pk

DEV_ONLY = {"pytest", "ruff", "pyright"}


def _installed_distributions(python: Path, cwd: Path) -> dict[str, str]:
    """스캐너와 별개로 대상 venv의 배포 목록을 직접 읽는다."""
    code = (
        "import json, importlib.metadata as m; "
        "print(json.dumps({d.metadata['Name']: d.version for d in m.distributions()}))"
    )
    raw = json.loads(pk.run_isolated(python, code, cwd=cwd).stdout)
    return {la.canonicalize_name(k): v for k, v in raw.items()}


def _load_outputs(build: Path) -> tuple[la.Baseline, dict[str, str]]:
    runtime = la.parse_runtime((build / "runtime.txt").read_text("utf-8"))
    marker_env = la.load_marker_env(json.loads((build / "marker_env.json").read_text("utf-8")))
    baseline = la.select_active(runtime, marker_env)
    scan = la.parse_pip_licenses(json.loads((build / "py.json").read_text("utf-8")))
    return baseline, {name: pkg.version for name, pkg in scan.items()}


@pytest.mark.packaging
def test_audit_pipeline_on_workspace(tmp_path: Path) -> None:
    build = tmp_path / "audit"
    assert lp.run_pipeline(pk.REPO_ROOT, build, with_js=False) == 0

    baseline, scanned = _load_outputs(build)
    expected = {name: str(req.version) for name, req in baseline.active.items()}
    assert expected, "제품 런타임 의존성이 비어 있다"
    assert not DEV_ONLY & expected.keys()

    # 기준 집합 = 스캔 집합
    assert scanned == expected
    # 스캐너가 대상 venv를 빠짐없이 읽었다 (기본 제외 목록에 빠진 것이 없다)
    venv_py = lp.venv_python(build / "venv")
    assert _installed_distributions(venv_py, tmp_path) == scanned

    # 감사 도구 때문에 추가된 패키지는 없다
    assert "pip-licenses" not in scanned
    assert "pip" not in scanned
    # 도구와 공통인 패키지는 제품이 요구할 때만 있다
    for shared in ("prettytable", "wcwidth"):
        assert (shared in scanned) == (shared in expected)

    notices = (build / "THIRD_PARTY_NOTICES.txt").read_text("utf-8")
    for req in baseline.active.values():
        assert f"{req.display_name} {req.version}" in notices


FIXTURE_PYPROJECT = """\
[project]
name = "audit-fixture"
version = "0.0.0"
requires-python = ">=3.14"
dependencies = ["prettytable"]
"""


@pytest.mark.packaging
def test_pipeline_keeps_product_dependency_shared_with_audit_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 제품 런타임이 prettytable(→ wcwidth)을 요구하는 작은 프로젝트
    project = tmp_path / "fixture"
    project.mkdir()
    (project / "pyproject.toml").write_text(FIXTURE_PYPROJECT, encoding="utf-8")
    pk.run([pk.uv_exe(), "lock", "--quiet"], cwd=project)

    build = tmp_path / "audit"
    assert lp.run_pipeline(project, build, with_js=False) == 0

    baseline, scanned = _load_outputs(build)
    assert {"prettytable", "wcwidth"} <= baseline.active.keys()
    assert scanned == {n: str(r.version) for n, r in baseline.active.items()}
    notices = (build / "THIRD_PARTY_NOTICES.txt").read_text("utf-8")
    assert "prettytable " in notices
    assert "wcwidth " in notices
    assert "pip-licenses" not in notices

    # 같은 대상 venv를 --with-system 없이 스캔하면 기본 제외 목록 때문에 빠져 감사가 실패한다
    default_json = build / "py-default.json"
    pk.run(
        [
            pk.uv_exe(),
            "tool",
            "run",
            "--quiet",
            "--isolated",
            "--from",
            f"pip-licenses=={lp.PIP_LICENSES_VERSION}",
            "pip-licenses",
            "--python",
            lp.venv_python(build / "venv"),
            "--from=mixed",
            "--format=json",
            "--with-license-file",
            "--with-notice-file",
            "--output-file",
            default_json,
        ],
        cwd=build,
    )
    capsys.readouterr()
    rc = la.main(
        [
            "--runtime",
            str(build / "runtime.txt"),
            "--marker-env",
            str(build / "marker_env.json"),
            "--python",
            str(default_json),
            "--allowlist",
            str(lp.TOOLS_DIR / "license-allowlist.toml"),
            "--notices-out",
            str(build / "NOTICES-default.txt"),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "[누락] prettytable" in err
    assert "[누락] wcwidth" in err
