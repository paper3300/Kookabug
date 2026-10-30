"""Rust 크레이트 라이선스 원문 모으기 (네트워크 없이, crates.io 응답을 바꿔 끼운다)."""

from pathlib import Path

import pytest

import fetch_crate_licenses as fc

APACHE = "Apache License\nVersion 2.0, January 2004\n..."
FILES = {
    ("a", "1.0"): [("LICENSE-APACHE", APACHE), ("LICENSE-MIT", "MIT\nCopyright A")],
    ("b", "2.0"): [("LICENSE-APACHE", APACHE), ("LICENSE-MIT", "MIT\nCopyright B")],
    ("c", "0.1"): [],
}


def test_render_dedupes_and_accepts_apache_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fc, "crate_license_files", lambda n, v: FILES[(n, v)])
    comps = [
        ("a", "1.0", "MIT OR Apache-2.0"),
        ("b", "2.0", "MIT OR Apache-2.0"),
        ("c", "0.1", "Apache-2.0 OR MIT"),
    ]
    text = fc.render("dist", "9.9", "dist.cyclonedx.json", comps)
    assert text.startswith("dist 9.9의 Rust 크레이트 라이선스 원문\n")
    # 크레이트마다 `이름 버전` 줄 (native_audit의 SBOM 대조가 찾는 형식)
    for name, version, _ in comps:
        assert f"\n{name} {version}\n" in text
    # 같은 Apache 원문은 한 번만 싣고, 나머지는 가리킨다 (끝의 표준 원문 절은 따로)
    assert text.count("Version 2.0, January 2004") == 2
    assert "--- LICENSE-APACHE: a 1.0의 LICENSE-APACHE와 글자까지 같다" in text
    assert "Copyright A" in text
    assert "Copyright B" in text
    # 파일 없는 크레이트는 Apache-2.0을 고르고 끝의 표준 원문을 가리킨다
    assert f"(라이선스 파일 없음. {fc.APACHE_CHOICE})" in text
    assert fc.APACHE_SECTION in text


def test_render_fails_when_no_file_and_no_apache_option(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fc, "crate_license_files", lambda n, v: [])
    with pytest.raises(fc.FetchError, match=r"x 1 \(MIT; Apache-2.0으로 못 채움: MIT\)"):
        fc.render("dist", "1", "s.json", [("x", "1", "MIT")])


@pytest.mark.parametrize(
    ("expr", "rest"),
    [
        # 검수 반례 r2_apache_fallback_drops_and: AND로 붙은 조건은 Apache 하나로 못 채운다
        ("(MIT OR Apache-2.0) AND Unicode-DFS-2016", "Unicode-DFS-2016"),
        ("Apache-2.0 AND (MIT OR BSD-3-Clause)", "MIT, BSD-3-Clause"),
        ("Apache-2.0 WITH LLVM-exception", "Apache-2.0 WITH LLVM-exception"),
    ],
)
def test_apache_fallback_needs_apache_alone_to_satisfy_expression(
    monkeypatch: pytest.MonkeyPatch, expr: str, rest: str
) -> None:
    seed = [("LICENSE-APACHE", APACHE)]
    monkeypatch.setattr(fc, "crate_license_files", lambda n, v: seed if n == "seed" else [])
    with pytest.raises(fc.FetchError, match="compound 1") as err:
        fc.render("dist", "1", "s.json", [("seed", "1", "Apache-2.0"), ("compound", "1", expr)])
    assert f"Apache-2.0으로 못 채움: {rest})" in str(err.value)

    # 괄호 안 OR가 Apache로 채워지는 식은 받아들인다
    ok = fc.render(
        "dist",
        "1",
        "s.json",
        [("seed", "1", "Apache-2.0"), ("compound", "1", "(MIT OR Apache-2.0) AND Apache-2.0")],
    )
    assert f"(라이선스 파일 없음. {fc.APACHE_CHOICE})" in ok


def _crate(name: str, version: str) -> bytes:
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"MIT\nCopyright X"
        info = tarfile.TarInfo(f"{name}-{version}/LICENSE-MIT")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_repo_sbom_checksums_checked_against_downloaded_crate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """레포 SBOM(uv 실행기)으로 원문을 모을 때 Cargo.lock 체크섬과 받은 .crate가 다르면 멈춘다."""
    import hashlib
    import io
    import json

    crate = _crate("a", "1.0")

    class Resp(io.BytesIO):
        def __enter__(self) -> Resp:
            return self

        def __exit__(self, *exc: object) -> None:
            pass

    monkeypatch.setattr(fc.urllib.request, "urlopen", lambda url, timeout: Resp(crate))
    sbom = {
        "metadata": {"component": {"name": "tool-x", "version": "0.1.0"}},
        "components": [
            {
                "name": "a",
                "version": "1.0",
                "licenses": [{"expression": "MIT"}],
                "hashes": [{"alg": "SHA-256", "content": hashlib.sha256(crate).hexdigest()}],
            }
        ],
    }
    path = tmp_path / "tool-x-sbom.json"
    path.write_text(json.dumps(sbom), encoding="utf-8")
    out = fc.render_sbom_file(path, tmp_path)
    assert out.name == "tool-x-crates.txt"
    text = out.read_text(encoding="utf-8")
    assert text.startswith("tool-x 0.1.0의 Rust 크레이트 라이선스 원문\n")
    assert "\na 1.0\n" in text and "Copyright X" in text

    sbom["components"][0]["hashes"][0]["content"] = "0" * 64
    path.write_text(json.dumps(sbom), encoding="utf-8")
    with pytest.raises(fc.FetchError, match=r"a 1\.0: 받은 \.crate의 SHA256이 SBOM과 다르다"):
        fc.render_sbom_file(path, tmp_path)
