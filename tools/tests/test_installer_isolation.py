"""무인 설치 검사가 이 PC의 실제 설치를 건드리지 않는가 (M1 검수 T13-1 #1, M2 T13 NSIS).

테스트 설치는 제품과 appId·이름·GUID(제거 등록 키)·기본 폴더가 모두 다른 테스트 전용 판만 하고, HKCU
제거 등록 전체를 앞뒤로 비교한다. 실제 설치 없이 레지스트리·설치를 가짜로 바꿔 끼워 본다."""

import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from installer import build, smoke

PRODUCT_KEY = build.PRODUCT.uninstall_key
TEST_KEY = build.TEST.uninstall_key


def test_test_variant_differs_from_product_in_every_identity() -> None:
    p, t = build.PRODUCT, build.TEST
    for field in ("app_guid", "app_name", "app_id", "dir_name", "file_prefix", "uninstall_key"):
        assert getattr(p, field) != getattr(t, field), field
    assert t.dir_name not in ("Kookabug",) and t.app_name.startswith("Kookabug")
    assert build.setup_name("1.0", t) == "kookabug-setup-test-1.0"
    assert build.setup_name("1.0") == "kookabug-setup-1.0"
    # 설정 파일은 판 정의만 쓴다 (제품 appId·이름·GUID를 박아 두지 않는다. build.py가 판마다 넣는다)
    for text in (
        build.EB_CONFIG.read_text(encoding="utf-8"),
        build.NSIS_INCLUDE.read_text(encoding="utf-8"),
    ):
        for v in (p, t):
            assert v.app_guid not in text and v.app_id not in text
    # 기본 설치 폴더 = 판 이름 (installer.nsh가 APP_FILENAME을 PRODUCT_NAME으로)
    assert '!define APP_FILENAME "${PRODUCT_NAME}"' in build.NSIS_INCLUDE.read_text("utf-8")


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
            smoke,
            "uninstaller",
            lambda root: root / build.TEST.uninstaller if root.exists() else None,
        )
        monkeypatch.setattr(smoke, "smoke_installed", lambda report: None)
        monkeypatch.setattr(smoke, "path_has", lambda paths, folder: True)
        monkeypatch.setattr(smoke, "user_path", lambda: "")
        monkeypatch.setattr(smoke, "removed_step", lambda root: (not root.exists(), "fake"))
        monkeypatch.setattr(smoke, "hkcu_values", self.hkcu_values)
        monkeypatch.setattr(smoke, "start_menu", lambda: self.menu)
        monkeypatch.setattr(smoke, "start_product_standin", self.start_standin)
        monkeypatch.setattr(
            smoke,
            "shortcut_target",
            lambda link: (
                (str(self.installed / build.TEST.app_exe),) * 2 if self.installed else ("", "")
            ),
        )

    def start_standin(self, target: Path) -> Any:
        machine = self

        class Fake:
            exe = target.with_name(target.name + "2") / build.PRODUCT.app_exe
            proc = type("P", (), {"pid": 0})()

            @property
            def alive(self) -> bool:
                return not machine.kills_product

            def stop(self) -> None:
                machine.standin_stopped = True

        return Fake()

    kills_product = False
    standin_stopped = False

    menu = Path("Z:/no-start-menu")
    installed: Path | None = None

    def hkcu_values(self, path: str) -> dict[str, str] | None:
        """설치 정보 키 (`Software\\<GUID>`): 설치한 동안만 있다."""
        if path == build.TEST.install_key and self.installed is not None:
            return {"InstallLocation": str(self.installed)}
        return None

    def install(self, setup: Path, target: Path, log: Path) -> None:
        self.installs.append(target)
        target.mkdir(parents=True)
        self.installed = target
        self.menu = target / "menu"
        self.menu.mkdir()
        (self.menu / build.TEST.shortcut).write_text("lnk", encoding="utf-8")
        uninstaller = target / build.TEST.uninstaller
        self.entries[TEST_KEY] = {"UninstallString": f'"{uninstaller}" /currentuser'}

    def uninstall(self, root: Path, **_: Any) -> bool:
        (self.menu / build.TEST.shortcut).unlink()
        self.menu.rmdir()
        root.rmdir()
        if not self.uninstall_leaves:
            del self.entries[TEST_KEY]
            self.installed = None
        if self.uninstall_also_drops is not None:
            self.entries.pop(self.uninstall_also_drops, None)
        return True


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
        "isolation.product_standin": True,
        "install": True,
        "isolation.after_install": True,
        "install.registration": True,
        "install.path": True,
        "install.shortcut": True,
        "uninstall": True,
        "isolation.after_uninstall": True,
        "uninstall.clean": True,
        "uninstall.registry": True,
        "path.guard": True,
    }
    assert machine.entries == {PRODUCT_KEY: product}
    assert machine.standin_stopped


def test_test_install_that_kills_product_app_fails(
    tmp_path: Path, setup_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """테스트 판 설치·제거가 실행 중인 제품 앱(대역)을 끄면 실패로 보인다 (T13 검수 1차 High)."""
    machine = FakeMachine({}, product="Kookabug Test")
    machine.patch(monkeypatch)
    original = machine.install

    def install_and_kill(setup: Path, target: Path, log: Path) -> None:
        original(setup, target, log)
        machine.kills_product = True  # 이름만 보고 Kookabug.exe를 끄는 고장

    monkeypatch.setattr(smoke, "install", install_and_kill)
    report = smoke.run_all(setup_file, tmp_path / "target", log=tmp_path / "log")
    ids = _ids(report)
    assert ids["isolation.after_install"] is False and ids["isolation.after_uninstall"] is False
    assert not report.ok and machine.standin_stopped


def test_user_path_guard_restores_exact_value_and_type(tmp_path: Path) -> None:
    """실제 사용자 PATH를 건드리는 검사의 보호막: 값·형식·존재를 백업하고, 달라지면 되돌린다.
    검사 전용 임시 HKCU 키로 확인한다 (사용자 Environment는 건드리지 않는다)."""
    import uuid
    import winreg

    key = rf"Software\KookabugGuardTest_{uuid.uuid4().hex}"
    winreg.CreateKey(winreg.HKEY_CURRENT_USER, key).Close()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "Path", 0, winreg.REG_SZ, "C:\\Tools;;C:\\%X%;")
        saved = smoke.read_user_path(key)
        assert saved == smoke.RegValue(True, "C:\\Tools;;C:\\%X%;", winreg.REG_SZ)

        guard = smoke.UserPathGuard(key)
        assert guard.check() is True and not guard.restored  # 그대로면 쓰지 않는다
        for broken in (
            smoke.RegValue(True, "C:\\Tools;C:\\%X%", winreg.REG_SZ),  # 빈 항목·끝 구분자 잃음
            smoke.RegValue(True, "C:\\Tools;;C:\\%X%;", winreg.REG_EXPAND_SZ),  # 형식만 바뀜
            smoke.RegValue(False),  # 값이 지워짐
        ):
            guard = smoke.UserPathGuard(key)
            smoke.write_user_path(broken, key)
            assert guard.check() is False, broken
            assert guard.restored and "되돌림=True" in guard.detail
            assert smoke.read_user_path(key) == saved

        # 원래 없던 값을 누가 만들면 지워서 되돌린다
        smoke.write_user_path(smoke.RegValue(False), key)
        guard = smoke.UserPathGuard(key)
        smoke.write_user_path(smoke.RegValue(True, "C:\\x", winreg.REG_EXPAND_SZ), key)
        with guard:
            pass
        assert guard.restored and smoke.read_user_path(key) == smoke.RegValue(False)
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)


def test_broadcast_result_argument_is_pointer_sized() -> None:
    """SendMessageTimeoutW의 마지막 인자는 PDWORD_PTR(포인터 크기)다. 검수 반례: DWORD(4바이트)를
    넘기면 Win64에서 옆 4바이트까지 덮였다 (T13 검수 2차 Low). 선언과, 실제 호출이 결과 칸 밖을
    건드리지 않는지 본다 (설정 변경 없이 바탕 화면 창에 WM_NULL만 보낸다)."""
    import ctypes
    from ctypes import wintypes

    fn = smoke.SendMessageTimeoutW
    assert fn.argtypes is not None and len(fn.argtypes) == 7
    result_type = fn.argtypes[-1]
    assert result_type is ctypes.POINTER(ctypes.c_size_t)
    assert ctypes.sizeof(ctypes.c_size_t) == ctypes.sizeof(ctypes.c_void_p)

    class Guarded(ctypes.Structure):
        _fields_ = [("value", ctypes.c_size_t), ("guard", wintypes.DWORD)]

    probe = Guarded(0, 0xAABBCCDD)
    user32 = ctypes.WinDLL("user32")
    user32.GetDesktopWindow.restype = wintypes.HWND
    result = ctypes.cast(ctypes.pointer(probe), ctypes.POINTER(ctypes.c_size_t))
    fn(user32.GetDesktopWindow(), 0, 0, 0, smoke.SMTO_ABORTIFHUNG, 1000, result)
    assert probe.guard == 0xAABBCCDD
    # 결과를 쓰지 않는 실제 도우미는 NULL을 넘긴다 (WM_SETTINGCHANGE 알림은 환경을 바꾸지 않는다)
    smoke.broadcast_environment()


def test_uninstall_waits_until_registration_and_shortcut_are_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NSIS 제거 프로그램은 폴더를 지운 뒤에 바로 가기·등록 키를 지운다. 폴더가 사라진 순간이 아니라
    그 판의 정리가 다 끝날 때까지 기다린다 (T13 검수 1차 Mid: 전체 pytest의 간헐 실패)."""
    variant = build.TEST
    root = tmp_path / "install"
    root.mkdir()
    (root / variant.uninstaller).write_bytes(b"MZ")
    menu = tmp_path / "menu"
    menu.mkdir()
    (menu / variant.shortcut).write_text("lnk", encoding="utf-8")
    state = {"entries": {variant.uninstall_key: {}}, "install_key": {"InstallLocation": str(root)}}
    monkeypatch.setattr(smoke, "uninstall_entries", lambda: dict(state["entries"]))
    monkeypatch.setattr(
        smoke,
        "hkcu_values",
        lambda path: state["install_key"] if path == variant.install_key else None,
    )
    monkeypatch.setattr(smoke, "start_menu", lambda: menu)
    finished: list[float] = []

    def late_cleanup(delay: float) -> None:
        time.sleep(delay)
        (menu / variant.shortcut).unlink()
        state["entries"] = {}
        state["install_key"] = None
        finished.append(time.monotonic())

    def fake_run(cmd: Any, **_: Any) -> subprocess.CompletedProcess[str]:
        # 제거 프로그램이 곧바로 끝나고(임시 폴더의 사본이 이어감) 폴더가 먼저 사라진다
        shutil.rmtree(root)
        threading.Thread(target=late_cleanup, args=(1.0,), daemon=True).start()
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)
    assert smoke.uninstall(root, variant=variant, timeout_s=20) is True
    assert finished and time.monotonic() >= finished[0]
    assert smoke.variant_cleaned(variant, root)

    # 정리가 끝나지 않으면 기한에 False (폴더만 사라진 것을 완료로 보지 않는다)
    root.mkdir()
    (root / variant.uninstaller).write_bytes(b"MZ")
    state["entries"] = {variant.uninstall_key: {}}

    def never(cmd: Any, **_: Any) -> subprocess.CompletedProcess[str]:
        shutil.rmtree(root)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(smoke.subprocess, "run", never)
    assert smoke.uninstall(root, variant=variant, timeout_s=1.5) is False


@pytest.mark.parametrize(
    ("fault", "message"),
    [("drops_product", "사라진 키 ['8B1C6E52"), ("leaves_test_key", "남은 키 ['5E0D7A3C")],
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


def _short_path(path: Path) -> str:
    """8.3 짧은 이름 (`PAPER3~1` 꼴). 볼륨이 짧은 이름을 만들지 않으면 긴 이름 그대로."""
    import ctypes

    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, len(buf))
    return buf.value if 0 < n < len(buf) else str(path)


def test_shortcut_same_file_ignores_short_name_alias(tmp_path: Path) -> None:
    """바로 가기 대상이 긴 이름, 설치 폴더가 짧은 이름(TEMP가 8.3)이어도 같은 파일이다
    (검수 T9-1 TEMP 판정)."""
    folder = tmp_path / "설치 폴더 공백 한글 long-name-folder"
    folder.mkdir()
    exe = folder / "KookabugTest.exe"
    exe.write_bytes(b"MZ")
    short = _short_path(exe)
    if short == str(exe):
        pytest.skip("이 볼륨은 8.3 짧은 이름을 만들지 않는다")
    assert short.lower() != str(exe).lower()
    assert smoke.same_file(short, exe)
    assert smoke.same_file(str(exe), Path(short))
    assert not smoke.same_file(str(folder / "other.exe"), exe)
    assert not smoke.same_file("", exe)
