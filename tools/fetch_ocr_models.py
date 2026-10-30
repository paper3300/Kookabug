"""OCR 모델과 라이선스 근거 원문 받기 (구현 계획 M1 2.6).

`python/kookabug_platform/src/kookabug_platform/ocr/models.toml`의 파일을 `build/ocr-models/`(또는
`--dest`)에 받는다. 이미 있고 크기·SHA256이 맞으면 받지 않는다(CI 캐시). 주소가 여럿이면 앞에서부터
시도하고, 받은 바이트의 크기·SHA256이 표와 다르면 그 주소는 실패로 보고 다음 주소로 간다. 임시
파일에 받아 확인한 뒤에만 제 이름으로 바꾼다.

    uv run python tools/fetch_ocr_models.py [--dest 폴더] [--check]

종료 코드: 0 전부 있음, 1 받기·확인 실패, 2 표 오류. `--check`는 받지 않고 확인만 한다.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final, Protocol

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
DEFAULT_DEST: Final = REPO_ROOT / "build" / "ocr-models"
MANIFEST: Final = (
    REPO_ROOT / "python" / "kookabug_platform" / "src" / "kookabug_platform" / "ocr" / "models.toml"
)
TIMEOUT_S: Final = 120
USER_AGENT: Final = "kookabug-fetch-ocr-models"

type Download = Callable[[str, Path], None]
"""주소 → 파일로 받기. 실패면 예외."""


class FileSpec(Protocol):
    @property
    def file(self) -> str: ...
    @property
    def sha256(self) -> str: ...
    @property
    def size(self) -> int: ...
    @property
    def urls(self) -> tuple[str, ...]: ...


class FetchError(Exception):
    pass


def http_download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response, dest.open("wb") as f:
        while chunk := response.read(1 << 20):
            f.write(chunk)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _matches(path: Path, spec: FileSpec) -> bool:
    try:
        return path.stat().st_size == spec.size and _sha256(path) == spec.sha256
    except OSError:
        return False


def fetch_one(spec: FileSpec, dest: Path, download: Download, log: Callable[[str], None]) -> bool:
    """하나를 받는다. 이미 맞으면 True(받지 않음). 실패면 FetchError."""
    target = dest / spec.file
    if _matches(target, spec):
        log(f"있음 {spec.file}")
        return True
    tmp = dest / f".{spec.file}.part"
    errors: list[str] = []
    for url in spec.urls:
        try:
            download(url, tmp)
        except Exception as exc:  # 네트워크·HTTP 오류는 다음 주소로
            errors.append(f"{url}: {exc}")
            continue
        if _matches(tmp, spec):
            os.replace(tmp, target)
            log(f"받음 {spec.file} ← {url}")
            return False
        errors.append(f"{url}: 크기·SHA256이 표와 다르다")
    tmp.unlink(missing_ok=True)
    raise FetchError(f"{spec.file}를 받지 못했다:\n  " + "\n  ".join(errors))


def fetch_all(
    specs: Sequence[FileSpec],
    dest: Path,
    *,
    download: Download = http_download,
    log: Callable[[str], None] = print,
) -> list[str]:
    """전부 받는다. 실패한 파일의 오류 목록(비면 성공)."""
    dest.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for spec in specs:
        try:
            fetch_one(spec, dest, download, log)
        except FetchError as exc:
            failures.append(str(exc))
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    from kookabug_platform.ocr.models import ManifestError, load_manifest
    from kookabug_sdk.console import utf8_stdio

    utf8_stdio()
    parser = argparse.ArgumentParser(description="OCR 모델·라이선스 근거 원문 받기")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--check", action="store_true", help="받지 않고 있는지만 확인")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
    except (OSError, ManifestError, ValueError) as exc:
        print(f"모델 표 오류: {exc}", file=sys.stderr)
        return 2
    specs: list[FileSpec] = [*manifest.models, *manifest.texts]
    if args.check:
        missing = [s.file for s in specs if not _matches(args.dest / s.file, s)]
        for name in missing:
            print(f"없음·불일치 {name}", file=sys.stderr)
        return 1 if missing else 0
    failures = fetch_all(specs, args.dest)
    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        return 1
    print(f"OCR 모델 준비됨: {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
