"""Rust 확장 wheel의 크레이트 라이선스 원문을 모은다 (구현 계획 M1 2.12, native_audit의 `sbom`).

pydantic-core·rpds-py·windows-capture 같은 Rust 확장의 pyd에는 크레이트 수십 개가 정적으로 들어
있지만 wheel에는 자기 LICENSE 하나만 있다. 동봉 SBOM(`*.dist-info/sboms/*.cyclonedx.json`)의
크레이트마다 crates.io의 `.crate`를 받아 맨 위 폴더의 라이선스 파일을 한 파일로 묶는다.
결과는 `tools/third_party_licenses/<배포물>-crates.txt`로 커밋한다. 직접 고치지 않는다.

    uv run python tools/fetch_crate_licenses.py --site-packages .venv/Lib/site-packages \
        pydantic-core rpds-py windows-capture
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tarfile
import urllib.request
from collections.abc import Sequence
from pathlib import Path

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


def crate_license_files(name: str, version: str) -> list[tuple[str, str]]:
    url = CRATE_URL.format(name=name, version=version)
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
    except OSError as exc:
        raise FetchError(f"{name} {version}: 받을 수 없다 ({exc})") from exc
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


def render(dist: str, version: str, sbom_name: str, comps: Sequence[tuple[str, str, str]]) -> str:
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
        files = crate_license_files(name, ver)
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rust 크레이트 라이선스 원문 모으기")
    parser.add_argument("--site-packages", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("dists", nargs="+", help="배포물 이름 (예: pydantic-core)")
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    try:
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
