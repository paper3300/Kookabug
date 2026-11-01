"""설치 파일의 사용자 PATH 매크로를 실제 NSIS·실제 레지스트리로 확인한다 (T13 검수 1차 High·Mid).

`apps/desktop/packaging/user-path.nsh`의 매크로를 그대로 컴파일하되 `KB_ENV_KEY`를 검사 전용 임시
HKCU 키로 정한다(사용자 Environment는 읽지도 쓰지도 않는다). 더하기 → 빼기 뒤 값·형식·존재가
처음과 바이트 단위로 같아야 하고, 읽지 못하거나 한도를 넘는 값은 손대지 않아야 한다.

makensis는 electron-builder가 받은 NSIS 3.0.4.1(설치 파일 빌드에 쓰는 바로 그것)을 쓴다. 없으면
(설치 파일을 한 번도 빌드하지 않은 환경) 건너뛴다. CI installer 잡은 빌드 뒤에 이 검사를 돌린다.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import uuid
import winreg
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGING = REPO_ROOT / "apps" / "desktop" / "packaging"
USER_PATH_NSH = PACKAGING / "user-path.nsh"
BIN = r"C:\Kookabug Test\bin"
NSIS_CACHE = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "electron-builder" / "Cache" / "nsis-3.0.4.1"
)
MAKENSIS = next(iter(sorted(NSIS_CACHE.glob("*/Bin/makensis.exe"))), None)
LIMIT = 8190  # NSIS_MAX_STRLEN(8192) - 2: 이 길이 이상은 다루지 않는다

pytestmark = pytest.mark.skipif(
    MAKENSIS is None, reason="electron-builder NSIS 없음 (설치 파일을 한 번 빌드하면 생긴다)"
)


@dataclass(frozen=True)
class Value:
    exists: bool
    value: str | bytes | list[str] = ""
    kind: int | None = None


def read(key: str) -> Value:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
        try:
            value, kind = winreg.QueryValueEx(k, "Path")
        except FileNotFoundError:
            return Value(False)
    return Value(True, value, kind)


def write(key: str, v: Value) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
        if v.exists:
            assert v.kind is not None
            winreg.SetValueEx(k, "Path", 0, v.kind, v.value)
        else:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(k, "Path")


def compile_script(out: Path, env_key: str, state_key: str, body: str) -> Path:
    assert MAKENSIS is not None
    nsi = out.with_suffix(".nsi")
    nsi.write_text(
        "\n".join(
            [
                "Unicode true",
                "RequestExecutionLevel user",
                "SilentInstall silent",
                f'OutFile "{out}"',
                f'!define KB_ENV_KEY "{env_key}"',
                "!define KB_NO_BROADCAST",
                "!include LogicLib.nsh",
                "!include WinMessages.nsh",
                f'!include "{USER_PATH_NSH}"',
                "Section",
                body.replace("STATE", state_key),
                "SectionEnd",
                "",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(MAKENSIS), "-WX", "-INPUTCHARSET", "UTF8", str(nsi)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    return out


@dataclass
class Rig:
    env_key: str
    state_key: str
    add: Path
    remove: Path

    def run(self, exe: Path) -> None:
        subprocess.run([str(exe), "/S"], check=True, timeout=60)

    def state(self) -> dict[str, str]:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.state_key) as k:
                out: dict[str, str] = {}
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(k, i)
                    except OSError:
                        return out
                    out[name] = str(value)
                    i += 1
        except FileNotFoundError:
            return {}


@pytest.fixture(scope="module")
def rig(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Rig]:
    """검사 전용 임시 키 둘(PATH 자리·설치 정보 자리)과 컴파일한 더하기·빼기 실행 파일."""
    tag = uuid.uuid4().hex
    env_key = rf"Software\KookabugTestEnv_{tag}"
    state_key = rf"Software\KookabugTestState_{tag}"
    out = tmp_path_factory.mktemp("user-path")
    add = compile_script(
        out / "add.exe", env_key, state_key, f'!insertmacro kbAddToUserPath "{BIN}" "STATE"'
    )
    remove = compile_script(
        out / "remove.exe", env_key, state_key, '!insertmacro kbRemoveFromUserPath "STATE"'
    )
    winreg.CreateKey(winreg.HKEY_CURRENT_USER, env_key).Close()
    winreg.CreateKey(winreg.HKEY_CURRENT_USER, state_key).Close()
    try:
        yield Rig(env_key, state_key, add, remove)
    finally:
        for key in (env_key, state_key):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)


EXPAND, SZ = winreg.REG_EXPAND_SZ, winreg.REG_SZ

# (이름, 처음 값, 더한 뒤 기대 값 — None이면 그대로)
ROUND_TRIPS = [
    (
        "trailing_separator",
        Value(True, r"C:\Tools;", EXPAND),
        Value(True, rf"C:\Tools;;{BIN}", EXPAND),
    ),
    (
        "empty_item_kept",
        Value(True, r"C:\Tools;;C:\SDK", SZ),
        Value(True, rf"C:\Tools;;C:\SDK;{BIN}", SZ),
    ),
    (
        "reg_sz_kept",
        Value(True, r"C:\%TEST_LITERAL%\bin", SZ),
        Value(True, rf"C:\%TEST_LITERAL%\bin;{BIN}", SZ),
    ),
    (
        "expand_kept",
        Value(True, r"%USERPROFILE%\bin", EXPAND),
        Value(True, rf"%USERPROFILE%\bin;{BIN}", EXPAND),
    ),
    ("absent_value", Value(False), Value(True, BIN, EXPAND)),
    ("empty_value", Value(True, "", SZ), Value(True, BIN, SZ)),
    (
        "leading_separator",
        Value(True, r";C:\Tools", EXPAND),
        Value(True, rf";C:\Tools;{BIN}", EXPAND),
    ),
    ("long_but_fits", Value(True, "x" * 8000, EXPAND), Value(True, "x" * 8000 + ";" + BIN, EXPAND)),
    # 이미 같은 폴더(끝 \ 포함)가 있으면 더하지 않고, 빼지도 않는다
    ("already_present", Value(True, BIN + "\\;C:\\X", EXPAND), None),
    # 한도: 더한 결과가 한도를 넘으면 그대로 (검수 반례 near_limit: 끝이 ";C:"로 잘리던 것)
    ("near_limit", Value(True, "x" * 8188, EXPAND), None),
    ("exact_room_short", Value(True, "x" * (LIMIT - len(BIN) - 1), EXPAND), None),
    # 읽을 수 없는 길이 (검수 반례 over_limit: PATH 전체가 bin 하나로 바뀌고 제거 때 값이
    # 지워지던 것)
    ("over_limit", Value(True, "x" * 9000, EXPAND), None),
    (
        "way_over_limit",
        Value(True, ";".join(["C:\\p" + str(i) for i in range(4000)]), EXPAND),
        None,
    ),
    # 다른 형식은 읽지 않는다
    ("multi_sz", Value(True, ["C:\\A", "C:\\B"], winreg.REG_MULTI_SZ), None),
    ("binary", Value(True, b"C:\\A\0", winreg.REG_BINARY), None),
]


@pytest.mark.parametrize(("case", "start", "added"), ROUND_TRIPS, ids=[c[0] for c in ROUND_TRIPS])
def test_add_then_remove_restores_exact_value(
    rig: Rig, case: str, start: Value, added: Value | None
) -> None:
    write(rig.env_key, start)
    rig.run(rig.add)
    assert read(rig.env_key) == (added or start), case
    # 더했을 때만 설치 정보에 기록이 남는다 (제거는 그 기록이 있을 때만 뺀다)
    state = rig.state()
    if added is None:
        assert "PathEntry" not in state
    else:
        assert state["PathEntry"] == BIN
        assert state["PathCreated"] == ("0" if start.exists else "1")
    rig.run(rig.remove)
    assert read(rig.env_key) == start, case


def test_remove_keeps_items_added_by_user_after_install(rig: Rig) -> None:
    """설치 뒤 사용자가 PATH를 고쳤어도 우리가 붙인 항목과 그 구분자만 뺀다."""
    start = Value(True, r"C:\Tools;", EXPAND)
    write(rig.env_key, start)
    rig.run(rig.add)
    write(rig.env_key, Value(True, rf"C:\New;C:\Tools;;{BIN};C:\Later", EXPAND))
    rig.run(rig.remove)
    assert read(rig.env_key) == Value(True, r"C:\New;C:\Tools;;C:\Later", EXPAND)
    # 사용자가 이미 지웠으면 아무것도 바꾸지 않는다
    write(rig.env_key, Value(True, r"C:\Only", SZ))
    rig.run(rig.add)
    write(rig.env_key, Value(True, r"C:\Only", SZ))
    rig.run(rig.remove)
    assert read(rig.env_key) == Value(True, r"C:\Only", SZ)


def test_remove_without_install_record_changes_nothing(rig: Rig) -> None:
    """이 설치가 더하지 않은 항목(설치 정보에 기록 없음)은 같은 경로라도 빼지 않는다."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rig.state_key, 0, winreg.KEY_SET_VALUE) as k:
        for name in ("PathEntry", "PathCreated"):
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(k, name)
    start = Value(True, rf"C:\Tools;{BIN}", EXPAND)
    write(rig.env_key, start)
    rig.run(rig.remove)
    assert read(rig.env_key) == start


def test_scripts_never_name_the_real_environment_key() -> None:
    """매크로는 레지스트리 키를 KB_ENV_KEY로만 쓴다 (검사가 임시 키로 바꿀 수 있고, 매크로만 떼어
    쓰는 스크립트가 실제 사용자 Environment를 고치지 않는다)."""
    for path in (USER_PATH_NSH, PACKAGING / "installer.nsh"):
        text = path.read_text(encoding="utf-8")
        assert 'HKCU "Environment"' not in text, path
    nsh = USER_PATH_NSH.read_text(encoding="utf-8")
    assert '!define KB_ENV_KEY "Environment"' in nsh
    assert nsh.count('HKCU "${KB_ENV_KEY}"') >= 4
