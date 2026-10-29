"""라이선스 감사 파이프라인 (M0a 계획 2.8의 1~5단계).

1. 잠금 파일에서 제품 런타임 집합을 뽑는다 (`uv export`, dev 그룹·워크스페이스 자신 제외)
2. 그 집합만 별도 venv에 설치하고, 그 venv의 마커 환경을 기록한다
3. 감사 도구(pip-licenses)는 `uvx`로 다른 환경에서 돌려 대상 venv를 `--with-system`으로 스캔한다.
   기본 제외 목록(prettytable·wcwidth 등)이 제품의 공통 의존성을 빼지 않게 하려는 것이다
4. JS prod 의존성 목록 (`pnpm licenses list --prod --json`)
5. `license_audit.py`로 판정하고 THIRD_PARTY_NOTICES 초안을 쓴다

CI와 `tools/license_audit.ps1`, 테스트가 모두 이 스크립트를 부른다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import license_audit

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
PIP_LICENSES_VERSION = "5.5.5"
BUILD_MARKER = ".kookabug-license-audit"
PNPM_EMPTY_OUTPUT = "No licenses in packages found"


class PipelineError(Exception):
    pass


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise PipelineError(f"{name}을(를) PATH에서 찾을 수 없다")
    return path


def _env() -> dict[str, str]:
    # `uv run` 아래에서 불려도 대상 프로젝트·venv를 헷갈리지 않게 한다
    env = dict(os.environ)
    for key in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    return env


def _run(cmd: Sequence[str | Path], cwd: Path, capture: bool = False) -> str:
    print("$ " + " ".join(str(c) for c in cmd), flush=True)
    proc = subprocess.run(
        [str(c) for c in cmd],
        cwd=cwd,
        env=_env(),
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip() if capture else ""
        raise PipelineError(f"명령 실패 (종료 코드 {proc.returncode}): {cmd[0]} {detail}")
    return proc.stdout if capture else ""


def prepare_build_dir(build_dir: Path) -> None:
    """감사 산출물 폴더를 비운다. 이 스크립트가 만든 폴더만 지운다."""
    if build_dir.exists():
        if any(build_dir.iterdir()) and not (build_dir / BUILD_MARKER).exists():
            raise PipelineError(
                f"{build_dir}가 비어 있지 않고 감사 폴더 표시가 없다. 지우지 않는다"
            )
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)
    (build_dir / BUILD_MARKER).write_text("", encoding="utf-8")


def venv_python(venv: Path) -> Path:
    return venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"


def has_requirements(runtime_txt: Path) -> bool:
    return any(
        line.split("#", 1)[0].strip() for line in runtime_txt.read_text("utf-8").splitlines()
    )


def run_pipeline(
    project: Path,
    build_dir: Path,
    *,
    python_version: str = "3.14",
    with_js: bool = True,
    allowlist: Path = TOOLS_DIR / "license-allowlist.toml",
) -> int:
    uv = _tool("uv")
    project = project.resolve()
    build_dir = build_dir.resolve()
    prepare_build_dir(build_dir)
    runtime_txt = build_dir / "runtime.txt"
    venv = build_dir / "venv"
    marker_env = build_dir / "marker_env.json"
    py_json = build_dir / "py.json"
    js_json = build_dir / "js.json"
    notices = build_dir / "THIRD_PARTY_NOTICES.txt"

    # 1. 제품 런타임 집합
    _run(
        [
            uv,
            "export",
            "--locked",
            "--all-packages",
            "--no-dev",
            "--no-emit-workspace",
            "--no-hashes",
            "--format",
            "requirements-txt",
            "--quiet",
            "-o",
            runtime_txt,
        ],
        cwd=project,
    )

    # 2. 대상 venv: 제품 의존성만, 의존성 해석 없이 설치. 마커는 uv가 대상 Python으로 평가한다
    _run([uv, "venv", venv, "--python", python_version, "--quiet"], cwd=build_dir)
    py = venv_python(venv)
    if has_requirements(runtime_txt):
        _run(
            [uv, "pip", "install", "--python", py, "--no-deps", "--quiet", "-r", runtime_txt],
            cwd=build_dir,
        )
    marker_env.write_text(
        _run([py, "-I", TOOLS_DIR / "marker_env.py"], cwd=build_dir, capture=True),
        encoding="utf-8",
    )

    # 3. 감사 도구는 uvx의 별도 환경에서. --with-system으로 기본 제외 목록을 끈다
    _run(
        [
            uv,
            "tool",
            "run",
            "--quiet",
            "--isolated",
            "--from",
            f"pip-licenses=={PIP_LICENSES_VERSION}",
            "pip-licenses",
            "--python",
            py,
            "--with-system",
            "--from=mixed",
            "--format=json",
            "--with-license-file",
            "--with-notice-file",
            "--output-file",
            py_json,
        ],
        cwd=build_dir,
    )

    # 4. JS prod 의존성
    audit_args = [
        "--runtime",
        str(runtime_txt),
        "--marker-env",
        str(marker_env),
        "--python",
        str(py_json),
        "--allowlist",
        str(allowlist),
        "--notices-out",
        str(notices),
    ]
    if with_js:
        out = _run(
            [_tool("pnpm"), "licenses", "list", "--prod", "--json"], cwd=project, capture=True
        )
        if out.strip() == PNPM_EMPTY_OUTPUT:
            out = "{}"
        try:
            json.loads(out)
        except json.JSONDecodeError as exc:
            raise PipelineError(f"pnpm licenses 출력이 JSON이 아니다: {out[:200]!r}") from exc
        js_json.write_text(out, encoding="utf-8")
        audit_args += ["--js", str(js_json)]

    # 5. 판정
    print("$ license_audit " + " ".join(audit_args), flush=True)
    return license_audit.main(audit_args)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kookabug 라이선스 감사 파이프라인")
    parser.add_argument("--project", type=Path, default=REPO_ROOT, help="uv 프로젝트 루트")
    parser.add_argument("--build-dir", type=Path, default=REPO_ROOT / "build" / "audit")
    parser.add_argument("--python-version", default="3.14", help="대상 venv의 Python")
    parser.add_argument("--allowlist", type=Path, default=TOOLS_DIR / "license-allowlist.toml")
    parser.add_argument("--no-js", action="store_true", help="JS 의존성 감사를 건너뛴다")
    args = parser.parse_args(argv)
    try:
        return run_pipeline(
            args.project,
            args.build_dir,
            python_version=args.python_version,
            with_js=not args.no_js,
            allowlist=args.allowlist,
        )
    except PipelineError as exc:
        print(f"라이선스 감사 파이프라인 오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
