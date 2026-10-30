"""무인 설치 검사가 이 PC의 실제 설치를 건드리지 않는가 (검수 T13-1 #1).

테스트 설치는 제품과 AppId·이름·기본 폴더·제거 등록 이름이 모두 다른 테스트 전용 판만 하고, HKCU
제거 등록 전체를 앞뒤로 비교한다. 실제 설치 없이 레지스트리·설치를 가짜로 바꿔 끼워 본다."""

import sys
from pathlib import Path
from typing import Any

import pytest

from installer import build, smoke

PRODUCT_KEY = build.PRODUCT.uninstall_key
TEST_KEY = build.TEST.uninstall_key


def test_test_variant_differs_from_product_in_every_identity() -> None:
    p, t = build.PRODUCT, build.TEST
    for field in ("app_guid", "app_name", "dir_name", "file_prefix", "uninstall_key"):
        assert getattr(p, field) != getattr(t, field), field
    assert t.dir_name not in ("Kookabug",) and t.app_name.startswith("Kookabug")
    assert build.setup_name("1.0", t) == "kookabug-setup-test-1.0"
    assert build.setup_name("1.0") == "kookabug-setup-1.0"
    # .iss는 판 정의만 쓴다 (제품 AppId·이름·폴더를 박아 두지 않는다)
    iss = build.ISS.read_text(encoding="utf-8-sig")
    assert p.app_guid not in iss and t.app_guid not in iss
    for line in (
        "AppId={{{#AppGuid}}",
        "AppName={#AppName}",
        "VersionInfoProductName={#AppName}",
        r"DefaultDirName={localappdata}\Programs\{#DirName}",
        "UninstallDisplayName={#AppName} {#AppVersion}",
    ):
        assert line in iss, line


def test_setup_product_name_reads_version_info(tmp_path: Path) -> None:
    assert smoke.setup_product_name(Path(sys.base_prefix) / "python.exe") == "Python"
    plain = tmp_path / "plain.exe"
    plain.write_bytes(b"MZ")
    assert smoke.setup_product_name(plain) is None


class FakeMachine:
    """HKCU 제거 등록과 설치·제거를 흉내 낸다. `uninstall_also_drops`는 제거가 다른 키까지 지우는
    고장(검수 반례: 같은 AppId 덮어쓰기로 기존 등록을 잃음)."""

    def __init__(self, entries: dict[str, dict[str, str]], product: str) -> None:
        self.entries = entries
        self.product = product
        self.installs: list[Path] = []
        self.uninstall_also_drops: str | None = None
        self.uninstall_leaves = False

    def patch(self, monkeypatch: pytest.MonkeyPatch, report_steps: bool = True) -> None:
        monkeypatch.setattr(
            smoke, "uninstall_entries", lambda: {k: dict(v) for k, v in self.entries.items()}
        )
        monkeypatch.setattr(smoke, "setup_product_name", lambda setup: self.product)
        monkeypatch.setattr(smoke, "install", self.install)
        monkeypatch.setattr(smoke, "uninstall", self.uninstall)
        monkeypatch.setattr(
            smoke, "uninstaller", lambda root: root / "unins000.exe" if root.exists() else None
        )
        monkeypatch.setattr(smoke, "smoke_installed", lambda report: None)
        monkeypatch.setattr(smoke, "path_has", lambda paths, folder: True)
        monkeypatch.setattr(smoke, "user_path", lambda: "")
        monkeypatch.setattr(smoke, "removed_step", lambda root: (not root.exists(), "fake"))

    def install(self, setup: Path, target: Path, log: Path) -> None:
        self.installs.append(target)
        target.mkdir(parents=True)
        self.entries[TEST_KEY] = {"InstallLocation": str(target) + "\\"}

    def uninstall(self, root: Path, **_: Any) -> None:
        root.rmdir()
        if not self.uninstall_leaves:
            del self.entries[TEST_KEY]
        if self.uninstall_also_drops is not None:
            self.entries.pop(self.uninstall_also_drops, None)


@pytest.fixture
def setup_file(tmp_path: Path) -> Path:
    path = tmp_path / "kookabug-setup-test-0.1.0.exe"
    path.write_bytes(b"MZ")
    return path


def _ids(report: smoke.SmokeReport) -> dict[str, bool]:
    return {s.id: s.ok for s in report.steps}


def test_run_all_refuses_product_setup_without_installing(
    tmp_path: Path, setup_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine = FakeMachine({PRODUCT_KEY: {"InstallLocation": "C:\\real\\"}}, product="Kookabug")
    machine.patch(monkeypatch)
    report = smoke.run_all(setup_file, tmp_path / "target", log=tmp_path / "log")
    assert _ids(report) == {"setup.variant": False}
    assert "설치하지 않는다" in report.steps[0].detail
    assert machine.installs == []

    # 제품 판을 명시해도, 제품이 이미 등록돼 있으면 덮어쓰지 않는다
    report = smoke.run_all(
        setup_file, tmp_path / "target", log=tmp_path / "log", variant=build.PRODUCT
    )
    assert _ids(report) == {"setup.variant": False}
    assert f"{PRODUCT_KEY}가 이미 등록돼 있다" in report.steps[0].detail
    assert machine.installs == []


def test_run_all_refuses_when_test_key_left_over(
    tmp_path: Path, setup_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine = FakeMachine({TEST_KEY: {"InstallLocation": "C:\\old\\"}}, product="Kookabug Test")
    machine.patch(monkeypatch)
    report = smoke.run_all(setup_file, tmp_path / "target", log=tmp_path / "log")
    assert _ids(report) == {"setup.variant": False} and machine.installs == []


def test_existing_product_registration_survives_test_install(
    tmp_path: Path, setup_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """검수 반례의 모양: 제품이 설치된 PC에서 스모크를 돌려도 제품 등록이 그대로다."""
    product = {"InstallLocation": "C:\\Users\\me\\AppData\\Local\\Programs\\Kookabug\\"}
    machine = FakeMachine({PRODUCT_KEY: dict(product)}, product="Kookabug Test")
    machine.patch(monkeypatch)
    report = smoke.run_all(setup_file, tmp_path / "target", log=tmp_path / "log")
    assert report.ok, report.to_json()
    assert _ids(report) == {
        "setup.variant": True,
        "install": True,
        "install.registration": True,
        "install.path": True,
        "uninstall": True,
        "uninstall.clean": True,
        "uninstall.registry": True,
    }
    assert machine.entries == {PRODUCT_KEY: product}


@pytest.mark.parametrize(
    ("fault", "message"),
    [("drops_product", "사라진 키 ['{8B1C6E52"), ("leaves_test_key", "남은 키 ['{5E0D7A3C")],
)
def test_registry_trace_or_loss_fails(
    tmp_path: Path,
    setup_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    message: str,
) -> None:
    machine = FakeMachine({PRODUCT_KEY: {"InstallLocation": "C:\\real\\"}}, product="Kookabug Test")
    if fault == "drops_product":
        machine.uninstall_also_drops = PRODUCT_KEY
    else:
        machine.uninstall_leaves = True
    machine.patch(monkeypatch)
    report = smoke.run_all(setup_file, tmp_path / "target", log=tmp_path / "log")
    step = next(s for s in report.steps if s.id == "uninstall.registry")
    assert not step.ok and message in step.detail
    assert not report.ok


def test_install_that_touches_other_keys_fails_registration_step(
    tmp_path: Path, setup_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """설치가 테스트 키 말고 다른 등록(예: 같은 AppId의 제품 키)을 바꾸면 바로 실패로 보인다."""
    machine = FakeMachine({PRODUCT_KEY: {"InstallLocation": "C:\\real\\"}}, product="Kookabug Test")
    machine.patch(monkeypatch)
    original = machine.install

    def overwrite(setup: Path, target: Path, log: Path) -> None:
        original(setup, target, log)
        machine.entries[PRODUCT_KEY] = {"InstallLocation": str(target) + "\\"}

    monkeypatch.setattr(smoke, "install", overwrite)
    report = smoke.run_all(setup_file, tmp_path / "target", log=tmp_path / "log")
    step = next(s for s in report.steps if s.id == "install.registration")
    assert not step.ok and f"바뀐 키 ['{PRODUCT_KEY}']" in step.detail
