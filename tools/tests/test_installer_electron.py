"""M2 설치 파일 구성 (구현 계획 M2 2.14 T13): M1 폴더 구조 유지, Electron 네이티브 표, ffmpeg 고정
바이너리 예외, NOTICES(JS·글꼴·Electron), 배포 번들(E2E 검사 훅 없음), NSIS 조각.

실제 빌드·설치는 `test_installer_e2e.py`. Electron 배포물(apps/desktop/node_modules/electron/dist)이
필요한 검사는 pnpm install이 안 된 환경(CI python 잡)에서는 건너뛴다.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path, PurePosixPath

import pytest
from packaging.utils import canonicalize_name

import license_audit as la
import native_audit as na
from installer import build
from kb_testing.audit_fixtures import WIN_314, policy, write_tree

REPO_ROOT = Path(__file__).resolve().parents[2]
TABLE = na.load_native_table_file(build.NATIVE_TABLE)
NO_ELECTRON = not (build.ELECTRON_DIST / "electron.exe").is_file()
needs_electron = pytest.mark.skipif(NO_ELECTRON, reason="Electron 배포물 없음 (pnpm install 필요)")
# Electron 배포물 이름 → 설치 트리 이름 (electron-builder가 바꾸는 것)
RENAMED = {"electron.exe": build.APP_EXE, "LICENSE": "LICENSE.electron.txt"}
FAKE_CREDITS = (
    "<pre>Most files in FFmpeg are under the GNU Lesser General Public License version 2.1\n"
    "opus: Copyright Xiph.Org</pre> CHROMIUM-CREDITS-BODY"
)


def layout_tree(root: Path) -> Path:
    return write_tree(
        root,
        {
            "python/python.exe": b"MZ",
            "bin/kookabug.exe": b"MZ",
            "ocr-models/model.onnx": b"x",
            "examples/sample-game/README.md": "x",
            "licenses/LICENSE.txt": "Apache License",
            build.FFMPEG_SOURCE_IN_INSTALL: "src",
            "VERSION": "0.1.0.dev0\n",
            build.APP_EXE: b"MZ",
            build.APP_ASAR: b"asar",
        },
    )


def dist_info(site: Path, name: str) -> None:
    write_tree(site, {f"{name}-0.1.0.dist-info/METADATA": f"Name: {name}\nVersion: 0.1.0\n"})


def test_staging_tree_layout_m1_folders_kept(tmp_path: Path) -> None:
    # M1 폴더(python·bin·ocr-models·examples·licenses·VERSION) + 데스크톱 앱이 맨 위에 있다
    root = layout_tree(tmp_path / "root")
    assert build.check_layout(root) == []
    (root / "bin/kookabug.exe").unlink()
    assert build.check_layout(root) == ["[설치 트리 구조] bin/kookabug.exe가 없다"]
    (root / "bin/kookabug.exe").write_bytes(b"MZ")
    # Electron 기본 앱이 남거나, VERSION이 Electron의 version 파일과 섞여 이름이 바뀌면 실패
    write_tree(root, {"resources/default_app.asar": b"x"})
    assert build.check_layout(root) == ["[설치 트리 구조] resources/default_app.asar가 남았다"]
    (root / "resources/default_app.asar").unlink()
    (root / "VERSION").rename(root / "version")
    assert "[설치 트리 구조] version가 남았다" in build.check_layout(root)

    # 스테이징 파일은 최종 트리에 같은 크기로 다 있어야 한다 (extraFiles 복사 대조)
    stage = write_tree(tmp_path / "stage", {"a/b.txt": "12", "c.txt": "3"})
    final = write_tree(tmp_path / "final", {"a/b.txt": "12", "c.txt": "3", "extra.dll": b"MZ"})
    assert build.compare_stage(stage, final) == []
    (final / "c.txt").write_text("345", encoding="utf-8")
    (final / "a/b.txt").unlink()
    assert build.compare_stage(stage, final) == [
        "[스테이징 파일 없음] a/b.txt",
        "[스테이징 파일 크기 다름] c.txt: 1 → 3",
    ]

    # 우리 패키지는 전부 들어간다 — daemon이 선택 설치로 쓰는 kookabug-platform 포함 (M2 T6)
    assert "kookabug-platform" in build.REQUIRED_PACKAGES
    assert {canonicalize_name(n) for n in build.REQUIRED_PACKAGES} == set(build.workspace_names())
    site = tmp_path / "site"
    for name in build.REQUIRED_PACKAGES:
        if name != "kookabug-platform":
            dist_info(site, name)
    assert build.check_required_packages(site) == ["[우리 패키지 없음] kookabug-platform"]
    dist_info(site, "kookabug-platform")
    assert build.check_required_packages(site) == []


def test_prepare_electron_dist_drops_default_app_and_version(tmp_path: Path) -> None:
    source = write_tree(
        tmp_path / "dist",
        {
            "electron.exe": b"MZ",
            "version": "44.8.0",
            "resources/default_app.asar": b"x",
            "locales/ko.pak": b"p",
        },
    )
    files = build.prepare_electron_dist(tmp_path / "out", source)
    assert files == ["electron.exe", "locales/ko.pak"]
    assert not (tmp_path / "out/version").exists()
    with pytest.raises(build.BuildError, match="Electron 배포물이 없다"):
        build.prepare_electron_dist(tmp_path / "out2", tmp_path / "missing")


@needs_electron
def test_every_electron_native_file_in_table(tmp_path: Path) -> None:
    """고정 Electron 배포물에서 설치 트리로 가는 파일 중 표에 있어야 하는 것(DLL·exe·pak·dat·
    bin·asar)은 전부 표 항목이 있다. 표에 없는 파일은 감사 실패다."""
    shipped: list[str] = []
    skip = {rel.casefold() for rel in build.ELECTRON_LEFTOVERS}
    for path in sorted(build.ELECTRON_DIST.rglob("*")):
        rel = path.relative_to(build.ELECTRON_DIST).as_posix()
        if path.is_file() and rel.casefold() not in skip:
            shipped.append(RENAMED.get(rel, rel))
    natives = [rel for rel in shipped if na.is_native(rel, na.INSTALL)]
    assert build.APP_EXE in natives and "ffmpeg.dll" in natives and "icudtl.dat" in natives
    missing = [rel for rel in natives if na.find_entry(TABLE, na.INSTALL, rel) is None]
    assert missing == []
    # 설치 때 더해지는 것과 앱 번들도 표에 있다
    for rel in (build.UNINSTALLER, build.APP_ASAR):
        assert na.find_entry(TABLE, na.INSTALL, rel) is not None, rel

    # 표에 없는 파일은 실패 (DLL도, Electron 자원 묶음도)
    root = write_tree(tmp_path / "tree", {"unknown.dll": b"MZ", "extra.pak": b"p", "x.json": "{}"})
    report = audit_tree(root, policy())
    assert sorted(
        p.split(":")[1] for p in report.problems if p.startswith("[네이티브 표 없음]")
    ) == [
        "extra.pak",
        "unknown.dll",
    ]


def audit_tree(
    root: Path, pol: la.Policy, versions: dict[str, str] | None = None
) -> na.NativeReport:
    """설치 트리 모양의 네이티브 판정만 (제거 목록 빗나감은 빌드 입력 종류가 없어 보지 않는다)."""
    return na.audit_build_input(
        na.Layout.install(root), TABLE, pol, origins=(), versions=versions or {}
    )


def ffmpeg_tree(root: Path, rel: str = "ffmpeg.dll") -> Path:
    data = (build.ELECTRON_DIST / "ffmpeg.dll").read_bytes()
    return write_tree(
        root,
        {
            rel: data,
            build.FFMPEG_SOURCE_IN_INSTALL: build.FFMPEG_SOURCE.read_text(encoding="utf-8"),
            "LICENSES.chromium.html": FAKE_CREDITS,
        },
    )


@needs_electron
def test_ffmpeg_exception_electron_only(tmp_path: Path) -> None:
    """실제 표·정책과 고정 Electron의 ffmpeg.dll: 설치 폴더 맨 위·고정판일 때만 허용된다."""
    pol = policy()
    pin = pol.pinned[0]
    real = (build.ELECTRON_DIST / "ffmpeg.dll").read_bytes()
    assert hashlib.sha256(real).hexdigest() == pin.sha256  # 예외는 그 바이너리에 묶여 있다
    versions = {"electron": build.pinned_electron()}

    root = ffmpeg_tree(tmp_path / "ok")
    report = audit_tree(root, pol, versions)
    assert report.problems == []
    assert [nf.rel for nf, _ in report.pinned] == ["ffmpeg.dll"]

    # 실행 파일에서 읽은 Electron 판이 없거나 다르면 금지
    for other in ({}, {"electron": "45.0.0"}):
        report = audit_tree(root, pol, other)
        assert any(
            p.startswith("[네이티브 라이선스] install:ffmpeg.dll") and "금지" in p
            for p in report.problems
        ), other

    # 다른 위치의 ffmpeg 이름 DLL은 실패 (표 항목도 예외도 맞지 않는다)
    for rel in ("python/ffmpeg.dll", "resources/ffmpeg.dll"):
        tree = ffmpeg_tree(tmp_path / rel.replace("/", "_"), rel)
        report = audit_tree(tree, pol, versions)
        assert report.pinned == [] and any(
            p.startswith(f"[네이티브 표 없음] install:{rel}") for p in report.problems
        ), rel


def test_electron_version_read_from_executable(tmp_path: Path) -> None:
    root = write_tree(
        tmp_path / "root",
        {"Kookabug.exe": b"MZ" + b"\0" * (1 << 22) + b"Chrome/152.0 Electron/44.8.0 Safari"},
    )
    assert na.electron_version(root) == "44.8.0"
    assert na.detect_versions(root) == {"electron": "44.8.0"}
    plain = write_tree(tmp_path / "plain", {"python.exe": b"MZ no marker"})
    assert na.electron_version(plain) is None and na.detect_versions(plain) == {}


@needs_electron
def test_notices_include_js_fonts_electron(tmp_path: Path) -> None:
    pol = policy()
    root = ffmpeg_tree(tmp_path / "tree")
    final = audit_tree(root, pol, {"electron": build.pinned_electron()})
    assert final.problems == []
    fonts = write_tree(
        tmp_path / "fonts",
        {"LICENSE": "SIL OPEN FONT LICENSE Version 1.1", "files/x-400.woff2": b"wOF2"},
    )
    react = write_tree(tmp_path / "react", {"LICENSE": "MIT License Meta Platforms"})
    js = la.parse_pnpm_licenses(
        {
            "OFL-1.1": [{"name": "@fontsource/x", "versions": ["5.3.0"], "paths": [str(fonts)]}],
            "MIT": [{"name": "react", "versions": ["19.3.1"], "paths": [str(react)]}],
        }
    )
    result = build.render_installer_notices([], WIN_314, {}, pol, final, frozenset(), js)
    assert result.problems == []
    text = result.notices
    for part in (
        "(JavaScript)",
        "@fontsource/x 5.3.0",
        "SIL OPEN FONT LICENSE",
        "react 19.3.1",
        "# 고정 바이너리 한정 라이선스 예외",
        "install:ffmpeg.dll: LGPL-2.1-or-later",
        "GNU LESSER GENERAL PUBLIC LICENSE",
        "2b68d2babae73714846961fb0ee47e3b3d2e39a9",
        "install:LICENSES.chromium.html (",
    ):
        assert part in text, part
    # 큰 Chromium credits는 옮겨 싣지 않고 위치만 적는다
    assert "CHROMIUM-CREDITS-BODY" not in text
    assert result.js_rows == [("@fontsource/x", "5.3.0", "OFL-1.1"), ("react", "19.3.1", "MIT")]


def test_variants_differ_in_every_identity() -> None:
    p, t = build.PRODUCT, build.TEST
    for name in (
        "app_guid",
        "app_name",
        "app_id",
        "file_prefix",
        "dir_name",
        "uninstall_key",
        "install_key",
        "shortcut",
        "updater_dir",
        "exe_name",
        "app_exe",
        "uninstaller",
    ):
        assert getattr(p, name) != getattr(t, name), name
    # 실행 파일 이름이 달라 설치·제거의 앱 끄기가 다른 판을 이름으로 맞히지 않는다
    assert (p.app_exe, t.app_exe) == ("Kookabug.exe", "KookabugTest.exe")
    assert p.app_exe == build.APP_EXE and p.uninstaller == build.UNINSTALLER
    # 두 판의 실행 파일·제거 프로그램 모두 네이티브 표에 있다
    for v in (p, t):
        for rel in (v.app_exe, v.uninstaller):
            assert na.find_entry(TABLE, na.INSTALL, rel) is not None, rel
    assert build.variant_config(t)["executableName"] == "KookabugTest"
    assert build.setup_name("1.0", t) == "kookabug-setup-test-1.0"
    assert build.setup_name("1.0") == "kookabug-setup-1.0"
    assert p.install_key == rf"Software\{p.app_guid}" and p.uninstall_key == p.app_guid
    assert build.semver("0.1.0.dev0") == "0.1.0-dev.0"
    assert build.semver("1.2") == "1.2.0" and build.semver("1.0rc2") == "1.0.0-rc.2"


def test_app_icon_is_confirmed_a1_and_checked_in_exe(tmp_path: Path) -> None:
    """확정 아이콘 A1이 설정에 연결돼 있고, 실행 파일 검사는 ICO의 이미지가 하나라도 빠지면 잡는다
    (T13 검수 1차 Mid: Electron 기본 아이콘)."""
    yml = build.EB_CONFIG.read_text(encoding="utf-8")
    assert re.search(
        r'^\s*icon: "\.\./\.\./Docs/Design/앱 아이콘 \(L3\)/확정 A1/kookabug\.ico"\s*$', yml, re.M
    )
    assert (
        build.DESKTOP_DIR / "../../Docs/Design/앱 아이콘 (L3)/확정 A1/kookabug.ico"
    ).resolve() == (build.APP_ICON.resolve())
    images = build.icon_images()
    assert sorted(w for w, _ in images) == [16, 20, 24, 32, 40, 48, 64, 128, 256]
    with_icon = tmp_path / "with.exe"
    with_icon.write_bytes(b"MZ" + b"".join(img for _, img in images) + b"tail")
    assert build.missing_icon_images(with_icon) == []
    partial = tmp_path / "partial.exe"
    partial.write_bytes(b"MZ" + b"".join(img for w, img in images if w != 256))
    assert build.missing_icon_images(partial) == [256]
    plain = tmp_path / "electron.exe"
    plain.write_bytes(b"MZ default electron icon")
    assert build.missing_icon_images(plain) == [16, 20, 24, 32, 40, 48, 64, 128, 256]
    # 고정 Electron의 기본 아이콘은 확정 아이콘이 아니다 (검사가 빈 대조가 아님)
    if not NO_ELECTRON:
        assert build.missing_icon_images(build.ELECTRON_DIST / "electron.exe")


def test_check_app_running_hook_bounded_to_install_dir() -> None:
    """설치·제거의 앱 끄기는 설치 폴더 경계 안 프로세스만: 실행 파일 이름(taskkill /IM)이나 경계
    없는 앞부분 비교를 쓰지 않고, 확인할 수 없으면 멈춘다 (T13 검수 1차 High)."""
    nsh = build.NSIS_INCLUDE.read_text(encoding="utf-8")
    hook = nsh[
        nsh.index("!macro customCheckAppRunning") : nsh.index(
            "!macroend", nsh.index("!macro customCheckAppRunning")
        )
    ]
    procs = nsh[nsh.index("!macro kbInstallProcesses") :]
    assert 'w "$INSTDIR\\")' in procs  # 경계 \ 를 붙인 설치 폴더
    assert "StartsWith($$d" in nsh and "OrdinalIgnoreCase" in nsh
    code = "\n".join(line for line in nsh.splitlines() if not line.lstrip().startswith(";"))
    for banned in ("taskkill", "tasklist", "/IM", "nsProcess", "_CHECK_APP_RUNNING"):
        assert banned not in code, banned
    # 조회 결과가 있음(0)·없음(1)이 아니면 아무것도 끄지 않고 끝낸다
    assert "${If} $R0 != 0" in hook and "${AndIf} $R0 != 1" in hook and "Quit" in hook
    assert "Stop-Process" not in hook  # 끄기는 경계 안 PID만 고르는 kbInstallProcesses stop으로만


def _installer_job_uploads(ci: str) -> list[str]:
    """ci.yml installer 잡의 upload-artifact `path: |` 목록."""
    job = ci[ci.index("\n  installer:\n") :]
    end = re.search(r"\n  [a-z][\w-]*:\n", job[1:])
    job = job[: end.start() + 1] if end else job
    block = job[job.index("uses: actions/upload-artifact") :]
    lines = block[block.index("path: |") :].splitlines()[1:]
    out: list[str] = []
    for line in lines:
        if not line.startswith(" " * 12) or not line.strip():
            break
        out.append(line.strip())
    return out


def test_ci_installer_artifacts_match_build_outputs(tmp_path: Path) -> None:
    """CI가 올리는 고지문 등 필수 artifact 경로는 build.py가 실제로 만드는 위치와 같다
    (T13 검수 2차 Mid: 판별 트리로 바뀐 뒤 옛 electron/win-unpacked 경로가 남음)."""
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    uploads = _installer_job_uploads(ci)
    assert "uv run python -m installer.build --check-artifacts" in ci
    required = [p.relative_to(REPO_ROOT).as_posix() for p in build.ci_artifacts()]
    assert "build/installer/electron-product/win-unpacked/licenses/THIRD_PARTY_NOTICES.txt" in (
        required
    )
    # 필수 파일은 모두 업로드 목록(글롭 포함)에 걸리고, 제외 글롭(!)에 걸리지 않는다
    keep = [u for u in uploads if not u.startswith("!")]
    drop = [u[1:] for u in uploads if u.startswith("!")]
    for rel in required:
        assert any(PurePosixPath(rel).full_match(u) for u in keep), rel
        assert not any(PurePosixPath(rel).full_match(u) for u in drop), rel
    # 글롭이 아닌 업로드 경로는 전부 필수 목록이다 (옛 경로가 남지 않는다)
    literal = [u for u in keep if not any(c in u for c in "*?[")]
    assert sorted(literal) == sorted(r for r in required if r in literal)
    assert set(literal) <= set(required), set(literal) - set(required)
    # 트리 경로는 build_tree가 쓰는 tree_root 그대로, README의 명령도 그 경로다
    for variant in (build.PRODUCT, build.TEST):
        assert build.tree_root(build.DEFAULT_OUT, variant).parts[-2:] == (
            f"electron-{variant.key}",
            "win-unpacked",
        )
    readme = (REPO_ROOT / "tools" / "installer" / "README.md").read_text(encoding="utf-8")
    assert "electron/win-unpacked" not in readme
    assert "installer.dllcheck build/installer/electron-product/win-unpacked" in readme

    # --check-artifacts: 하나라도 없으면 1, 다 있으면 0
    out = tmp_path / "out"
    for path in build.ci_artifacts(out)[:-1]:
        write_tree(path.parent, {path.name: "x"})
    assert build.main(["--check-artifacts", "--out", str(out)]) == 1
    notices = build.ci_artifacts(out)[-1]
    write_tree(notices.parent, {notices.name: "x"})
    assert build.main(["--check-artifacts", "--out", str(out)]) == 0


def test_nsis_header_and_installer_script(tmp_path: Path) -> None:
    root = write_tree(
        tmp_path / "root", {"python/x.py": "x", "Kookabug.exe": b"MZ", "VERSION": "1"}
    )
    header = build.nsis_header(root)
    assert f"!define KB_MAX_REL_PATH {build.max_rel_path(root)}" in header
    assert '  RMDir /r "$INSTDIR\\python"' in header
    assert '  Delete "$INSTDIR\\Kookabug.exe"' in header
    assert f'!include "{build.NSIS_INCLUDE}"' in header
    bad = write_tree(tmp_path / "bad", {"a$b.txt": "x"})
    with pytest.raises(build.BuildError, match="NSIS"):
        build.nsis_header(bad)

    # 사용자별 설치만, elevate.exe 없음, zip 묶음(nsisunz)·차등 묶음 없음 (nsis7z = LGPL 7-Zip)
    yml = build.EB_CONFIG.read_text(encoding="utf-8")
    for line in (
        "oneClick: false",
        "perMachine: false",
        "allowElevation: false",
        "packElevateHelper: false",
        "useZip: true",
        "differentialPackage: false",
        "executableName: Kookabug",
    ):
        assert re.search(rf"^\s*{re.escape(line)}\s*$", yml, re.M), line

    # 기본 스크립트가 부르는 StdUtils(LGPL-2.1) 함수는 installer.nsh가 모두 바꿔 정의한다
    nsh = build.NSIS_INCLUDE.read_text(encoding="utf-8")
    redefined = set(re.findall(r"^!define (StdUtils\.\w+) ", nsh, re.M))
    assert {"StdUtils.TestParameter", "StdUtils.GetAllParameters"} <= redefined
    lib = REPO_ROOT / "node_modules" / ".pnpm"
    templates = sorted(lib.glob("app-builder-lib@*/node_modules/app-builder-lib/templates/nsis"))
    if templates:
        used: set[str] = set()
        for f in templates[-1].rglob("*.ns[hi]"):
            if f.name in ("StdUtils.nsh", "portable.nsi"):
                continue
            used |= set(re.findall(r"\$\{(StdUtils\.\w+)\}", f.read_text(encoding="utf-8")))
        # 웹 설치 파일 전용(HashFile·GetParameter)은 이 설치 파일에 컴파일되지 않는다.
        # TestParameter는 스크립트 생성기가 만드는 플래그 매크로(isUpdated 등)가 부른다
        assert used - {"StdUtils.HashFile", "StdUtils.GetParameter"} <= redefined


def test_install_mode_page_left_out(tmp_path: Path) -> None:
    """설치 범위(모든 사용자/나만) 화면은 넣지 않는다 (M2 사람 확인 S3 결함). 실제 설치 파일의 첫
    화면은 `test_installer_pages.py`."""
    root = write_tree(tmp_path / "root", {"Kookabug.exe": b"MZ"})
    marker = tmp_path / "nsis-test-pages.txt"
    header = build.nsis_header(root, marker=marker)
    assert header.index(f'!define KB_PAGE_MARKER "{marker}"') < header.index("!include")
    assert "KB_PAGE_MARKER" not in build.nsis_header(root)

    # 빌드는 설치·제거 프로그램 컴파일이 모두 빈 매크로를 거쳤다는 표식을 본다
    assert len(build.check_page_markers(marker)) == 2  # 표식 파일 없음
    marker.write_text("installer: no install mode page\n", encoding="utf-8")
    (problem,) = build.check_page_markers(marker)
    assert "uninstaller: no install mode page" in problem
    marker.write_text("".join(f"{m}\r\n" for m in build.PAGE_MARKERS), encoding="utf-8")
    assert build.check_page_markers(marker) == []

    # 기본 스크립트가 PAGE_INSTALL_MODE를 넣기 직전 훅에서 그 매크로를 빈 것으로 바꾼다
    nsh = build.NSIS_INCLUDE.read_text(encoding="utf-8")
    drop = re.search(r"^!macro kbDropInstallModePage\n(.*?)^!macroend", nsh, re.M | re.S)
    assert drop is not None
    assert "!macroundef PAGE_INSTALL_MODE" in drop.group(1)
    assert "no-install-mode-page.nsh" in drop.group(1)
    for hook in ("customWelcomePage", "customUnWelcomePage"):
        body = re.search(rf"^!macro {hook}\n(.*?)^!macroend", nsh, re.M | re.S)
        assert body is not None and "!insertmacro kbDropInstallModePage" in body.group(1), hook
    assert "customInstallMode" not in re.sub(r"^;.*$", "", nsh, flags=re.M)
    empty = (build.NSIS_INCLUDE.parent / "no-install-mode-page.nsh").read_text(encoding="utf-8")
    page = re.search(r"^!macro PAGE_INSTALL_MODE\n(.*?)^!macroend", empty, re.M | re.S)
    assert page is not None
    assert not re.search(r"^\s*(Page|PageEx|UninstPage)\b", page.group(1), re.M)

    lib = REPO_ROOT / "node_modules" / ".pnpm"
    templates = sorted(lib.glob("app-builder-lib@*/node_modules/app-builder-lib/templates/nsis"))
    if templates:
        # 훅이 PAGE_INSTALL_MODE보다 먼저 펼쳐지는 기본 스크립트 순서 (설치·제거 갈래 각각)
        text = (templates[-1] / "assistedInstaller.nsh").read_text(encoding="utf-8")
        installer, uninstaller = text.split("\n!else\n", 1)
        for part, hook in ((installer, "customWelcomePage"), (uninstaller, "customUnWelcomePage")):
            assert part.index(f"!insertmacro {hook}") < part.index("!insertmacro PAGE_INSTALL_MODE")


def write_asar(path: Path, files: dict[str, bytes]) -> None:
    """검사용 asar 묶음 (read_asar가 읽는 형식)."""
    tree: dict[str, object] = {"files": {}}
    body = b""
    for rel, data in files.items():
        node = tree
        parts = rel.split("/")
        for part in parts[:-1]:
            node = node["files"].setdefault(part, {"files": {}})  # type: ignore[index,union-attr]
        node["files"][parts[-1]] = {"size": len(data), "offset": str(len(body))}  # type: ignore[index]
        body += data
    header = json.dumps(tree).encode("utf-8")
    pickle = struct.pack("<I", len(header)) + header
    pickle += b"\0" * (-len(pickle) % 4)
    payload = struct.pack("<I", len(pickle)) + pickle
    path.write_bytes(struct.pack("<II", 4, len(payload)) + payload + body)


def test_release_bundle_has_no_e2e_hooks(tmp_path: Path) -> None:
    """배포 번들에 E2E 검사 전용 훅이 남아 있으면 빌드가 멈추고, 설치된 app.asar도 같은 검사로
    본다."""
    dist = write_tree(
        tmp_path / "dist",
        {
            "main/main.cjs": "manager.dropConnection(); session.hello",
            "main/main.cjs.map": "{}",
            "preload/preload.cjs": "bridge",
            "renderer/index.html": "<html>",
            "renderer/assets/app.js": "ui",
        },
    )
    files = build.prepare_app_dir(dist, tmp_path / "app", "0.1.0.dev0")
    assert files == [
        "dist/main/main.cjs",
        "dist/preload/preload.cjs",
        "dist/renderer/assets/app.js",
        "dist/renderer/index.html",
        "package.json",
    ]
    package = json.loads((tmp_path / "app/package.json").read_text(encoding="utf-8"))
    assert package["main"] == "dist/main/main.cjs" and package["version"] == "0.1.0-dev.0"
    assert "dependencies" not in package

    for marker in build.E2E_HOOK_MARKERS:
        (dist / "renderer/assets/app.js").write_text(f"x.{marker}", encoding="utf-8")
        with pytest.raises(build.BuildError, match="E2E 검사 훅"):
            build.prepare_app_dir(dist, tmp_path / "app", "0.1.0.dev0")

    # 설치된 묶음 읽기 (smoke bundle_step과 같은 함수)
    asar = tmp_path / "app.asar"
    write_asar(asar, {"package.json": b"{}", "dist/main/main.cjs": b"dropConnection __kookabugE2E"})
    read = build.read_asar(asar)
    assert read == {"package.json": b"{}", "dist/main/main.cjs": b"dropConnection __kookabugE2E"}
    assert build.e2e_hook_markers(read) == ["dist/main/main.cjs: __kookabugE2E"]
