"""GitHub Actions 워크플로 파일이 YAML로 읽히고 잡이 그대로 있다 (M3 T5 검수 High).

파싱되지 않는 워크플로는 잡을 하나도 돌리지 않는다 — push한 뒤에야 알게 되므로 여기서 막는다.
`run:` 단계의 여러 줄 명령은 YAML이 줄을 접어 원문과 달라질 수 있어, 파이썬 한 줄 명령 대신 모듈·
스크립트를 부른다.
"""

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
JOBS = {"python", "codegen", "desktop", "desktop-probe", "installer", "licenses"}


def test_workflows_parse_as_yaml() -> None:
    assert WORKFLOWS
    for path in WORKFLOWS:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict) and isinstance(data.get("jobs"), dict), path
        for name, job in data["jobs"].items():
            for step in job.get("steps", []):
                assert isinstance(step, dict), (path.name, name, step)


def test_ci_jobs_kept() -> None:
    data = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    assert set(data["jobs"]) == JOBS


def test_video_probe_summary_step_runs() -> None:
    # ci.yml의 영상 인코더 요약 단계가 부르는 진입점 (Markdown 제목 + 한 줄)
    data = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    runs = [s.get("run", "") for s in data["jobs"]["python"]["steps"]]
    assert any("-m kookabug_platform.video" in run for run in runs)
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "kookabug_platform.video"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert lines[0] == "### 영상 인코더" and lines[2].startswith("- ")
