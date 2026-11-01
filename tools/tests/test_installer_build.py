"""설치 파일 빌드 단계 (구현 계획 M1 2.12, T13). 가짜 입력으로 빠르게 본다 — 실제 빌드·설치는
`test_installer_e2e.py`."""

import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

import license_audit as la
import license_pipeline as lp
import native_audit as na
from installer import build
from kb_testing.audit_fixtures import (
    WIN_314,
    native_table,
    policy,
    scan_item,
    write_record,
    write_tree,
)

SITE = na.SITE_PACKAGES_IN_INSTALL
FFMPEG = "cv2/opencv_videoio_ffmpeg500_64.dll"


def _tarball(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _dist(data: bytes, **overrides: Any) -> build.PythonDist:
    fields: dict[str, Any] = {
        "tag": "20990101",
        "version": "3.14.10",
        "file": "cpython.tar.gz",
        "url": "https://example.invalid/cpython.tar.gz",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }
    return build.PythonDist(**{**fields, **overrides})


def test_pbs_hash_verified_before_extract(tmp_path: Path) -> None:
    data = _tarball({"python/python.exe": b"MZ", "python/LICENSE.txt": b"PSF"})
    archive = tmp_path / "cpython.tar.gz"
    archive.write_bytes(data)

    # 표와 다르면 아무것도 풀지 않는다 (해시가 다르거나 크기가 다르거나)
    for bad in (_dist(data, sha256="0" * 64), _dist(data, size=len(data) + 1)):
        stage = tmp_path / f"stage-{bad.sha256[:4]}-{bad.size}"
        stage.mkdir()
        with pytest.raises(build.BuildError, match="풀지 않는다"):
            build.extract_python(archive, bad, stage)
        assert list(stage.iterdir()) == []

    # 같으면 python/ 아래에 푼다
    stage = tmp_path / "stage"
    stage.mkdir()
    assert build.extract_python(archive, _dist(data), stage) == stage / "python"
    assert (stage / "python" / "python.exe").read_bytes() == b"MZ"

    # python/ 밖 항목이 있는 배포본은 해시가 맞아도 거부
    evil = _tarball({"python/python.exe": b"MZ", "other/x.dll": b"MZ"})
    archive.write_bytes(evil)
    other = tmp_path / "stage-evil"
    other.mkdir()
    with pytest.raises(build.BuildError, match="밖 항목"):
        build.extract_python(archive, _dist(evil), other)
    assert list(other.iterdir()) == []


def test_fetch_rejects_wrong_download_and_reuses_verified_cache(tmp_path: Path) -> None:
    data = _tarball({"python/python.exe": b"MZ"})
    dist = _dist(data)
    cache = tmp_path / "cache"
    calls: list[str] = []

    def wrong(url: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes(data + b"x")

    with pytest.raises(build.BuildError, match=r"pbs\.toml과 다르다"):
        build.fetch_python(dist, cache, download=wrong)
    assert list(cache.iterdir()) == []  # 받다 만 파일도 남기지 않는다

    def right(url: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes(data)

    path = build.fetch_python(dist, cache, download=right)
    assert path.read_bytes() == data
    assert build.fetch_python(dist, cache, download=wrong) == path  # 캐시가 맞으면 받지 않는다
    assert calls == [dist.url, dist.url]


def test_inputs_table_pins_pbs_and_vc_files() -> None:
    inputs = build.load_inputs()
    assert inputs.python.file.startswith(f"cpython-{inputs.python.version}+{inputs.python.tag}")
    assert len(inputs.python.sha256) == 64 and inputs.python.size > 0
    assert "msvcp140*.dll" in inputs.vc_redist.files
    assert build.file_version("0.1.0.dev0") == "0.1.0.0"
    assert build.file_version("1.2") == "1.2.0.0"


def _stage(root: Path) -> Path:
    """제거 대상이 든 스테이징 트리 (실제 네이티브 표의 제거 목록에 맞는 이름)."""
    write_tree(
        root,
        {
            "python/python.exe": b"MZ",
            "python/Lib/idlelib/idle.py": "",
            "python/Lib/ensurepip/__init__.py": "",
            "python/Lib/os.py": "",
            f"{SITE}/README.txt": "PBS",
            f"{SITE}/pip/__init__.py": "",
            f"{SITE}/pip/_vendor/distlib/t64.exe": b"MZ",
            f"{SITE}/cv2/cv2.pyd": b"MZ",
            f"{SITE}/cv2/__init__.py": "",
            f"{SITE}/{FFMPEG}": b"MZ",
        },
    )
    site = root / SITE
    write_record(site, "opencv_python-5.0.0.93", ["cv2"])
    write_record(site, "pip-26.2.2", ["pip"])
    return root


def test_strip_removes_ffmpeg_file_and_record_line(tmp_path: Path) -> None:
    table = na.load_native_table_file(build.NATIVE_TABLE)
    stage = _stage(tmp_path / "stage")
    site = stage / SITE
    record = site / "opencv_python-5.0.0.93.dist-info" / "RECORD"
    assert FFMPEG in record.read_text("utf-8")

    removed = build.strip_tree(stage, table)

    assert removed == [
        "install:python/Lib/ensurepip",
        "install:python/Lib/idlelib",
        "site-packages:README.txt",
        f"site-packages:{FFMPEG}",
        "site-packages:pip",
        "site-packages:pip-26.2.2.dist-info",
    ]
    assert not (site / FFMPEG).exists() and (site / "cv2" / "cv2.pyd").is_file()
    lines = record.read_text("utf-8").splitlines()
    assert not any(FFMPEG in line for line in lines)
    assert "cv2/cv2.pyd,sha256=x,1" in lines  # 다른 줄은 그대로
    assert not (site / "pip").exists() and not (stage / "python/Lib/idlelib").exists()
    assert (stage / "python/Lib/os.py").is_file()
    # 제거 뒤 RECORD와 실제 파일이 서로 맞는다
    assert na.audit_records(site, table) == []


@pytest.mark.process
def test_launcher_python_path_relative_to_launcher(tmp_path: Path) -> None:
    """uv 실행기의 Python 경로 자원을 상대 경로로 바꾸면 실행기 폴더 기준으로 풀린다 (현재 폴더가
    아니라). 레포 venv의 `kookabug.exe`를 복사하고, venv는 교차점(junction)으로 옆에 붙인다."""
    import _winapi
    import subprocess

    venv = build.REPO_ROOT / ".venv"
    source = venv / "Scripts" / build.LAUNCHER
    assert build.launcher_python(source) == str(venv / "Scripts" / "python.exe")
    assert build.is_script_launcher(source)
    # venv의 python.exe도 uv 실행기지만 인터프리터 실행기라 바꾸지 않는다. 진짜 python.exe는 아님
    assert not build.is_script_launcher(venv / "Scripts" / "python.exe")
    assert build.launcher_python(Path(sys.base_prefix) / "python.exe") is None

    root = tmp_path / "설치 폴더 공백 한글"
    (root / "bin").mkdir(parents=True)
    _winapi.CreateJunction(str(venv), str(root / "venv"))
    try:
        exe = root / "bin" / build.LAUNCHER
        shutil.copy2(source, exe)
        build.set_launcher_python(exe, "..\\venv\\Scripts\\python.exe")
        assert build.launcher_python(exe) == "..\\venv\\Scripts\\python.exe"
        # kookabug는 시작하자마자 표준 입출력을 UTF-8로 바꾼다 (부모도 UTF-8로 읽는다)
        proc = subprocess.run(
            [str(exe), "--version"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert (proc.returncode, proc.stdout.strip()) == (0, f"kookabug {build.cli_version()}")

        # RECORD의 그 파일 줄은 바뀐 해시·크기로
        site = root / "site"
        write_tree(site, {"pkg-1.0.dist-info/METADATA": "Name: pkg\n"})
        record = site / "pkg-1.0.dist-info" / "RECORD"
        record.write_text(
            "../bin/kookabug.exe,sha256=old,1\npkg-1.0.dist-info/RECORD,,\n", encoding="utf-8"
        )
        assert build.update_record_hashes(site, [exe]) == 1
        first = record.read_text("utf-8").splitlines()[0]
        size = exe.stat().st_size
        assert first == f"../bin/kookabug.exe,{build.record_hash(exe)},{size}"
    finally:
        os.rmdir(root / "venv")  # 교차점만 지운다 (venv는 그대로)


def _launcher_entry(table: na.NativeTable) -> na.NativeEntry:
    entry = na.find_entry(table, na.INSTALL, f"{build.BIN}/{build.LAUNCHER}")
    assert entry is not None
    return entry


def test_launcher_crates_listed_and_each_needs_its_text(tmp_path: Path) -> None:
    """설치본 실행기(uv 실행기 스텁)의 실행 시 크레이트(검수 T13-1 #2: dunce·ufmt·ufmt-write·
    windows 등)가 SBOM으로 표에 연결되고, 크레이트 원문 하나가 빠지면 감사가 실패한다."""
    table = na.load_native_table_file(build.NATIVE_TABLE)
    entry = _launcher_entry(table)
    assert entry.sbom_file
    sbom = json.loads((table.base_dir / entry.sbom_file).read_text(encoding="utf-8"))
    crates = {(n, v) for n, v, _ in na.sbom_components(sbom)}
    for crate in (("dunce", "1.0.5"), ("ufmt", "0.2.0"), ("ufmt-write", "0.1.0")):
        assert crate in crates
    assert ("windows", "0.61.3") in crates
    # 모든 구성요소에 Cargo.lock 체크섬이 있다 (원문을 모을 때 받은 .crate와 대조)
    assert all(len(h) == 64 for h in fc_checksums(sbom).values()) and len(
        fc_checksums(sbom)
    ) == len(crates)
    layout = na.Layout.install(tmp_path)

    def problems(t: na.NativeTable) -> list[str]:
        return na.check_texts(_launcher_entry(t), t, policy(), layout, {})[0]

    assert problems(table) == []

    # 레포 원문을 복사해 크레이트 절 하나(ufmt 0.2.0)를 지운다
    copy = tmp_path / "tools"
    shutil.copytree(build.TOOLS_DIR / "third_party_licenses", copy / "third_party_licenses")
    crates_txt = copy / "third_party_licenses" / "uv-trampoline-crates.txt"
    text = crates_txt.read_text(encoding="utf-8")
    crates_txt.write_text(text.replace("\nufmt 0.2.0\n", "\n(지움)\n"), encoding="utf-8")
    broken = na.NativeTable(table.entries, table.strip, table.license_refs, copy)
    assert any(
        p.startswith("[SBOM 구성요소 원문 없음]") and "ufmt 0.2.0" in p for p in problems(broken)
    )

    # uv 워크스페이스 크레이트(uv-trampoline·uv-windows) 표기가 빠져도 실패
    crates_txt.write_text(text, encoding="utf-8")
    uv_txt = copy / "third_party_licenses" / "uv-trampoline.txt"
    uv_txt.write_text(
        uv_txt.read_text(encoding="utf-8").replace("uv-windows 0.0.98", "uv-windows"),
        encoding="utf-8",
    )
    assert any("uv-windows 0.0.98" in p for p in problems(broken))

    # SBOM 파일이 없으면 실패
    (copy / entry.sbom_file).unlink()
    assert any(p.startswith("[SBOM 없음]") for p in problems(broken))


def fc_checksums(sbom: dict[str, Any]) -> dict[tuple[str, str], str]:
    import fetch_crate_licenses as fc

    return fc.sbom_checksums(sbom)


def test_uv_version_pinned_for_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    """실행기 구성요소 표의 uv 판 = 빌드 입력 표 = CI의 uv. 빌드는 다른 uv로는 멈춘다."""
    want = build.load_inputs().uv_version
    table = na.load_native_table_file(build.NATIVE_TABLE)
    sbom = json.loads((table.base_dir / _launcher_entry(table).sbom_file).read_text("utf-8"))
    props = {p["name"]: p["value"] for p in sbom["metadata"]["properties"]}
    assert props["kookabug:uv_version"] == want
    assert f"/uv/blob/{want}/" in props["kookabug:source"]
    uv_txt = (table.base_dir / "third_party_licenses" / "uv-trampoline.txt").read_text("utf-8")
    assert uv_txt.startswith(f"uv {want}의 실행기")
    ci = (build.REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert f'UV_VERSION: "{want}"' in ci

    seen: list[list[str]] = []

    def fake_run(cmd: Any, *, cwd: Path, capture: bool = False) -> str:
        seen.append([str(c) for c in cmd])
        return "uv 0.99.0 (abc 2099-01-01)\n"

    monkeypatch.setattr(build, "run", fake_run)
    with pytest.raises(build.BuildError, match=f"uv {want} 기준"):
        build.check_uv_version("uv", want)
    build.check_uv_version("uv", "0.99.0")
    assert seen[0][1:] == ["--version"]


def test_vc_runtime_copied_next_to_python(tmp_path: Path) -> None:
    crt = write_tree(
        tmp_path / "Microsoft.VC143.CRT",
        {
            name: b"MZ"
            for name in (
                "msvcp140.dll",
                "msvcp140_1.dll",
                "vcruntime140.dll",
                "vcruntime140_1.dll",
                "concrt140.dll",
                "vccorlib140.dll",
            )
        },
    )
    python_dir = tmp_path / "stage" / "python"
    python_dir.mkdir(parents=True)
    vc = build.load_inputs().vc_redist

    copied = build.copy_vc_runtime(crt, vc, python_dir)

    assert sorted(copied) == sorted(
        [
            "msvcp140.dll",
            "msvcp140_1.dll",
            "vcruntime140.dll",
            "vcruntime140_1.dll",
            "concrt140.dll",
        ]
    )
    assert sorted(p.name for p in python_dir.iterdir()) == sorted(copied)  # vccorlib는 안 넣는다
    # 설치본의 네이티브 표가 그 파일을 VC++ 재배포 파일로 본다
    table = na.load_native_table_file(build.NATIVE_TABLE)
    for name in copied:
        entry = na.find_entry(table, na.INSTALL, f"python/{name}")
        assert entry is not None and entry.license == "LicenseRef-MS-VC-Redist", name

    (crt / "msvcp140.dll").unlink()
    with pytest.raises(build.BuildError, match=r"msvcp140\.dll"):
        build.copy_vc_runtime(crt, vc, tmp_path / "other")


def test_runtime_set_equals_audit_runtime_txt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1) 감사와 빌드가 같은 `uv export`를 쓴다: 해시만 다르다
    commands: list[list[str]] = []
    monkeypatch.setattr(lp, "_run", lambda cmd, cwd, capture=False: commands.append(cmd) or "")
    lp.export_runtime("uv", tmp_path, tmp_path / "a.txt")
    lp.export_runtime("uv", tmp_path, tmp_path / "b.txt", hashes=True)
    plain, hashed = ([str(c) for c in cmd] for cmd in commands)
    for flag in ("--locked", "--all-packages", "--no-dev", "--no-emit-workspace"):
        assert flag in plain and flag in hashed
    assert [c for c in plain if c != "--no-hashes"][:-1] == hashed[:-1]
    assert "--no-hashes" in plain and "--no-hashes" not in hashed

    # 2) 빌드는 그 함수로 runtime.txt(감사와 같은 형식)와 해시 고정판을 뽑아 해시판으로 설치한다
    exports: list[tuple[Path, bool]] = []

    def fake_export(uv: str, project: Path, out: Path, *, hashes: bool = False) -> None:
        exports.append((out, hashes))
        out.write_text("numpy==2.5.4\n", encoding="utf-8")

    runs: list[list[str]] = []

    def fake_run(cmd: Any, *, cwd: Path, capture: bool = False) -> str:
        args = [str(c) for c in cmd]
        runs.append(args)
        if "build" in args:
            out = Path(args[args.index("--out-dir") + 1])
            out.mkdir(parents=True)
            (out / "kookabug_cli-0.1.0.dev0-py3-none-any.whl").write_bytes(b"PK")
        return ""

    monkeypatch.setattr(lp, "export_runtime", fake_export)
    monkeypatch.setattr(build, "run", fake_run)
    work = tmp_path / "work"
    result = build.install_runtime("uv", tmp_path / "python.exe", work)
    assert exports == [(work / "runtime.txt", False), (work / "runtime-hashes.txt", True)]
    assert result.runtime_txt == work / "runtime.txt"
    third_party = next(r for r in runs if "-r" in r)
    assert third_party[third_party.index("-r") + 1] == str(work / "runtime-hashes.txt")
    for flag in ("--no-deps", "--require-hashes", "--only-binary"):
        assert flag in third_party
    assert third_party[third_party.index("--link-mode") + 1] == "copy"

    # 3) 설치된 집합 = runtime.txt(대상 마커에서 활성) + 우리 wheel. 이름·버전 모두
    site = tmp_path / "site"
    for name, version in (("numpy", "2.5.4"), ("kookabug_cli", "0.1.0.dev0")):
        write_tree(
            site, {f"{name}-{version}.dist-info/METADATA": f"Name: {name}\nVersion: {version}\n"}
        )
    runtime = tmp_path / "runtime.txt"
    runtime.write_text(
        "numpy==2.5.4\ncolorama==0.4.6 ; sys_platform == 'darwin'\n", encoding="utf-8"
    )
    assert build.check_runtime_set(site, runtime, WIN_314, result.wheels) == []

    write_tree(site, {"pip-26.2.2.dist-info/METADATA": "Name: pip\nVersion: 26.2.2\n"})
    runtime.write_text("numpy==2.5.5\nattrs==26.1.0\n", encoding="utf-8")
    assert build.check_runtime_set(site, runtime, WIN_314, result.wheels) == [
        "[설치 누락] attrs==26.1.0",
        "[설치 집합 밖] pip==26.2.2",
        "[버전 불일치] numpy: 기대 2.5.5, 설치 2.5.4",
    ]


FFMPEG_NATIVE = {
    "glob": "cv2/opencv_videoio_ffmpeg*.dll",
    "package": "opencv-python",
    "license": "LGPL-2.1-or-later",
    "reason": "제거 대상",
}
FFMPEG_STRIP = {"glob": "cv2/opencv_videoio_ffmpeg*.dll", "reason": "FFmpeg (LGPL)"}


def _notices_inputs(
    root: Path,
    *,
    native: list[dict[str, Any]] | None = None,
    strip: list[dict[str, Any]] | None = None,
) -> tuple[na.NativeTable, list[na.ModelEntry], na.NativeReport]:
    """numpy(패키지별 예외)·VC++(LicenseRef)·근거 원문·OCR 모델이 든 작은 최종 트리."""
    model = b"onnx model bytes"
    text = "Apache License Version 2.0 (model weights)"
    write_tree(
        root,
        {
            "python/python.exe": b"MZ",
            "python/vcruntime140.dll": b"MZ",
            "python/LICENSE.txt": "PSF LICENSE",
            f"{SITE}/numpy/_core/m.pyd": b"MZ",
            f"{SITE}/numpy.libs/libscipy_openblas64_.dll": b"MZ",
            f"{SITE}/numpy-2.5.4.dist-info/LICENSE.txt": "NumPy BSD; GCC RUNTIME LIBRARY EXCEPTION",
            "ocr-models/det.onnx": model,
            "ocr-models/LICENSE-model.txt": text,
        },
    )
    write_record(root / SITE, "numpy-2.5.4", ["numpy", "numpy.libs"])
    table = native_table(
        strip=strip or [],
        native=[
            *(native or []),
            {
                "glob": "numpy.libs/*.dll",
                "package": "numpy",
                "license": "BSD-3-Clause AND GPL-3.0-or-later WITH GCC-exception-3.1",
                "texts": [
                    {
                        "path": "numpy-*.dist-info/LICENSE.txt",
                        "covers": ["BSD-3-Clause", "GPL-3.0-or-later WITH GCC-exception-3.1"],
                        "expect": ["GCC RUNTIME LIBRARY EXCEPTION"],
                    }
                ],
                "reason": "OpenBLAS",
            },
            {
                "glob": "numpy/**/*.pyd",
                "package": "numpy",
                "license": "BSD-3-Clause",
                "texts": [
                    {
                        "path": "numpy-*.dist-info/LICENSE.txt",
                        "covers": ["BSD-3-Clause"],
                        "expect": ["NumPy BSD"],
                    }
                ],
                "reason": "NumPy",
            },
            {
                "scope": "install",
                "glob": "python/vcruntime140*.dll",
                "package": "vc-redist",
                "license": "LicenseRef-MS-VC-Redist",
                "reason": "VC++",
            },
            {
                "scope": "install",
                "glob": "python/python.exe",
                "package": "python-build-standalone",
                "license": "PSF-2.0",
                "texts": [{"path": "python/LICENSE.txt", "covers": ["PSF-2.0"], "expect": ["PSF"]}],
                "reason": "CPython",
            },
            {
                "scope": "install",
                "glob": "Uninstall *.exe",
                "package": "nsis",
                "license": "Zlib",
                "texts": [
                    {
                        "file": "third_party_licenses/nsis.txt",
                        "covers": ["Zlib"],
                        "expect": ["zlib/libpng license"],
                    }
                ],
                "reason": "제거 프로그램",
            },
        ],
        refs={
            "LicenseRef-MS-VC-Redist": {
                "name": "VC++ 재배포 파일",
                "source": "Visual Studio 사용 조건",
                "reason": "수정 없이 배포",
                "notice": "Copyright (c) Microsoft Corporation. (VC++ 고지)",
            },
        },
    )
    models = na.load_model_table(
        {
            "model": [
                {
                    "file": "det.onnx",
                    "sha256": hashlib.sha256(model).hexdigest(),
                    "size": len(model),
                    "license": "Apache-2.0",
                    "source": "모델 출처",
                    "license_texts": ["LICENSE-model.txt"],
                }
            ],
            "text": [
                {
                    "file": "LICENSE-model.txt",
                    "label": "모델 라이선스 원문",
                    "sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "size": len(text.encode()),
                }
            ],
        }
    )
    final = na.audit_final_tree(
        root, table, policy(), models=models, installer_files=(build.UNINSTALLER,)
    )
    return table, models, final


def test_notices_contains_all_sections(tmp_path: Path) -> None:
    _, _, final = _notices_inputs(tmp_path / "stage")
    assert final.problems == []
    own = frozenset(build.workspace_names())
    assert {"kookabug-cli", "kookabug-sdk", "kookabug-platform"} <= own
    scanned = la.parse_pip_licenses(
        [
            scan_item("numpy", "2.5.4", "BSD-3-Clause", "numpy license text"),
            scan_item("kookabug-cli", "0.1.0.dev0", "Apache-2.0"),
            scan_item("kookabug-sdk", "0.1.0.dev0", "MIT"),
        ]
    )
    result = build.render_installer_notices(
        la.parse_runtime("numpy==2.5.4\n"), WIN_314, scanned, policy(), final, own
    )
    assert result.problems == []
    text = result.notices
    for section in (
        "numpy 2.5.4",  # Python 패키지 절 (스테이징 Python 스캔)
        "numpy license text",
        "# 네이티브 파일 (DLL·pyd·exe)과 그 안의 구성요소",
        "# 패키지별 라이선스 예외",
        "GPL-3.0-or-later WITH GCC-exception-3.1",
        "# SPDX 밖 배포 조건 (LicenseRef)",
        "(VC++ 고지)",
        "# 네이티브 파일 근거 원문",
        "PSF LICENSE",
        "# OCR 모델",
        "Apache License Version 2.0 (model weights)",  # 모델 근거 원문 본문
        # 설치 때 NSIS가 더하는 제거 프로그램도 NOTICES에 실린다 (설치 전 트리에는 없다)
        "install:Uninstall Kookabug.exe",
        "NSIS 3.04",
    ):
        assert section in text, section
    assert "kookabug-cli" not in text  # 우리 패키지는 서드파티 절에 없다

    # 우리 패키지도 허용 라이선스여야 한다
    bad = la.parse_pip_licenses([scan_item("kookabug-cli", "0.1.0.dev0", "GPL-3.0-only")])
    result = build.render_installer_notices([], WIN_314, bad, policy(), final, own)
    assert result.problems == ["[우리 패키지 라이선스] kookabug-cli: 'GPL-3.0-only'"]


def test_final_tree_audit_runs_on_build_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """빌드의 마지막 감사는 설치 파일에 들어갈 트리 자체(M2: electron-builder win-unpacked)에 최종
    트리 감사를 건다: 제거 대상이 남았거나 RECORD가 어긋나면 실패하고, 그 트리의 Python 스캔
    결과로 NOTICES를 만든다."""
    stage = tmp_path / "stage"
    table, models, _ = _notices_inputs(stage, native=[FFMPEG_NATIVE], strip=[FFMPEG_STRIP])
    write_tree(stage, {f"{SITE}/{FFMPEG}": b"MZ"})  # 지웠어야 할 파일이 남음
    runtime = tmp_path / "runtime.txt"
    runtime.write_text("numpy==2.5.4\n", encoding="utf-8")

    def fake_scan(uv: str, python: Path, out: Path, *, cwd: Path) -> None:
        assert python == stage / "python" / "python.exe"  # 스테이징 Python을 스캔한다
        out.write_text(json.dumps([scan_item("numpy", "2.5.4", "BSD-3-Clause")]), "utf-8")

    monkeypatch.setattr(lp, "scan_python", fake_scan)
    monkeypatch.setattr(build, "read_marker_env", lambda python, work: dict(WIN_314))

    def final_audit() -> tuple[na.NativeReport, build.NoticesResult]:
        return build.audit_final(
            stage, table, policy(), models, uv="uv", runtime_txt=runtime, work=tmp_path
        )

    final, notices = final_audit()
    assert any(p.startswith(f"[제거 대상 남음] site-packages:{FFMPEG}") for p in final.problems)
    assert any(p.startswith(f"[RECORD에 없는 파일] site-packages:{FFMPEG}") for p in final.problems)
    assert notices.problems == [] and "numpy 2.5.4" in notices.notices

    (stage / SITE / FFMPEG).unlink()
    final, _ = final_audit()
    assert final.problems == []


def test_unlisted_native_in_strip_folder_is_note_in_build_input(tmp_path: Path) -> None:
    """PBS pip의 distlib 실행기처럼 표에 없는 파일도 제거 목록 안이면 빌드 입력에서는 참고다.
    최종 트리에 남으면 실패다."""
    table = na.load_native_table_file(build.NATIVE_TABLE)
    stage = _stage(tmp_path / "stage")
    shutil.rmtree(stage / SITE / "cv2")
    shutil.rmtree(stage / SITE / "opencv_python-5.0.0.93.dist-info")
    report = na.audit_build_input(na.Layout.install(stage), table, policy(), origins=("pbs",))
    where = "site-packages:pip/_vendor/distlib/t64.exe"
    assert not any(where in p for p in report.problems)
    assert any(n.startswith(f"[제거 대상] {where} (표 없음)") for n in report.notes)
    final = na.audit_final_tree(stage, table, policy())
    assert any(p.startswith(f"[네이티브 표 없음] {where}") for p in final.problems)
    assert any(p.startswith("[제거 대상 남음] site-packages:pip") for p in final.problems)
