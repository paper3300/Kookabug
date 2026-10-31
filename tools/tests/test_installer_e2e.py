"""설치 파일 무인 설치 → 최종 트리 감사 → 헤드리스 스모크 → 제거 (구현 계획 M1 2.12, T13).

설치 파일은 **테스트 전용 판**(제품과 다른 AppId·이름·기본 폴더·제거 등록 이름)이다.
`KOOKABUG_INSTALLER`(CI installer 잡이 `--test-setup`으로 빌드한 것)를 쓰고, 없으면 세션에 한 번
빌드한다(`installer_test_setup`, M1 인수 4와 같이 씀 — Inno Setup 6·Visual Studio VC++ 재배포 파일·
OCR 모델·네트워크 필요). 제품 판을 넘기면 설치하지 않고
실패한다. 사용자 PATH에 테스트 폴더의 bin을 잠시 더하고, HKCU 제거 등록은 끝에 처음과 똑같아야 한다
(테스트 흔적 없음, 이 PC의 실제 Kookabug 등록을 건드리지 않음). 결과 JSON은 `KOOKABUG_SMOKE_JSON`에.
"""

import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from installer import build, smoke

pytestmark = [pytest.mark.packaging, pytest.mark.timeout(1800)]

STEPS = [
    "setup.variant",
    "install",
    "install.registration",
    "install.path",
    "audit.final_tree",
    "licenses.notices",
    "env.python_free",
    "cli.version",
    "cli.doctor_headless",
    "cli.smoke_graph",
    "dll.check",
    "uninstall",
    "uninstall.clean",
    "uninstall.registry",
]


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """설치 폴더 + 가장 긴 상대 경로가 MAX_PATH 안에 들도록 pytest 임시 폴더 대신 짧은 경로."""
    base = Path(tempfile.mkdtemp(prefix="kb-e2e-"))
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_silent_install_space_korean_path_audit_smoke_and_uninstall(
    installer_test_setup: Path, short_dir: Path
) -> None:
    target = short_dir / "설치 폴더 공백 한글"
    before = smoke.uninstall_entries()
    try:
        report = smoke.run_all(installer_test_setup, target, log=short_dir / "install.log")
    finally:
        if smoke.uninstaller(target) is not None:  # 중간에 죽었으면 여기서라도 제거
            smoke.uninstall(target)
    # 테스트 판의 제거 등록은 남지 않고, 다른 제거 등록(실제 설치 포함)은 그대로다
    after = smoke.uninstall_entries()
    assert build.TEST.uninstall_key not in after
    assert after == before
    body = report.to_json()
    if out := os.environ.get("KOOKABUG_SMOKE_JSON"):
        Path(out).write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", "utf-8")
    sizes = report.sizes
    print(
        f"\n설치 파일 {sizes['setup_bytes'] / 2**20:.1f} MiB, "
        f"설치본 {sizes.get('install_bytes', 0) / 2**20:.1f} MiB "
        f"({sizes.get('install_files', 0)}개 파일), "
        f"설치 {next(s.seconds for s in report.steps if s.id == 'install')} s"
    )
    assert [s.id for s in report.steps] == STEPS, json.dumps(body, ensure_ascii=False, indent=2)
    assert report.ok, json.dumps(body, ensure_ascii=False, indent=2)
    assert not target.exists()
