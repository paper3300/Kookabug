"""동봉 uv(`<앱>\\tools\\uv\\uv.exe`)의 전체 크레이트 SBOM을 만든다 (M6 계획 3.12, U10).

uv 배포본 `uv.exe`에는 cargo-auditable 의존성 목록(PE 구역 `.dep-v0`, zlib JSON)이
들어 있다 — 그 바이너리에 실제로 링크된 크레이트 목록이다. 그중 실행 시 크레이트(`kind`가
build가 아닌 것 = 빌드 의존성·proc-macro 제외)를
- crates.io 크레이트: uv 그 판의 `Cargo.lock` 체크섬과 대조한 `.crate`의 `Cargo.toml`
  `license`로 CycloneDX 구성요소 (`third_party_licenses/uv-sbom.json`)
- uv 워크스페이스 크레이트(`source: local`): uv의 LICENSE(Apache-2.0 OR MIT)로 덮는다 —
  이름·판을 `third_party_licenses/uv.txt`에 적는다
- uv.exe 안에 바이트로 든 실행기 스텁의 크레이트: 실행기 SBOM에서 더한다
원문 묶음 `uv-crates.txt`는 `fetch_crate_licenses.py --sbom`이 같은 `.crate`에서 모은다.

    uv run python tools/uv_sbom.py --zip <uv 릴리스 zip> [--cache <폴더>]
    uv run python tools/fetch_crate_licenses.py --sbom tools/third_party_licenses/uv-sbom.json

받는 곳: GitHub(uv `Cargo.lock`·LICENSE), static.crates.io(`.crate`). `--cache`의 `.crate`는
체크섬이 맞을 때만 다시 쓴다. 결과는 커밋한다 (직접 고치지 않는다).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import sys
import tarfile
import tomllib
import urllib.request
import zipfile
import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

TOOLS_DIR: Final = Path(__file__).resolve().parent
OUT_DIR: Final = TOOLS_DIR / "third_party_licenses"
CARGO_LOCK_URL: Final = "https://raw.githubusercontent.com/astral-sh/uv/{v}/Cargo.lock"
LICENSE_URL: Final = "https://raw.githubusercontent.com/astral-sh/uv/{v}/{name}"
CRATE_URL: Final = "https://static.crates.io/crates/{name}/{name}-{version}.crate"
RULE: Final = (
    "uv.exe의 cargo-auditable 목록(.dep-v0)에서 kind가 build가 아닌 crates.io 크레이트. "
    "체크섬은 uv 그 판의 Cargo.lock과 대조한 .crate, 라이선스는 그 .crate의 Cargo.toml "
    "license. uv 워크스페이스 크레이트(local)는 uv의 LICENSE(third_party_licenses/uv.txt)로 "
    "덮는다. uv.exe 안에 바이트로 든 실행기 스텁의 크레이트(kookabug:embedded)는 실행기 "
    "SBOM(uv-trampoline-sbom.json)에서 더한다"
)


class SbomError(Exception):
    pass


def auditable_packages(exe: bytes) -> list[dict[str, Any]]:
    """PE 실행 파일의 cargo-auditable 목록(`.dep-v0`). 없으면 SbomError."""
    if exe[:2] != b"MZ":
        raise SbomError("PE 실행 파일이 아니다")
    pe = struct.unpack_from("<I", exe, 0x3C)[0]
    if exe[pe : pe + 4] != b"PE\0\0":
        raise SbomError("PE 머리가 없다")
    count = struct.unpack_from("<H", exe, pe + 6)[0]
    optional = struct.unpack_from("<H", exe, pe + 20)[0]
    table = pe + 24 + optional
    for i in range(count):
        name, _vsize, _va, raw_size, raw_ptr = struct.unpack_from("<8sIIII", exe, table + 40 * i)
        if name.rstrip(b"\0") == b".dep-v0":
            data = json.loads(zlib.decompress(exe[raw_ptr : raw_ptr + raw_size]))
            return list(data["packages"])
    raise SbomError(".dep-v0 구역(cargo-auditable)이 없다")


def runtime_crates(
    packages: Sequence[Mapping[str, Any]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(crates.io 실행 시 크레이트, 워크스페이스(local) 실행 시 크레이트) — 이름·판 순."""
    registry: set[tuple[str, str]] = set()
    local: set[tuple[str, str]] = set()
    for p in packages:
        if p.get("kind", "runtime") == "build":
            continue
        key = (str(p["name"]), str(p["version"]))
        source = p.get("source", "crates.io")
        if source == "crates.io":
            registry.add(key)
        elif source == "local":
            local.add(key)
        else:
            raise SbomError(
                f"{key[0]} {key[1]}: 모르는 출처 {source!r} (git 등은 따로 판정해야 한다)"
            )
    return sorted(registry), sorted(local)


def lock_checksums(cargo_lock: str) -> dict[tuple[str, str], str]:
    data = tomllib.loads(cargo_lock)
    return {
        (str(p["name"]), str(p["version"])): str(p["checksum"])
        for p in data.get("package", [])
        if "checksum" in p
    }


def normalize_license(text: str) -> str:
    """Cargo 옛 표기(`MIT/Apache-2.0`)를 SPDX 식으로."""
    return " OR ".join(part.strip() for part in text.split("/")) if "/" in text else text.strip()


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()


def crate_bytes(name: str, version: str, sha256: str, cache: Path | None) -> bytes:
    cached = None if cache is None else cache / f"{name}-{version}.crate"
    if cached is not None and cached.is_file():
        data = cached.read_bytes()
        if hashlib.sha256(data).hexdigest() == sha256:
            return data
    data = _get(CRATE_URL.format(name=name, version=version))
    if hashlib.sha256(data).hexdigest() != sha256:
        raise SbomError(f"{name} {version}: 받은 .crate의 SHA256이 Cargo.lock과 다르다")
    if cached is not None:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    return data


def crate_license(name: str, version: str, data: bytes) -> str:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        member = tar.extractfile(f"{name}-{version}/Cargo.toml")
        if member is None:
            raise SbomError(f"{name} {version}: Cargo.toml이 없다")
        manifest = tomllib.loads(member.read().decode("utf-8"))
    lic = manifest.get("package", {}).get("license")
    if not isinstance(lic, str) or not lic.strip():
        raise SbomError(
            f"{name} {version}: Cargo.toml에 license가 없다 (license-file만 있으면 직접 판정)"
        )
    return normalize_license(lic)


def build_sbom(
    uv_version: str,
    packages: Sequence[Mapping[str, Any]],
    checksums: Mapping[tuple[str, str], str],
    licenses: Mapping[tuple[str, str], str],
    embedded: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """`embedded`: uv.exe 안에 바이트로 든 실행기 스텁(uv-trampoline-builder)의 크레이트 —
    별도 컴파일이라 `.dep-v0`에 없다. 실행기 SBOM의 구성요소를 그대로 더한다."""
    registry, local = runtime_crates(packages)
    components: list[dict[str, Any]] = []
    seen = set(registry)
    for comp in embedded:
        key = (str(comp["name"]), str(comp["version"]))
        if key not in seen:
            seen.add(key)
            components.append(
                {**comp, "properties": [{"name": "kookabug:embedded", "value": "uv-trampoline"}]}
            )
    for name, version in registry:
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "scope": "required",
                "licenses": [{"expression": licenses[(name, version)]}],
                "hashes": [{"alg": "SHA-256", "content": checksums[(name, version)]}],
                "purl": f"pkg:cargo/{name}@{version}",
            }
        )
    components.sort(key=lambda c: (c["name"], c["version"]))
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {
            "component": {
                "type": "application",
                "name": "uv",
                "version": uv_version,
                "licenses": [{"expression": "MIT OR Apache-2.0"}],
            },
            "properties": [
                {"name": "kookabug:uv_version", "value": uv_version},
                {"name": "kookabug:source", "value": "uv.exe .dep-v0 (cargo-auditable)"},
                {"name": "kookabug:checksums", "value": CARGO_LOCK_URL.format(v=uv_version)},
                {"name": "kookabug:rule", "value": RULE},
                {"name": "kookabug:path_crates", "value": ", ".join(f"{n} {v}" for n, v in local)},
            ],
        },
        "components": components,
    }


def render_uv_text(uv_version: str, local: Sequence[tuple[str, str]], apache: str, mit: str) -> str:
    lines = [
        f"uv {uv_version} 라이선스 원문",
        "설치본 tools/uv/uv.exe는 uv 배포본(astral-sh/uv 릴리스 zip)의 uv.exe다.",
        "그 안의 uv 워크스페이스 크레이트는 아래이고 uv의 라이선스(Apache-2.0 OR MIT)를 따른다.",
        "crates.io 크레이트의 원문은 uv-crates.txt (SBOM uv-sbom.json, tools/uv_sbom.py).",
        "직접 고치지 않는다.",
        "",
        *(f"{n} {v}" for n, v in local),
        "",
        "=" * 78,
        "uv LICENSE-APACHE",
        "-" * 78,
        apache.strip(),
        "",
        "=" * 78,
        "uv LICENSE-MIT",
        "-" * 78,
        mit.strip(),
        "",
    ]
    return "\n".join(lines)


def read_uv_exe(zip_path: Path) -> bytes:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read("uv.exe")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="동봉 uv 전체 크레이트 SBOM")
    parser.add_argument("--zip", type=Path, required=True, help="uv 릴리스 zip (pbs.toml [uv])")
    parser.add_argument("--cache", type=Path, help=".crate 캐시 폴더")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(TOOLS_DIR))
    from installer.build import load_inputs, sha256_file

    want = load_inputs().uv
    if sha256_file(args.zip) != want.sha256:
        print(f"{args.zip}의 SHA256이 pbs.toml [uv]와 다르다", file=sys.stderr)
        return 1
    try:
        packages = auditable_packages(read_uv_exe(args.zip))
        registry, local = runtime_crates(packages)
        checksums = lock_checksums(_get(CARGO_LOCK_URL.format(v=want.version)).decode("utf-8"))
        missing = [f"{n} {v}" for n, v in registry if (n, v) not in checksums]
        if missing:
            raise SbomError(f"Cargo.lock에 없는 크레이트: {missing}")
        licenses = {}
        for i, (name, version) in enumerate(registry, 1):
            data = crate_bytes(name, version, checksums[(name, version)], args.cache)
            licenses[(name, version)] = crate_license(name, version, data)
            print(
                f"[{i}/{len(registry)}] {name} {version}: {licenses[(name, version)]}", flush=True
            )
        trampoline = json.loads((args.out_dir / "uv-trampoline-sbom.json").read_text("utf-8"))
        sbom = build_sbom(want.version, packages, checksums, licenses, trampoline["components"])
        apache = _get(LICENSE_URL.format(v=want.version, name="LICENSE-APACHE")).decode("utf-8")
        mit = _get(LICENSE_URL.format(v=want.version, name="LICENSE-MIT")).decode("utf-8")
    except (SbomError, OSError) as exc:
        print(f"uv SBOM 만들기 실패: {exc}", file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "uv-sbom.json").write_text(
        json.dumps(sbom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (args.out_dir / "uv.txt").write_text(
        render_uv_text(want.version, local, apache, mit), encoding="utf-8", newline="\n"
    )
    print(f"crates.io {len(registry)}개, 워크스페이스 {len(local)}개 → {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
