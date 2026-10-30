"""Rust 확장 wheel의 크레이트 라이선스 원문을 모은다 (구현 계획 M1 2.12, native_audit의 `sbom`).

pydantic-core·rpds-py·windows-capture 같은 Rust 확장의 pyd에는 크레이트 수십 개가 정적으로 들어
있지만 wheel에는 자기 LICENSE 하나만 있다. 동봉 SBOM(`*.dist-info/sboms/*.cyclonedx.json`)의
크레이트마다 crates.io의 `.crate`를 받아 맨 위 폴더의 라이선스 파일을 한 파일로 묶는다.
결과는 `tools/third_party_licenses/<배포물>-crates.txt`로 커밋한다. 직접 고치지 않는다.

    uv run python tools/fetch_crate_licenses.py --site-packages .venv/Lib/site-packages \
        pydantic-core rpds-py windows-capture

배포물에 SBOM이 없는 바이너리(설치본의 uv 실행기)는 레포에 둔 SBOM으로 같은 묶음을 만든다. SBOM의
구성요소 SHA-256(Cargo.lock 체크섬)을 받은 `.crate`와 대조한다:

    uv run python tools/fetch_crate_licenses.py \
        --sbom tools/third_party_licenses/uv-trampoline-sbom.json
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import tarfile
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from packaging.utils import canonicalize_name

from license_audit import expression_satisfied
from native_audit import sbom_components

TOOLS_DIR = Path(__file__).resolve().parent
OUT_DIR = TOOLS_DIR / "third_party_licenses"
CRATE_URL = "https://static.crates.io/crates/{name}/{name}-{version}.crate"
LICENSE_FILE = re.compile(r"^(licen[cs]e|copying|copyright|notice|unlicense)([-_.].*)?$", re.I)
APACHE_TITLE = "Apache License"
APACHE_SECTION = "Apache-2.0 표준 원문"
APACHE_CHOICE = f"Apache-2.0을 고른다. 원문은 이 파일 끝 '{APACHE_SECTION}' 절"


class FetchError(Exception):
    pass


def crate_license_files(
    name: str, version: str, sha256: str | None = None
) -> list[tuple[str, str]]:
    """`.crate` 맨 위 폴더의 라이선스 파일들. `sha256`(Cargo.lock 체크섬)을 주면 받은 파일과
    대조한다."""
    url = CRATE_URL.format(name=name, version=version)
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
    except OSError as exc:
        raise FetchError(f"{name} {version}: 받을 수 없다 ({exc})") from exc
    if sha256 is not None and hashlib.sha256(data).hexdigest() != sha256.lower():
        raise FetchError(f"{name} {version}: 받은 .crate의 SHA256이 SBOM과 다르다")
    files: list[tuple[str, str]] = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            parts = member.name.split("/")
            if member.isfile() and len(parts) == 2 and LICENSE_FILE.match(parts[1]):
                f = tar.extractfile(member)
                assert f is not None
                files.append((parts[1], f.read().decode("utf-8", errors="replace")))
    return sorted(files)


def find_sbom(site: Path, dist: str) -> tuple[Path, str]:
    """(SBOM 경로, 배포물 버전)."""
    want = canonicalize_name(dist)
    for info in sorted(site.glob("*.dist-info")):
        name, _, version = info.name.removesuffix(".dist-info").partition("-")
        if canonicalize_name(name) == want:
            sboms = sorted(info.glob("sboms/*.json"))
            if len(sboms) != 1:
                raise FetchError(f"{info.name}: SBOM이 하나가 아니다 ({len(sboms)}개)")
            return sboms[0], version
    raise FetchError(f"{dist}: {site}에 설치돼 있지 않다")


def sbom_checksums(sbom: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    """SBOM 구성요소의 SHA-256 (있는 것만): (이름, 버전) → 16진수."""
    out: dict[tuple[str, str], str] = {}
    for comp in sbom.get("components", []):
        for h in comp.get("hashes", []):
            if h.get("alg") == "SHA-256":
                out[(str(comp["name"]), str(comp["version"]))] = str(h["content"])
    return out


def render(
    dist: str,
    version: str,
    sbom_name: str,
    comps: Sequence[tuple[str, str, str]],
    checksums: Mapping[tuple[str, str], str] | None = None,
) -> str:
    lines = [
        f"{dist} {version}의 Rust 크레이트 라이선스 원문",
        f"SBOM: {sbom_name} (excluded 제외 {len(comps)}개)",
        "tools/fetch_crate_licenses.py가 crates.io의 .crate에서 모은다. 직접 고치지 않는다.",
        "",
    ]
    missing: list[str] = []
    apache_text = ""
    # 글자까지 같은 원문(표준 Apache-2.0 등)은 처음 나온 곳만 싣고 뒤에서는 가리킨다
    first_seen: dict[str, str] = {}
    for name, ver, lic in comps:
        digest = (checksums or {}).get((name, ver))
        files = (
            crate_license_files(name, ver, digest)
            if digest is not None
            else crate_license_files(name, ver)
        )
        lines += ["=" * 78, f"{name} {ver}", f"License: {lic}", "-" * 78]
        for fname, text in files:
            body = text.strip()
            where = first_seen.get(body)
            if where is None:
                first_seen[body] = f"{name} {ver}의 {fname}"
                lines += [f"--- {fname}", body, ""]
            else:
                lines += [f"--- {fname}: {where}와 글자까지 같다", ""]
            if not apache_text and "apache" in fname.lower() and APACHE_TITLE in text:
                apache_text = body
        if not files:
            # 크레이트에 라이선스 파일이 없으면 Apache-2.0 **하나로** 식 전체를 채울 수 있을 때만
            # 받아들인다(AND로 붙은 다른 조건이 남으면 실패). Apache-2.0은 목적 코드 배포에
            # 라이선스 사본(아래 표준 원문)만 요구한다
            ok, rest = expression_satisfied(lic, lambda leaf: leaf == "Apache-2.0")
            if ok:
                lines += [f"(라이선스 파일 없음. {APACHE_CHOICE})", ""]
            else:
                missing.append(f"{name} {ver} ({lic}; Apache-2.0으로 못 채움: {', '.join(rest)})")
    if missing:
        raise FetchError("라이선스 파일이 없는 크레이트: " + ", ".join(missing))
    if any(APACHE_CHOICE in line for line in lines):
        if not apache_text:
            raise FetchError("Apache-2.0 표준 원문을 크레이트에서 찾지 못했다")
        lines += ["=" * 78, APACHE_SECTION, "-" * 78, apache_text, ""]
    return "\n".join(lines).rstrip() + "\n"


def render_sbom_file(sbom_path: Path, out_dir: Path) -> Path:
    """레포에 둔 SBOM(배포물에 SBOM이 없는 바이너리, 예: uv 실행기)의 원문 묶음
    `<metadata.component.name>-crates.txt`. 구성요소 SHA-256을 받은 .crate와 대조한다."""
    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    component = sbom["metadata"]["component"]
    name, version = str(component["name"]), str(component["version"])
    text = render(name, version, sbom_path.name, sbom_components(sbom), sbom_checksums(sbom))
    out = out_dir / f"{canonicalize_name(name)}-crates.txt"
    out.write_text(text, encoding="utf-8", newline="\n")
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rust 크레이트 라이선스 원문 모으기")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--site-packages", type=Path, help="Rust 확장 wheel이 설치된 폴더")
    source.add_argument("--sbom", type=Path, help="레포에 둔 SBOM 파일 (배포물에 SBOM이 없을 때)")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("dists", nargs="*", help="배포물 이름 (--site-packages, 예: pydantic-core)")
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.sbom is not None:
            print(render_sbom_file(args.sbom, args.out_dir))
            return 0
        if not args.dists:
            parser.error("--site-packages에는 배포물 이름이 있어야 한다")
        for dist in args.dists:
            sbom_path, version = find_sbom(args.site_packages, dist)
            sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
            text = render(dist, version, sbom_path.name, sbom_components(sbom))
            out = args.out_dir / f"{canonicalize_name(dist)}-crates.txt"
            out.write_text(text, encoding="utf-8", newline="\n")
            print(out)
    except FetchError as exc:
        print(f"크레이트 라이선스 모으기 실패: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
