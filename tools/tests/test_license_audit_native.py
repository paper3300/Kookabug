"""네이티브 파일 감사: 표 항목·구성요소별 식·구성요소 원문·SBOM·NOTICES (구현 계획 M1 2.12)."""

import hashlib
import json
import sysconfig
from pathlib import Path

import pytest

import license_audit as la
import native_audit as na
from kb_testing.audit_fixtures import native_table, policy, write_tree

GCC = "GPL-3.0-or-later WITH GCC-exception-3.1"
OPENBLAS_TEXT = {
    "path": "numpy-*.dist-info/licenses/LICENSE.txt",
    "covers": ["BSD-3-Clause", "BSD-3-Clause-Open-MPI", GCC],
    "expect": ["Name: OpenBLAS", "GCC RUNTIME LIBRARY EXCEPTION"],
}
OPENBLAS_ENTRY = {
    "glob": "numpy.libs/libscipy_openblas*.dll",
    "package": "numpy",
    "license": f"BSD-3-Clause AND BSD-3-Clause-Open-MPI AND {GCC}",
    "components": "OpenBLAS, LAPACK, GCC 런타임",
    "texts": [OPENBLAS_TEXT],
    "reason": "numpy LICENSE.txt",
}
NUMPY_TREE = {
    "numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll": b"MZ",
    "numpy.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll": b"MZ",
    "numpy/_core/_multiarray_umath.cp314-win_amd64.pyd": b"MZ",
    "numpy-2.5.4.dist-info/licenses/LICENSE.txt": (
        "Copyright NumPy Developers\nName: OpenBLAS\nOPENBLAS TEXT\n"
        "GCC RUNTIME LIBRARY\nEXCEPTION\n"
    ),
    "numpy-2.5.4.dist-info/licenses/numpy/libdivide/LICENSE.txt": "zlib License\n",
}
VC_REF = {
    "LicenseRef-MS-VC-Redist": {
        "name": "VC++ 재배포",
        "source": "https://example.invalid/terms",
        "reason": "수정 없이 재배포",
        "notice": "VC 고지문",
    }
}
NUMPY_TABLE = [
    OPENBLAS_ENTRY,
    {
        "glob": "numpy.libs/msvcp140-*.dll",
        "package": "numpy",
        "license": "LicenseRef-MS-VC-Redist",
        "reason": "VC++ (고지문 있는 LicenseRef는 그 고지문으로 덮인다)",
    },
    {
        "glob": "numpy/**/*.pyd",
        "package": "numpy",
        "license": "BSD-3-Clause AND Zlib",
        "texts": [
            {
                "path": "numpy-*.dist-info/licenses/**/*",
                "covers": ["BSD-3-Clause", "Zlib"],
                "expect": ["NumPy Developers", "zlib License"],
            }
        ],
        "reason": "numpy 메타데이터",
    },
]
VENDOR_DLL = {"vendor/runtime.dll": b"MZ"}


def _audit(
    site: Path,
    table: na.NativeTable,
    models: list[na.ModelEntry] | None = None,
    models_dir: Path | None = None,
) -> na.NativeReport:
    return na.audit_build_input(
        na.Layout.site_packages(site), table, policy(), models=models, models_dir=models_dir
    )


def _vendor(license: str, texts: list[dict[str, object]], **extra: object) -> dict[str, object]:
    return {
        "glob": "vendor/runtime.dll",
        "package": "vendor",
        "license": license,
        "texts": texts,
        "reason": "fixture",
        **extra,
    }


def test_native_file_without_entry_fails(tmp_path: Path) -> None:
    site = write_tree(tmp_path / "site", {**NUMPY_TREE, "mystery/_ext.cp314-win_amd64.pyd": b"MZ"})
    report = _audit(site, native_table(NUMPY_TABLE, refs=VC_REF))
    assert report.problems == [
        "[네이티브 표 없음] site-packages:mystery/_ext.cp314-win_amd64.pyd: "
        "tools/native-licenses.toml에 구성요소별 라이선스를 적어야 한다"
    ]
    # exe도 네이티브 파일이다
    write_tree(site, {"mystery/tool.EXE": b"MZ"})
    problems = _audit(site, native_table(NUMPY_TABLE, refs=VC_REF)).problems
    assert any("mystery/tool.EXE" in p for p in problems)


def test_entry_glob_matches_hashed_names(tmp_path: Path) -> None:
    site = write_tree(tmp_path / "site", NUMPY_TREE)
    report = _audit(site, native_table(NUMPY_TABLE, refs=VC_REF))
    assert report.problems == []
    by_rel = {nf.rel: nf.entry for nf in report.files}
    assert (
        by_rel["numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll"]
        == na.load_native_table({"native": [OPENBLAS_ENTRY]}).entries[0]
    )
    assert by_rel["numpy.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll"] is not None

    # 대소문자 무시, `**`는 0개 이상 폴더, 중괄호는 고르기
    assert na.glob_match("NumPy.libs/LIBSCIPY_openblas64_-AB.dll", OPENBLAS_ENTRY["glob"])
    assert na.glob_match("numpy/x.pyd", "numpy/**/*.pyd")
    assert na.glob_match("numpy/a/b/x.pyd", "numpy/**/*.pyd")
    assert na.glob_match("python/python3.dll", "python/{python.exe,python3.dll}")
    assert not na.glob_match("numpy.libs/libopenblas.dll", OPENBLAS_ENTRY["glob"])
    assert not na.glob_match("other/numpy.libs/libscipy_openblas.dll", OPENBLAS_ENTRY["glob"])


@pytest.mark.parametrize(
    ("package", "license", "ok"),
    [
        ("numpy", f"BSD-3-Clause AND BSD-3-Clause-Open-MPI AND {GCC}", True),
        # 세 부분 중 하나만 허용 밖이어도 실패
        ("numpy", f"BSD-3-Clause AND Foo-1.0 AND {GCC}", False),
        ("numpy", f"BSD-3-Clause AND BSD-3-Clause-Open-MPI AND {GCC} AND LGPL-2.1-only", False),
        ("numpy", "BSD-3-Clause AND BSD-3-Clause-Open-MPI AND GPL-3.0-or-later", False),
        # GCC 예외는 numpy 한정
        ("other-blas", f"BSD-3-Clause AND BSD-3-Clause-Open-MPI AND {GCC}", False),
    ],
)
def test_component_expression_all_parts_checked(
    tmp_path: Path, package: str, license: str, ok: bool
) -> None:
    site = write_tree(tmp_path / "site", NUMPY_TREE)
    entry = {**OPENBLAS_ENTRY, "package": package, "license": license}
    report = _audit(site, native_table([entry, *NUMPY_TABLE[1:]], refs=VC_REF))
    problems = [p for p in report.problems if "openblas" in p]
    assert (problems == []) is ok, report.problems
    if not ok:
        assert problems[0].startswith("[네이티브 라이선스]")


def test_missing_evidence_fails(tmp_path: Path) -> None:
    tree = {k: v for k, v in NUMPY_TREE.items() if "LICENSE" not in k}
    site = write_tree(tmp_path / "site", tree)
    report = _audit(site, native_table(NUMPY_TABLE, refs=VC_REF))
    assert any(p.startswith("[근거 원문 없음] numpy") for p in report.problems)


def test_component_without_text_fails(tmp_path: Path) -> None:
    """검수 반례 no_component_evidence: 원문 없이 구성요소 식만 적은 항목은 통과하지 않는다."""
    site = write_tree(
        tmp_path / "site", {**VENDOR_DLL, "vendor-1.0.dist-info/LICENSE": "MIT by Vendor"}
    )
    mit = {"path": "vendor-*.dist-info/LICENSE", "covers": ["MIT"], "expect": ["Vendor"]}

    none = _audit(site, native_table([_vendor("MIT AND Unicode-3.0", [])]))
    assert none.problems == [
        "[구성요소 원문 없음] vendor vendor/runtime.dll: MIT, Unicode-3.0의 원문이 texts에 없다"
    ]
    # 자기 LICENSE(MIT)만 있으면 정적으로 들어간 Unicode-3.0 구성요소의 원문이 빠진 것
    partial = _audit(site, native_table([_vendor("MIT AND Unicode-3.0", [mit])]))
    assert partial.problems == [
        "[구성요소 원문 없음] vendor vendor/runtime.dll: Unicode-3.0의 원문이 texts에 없다"
    ]
    # OR는 고른 쪽 하나만 있으면 된다
    either = _audit(site, native_table([_vendor("MIT AND (MIT OR Apache-2.0)", [mit])]))
    assert either.problems == []
    # 검수 반례 r2_inconsistent_or_choice: 허용된 쪽(MIT) 원문 없이 금지된 쪽(GPL) 원문만으로는
    # OR를 채우지 못한다. 허용 판정과 원문 판정이 같은 선택지를 써야 한다
    gpl = {"path": "vendor-*.dist-info/LICENSE", "covers": ["GPL-3.0-only"], "expect": ["Vendor"]}
    wrong_branch = _audit(site, native_table([_vendor("MIT OR GPL-3.0-only", [gpl])]))
    assert wrong_branch.problems == [
        "[구성요소 원문 없음] vendor vendor/runtime.dll: MIT, "
        "GPL-3.0-only(허용 밖이라 선택지가 될 수 없음)의 원문이 texts에 없다"
    ]
    assert _audit(site, native_table([_vendor("MIT OR GPL-3.0-only", [mit])])).problems == []
    # 조건부(MPL-2.0)는 네이티브 항목 reason으로 허용되는 선택지다
    mpl = {"path": "vendor-*.dist-info/LICENSE", "covers": ["MPL-2.0"], "expect": ["Vendor"]}
    assert _audit(site, native_table([_vendor("MPL-2.0 OR Foo-1.0", [mpl])])).problems == []
    # 같은 GCC WITH 원문이라도 numpy 밖 패키지에서는 선택지가 아니다
    gcc = {"path": "vendor-*.dist-info/LICENSE", "covers": [GCC], "expect": ["Vendor"]}
    gcc_entry = _vendor(f"MIT OR {GCC}", [gcc])
    assert _audit(site, native_table([gcc_entry])).problems == [
        f"[구성요소 원문 없음] vendor vendor/runtime.dll: MIT, "
        f"{GCC}(허용 밖이라 선택지가 될 수 없음)의 원문이 texts에 없다"
    ]
    assert _audit(site, native_table([{**gcc_entry, "package": "numpy"}])).problems == [], (
        "numpy 한정 예외 문맥에서는 GCC 쪽이 선택지"
    )
    # 고지문 없는 LicenseRef는 원문이 있어야 한다
    ref = {"LicenseRef-X": {"name": "x", "source": "s", "reason": "r"}}
    no_notice = _audit(site, native_table([_vendor("LicenseRef-X", [])], refs=ref))
    assert no_notice.problems == [
        "[구성요소 원문 없음] vendor vendor/runtime.dll: LicenseRef-X의 원문이 texts에 없다"
    ]


def test_text_must_contain_expected_phrases(tmp_path: Path) -> None:
    # 엉뚱한 파일(다른 구성요소의 원문)을 가리키면 글귀 확인에서 걸린다
    site = write_tree(
        tmp_path / "site", {**VENDOR_DLL, "vendor-1.0.dist-info/LICENSE": "MIT by Vendor"}
    )
    text = {
        "path": "vendor-*.dist-info/LICENSE",
        "covers": ["MIT", "Unicode-3.0"],
        "expect": ["Vendor", "UNICODE LICENSE V3"],
    }
    report = _audit(site, native_table([_vendor("MIT AND Unicode-3.0", [text])]))
    assert report.problems == [
        "[근거 원문 불일치] vendor vendor/runtime.dll: vendor-*.dist-info/LICENSE에 "
        "'UNICODE LICENSE V3'가 없다"
    ]


def test_repo_text_file_is_checked_and_included(tmp_path: Path) -> None:
    site = write_tree(tmp_path / "site", VENDOR_DLL)
    repo = write_tree(tmp_path / "repo", {"texts/unicode.txt": "UNICODE LICENSE V3\nUnicode, Inc."})
    text = {"file": "texts/unicode.txt", "covers": ["Unicode-3.0"], "expect": ["Unicode, Inc."]}
    table = na.load_native_table({"native": [_vendor("Unicode-3.0", [text])]}, base_dir=repo)
    report = _audit(site, table)
    assert report.problems == []
    notices = la.render_notices([], [], report.notice_sections)
    assert "tools:texts/unicode.txt" in notices
    assert "Unicode, Inc." in notices

    (repo / "texts/unicode.txt").unlink()
    missing = _audit(site, table).problems
    assert missing == [
        "[근거 원문 없음] vendor vendor/runtime.dll: texts/unicode.txt에 맞는 파일이 없다"
    ]


def _sbom(*components: dict[str, object]) -> str:
    return json.dumps({"bomFormat": "CycloneDX", "components": list(components)})


def _crate(name: str, version: str, lic: str, scope: str = "required") -> dict[str, object]:
    return {"name": name, "version": version, "scope": scope, "licenses": [{"expression": lic}]}


def test_sbom_crates_need_their_own_text_sections(tmp_path: Path) -> None:
    sbom = _sbom(
        _crate("icu_normalizer", "1.5.0", "Unicode-3.0"),
        _crate("foldhash", "0.1.5", "Zlib"),
        _crate("target-lexicon", "0.13.5", "Apache-2.0 WITH LLVM-exception", scope="excluded"),
    )
    site = write_tree(tmp_path / "site", {**VENDOR_DLL, "vendor-1.0.dist-info/sboms/v.json": sbom})
    bundle = "\n".join(
        ["vendor 크레이트", "=" * 10, "icu_normalizer 1.5.0", "UNICODE LICENSE V3", ""]
    )
    repo = write_tree(tmp_path / "repo", {"crates.txt": bundle})
    text = {"file": "crates.txt", "covers": ["Unicode-3.0", "Zlib"], "expect": ["UNICODE"]}
    entry = _vendor("Unicode-3.0 AND Zlib", [text], sbom="vendor-*.dist-info/sboms/*.json")
    table = na.load_native_table({"native": [entry]}, base_dir=repo)
    report = _audit(site, table)
    # foldhash 절이 없다. excluded(빌드 도구) 크레이트는 보지 않는다
    assert report.problems == [
        "[SBOM 구성요소 원문 없음] vendor vendor/runtime.dll: foldhash 0.1.5 "
        "(tools/fetch_crate_licenses.py로 다시 모은다)"
    ]

    # 크레이트 라이선스도 판정한다
    bad = _sbom(_crate("icu_normalizer", "1.5.0", "Unicode-3.0"), _crate("x", "1", "GPL-3.0-only"))
    write_tree(site, {"vendor-1.0.dist-info/sboms/v.json": bad})
    write_tree(repo, {"crates.txt": bundle + "\nx 1\n"})
    problems = _audit(site, table).problems
    assert len(problems) == 1
    assert problems[0].startswith("[SBOM 구성요소 라이선스] vendor vendor/runtime.dll: x 1")

    # SBOM을 가리켰는데 없으면 실패
    (site / "vendor-1.0.dist-info/sboms/v.json").unlink()
    assert any(p.startswith("[SBOM 없음]") for p in _audit(site, table).problems)


def test_real_rust_extensions_cover_every_crate() -> None:
    """검수 반례 real_pydantic_evidence: 실제 설치된 Rust 확장의 SBOM 크레이트 원문이 다 있다."""
    site = Path(sysconfig.get_paths()["purelib"])
    table = na.load_native_table_file(Path(na.__file__).with_name("native-licenses.toml"))
    layout = na.Layout.site_packages(site)
    files = {na.SITE_PACKAGES: [rel for _, rel, _ in na.iter_files(layout)]}
    for glob in ("pydantic_core/*.pyd", "rpds/*.pyd", "windows_capture/*.pyd"):
        entry = next(e for e in table.entries if e.glob == glob)
        problems, collected = na.check_texts(entry, table, policy(), layout, files)
        assert problems == [], glob
        body = "\n".join(text for _, text in collected)
        assert "Apache License" in body
        if glob.startswith("pydantic_core"):
            # ICU4X(Unicode-3.0) 원문·저작권과 foldhash(Zlib) 저작권
            assert "UNICODE LICENSE V3" in body
            assert "Unicode, Inc." in body
            assert "Orson Peters" in body


def test_notices_include_native_model_and_exception_sections(tmp_path: Path) -> None:
    site = write_tree(tmp_path / "site", NUMPY_TREE)
    models_dir = write_tree(tmp_path / "models", {"det.onnx": b"model-bytes"})
    models = na.load_model_table(
        {
            "model": [
                {
                    "file": "det.onnx",
                    "sha256": hashlib.sha256(b"model-bytes").hexdigest(),
                    "size": len(b"model-bytes"),
                    "license": "Apache-2.0",
                    "source": "PaddleOCR (Apache-2.0)",
                }
            ]
        }
    )
    report = _audit(
        site, native_table(NUMPY_TABLE, refs=VC_REF), models=models, models_dir=models_dir
    )
    assert report.problems == []
    notices = la.render_notices([], [], report.notice_sections)

    assert "# 네이티브 파일 (DLL·pyd·exe)과 그 안의 구성요소" in notices
    assert "numpy: numpy.libs/libscipy_openblas*.dll" in notices
    assert f"License: BSD-3-Clause AND BSD-3-Clause-Open-MPI AND {GCC}" in notices
    assert "원문: numpy-*.dist-info/licenses/LICENSE.txt (BSD-3-Clause, " in notices
    # numpy 한정 예외와 그 이유
    assert "# 패키지별 라이선스 예외" in notices
    assert f"numpy: {GCC}" in notices
    assert "GCC Runtime Library Exception" in notices
    # LicenseRef 원문 위치·근거·고지
    assert "LicenseRef-MS-VC-Redist: VC++ 재배포" in notices
    assert "VC 고지문" in notices
    # 구성요소 원문은 파일마다 한 번만
    assert notices.count("OPENBLAS TEXT") == 1
    assert "site-packages:numpy-2.5.4.dist-info/licenses/numpy/libdivide/LICENSE.txt" in notices
    # 모델
    assert "# OCR 모델" in notices
    assert "det.onnx" in notices
    assert "출처: PaddleOCR (Apache-2.0)" in notices


def test_model_hash_and_license_checked(tmp_path: Path) -> None:
    models_dir = write_tree(tmp_path / "models", {"rec.onnx": b"tampered"})
    entry = {
        "file": "rec.onnx",
        "sha256": "0" * 64,
        "size": 8,
        "license": "LicenseRef-Unknown",
        "source": "x",
    }
    problems = na.audit_models(na.load_model_table({"model": [entry]}), models_dir, policy())
    assert any(p.startswith("[모델 라이선스] rec.onnx") for p in problems)
    assert any(p.startswith("[모델 해시 불일치] rec.onnx") for p in problems)
    missing = na.audit_models(
        na.load_model_table({"model": [{**entry, "file": "det.onnx"}]}), models_dir, policy()
    )
    assert any(p.startswith("[모델 없음] det.onnx") for p in missing)


@pytest.mark.parametrize(
    "file",
    [
        "C:\\models\\external.onnx",
        "C:external.onnx",
        "\\\\server\\share\\external.onnx",
        "/abs/external.onnx",
        "../external.onnx",
        "sub/../../external.onnx",
        "sub\\..\\..\\external.onnx",
    ],
)
def test_model_file_must_stay_inside_models_dir(file: str) -> None:
    """검수 반례 external_model: 모델 표가 설치 폴더 밖 파일을 가리킬 수 없다."""
    entry = {"file": file, "sha256": "0" * 64, "size": 1, "license": "Apache-2.0", "source": "x"}
    with pytest.raises(la.AuditInputError, match="모델 폴더 안의 상대 경로"):
        na.load_model_table({"model": [entry]})


def test_repo_native_table_loads(tmp_path: Path) -> None:
    table = na.load_native_table_file(Path(__file__).resolve().parents[1] / "native-licenses.toml")
    pol = policy()
    stripped = {r.glob for r in table.strip}
    pinned = {(pin.package, pin.path): pin for pin in pol.pinned}
    for entry in table.entries:
        status, expr = na.judge_entry(entry, table, pol)
        # 제거 대상(opencv FFmpeg) 밖의 모든 항목은 허용이어야 한다
        if entry.glob in stripped:
            assert status is la.Status.DENIED, entry.glob
            continue
        # 고정 바이너리 한정 예외(Electron ffmpeg.dll)는 그 예외의 잎을 더해야 허용된다
        pin = pinned.get((entry.package, entry.glob))
        if pin is not None:
            assert status is la.Status.DENIED, entry.glob
            status, expr = na.judge_entry(entry, table, pol, pin.leaves)
        assert status is la.Status.ALLOWED, (entry.glob, expr)
        # 감사 venv에 들어가는 항목은 모든 구성요소에 원문이 연결돼 있다
        if entry.scope == na.SITE_PACKAGES:
            # 허용이면서 원문이 있는 선택지로 채워져야 한다 (check_texts와 같은 판정)
            site = write_tree(tmp_path / entry.glob.replace("*", "_").replace("/", "_"), {})
            problems, _ = na.check_texts(
                entry, table, pol, na.Layout.site_packages(site), {na.SITE_PACKAGES: []}
            )
            assert not [p for p in problems if p.startswith("[구성요소 원문 없음]")], problems
        for text in entry.texts:
            if text.file:
                assert (table.base_dir / text.file).is_file(), text.file
