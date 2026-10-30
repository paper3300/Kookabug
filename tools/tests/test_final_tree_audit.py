"""빌드 입력 감사와 최종 설치 트리 감사의 분리, RECORD 대조 (구현 계획 M1 2.12, 검수 14)."""

import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

import native_audit as na
from kb_testing.audit_fixtures import native_table, policy, write_record, write_tree

SITE = na.SITE_PACKAGES_IN_INSTALL
FFMPEG = "cv2/opencv_videoio_ffmpeg500_64.dll"
TABLE = native_table(
    native=[
        {
            "glob": "cv2/opencv_videoio_ffmpeg*.dll",
            "package": "opencv-python",
            "license": "LGPL-2.1-or-later",
            "reason": "제거 대상",
        },
        {
            "glob": "cv2/cv2.pyd",
            "package": "opencv-python",
            "license": "Apache-2.0 AND BSD-3-Clause",
            "texts": [
                {
                    "path": "cv2/LICENSE.txt",
                    "covers": ["Apache-2.0", "BSD-3-Clause"],
                    "expect": ["Apache"],
                }
            ],
            "reason": "OpenCV",
        },
        {
            "scope": "install",
            "glob": "python/**/*.{exe,dll}",
            "package": "python-build-standalone",
            "license": "PSF-2.0",
            "texts": [{"path": "python/LICENSE.txt", "covers": ["PSF-2.0"], "expect": ["PSF"]}],
            "reason": "CPython",
        },
    ],
    strip=[
        {"glob": "cv2/opencv_videoio_ffmpeg*.dll", "reason": "FFmpeg (LGPL)"},
        {"scope": "install", "origin": "pbs", "glob": "python/Lib/idlelib", "reason": "IDLE"},
    ],
)


def _install_tree(root: Path, *, ffmpeg: bool, record_ffmpeg: bool | None = None) -> Path:
    files: dict[str, str | bytes] = {
        "python/python.exe": b"MZ",
        "python/LICENSE.txt": "PSF",
        f"{SITE}/cv2/cv2.pyd": b"MZ",
        f"{SITE}/cv2/__init__.py": "",
        f"{SITE}/cv2/LICENSE.txt": "Apache",
        f"{SITE}/opencv_python-5.0.0.93.dist-info/METADATA": "Name: opencv-python",
    }
    if ffmpeg:
        files[f"{SITE}/{FFMPEG}"] = b"MZ"
    write_tree(root, files)
    site = root / SITE
    write_record(site, "opencv_python-5.0.0.93", ["cv2"])
    if record_ffmpeg if record_ffmpeg is not None else ffmpeg:
        record = site / "opencv_python-5.0.0.93.dist-info/RECORD"
        record.write_text(record.read_text("utf-8") + f"{FFMPEG},sha256=x,1\n", encoding="utf-8")
    # compileall이 만든 .pyc는 RECORD에 없어도 된다
    write_tree(site, {"cv2/__pycache__/__init__.cpython-314.pyc": b"\0"})
    return root


def _final(root: Path) -> list[str]:
    return na.audit_final_tree(root, TABLE, policy()).problems


def test_denied_file_present_fails_even_if_listed_for_strip(tmp_path: Path) -> None:
    root = _install_tree(tmp_path / "install", ffmpeg=True)
    problems = _final(root)
    assert any(p.startswith(f"[제거 대상 남음] site-packages:{FFMPEG}") for p in problems)
    assert any(
        p.startswith(f"[네이티브 라이선스] site-packages:{FFMPEG}") and "금지" in p
        for p in problems
    )

    # 같은 파일이 빌드 입력에서는 "제거 목록에 있음"으로만 허용된다 (참고로 남는다)
    report = na.audit_build_input(na.Layout.site_packages(root / SITE), TABLE, policy())
    assert report.problems == []
    assert any(n.startswith(f"[제거 대상] site-packages:{FFMPEG}") for n in report.notes)


def test_denied_file_present_without_strip_rule_fails_in_build_input(tmp_path: Path) -> None:
    root = _install_tree(tmp_path / "install", ffmpeg=True)
    no_strip = native_table(
        native=[
            {
                "glob": "cv2/opencv_videoio_ffmpeg*.dll",
                "package": "opencv-python",
                "license": "LGPL-2.1-or-later",
                "reason": "x",
            },
            {"glob": "cv2/*.pyd", "package": "opencv-python", "license": "MIT", "reason": "x"},
        ]
    )
    report = na.audit_build_input(na.Layout.site_packages(root / SITE), no_strip, policy())
    assert any(p.startswith(f"[네이티브 라이선스] site-packages:{FFMPEG}") for p in report.problems)


def test_denied_file_absent_and_listed_passes(tmp_path: Path) -> None:
    root = _install_tree(tmp_path / "install", ffmpeg=False)
    assert _final(root) == []


def test_record_lists_missing_file_fails(tmp_path: Path) -> None:
    root = _install_tree(tmp_path / "install", ffmpeg=False)
    (root / SITE / "cv2/__init__.py").unlink()
    (root / SITE / "cv2/__pycache__/__init__.cpython-314.pyc").unlink()
    assert _final(root) == [
        "[RECORD에 있는데 없음] opencv_python-5.0.0.93.dist-info: cv2/__init__.py"
    ]


def test_file_not_in_record_fails(tmp_path: Path) -> None:
    root = _install_tree(tmp_path / "install", ffmpeg=False)
    write_tree(root / SITE, {"cv2/extra.py": "", "stray.pth": ""})
    assert sorted(_final(root)) == [
        "[RECORD에 없는 파일] site-packages:cv2/extra.py",
        "[RECORD에 없는 파일] site-packages:stray.pth",
    ]


def test_stripped_file_still_in_record_fails(tmp_path: Path) -> None:
    # 파일은 지웠는데 RECORD 줄은 남은 경우
    root = _install_tree(tmp_path / "install", ffmpeg=False, record_ffmpeg=True)
    assert _final(root) == [
        f"[RECORD에 제거한 파일] opencv_python-5.0.0.93.dist-info: {FFMPEG} — "
        "제거한 파일의 줄도 RECORD에서 지워야 한다"
    ]


def test_strip_glob_matching_nothing_is_reported(tmp_path: Path) -> None:
    # 새 버전에서 FFmpeg DLL 이름이 바뀌어 제거 glob이 빗나간 빌드 입력
    site = write_tree(
        tmp_path / "site",
        {"cv2/cv2.pyd": b"MZ", "cv2/LICENSE.txt": "Apache", "cv2/videoio_plugin_ffmpeg.dll": b"MZ"},
    )
    report = na.audit_build_input(na.Layout.site_packages(site), TABLE, policy())
    assert (
        "[제거 목록 빗나감] site-packages:cv2/opencv_videoio_ffmpeg*.dll: 빌드 입력에 맞는 "
        "파일이 없다 (버전이 바뀌어 이름이 달라졌는지 확인)"
    ) in report.problems
    assert not any("빗나감" in n for n in report.notes)
    # 이름이 바뀐 DLL은 표 항목도 없어 따로 실패한다
    assert any(
        p.startswith("[네이티브 표 없음] site-packages:cv2/videoio_plugin_ffmpeg.dll")
        for p in report.problems
    )


def test_pbs_strip_rules_checked_only_when_pbs_is_an_input(tmp_path: Path) -> None:
    root = _install_tree(tmp_path / "install", ffmpeg=True)
    layout = na.Layout.install(root)
    wheel_only = na.audit_build_input(layout, TABLE, policy())
    assert not any("idlelib" in p for p in wheel_only.problems)
    with_pbs = na.audit_build_input(layout, TABLE, policy(), origins=("wheel", "pbs"))
    assert any(
        p.startswith("[제거 목록 빗나감] install:python/Lib/idlelib") for p in with_pbs.problems
    )

    # 최종 트리에 남은 제거 대상 폴더는 그 아래 파일마다 실패
    write_tree(root, {"python/Lib/idlelib/idle.py": ""})
    assert any(
        p.startswith("[제거 대상 남음] install:python/Lib/idlelib/idle.py") for p in _final(root)
    )


def _unreadable(monkeypatch: pytest.MonkeyPatch, *dirs: Path) -> None:
    """그 폴더의 열거만 실패하게 한다 (실제 ACL은 건드리지 않는다)."""
    original = os.scandir
    blocked = {d.resolve() for d in dirs}

    def scandir(path: Any = ".") -> Any:
        if Path(path).resolve() in blocked:
            raise PermissionError(13, "접근 거부 (주입)", str(path))
        return original(path)

    monkeypatch.setattr(os, "scandir", scandir)


@pytest.mark.parametrize("where", ["install", "site-packages"])
def test_unreadable_directory_fails_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """검수 반례 unreadable_directory: 읽지 못한 폴더 안의 DLL이 판정 없이 통과하지 않는다."""
    root = _install_tree(tmp_path / "install", ffmpeg=False)
    if where == "install":
        hidden = root / "python/DLLs"
        write_tree(root, {"python/DLLs/unreviewed.pyd": b"MZ"})
    else:
        hidden = root / SITE / "vendor"
        write_tree(root / SITE, {"vendor/unreviewed.pyd": b"MZ"})
    readable = _final(root)
    assert any(p.startswith("[네이티브 표 없음]") and "unreviewed" in p for p in readable)

    _unreadable(monkeypatch, hidden)
    final = _final(root)
    expected = f"[읽을 수 없는 폴더] {hidden}: 접근 거부 (주입)"
    assert final.count(expected) == 1, final
    build = na.audit_build_input(na.Layout.install(root), TABLE, policy()).problems
    assert expected in build
    # 오류를 모을 곳이 없으면 예외로 올린다
    with pytest.raises(PermissionError):
        list(na.iter_files(na.Layout.install(root)))


def test_missing_models_dir_fails_final_tree(tmp_path: Path) -> None:
    """검수 반례 external_model의 다른 면: 모델 폴더가 없는 설치본은 통과하지 않는다."""
    root = _install_tree(tmp_path / "install", ffmpeg=False)
    data = b"model"
    models = na.load_model_table(
        {
            "model": [
                {
                    "file": "det.onnx",
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                    "license": "Apache-2.0",
                    "source": "x",
                }
            ]
        }
    )
    # 설치본 밖에 같은 파일이 있어도 쓰지 않는다
    write_tree(tmp_path, {"det.onnx": data})
    report = na.audit_final_tree(root, TABLE, policy(), models=models)
    assert report.problems == [f"[모델 폴더 없음] {na.MODELS_IN_INSTALL}"]

    write_tree(root, {f"{na.MODELS_IN_INSTALL}/det.onnx": data})
    assert na.audit_final_tree(root, TABLE, policy(), models=models).problems == []


def test_missing_install_root_fails(tmp_path: Path) -> None:
    assert _final(tmp_path / "nowhere")[0] == f"[설치 폴더 없음] {tmp_path / 'nowhere'}"
