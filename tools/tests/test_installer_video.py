"""설치본의 영상 (구현 계획 M3 2.5, T5, 검수 M9).

설치 파일(테스트 전용 판)을 무인 설치한 트리에서:
- 최종 트리 감사가 새 네이티브 파일 없이 통과한다 (영상은 OS 구성요소 + 이미 감사한 cv2.pyd)
- NOTICES에 "OS 구성요소 사용" 절이 있다
- 설치본 `doctor --profile headless`에 "영상 인코더" 항목이 있다
- 영상 사용 불가를 주입해도(`KOOKABUG_VIDEO_TEST`) 설치본 runner의 헤드리스 그래프와
  `Kookabug.exe --smoke`가 정상이다

설치 파일은 `KOOKABUG_INSTALLER`(CI installer 잡) 또는 세션에 한 번 빌드한 것
(`installer_test_setup`).
"""

import json
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from installer import build, smoke

pytestmark = [pytest.mark.packaging, pytest.mark.timeout(1800)]

UNAVAILABLE = json.dumps({"encoder": "msmf", "msmf": {"mf_dlls": ["kb-missing-mfplat.dll"]}})


@pytest.fixture(scope="module")
def root(installer_test_setup: Path) -> Iterator[Path]:
    base = Path(tempfile.mkdtemp(prefix="kb-video-"))
    target = base / "설치 폴더"
    guard = smoke.UserPathGuard()
    try:
        smoke.install(installer_test_setup, target, base / "install.log")
        yield target
    finally:
        if smoke.uninstaller(target) is not None:
            smoke.uninstall(target)
        guard.check()
        shutil.rmtree(base, ignore_errors=True)


def test_installed_tree_audit_passes_without_new_native_files(root: Path) -> None:
    ok, detail = smoke.audit_step(root)
    assert ok, detail
    site = root / "python" / "Lib" / "site-packages"
    assert not list(site.glob("cv2/opencv_videoio_ffmpeg*.dll"))


def test_notices_have_os_components_section(root: Path) -> None:
    text = (root / build.NOTICES).read_text(encoding="utf-8")
    assert "# OS 구성요소 사용" in text and "Windows Media Foundation" in text


def test_installed_doctor_reports_video_encoder(root: Path) -> None:
    env = smoke.python_free_env(root)
    proc = smoke.run_cli(root, env, ["doctor", "--profile", "headless", "--json"], cwd=root)
    body = json.loads(proc.stdout)
    checks = {c["id"]: c for c in body["checks"]}
    video = checks["video.encoder"]
    assert video["ok"] is True
    assert video["detail"].startswith(("영상 사용 가능", "영상 사용 불가")), video
    assert proc.returncode == 0 and body["ok"] is True, proc.stdout


def test_installed_tree_runs_with_video_unavailable(root: Path) -> None:
    env = smoke.python_free_env(root)
    env["KOOKABUG_VIDEO_TEST"] = UNAVAILABLE
    base = Path(tempfile.mkdtemp(prefix="kb-video-ws-"))
    try:
        # 가짜 플랫폼 사양이 예제 폴더의 장면 표(`../frames`)를 가리키므로 예제 폴더째 복사한다
        example = root / smoke.WORKSPACE
        shutil.copytree(example.parent, base / "example", ignore=shutil.ignore_patterns("runs"))
        workspace = base / "example" / example.name
        proc = smoke.run_cli(
            root,
            env,
            ["run", smoke.SMOKE_GRAPH, "--platform-fake", smoke.FAKE_PLATFORM, "--json"],
            cwd=workspace,
        )
        body = json.loads(proc.stdout)
        assert proc.returncode == 0 and body["verdict"] == "pass", proc.stdout + proc.stderr
        run_json = json.loads((Path(body["run_dir"]) / "run.json").read_text(encoding="utf-8"))
        assert run_json["video"]["status"] == "unavailable"
        assert run_json["video"]["reason"] == "mf_missing"
    finally:
        shutil.rmtree(base, ignore_errors=True)
    # 앱 기동(daemon·session.hello·graph.open·무수정 graph.save)도 영상 없이 정상
    ok, detail = smoke.app_step(root, env)
    assert ok, detail
