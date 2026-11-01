"""M2 라이선스 정책: Electron ffmpeg.dll 고정 바이너리 한정 예외.

구현 계획 M2 2.14·U8, 계획 검수 M11.

예외는 배포물 판·설치 폴더 안 상대 경로·sha256 셋이 **모두** 맞는 파일 하나에서만 LGPL을 허용한다.
판정기는 거부 패턴보다 먼저 보되 하나라도 다르면 금지 그대로다. 같은 이름의 다른 DLL, Python 쪽
FFmpeg(opencv), 다른 LGPL 구성요소는 여전히 막힌다.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from packaging.utils import canonicalize_name

import license_audit as la
import native_audit as na
from kb_testing.audit_fixtures import POLICY_BASE, native_table, policy, write_tree

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
FFMPEG_SOURCE = TOOLS / "third_party_licenses" / "ffmpeg-SOURCE.txt"
FAKE_FFMPEG = b"MZ fake ffmpeg build"
SOURCE_REL = "licenses/ffmpeg-SOURCE.txt"
ELECTRON = {"electron": "44.8.0"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_tree(
    root: Path, rel: str = "ffmpeg.dll", data: bytes = FAKE_FFMPEG, *, source: bool = True
) -> Path:
    files: dict[str, str | bytes] = {
        rel: data,
        "licenses/ffmpeg-LGPL.txt": "GNU LESSER GENERAL PUBLIC LICENSE Version 2.1",
        "credits.txt": "opus: Copyright Xiph.Org",
    }
    if source:
        files[SOURCE_REL] = "ffmpeg 2b68d2babae73714846961fb0ee47e3b3d2e39a9"
    return write_tree(root, files)


def entry(
    glob: str = "ffmpeg.dll",
    package: str = "electron",
    license: str = "LGPL-2.1-or-later AND BSD-3-Clause",
) -> dict[str, Any]:
    return {
        "scope": "install",
        "glob": glob,
        "package": package,
        "license": license,
        "reason": "검사용",
        "texts": [
            {
                "path": "licenses/ffmpeg-LGPL.txt",
                "covers": ["LGPL-2.1-or-later", "LGPL-3.0-only"],
                "expect": ["Version 2.1"],
            },
            {"path": "credits.txt", "covers": ["BSD-3-Clause"], "expect": ["Xiph.Org"]},
        ],
    }


def pinned_policy(digest: str, **overrides: str) -> la.Policy:
    item = {
        "package": "electron",
        "version": "44.8.0",
        "path": "ffmpeg.dll",
        "sha256": digest,
        "license": "LGPL-2.1-or-later",
        "reason": "검사용",
        "source": SOURCE_REL,
        **overrides,
    }
    return la.load_policy({**POLICY_BASE, "pinned_binary": [item]})


def audit(
    root: Path,
    pol: la.Policy,
    entries: list[dict[str, Any]] | None = None,
    versions: dict[str, str] | None = None,
) -> na.NativeReport:
    table = native_table(entries if entries is not None else [entry()])
    return na.audit_build_input(
        na.Layout.install(root), table, pol, versions=ELECTRON if versions is None else versions
    )


def denied(report: na.NativeReport, rel: str) -> bool:
    return any(
        p.startswith(f"[네이티브 라이선스] install:{rel}:") and "금지 라이선스" in p
        for p in report.problems
    )


def test_ffmpeg_exception_requires_version_path_and_hash(tmp_path: Path) -> None:
    # 셋이 다 맞으면 허용: 문제 없음, 예외로 허용한 파일로 남고 NOTICES에 예외 절이 생긴다
    root = make_tree(tmp_path / "ok")
    report = audit(root, pinned_policy(sha(FAKE_FFMPEG)))
    assert report.problems == []
    assert [(nf.rel, pin.version) for nf, pin in report.pinned] == [("ffmpeg.dll", "44.8.0")]
    notices = "\n".join(report.notice_sections)
    assert "# 고정 바이너리 한정 라이선스 예외" in notices and sha(FAKE_FFMPEG) in notices

    # 판만 다르다 (실제 배포물 판이 다르거나 읽지 못함)
    for versions in ({"electron": "45.0.0"}, {}):
        report = audit(root, pinned_policy(sha(FAKE_FFMPEG)), versions=versions)
        assert denied(report, "ffmpeg.dll") and report.pinned == [], versions
    # 예외 항목의 판이 다르다
    assert denied(audit(root, pinned_policy(sha(FAKE_FFMPEG), version="44.7.0")), "ffmpeg.dll")

    # 경로만 다르다: 같은 바이트가 다른 위치에 있다 (표 항목은 어디든 맞게)
    moved = make_tree(tmp_path / "moved", rel="resources/ffmpeg.dll")
    report = audit(moved, pinned_policy(sha(FAKE_FFMPEG)), [entry(glob="**/ffmpeg.dll")])
    assert denied(report, "resources/ffmpeg.dll") and report.pinned == []

    # 해시만 다르다: 같은 판·같은 위치의 다른 바이트
    other = make_tree(tmp_path / "other", data=FAKE_FFMPEG + b"!")
    report = audit(other, pinned_policy(sha(FAKE_FFMPEG)))
    assert denied(report, "ffmpeg.dll") and report.pinned == []

    # 대응 소스 정보 산출물이 설치 트리에 없으면 예외가 맞아도 실패다
    nosource = make_tree(tmp_path / "nosource", source=False)
    report = audit(nosource, pinned_policy(sha(FAKE_FFMPEG)))
    assert any(p.startswith("[예외 근거 산출물 없음] install:ffmpeg.dll") for p in report.problems)


def test_same_name_other_dll_denied(tmp_path: Path) -> None:
    pol = pinned_policy(sha(FAKE_FFMPEG))
    # 같은 이름·같은 위치지만 다른 배포물의 파일(표 항목 package가 다름)이면 예외가 맞지 않는다
    root = make_tree(tmp_path / "pkg")
    assert denied(audit(root, pol, [entry(package="other-app")]), "ffmpeg.dll")
    # 같은 이름의 다른 DLL(내용이 다름)
    root = make_tree(tmp_path / "content", data=b"MZ another ffmpeg")
    assert denied(audit(root, pol), "ffmpeg.dll")
    # 다른 폴더의 같은 이름 DLL은 표에도 없다 (실제 표의 ffmpeg.dll 항목은 설치 폴더 맨 위만)
    real = na.load_native_table_file(TOOLS / "native-licenses.toml")
    assert na.find_entry(real, na.INSTALL, "ffmpeg.dll") is not None
    for rel in ("python/ffmpeg.dll", "resources/ffmpeg.dll", "bin/ffmpeg.dll"):
        assert na.find_entry(real, na.INSTALL, rel) is None, rel


def test_opencv_ffmpeg_still_denied(tmp_path: Path) -> None:
    """Python 쪽 FFmpeg(opencv의 videoio 플러그인)는 예외와 무관하게 금지다. 예외 항목이 그 파일의
    해시를 가리켜도 배포물·경로가 다르므로 맞지 않는다."""
    data = b"MZ opencv ffmpeg"
    rel = "cv2/opencv_videoio_ffmpeg500_64.dll"
    real = na.load_native_table_file(TOOLS / "native-licenses.toml")
    found = na.find_entry(real, na.SITE_PACKAGES, rel)
    assert found is not None and found.package == "opencv-python"
    pol = pinned_policy(sha(data), path=f"{na.SITE_PACKAGES_IN_INSTALL}/{rel}")
    for p in (policy(), pol):
        assert na.judge_entry(found, real, p)[0] is la.Status.DENIED
        # 최종 트리에 남으면 제거 대상 남음 + 금지 라이선스로 실패, 예외로 허용되지 않는다
        tree = write_tree(tmp_path / f"tree-{len(p.pinned)}" / na.SITE_PACKAGES_IN_INSTALL, {})
        write_tree(tree, {rel: data})
        report = na.audit_final_tree(tree.parents[2], real, p, versions=ELECTRON)
        assert report.pinned == []
        assert any(q.startswith(f"[제거 대상 남음] site-packages:{rel}") for q in report.problems)
        assert any(
            q.startswith(f"[네이티브 라이선스] site-packages:{rel}") and "금지 라이선스" in q
            for q in report.problems
        )


def test_other_lgpl_component_denied(tmp_path: Path) -> None:
    pol = pinned_policy(sha(FAKE_FFMPEG))
    # 같은 배포물(electron)의 다른 LGPL DLL: 예외 경로가 아니다
    root = make_tree(tmp_path / "lib", rel="libfoo.dll")
    assert denied(audit(root, pol, [entry(glob="libfoo.dll")]), "libfoo.dll")
    # 예외 파일이어도 예외 라이선스(LGPL-2.1-or-later) 밖의 금지 구성요소가 식에 있으면 금지
    root = make_tree(tmp_path / "v3")
    report = audit(root, pol, [entry(license="LGPL-2.1-or-later AND LGPL-3.0-only")])
    assert denied(report, "ffmpeg.dll") and report.pinned == []
    # 패키지 메타데이터 판정에는 고정 바이너리 예외가 쓰이지 않는다 (일반 예외로도 우회 불가)
    real = policy()
    assert la.judge_package(canonicalize_name("electron"), "LGPL-2.1-or-later", real).ok is False
    exc = la.load_policy(
        {**POLICY_BASE, "exceptions": {"foo": {"license": "LGPL-2.1-or-later", "reason": "x"}}}
    )
    assert la.judge_package(canonicalize_name("foo"), "LGPL-2.1-or-later", exc).ok is False


def test_exception_checked_before_denied_pattern_only_when_exact() -> None:
    real = policy()
    lgpl = "LGPL-2.1-or-later"
    # 거부 패턴에 걸리는 식도 맞은 예외의 잎이면 허용 (거부 패턴보다 먼저)
    assert la.classify_license(lgpl, real)[0] is la.Status.DENIED
    assert la.classify_license(lgpl, real, pinned_ok=frozenset({lgpl}))[0] is la.Status.ALLOWED
    # 정확히 그 잎만: 다른 LGPL 판·GPL은 그대로 금지
    for other in ("LGPL-2.1-only", "LGPL-3.0-or-later", "GPL-2.0-or-later"):
        assert la.classify_license(other, real, pinned_ok=frozenset({lgpl}))[0] is la.Status.DENIED
    assert la.classify_license(f"{lgpl} AND MIT", real, pinned_ok=frozenset({lgpl}))[0] is (
        la.Status.ALLOWED
    )

    # 실제 정책: ffmpeg.dll 하나, 판은 앱의 Electron 고정판, 경로는 설치 폴더 맨 위
    assert len(real.pinned) == 1
    pin = real.pinned[0]
    desktop = json.loads((REPO_ROOT / "apps/desktop/package.json").read_text(encoding="utf-8"))
    assert (pin.package, pin.path, pin.license) == ("electron", "ffmpeg.dll", lgpl)
    assert pin.version == desktop["devDependencies"]["electron"]
    assert pin.source == SOURCE_REL and pin.leaves == frozenset({lgpl})

    # 정책 파일 검사: 셋 중 하나라도 빠지거나 틀린 항목은 읽지 않는다
    base = {
        "package": "electron",
        "version": "44.8.0",
        "path": "ffmpeg.dll",
        "sha256": "0" * 64,
        "license": lgpl,
        "reason": "r",
        "source": SOURCE_REL,
    }
    bad: list[dict[str, str]] = [
        {"sha256": "abc"},
        {"sha256": ""},
        {"version": ""},
        {"path": "C:/x/ffmpeg.dll"},
        {"path": "/ffmpeg.dll"},
        {"path": "../ffmpeg.dll"},
        {"path": "a\\ffmpeg.dll"},
        {"source": ""},
        {"license": "LicenseRef-x"},
        {"license": ""},
    ]
    for override in bad:
        with pytest.raises(la.AuditInputError):
            la.load_policy({**POLICY_BASE, "pinned_binary": [{**base, **override}]})


def test_ffmpeg_source_file_present_with_pinned_refs() -> None:
    """대응 소스·패치·빌드 정보: 판 고정 URL·커밋이 있고 Chromium 첫 화면 링크만이 아니다."""
    text = FFMPEG_SOURCE.read_text(encoding="utf-8")
    pin = policy().pinned[0]
    assert pin.sha256 in text
    commits = set(re.findall(r"\b[0-9a-f]{40}\b", text))
    # FFmpeg 리비전(Chromium DEPS)과 Electron 커밋
    assert "2b68d2babae73714846961fb0ee47e3b3d2e39a9" in commits
    assert "60169b45c12488c6fda237af7f6425526a7ce5f0" in commits
    ffmpeg_url = (
        "https://chromium.googlesource.com/chromium/third_party/ffmpeg/+/"
        "2b68d2babae73714846961fb0ee47e3b3d2e39a9"
    )
    assert ffmpeg_url in text
    assert f"https://github.com/electron/electron/tree/v{pin.version}" in text
    assert "https://chromium.googlesource.com/chromium/src/+/refs/tags/152.0.7977.167" in text
    # 패치·빌드 설정도 판 고정 주소
    for path in ("patches/ffmpeg/.patches", "build/args/all.gn", "build/args/release.gn"):
        assert f"https://github.com/electron/electron/blob/v{pin.version}/{path}" in text, path
    assert "chromium/config/Chrome/win/x64/config.h" in text and "CONFIG_GPL 0" in text
    assert "제공 방법" in text
    # 첫 화면 링크(source.chromium.org 등)만으로 대신하지 않는다: 소스를 보여 주는 주소는 모두
    # 커밋·태그로 고정돼 있다 (git clone 주소는 바로 다음 줄이 커밋으로 checkout 한다)
    assert "source.chromium.org" not in text
    browse = [u for u in re.findall(r"https://\S+", text) if re.search(r"/\+/|/blob/|/tree/", u)]
    assert browse and all(
        re.search(r"/\+/[0-9a-f]{40}|/\+/refs/tags/\d|/(blob|tree)/v\d+\.\d+\.\d+", u)
        for u in browse
    ), browse
    assert "checkout 2b68d2babae73714846961fb0ee47e3b3d2e39a9" in text
    # 표가 그 파일을 원문으로 요구한다 (설치 트리에 없으면 감사 실패)
    table = na.load_native_table_file(TOOLS / "native-licenses.toml")
    ff = na.find_entry(table, na.INSTALL, "ffmpeg.dll")
    assert ff is not None and any(t.path == SOURCE_REL for t in ff.texts)
