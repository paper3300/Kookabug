"""설치본의 플러그인 준비물 (M6 계획 3.12): 동봉 uv(PATH 밖)·전체 크레이트 감사·SDK wheel·
예제 플러그인."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest

import license_audit as la
import native_audit as na
import uv_sbom
from installer import build

UV_EXE = build.TOOLS_UV


def _uv_entry(table: na.NativeTable) -> na.NativeEntry:
    entry = na.find_entry(table, na.INSTALL, UV_EXE)
    assert entry is not None, "tools/uv/uv.exe에 맞는 네이티브 표 항목이 없다"
    return entry


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _uv_dist(data: bytes, **over: Any) -> build.UvDist:
    fields: dict[str, Any] = {
        "version": "0.13.6",
        "file": "uv.zip",
        "url": "https://example.invalid/uv.zip",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }
    return build.UvDist(**{**fields, **over})


def test_inputs_pin_bundled_uv() -> None:
    inputs = build.load_inputs()
    uv = inputs.uv
    assert uv.version == inputs.uv_version
    assert uv.file == "uv-x86_64-pc-windows-msvc.zip"
    assert uv.url == f"https://github.com/astral-sh/uv/releases/download/{uv.version}/{uv.file}"
    assert len(uv.sha256) == 64 and uv.size > 0


def test_uv_extracted_only_from_verified_zip(tmp_path: Path) -> None:
    data = _zip({"uv.exe": b"MZuv", "uvx.exe": b"MZuvx", "uvw.exe": b"MZuvw"})
    archive = tmp_path / "uv.zip"
    archive.write_bytes(data)
    for bad in (_uv_dist(data, sha256="0" * 64), _uv_dist(data, size=len(data) + 1)):
        stage = tmp_path / f"stage-{bad.sha256[:2]}{bad.size}"
        stage.mkdir()
        with pytest.raises(build.BuildError, match="풀지 않는다"):
            build.extract_uv(archive, bad, stage)
        assert list(stage.iterdir()) == []
    stage = tmp_path / "stage"
    stage.mkdir()
    exe = build.extract_uv(archive, _uv_dist(data), stage)
    assert exe == stage / "tools" / "uv" / "uv.exe" and exe.read_bytes() == b"MZuv"
    # uv.exe 하나만 (uvx·uvw 없음)
    assert sorted(p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()) == [
        "tools/uv/uv.exe"
    ]
    # 받기는 PBS와 같은 확인 (크기·SHA256이 틀린 받기는 캐시에 남기지 않음)
    cache = tmp_path / "cache"

    def wrong(url: str, dest: Path) -> None:
        dest.write_bytes(b"x")

    with pytest.raises(build.BuildError):
        build.fetch_uv(_uv_dist(data), cache, download=wrong)
    assert list(cache.iterdir()) == []


def test_bundled_uv_outside_path() -> None:
    """동봉 uv는 PATH에 넣지 않는다: 설치 프로그램이 PATH에 더하는 것은 bin 하나뿐이고
    uv는 bin 밖."""
    assert not UV_EXE.startswith(f"{build.BIN}/")
    nsh = build.NSIS_INCLUDE.read_text(encoding="utf-8")
    added = [
        line.strip()
        for line in nsh.splitlines()
        if "kbAddToUserPath" in line and "!insertmacro" in line
    ]
    assert added == ['!insertmacro kbAddToUserPath "$INSTDIR\\bin" "${INSTALL_REGISTRY_KEY}"']
    assert "tools\\uv" not in nsh and "tools/uv" not in nsh
    # 최종 트리 구조 검사가 동봉 uv·SDK wheel·예제 플러그인을 요구한다
    problems = build.check_layout(Path("Z:/nonexistent"))
    for rel in (UV_EXE, build.PLUGIN_SDK, build.EXAMPLE_PLUGINS):
        assert f"[설치 트리 구조] {rel}가 없다" in problems


def test_bundled_uv_full_crate_audit(tmp_path: Path) -> None:
    """동봉 uv의 SBOM = 실행 시 crates.io 크레이트 전부 + 안에 든 실행기 스텁 크레이트.
    실제 허용 목록으로
    크레이트마다 판정하고 원문이 있어야 한다. 원문 하나가 빠지면 실패한다 (실행기 항목과 따로)."""
    table = na.load_native_table_file(build.NATIVE_TABLE)
    policy = la.load_policy_file(build.ALLOWLIST)
    entry = _uv_entry(table)
    assert entry.sbom_file == "third_party_licenses/uv-sbom.json"
    trampoline = na.find_entry(table, na.INSTALL, "bin/kookabug.exe")
    assert trampoline is not None and trampoline is not entry
    sbom = json.loads((table.base_dir / entry.sbom_file).read_text(encoding="utf-8"))
    props = {p["name"]: p["value"] for p in sbom["metadata"]["properties"]}
    assert props["kookabug:uv_version"] == build.load_inputs().uv_version
    comps = na.sbom_components(sbom)
    assert len(comps) > 300  # 실행기 전용(12개) 감사로 대신하지 않는다
    assert all(len(h["content"]) == 64 for c in sbom["components"] for h in c["hashes"])
    layout = na.Layout.install(tmp_path)
    assert na.check_texts(entry, table, policy, layout, {})[0] == []

    copy = tmp_path / "tools"
    shutil.copytree(build.TOOLS_DIR / "third_party_licenses", copy / "third_party_licenses")
    crates = copy / "third_party_licenses" / "uv-crates.txt"
    name, version, _ = comps[len(comps) // 2]
    text = crates.read_text(encoding="utf-8")
    assert f"\n{name} {version}\n" in text
    crates.write_text(text.replace(f"\n{name} {version}\n", "\n(지움)\n"), encoding="utf-8")
    broken = na.NativeTable(table.entries, table.strip, table.license_refs, copy)
    problems = na.check_texts(_uv_entry(broken), broken, policy, layout, {})[0]
    assert any(
        p.startswith("[SBOM 구성요소 원문 없음]") and f"{name} {version}" in p for p in problems
    )


def test_bundled_uv_sbom_matches_binary() -> None:
    """빌드 캐시의 uv 릴리스 zip(pbs.toml 해시)이 있으면: 그 uv.exe의 cargo-auditable 목록과
    SBOM이 같다."""
    dist = build.load_inputs().uv
    archive = build.DEFAULT_CACHE / dist.file
    if not build.verified(archive, dist.sha256, dist.size):
        pytest.skip("build/installer-cache에 uv 릴리스 zip이 없다 (설치 파일 빌드가 받는다)")
    packages = uv_sbom.auditable_packages(uv_sbom.read_uv_exe(archive))
    registry, local = uv_sbom.runtime_crates(packages)
    sbom = json.loads(
        (build.TOOLS_DIR / "third_party_licenses" / "uv-sbom.json").read_text("utf-8")
    )
    listed = {
        (c["name"], c["version"])
        for c in sbom["components"]
        if not any(p["name"] == "kookabug:embedded" for p in c.get("properties", []))
    }
    assert listed == set(registry)
    uv_txt = (build.TOOLS_DIR / "third_party_licenses" / "uv.txt").read_text("utf-8")
    assert all(f"\n{n} {v}\n" in uv_txt for n, v in local)


def test_plugin_sdk_wheel_copied(tmp_path: Path) -> None:
    wheels = [
        tmp_path / "kookabug_core-0.1.0-py3-none-any.whl",
        tmp_path / "kookabug_sdk-0.1.0-py3-none-any.whl",
    ]
    for w in wheels:
        w.write_bytes(b"PK")
    stage = tmp_path / "stage"
    out = build.copy_plugin_sdk(wheels, stage)
    assert out == stage / "plugin-sdk" / "kookabug_sdk-0.1.0-py3-none-any.whl"
    with pytest.raises(build.BuildError):
        build.copy_plugin_sdk(wheels[:1], tmp_path / "other")


@pytest.mark.packaging
def test_example_plugin_wheel_built(tmp_path: Path) -> None:
    """예제 플러그인 wheel: 스키마 생성 뒤 `uv build` (위젯 ui 폴더 포함) + 예제 그래프.
    원본 폴더에 쓰지 않는다."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv가 없다")
    stage = tmp_path / "stage"
    names = build.build_example_plugins(uv, tmp_path / "work", stage)
    wheel = next(n for n in names if n.endswith(".whl"))
    assert wheel.startswith("kookabug_plugin_sample-0.1.0-")
    assert "sample_reverse.graph.json" in names
    assert ".gitignore" not in names
    with zipfile.ZipFile(stage / build.EXAMPLE_PLUGINS / wheel) as zf:
        files = set(zf.namelist())
    for rel in ("kookabug.schema.json", "ui/index.js", "ui/kookabug-ui.js", "nodes/widgets.py"):
        assert f"kookabug_plugin_sample/{rel}" in files
    assert not (
        build.SAMPLE_PLUGIN / "src" / "kookabug_plugin_sample" / "kookabug.schema.json"
    ).exists()
