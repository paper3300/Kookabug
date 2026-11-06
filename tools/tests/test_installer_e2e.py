"""설치 파일 무인 설치 → 최종 트리 감사 → CLI·앱 스모크 → 제거 (구현 계획 M1 2.12, M2 2.14 T13).

설치 파일은 **테스트 전용 판**(제품과 다른 appId·이름·GUID·기본 폴더)이다.
`KOOKABUG_INSTALLER`(CI installer 잡이 `--test-setup`으로 빌드한 것)를 쓰고, 없으면 세션에 한 번
빌드한다(`installer_test_setup`, M1 인수 4와 같이 씀 — Node·pnpm·Visual Studio VC++ 재배포 파일·
OCR 모델·네트워크 필요). 제품 판을 넘기면 설치하지 않고 실패한다.

모듈에서 한 번 설치·스모크·제거하고(`run`), 세 검사가 그 결과를 나눠 본다. 사용자 PATH에 테스트
폴더의 bin을 잠시 더하고, 설치 흔적(HKCU 제거 등록 전체·`Software\\<GUID>`·시작 메뉴 바로 가기·
설치 파일 사본 폴더·사용자 PATH)은 끝에 처음과 똑같아야 한다 (이 PC의 실제 Kookabug를 건드리지
않음). 결과 JSON은 `KOOKABUG_SMOKE_JSON`에.
"""

import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from installer import build, smoke

pytestmark = [pytest.mark.packaging, pytest.mark.timeout(1800)]

STEPS = [
    "setup.variant",
    "isolation.product_standin",
    "install",
    "isolation.after_install",
    "install.registration",
    "install.path",
    "install.shortcut",
    "audit.final_tree",
    "licenses.notices",
    "packaging.app_bundle",
    "env.python_free",
    "cli.version",
    "cli.doctor_headless",
    "cli.smoke_graph",
    "cli.video",
    "recorder.hook",
    "cli.mcp",
    "app.smoke",
    "dll.check",
    "uninstall",
    "isolation.after_uninstall",
    "uninstall.clean",
    "uninstall.registry",
    "path.guard",
]


@dataclass
class Run:
    report: smoke.SmokeReport
    target: Path
    before: dict[str, Any]
    after: dict[str, Any]

    def body(self) -> str:
        return json.dumps(self.report.to_json(), ensure_ascii=False, indent=2)

    def ok(self, *ids: str) -> None:
        for step_id in ids:
            step = self.report.get(step_id)
            assert step is not None and step.ok, f"{step_id}\n{self.body()}"


@pytest.fixture(scope="module")
def run(installer_test_setup: Path) -> Iterator[Run]:
    # 설치 폴더 + 가장 긴 상대 경로가 MAX_PATH 안에 들도록 pytest 임시 폴더 대신 짧은 경로
    base = Path(tempfile.mkdtemp(prefix="kb-e2e-"))
    target = base / "설치 폴더 공백 한글"
    before = smoke.traces(build.TEST)
    # 실제 사용자 PATH 보호: 백업 → 끝나면 바이트·형식 단위 비교 → 다르면 되돌림
    # (run_all 안에도 있다)
    guard = smoke.UserPathGuard()
    try:
        report = smoke.run_all(installer_test_setup, target, log=base / "install.log")
    finally:
        if smoke.uninstaller(target) is not None:  # 중간에 죽었으면 여기서라도 제거
            smoke.uninstall(target)
        guard.check()
    after = smoke.traces(build.TEST)
    assert guard.same, guard.detail
    if out := os.environ.get("KOOKABUG_SMOKE_JSON"):
        Path(out).write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=2) + "\n", "utf-8"
        )
    sizes = report.sizes
    install = report.get("install")
    print(
        f"\n설치 파일 {sizes['setup_bytes'] / 2**20:.1f} MiB, "
        f"설치본 {sizes.get('install_bytes', 0) / 2**20:.1f} MiB "
        f"({sizes.get('install_files', 0)}개 파일), "
        f"설치 {install.seconds if install else '-'} s"
    )
    try:
        yield Run(report, target, before, after)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_silent_install_test_edition_doctor_headless_and_app_smoke(run: Run) -> None:
    """공백·한글 경로 무인 설치 → Python 없는 환경의 `doctor --profile headless`·헤드리스 그래프 →
    `Kookabug.exe --smoke`(daemon·session.hello·graph.open·무수정 graph.save, 종료 코드 0)."""
    assert [s.id for s in run.report.steps] == STEPS, run.body()
    run.ok(
        "setup.variant",
        "isolation.product_standin",
        "isolation.after_install",
        "install",
        "install.registration",
        "install.path",
        "install.shortcut",
        "env.python_free",
        "cli.version",
        "cli.doctor_headless",
        "cli.smoke_graph",
        "cli.video",
        "recorder.hook",
        "cli.mcp",
        "app.smoke",
        "dll.check",
    )
    assert run.report.ok, run.body()
    # 영상 단계는 설치본 Python으로 인코더를 따로 탐지했다 (탐지 실패를 인코더 부재로 넘기지 않음)
    video = run.report.get("cli.video")
    assert video is not None and "probe_failed" not in video.detail, run.body()
    assert "인코더 탐지 True" in video.detail or "인코더 없음" in video.detail, run.body()


def test_uninstall_restores_hkcu(run: Run) -> None:
    """제거가 끝난 뒤(폴더·등록·바로 가기 정리까지 기다림) 설치 폴더가 없고 HKCU 제거 등록·설치 정보
    키·바로 가기·PATH(값·형식·존재)가 처음과 같다. 실행 중인 제품 판 대역은 설치·제거 뒤에도
    산다."""
    run.ok(
        "uninstall",
        "isolation.after_uninstall",
        "uninstall.clean",
        "uninstall.registry",
        "path.guard",
    )
    assert not run.target.exists()
    assert build.TEST.uninstall_key not in run.after["uninstall"]
    assert run.after == run.before


def test_final_tree_audit_on_installed(run: Run) -> None:
    """설치된 트리 그대로: 최종 트리 감사(Electron 표·ffmpeg 고정 바이너리 예외), NOTICES 절,
    앱 번들(E2E 검사 훅 없음·kookabug-platform 포함)."""
    run.ok("audit.final_tree", "licenses.notices", "packaging.app_bundle")
    audit = run.report.get("audit.final_tree")
    assert audit is not None and "ffmpeg.dll (electron" in audit.detail
