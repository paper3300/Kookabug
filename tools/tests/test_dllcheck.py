"""설치 트리 DLL 의존성 검사 (구현 계획 M1 2.12, T13). import 표만 든 작은 PE를 만들어 본다."""

import struct
from collections.abc import Sequence
from pathlib import Path

import pytest

from installer import dllcheck


def make_pe(
    path: Path, imports: Sequence[str], delay: Sequence[str] = (), *, pe32: bool = False
) -> Path:
    """import·지연 import 표만 든 PE(32+ 또는 32). 섹션 하나(RVA 0x1000 = 파일 0x200)."""
    section_rva, section_raw = 0x1000, 0x200
    n_imp, n_delay = len(imports), len(delay)
    imp_at = 0
    delay_at = imp_at + 20 * (n_imp + 1)
    names_at = delay_at + (32 * (n_delay + 1) if delay else 0)
    body = bytearray(names_at)
    name_rvas: list[int] = []
    for name in [*imports, *delay]:
        name_rvas.append(section_rva + len(body))
        body += name.encode("ascii") + b"\0"
    for i in range(n_imp):
        struct.pack_into("<IIIII", body, imp_at + 20 * i, 0x1, 0, 0, name_rvas[i], 0x1)
    for i in range(n_delay):
        struct.pack_into("<II", body, delay_at + 32 * i, 1, name_rvas[n_imp + i])

    opt_size = 224 if pe32 else 240
    dirs_off = 96 if pe32 else 112
    opt = bytearray(opt_size)
    struct.pack_into("<H", opt, 0, 0x10B if pe32 else 0x20B)
    struct.pack_into("<I", opt, dirs_off - 4, 16)  # NumberOfRvaAndSizes
    struct.pack_into("<II", opt, dirs_off + 8 * 1, section_rva + imp_at, 20 * (n_imp + 1))
    if delay:
        struct.pack_into("<II", opt, dirs_off + 8 * 13, section_rva + delay_at, 32 * n_delay)
    coff = struct.pack("<HHIIIHH", 0x14C if pe32 else 0x8664, 1, 0, 0, 0, opt_size, 0x2022)
    sect = struct.pack(
        "<8sIIIIIIHHI", b".idata", len(body), section_rva, len(body), section_raw, 0, 0, 0, 0, 0
    )
    head = bytearray(b"MZ" + b"\0" * 58 + struct.pack("<I", 0x40))
    head += b"PE\0\0" + coff + opt + sect
    head += b"\0" * (section_raw - len(head))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(head + body))
    return path


@pytest.mark.parametrize("pe32", [False, True], ids=["pe32+", "pe32"])
def test_reads_imports_and_delay_imports(tmp_path: Path, pe32: bool) -> None:
    pe = make_pe(tmp_path / "m.pyd", ["KERNEL32.dll", "python314.dll"], ["dxgi.dll"], pe32=pe32)
    assert dllcheck.read_imports(pe) == dllcheck.PeImports(
        ("KERNEL32.dll", "python314.dll"), ("dxgi.dll",)
    )
    (tmp_path / "bad.dll").write_bytes(b"not a pe")
    with pytest.raises(dllcheck.PeError):
        dllcheck.read_imports(tmp_path / "bad.dll")


def _tree(root: Path) -> tuple[Path, Path, Path]:
    """설치 폴더, 가짜 System32, 설치 밖 비시스템 폴더(PATH에 있을 법한 곳)."""
    system = root / "System32"
    outside = root / "elsewhere"
    install = root / "install"
    for name in ("KERNEL32.dll", "msvcp140.dll", "VCRUNTIME140.dll"):
        make_pe(system / name, [])
    make_pe(install / "python" / "python.exe", ["python314.dll", "KERNEL32.dll"])
    make_pe(
        install / "python" / "python314.dll", ["KERNEL32.dll", "api-ms-win-crt-runtime-l1-1-0.dll"]
    )
    return install, system, outside


def test_flags_dependency_resolved_outside_install(tmp_path: Path) -> None:
    install, system, outside = _tree(tmp_path)
    make_pe(outside / "foo.dll", [])
    make_pe(
        install / "python/Lib/site-packages/pkg/m.pyd",
        ["python314.dll", "foo.dll", "missing.dll"],
        ["optional.dll", "foo.dll"],
    )
    report = dllcheck.check_tree(install, system_dir=system, outside=[outside])
    assert report.files == 3
    # 일반·지연 import 양쪽에 있는 이름은 한 번만 본다
    assert report.problems == [
        f"[설치 밖에서 풀림] python/Lib/site-packages/pkg/m.pyd: foo.dll → {outside / 'foo.dll'} "
        "(비시스템 DLL)",
        "[풀리지 않음] python/Lib/site-packages/pkg/m.pyd: missing.dll",
    ]
    assert report.notes == ["[지연 import 없음] python/Lib/site-packages/pkg/m.pyd: optional.dll"]

    # 같은 DLL이 설치 안(그 파일 폴더)에 있으면 설치 밖 것을 쓰지 않는다
    make_pe(install / "python/Lib/site-packages/pkg/foo.dll", [])
    make_pe(install / "python/Lib/site-packages/pkg/missing.dll", [])
    report = dllcheck.check_tree(install, system_dir=system, outside=[outside])
    assert report.problems == []


def test_system32_allowed_except_vc_runtime(tmp_path: Path) -> None:
    install, system, outside = _tree(tmp_path)
    pyd = "python/Lib/site-packages/cv2/cv2.pyd"
    make_pe(install / pyd, ["KERNEL32.dll", "MSVCP140.dll", "VCRUNTIME140.dll", "python3.dll"])
    make_pe(install / "python" / "python3.dll", [])
    report = dllcheck.check_tree(install, system_dir=system, outside=[outside])
    # 시스템 DLL·API 집합은 System32에서, VC++ 런타임은 System32에 있어도 실패
    via = "(System32·PATH에서 읽힘)"
    assert sorted(report.problems) == [
        f"[VC++ 런타임 탐색 경로 밖] {pyd}: MSVCP140.dll이 설치 폴더에 없다 {via}",
        f"[VC++ 런타임 탐색 경로 밖] {pyd}: VCRUNTIME140.dll이 설치 폴더에 없다 {via}",
    ]

    # VC++ 런타임을 설치 폴더의 엉뚱한 곳에 두어도 실패 (탐색 경로 밖)
    make_pe(install / "orphan" / "msvcp140.dll", ["KERNEL32.dll"])
    make_pe(install / "orphan" / "vcruntime140.dll", ["KERNEL32.dll"])
    report = dllcheck.check_tree(install, system_dir=system, outside=[outside])
    assert sorted(report.problems) == [
        f"[VC++ 런타임 탐색 경로 밖] {pyd}: MSVCP140.dll이 설치 폴더의 ['orphan']에만 있다 {via}",
        f"[VC++ 런타임 탐색 경로 밖] {pyd}: VCRUNTIME140.dll이 설치 폴더의 ['orphan']에만 있다 "
        f"{via}",
    ]

    # 앱 폴더(python.exe 옆)에 앱 로컬로 두면 통과
    make_pe(install / "python" / "msvcp140.dll", ["KERNEL32.dll"])
    make_pe(install / "python" / "vcruntime140.dll", ["KERNEL32.dll"])
    report = dllcheck.check_tree(install, system_dir=system, outside=[outside])
    assert report.problems == []


NUMPY_INIT = """\
# start delvewheel patch
def _delvewheel_patch_1_11_2():
    import os
    if os.path.isdir(libs_dir := os.path.abspath(os.path.join(os.path.dirname(__file__), \
os.pardir, 'numpy.libs'))):
        os.add_dll_directory(libs_dir)
"""


def test_other_install_folder_fails_unless_registered(tmp_path: Path) -> None:
    """설치 폴더 어딘가에 있다는 것만으로는 풀리지 않는다 (검수 T13-1 #3). 등록 근거가 확인된 DLL
    폴더만, 그 패키지 안 파일의 import에만 쓴다."""
    install, system, outside = _tree(tmp_path)
    site = install / "python/Lib/site-packages"
    # 검수 반례: _ctypes.pyd의 libffi가 등록되지 않은 폴더에만 있다
    make_pe(install / "python/DLLs/_ctypes.pyd", ["python314.dll", "libffi-8.dll"])
    make_pe(install / "orphan/libffi-8.dll", [])
    # delvewheel이 이름을 바꿔 넣은 런타임: numpy 안 파일은 numpy.libs에서 풀린다
    make_pe(site / "numpy.libs/msvcp140-abc.dll", [])
    make_pe(site / "numpy/_core/m.pyd", ["msvcp140-abc.dll"])
    # numpy 밖 파일은 numpy.libs 등록에 기대지 못한다
    make_pe(site / "other/x.pyd", ["msvcp140-abc.dll"])
    (site / "numpy/__init__.py").write_text(NUMPY_INIT, encoding="utf-8")

    report = dllcheck.check_tree(install, system_dir=system, outside=[outside])
    assert sorted(report.problems) == [
        "[VC++ 런타임 탐색 경로 밖] python/Lib/site-packages/other/x.pyd: msvcp140-abc.dll이 "
        "설치 폴더의 ['python/Lib/site-packages/numpy.libs']에만 있다 (System32·PATH에서 읽힘)",
        "[탐색 경로 밖] python/DLLs/_ctypes.pyd: libffi-8.dll이 설치 폴더의 ['orphan']에 있지만 "
        "그 파일 폴더·앱 폴더·등록 DLL 폴더가 아니다",
    ]
    assert report.notes == [
        "[등록 DLL 폴더] msvcp140-abc.dll ← python/Lib/site-packages/numpy.libs (1개 파일)"
    ]

    # 등록 근거(delvewheel 패치)가 사라지면 numpy.libs도 쓰지 않는다
    (site / "numpy/__init__.py").write_text("import os\n", encoding="utf-8")
    report = dllcheck.check_tree(install, system_dir=system, outside=[outside])
    assert any(
        p.startswith("[DLL 폴더 등록 근거 없음] python/Lib/site-packages/numpy.libs")
        for p in report.problems
    )
    assert any("numpy/_core/m.pyd: msvcp140-abc.dll" in p for p in report.problems)


@pytest.mark.process
def test_unregistered_folder_dll_really_fails_to_load(tmp_path: Path) -> None:
    """검수 반례를 실제 DLL로: PBS의 `_ctypes.pyd`를 두고 `libffi-8.dll`을 등록 안 된 폴더에만 두면
    검사가 실패하고 실제 import도 실패한다. 확장 옆에 두면 둘 다 통과한다."""
    import os
    import shutil
    import subprocess
    import sys

    base = Path(sys.base_prefix)
    install = tmp_path / "install"
    dlls = install / "python" / "DLLs"
    dlls.mkdir(parents=True)
    shutil.copy2(base / "DLLs" / "_ctypes.pyd", dlls / "_ctypes.pyd")
    (install / "orphan").mkdir()
    shutil.copy2(base / "DLLs" / "libffi-8.dll", install / "orphan" / "libffi-8.dll")
    for name in ("python3.dll", "python314.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        shutil.copy2(base / name, install / "python" / name)

    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    env["PATH"] = str(Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32")
    code = "import sys; sys.path.insert(0, sys.argv[1]); import _ctypes; print(_ctypes.__file__)"

    def load() -> subprocess.CompletedProcess[str]:
        # 자식도 UTF-8 모드로 띄우고 같은 인코딩으로 읽는다. `-I`는 PYTHONIOENCODING·PYTHONUTF8을
        # 무시하므로 `-X utf8`로 넘긴다 (Windows의 DLL 로드 오류 문구는 시스템 언어 글자다)
        return subprocess.run(
            [str(base / "python.exe"), "-I", "-X", "utf8", "-c", code, str(dlls)],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    report = dllcheck.check_tree(install, outside=[])
    assert [p for p in report.problems if "_ctypes.pyd: libffi-8.dll" in p], report.problems
    failed = load()
    assert failed.returncode != 0 and "DLL load failed" in failed.stderr

    shutil.copy2(install / "orphan" / "libffi-8.dll", dlls / "libffi-8.dll")
    report = dllcheck.check_tree(install, outside=[])
    assert not [p for p in report.problems if "_ctypes.pyd" in p], report.problems
    loaded = load()
    assert loaded.returncode == 0 and str(dlls) in loaded.stdout
