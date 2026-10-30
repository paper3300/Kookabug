"""OCR 모델 표·모델 찾기·해시 확인 (구현 계획 M1 2.6).

- 표: 이 폴더의 `models.toml`(모델 2개와 라이선스 근거 원문). 받기는 `tools/fetch_ocr_models.py`
- 찾는 순서: 환경 변수 `KOOKABUG_OCR_MODELS` → 설치본 `<설치>/ocr-models` → 레포
  `build/ocr-models`. 환경 변수를 주면 그 폴더만 본다(다른 곳으로 넘어가면 무엇을 쓰는지 헷갈린다).
  주지 않으면 있는 폴더 중 앞의 것
- 그 폴더에 모델이 없으면 `ocr_model_missing`, 크기·SHA256이 표와 다르면 `ocr_model_corrupt`.
  **실행 중에 내려받지 않는다**
- 설치본 위치는 동봉 Python(`<설치>/python`)의 부모다 (`sys.base_prefix`의 부모)

이 모듈은 opencv·onnxruntime을 import하지 않는다(받기 도구와 감사가 쓴다).
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Final

from kookabug_platform.errors import OCR_MODEL_CORRUPT, OCR_MODEL_MISSING, PlatformError

__all__ = [
    "ENV",
    "FETCH_HINT",
    "INSTALL_DIR_NAME",
    "MANIFEST_PATH",
    "Manifest",
    "ModelSpec",
    "OcrModels",
    "TextSpec",
    "candidate_dirs",
    "find_models",
    "install_root",
    "load_manifest",
    "repo_root",
    "sha256_file",
    "verify_file",
]

ENV: Final = "KOOKABUG_OCR_MODELS"
INSTALL_DIR_NAME: Final = "ocr-models"
MANIFEST_PATH: Final = Path(__file__).with_name("models.toml")
FETCH_HINT: Final = "`uv run python tools/fetch_ocr_models.py`로 받는다"
ROLES: Final = ("det", "rec")


class ManifestError(ValueError):
    """모델 표 형식 오류."""


@dataclass(frozen=True, slots=True)
class ModelSpec:
    role: str
    file: str
    sha256: str
    size: int
    license: str
    source: str
    url: str
    mirrors: tuple[str, ...] = ()
    license_texts: tuple[str, ...] = ()

    @property
    def urls(self) -> tuple[str, ...]:
        return (self.url, *self.mirrors)


@dataclass(frozen=True, slots=True)
class TextSpec:
    """라이선스 근거 원문 파일."""

    file: str
    label: str
    sha256: str
    size: int
    url: str

    @property
    def urls(self) -> tuple[str, ...]:
        return (self.url,)


@dataclass(frozen=True, slots=True)
class Manifest:
    models: tuple[ModelSpec, ...]
    texts: tuple[TextSpec, ...]

    def model(self, role: str) -> ModelSpec:
        for m in self.models:
            if m.role == role:
                return m
        raise KeyError(role)


def _str(item: Mapping[str, Any], key: str, where: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{where}: {key}는 비어 있지 않은 문자열이다")
    return value.strip()


def _strs(item: Mapping[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = item.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ManifestError(f"{where}: {key}는 문자열 목록이다")
    return tuple(value)


def _file(item: Mapping[str, Any], where: str) -> str:
    file = _str(item, "file", where)
    win = PureWindowsPath(file)
    if win.drive or win.root or PurePosixPath(file).is_absolute() or len(win.parts) != 1:
        raise ManifestError(f"{where}: file은 모델 폴더 바로 아래 파일 이름이다 ({file!r})")
    return file


def _hash_size(item: Mapping[str, Any], where: str) -> tuple[str, int]:
    sha = _str(item, "sha256", where).lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ManifestError(f"{where}: sha256은 16진수 64자다")
    size = item.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ManifestError(f"{where}: size는 양의 정수다")
    return sha, size


def parse_manifest(data: Mapping[str, Any]) -> Manifest:
    texts: list[TextSpec] = []
    for i, item in enumerate(data.get("text", [])):
        where = f"text[{i}]"
        sha, size = _hash_size(item, where)
        texts.append(
            TextSpec(
                file=_file(item, where),
                label=_str(item, "label", where),
                sha256=sha,
                size=size,
                url=_str(item, "url", where),
            )
        )
    text_files = {t.file for t in texts}
    models: list[ModelSpec] = []
    for i, item in enumerate(data.get("model", [])):
        where = f"model[{i}]"
        sha, size = _hash_size(item, where)
        role = _str(item, "role", where)
        if role not in ROLES or any(m.role == role for m in models):
            raise ManifestError(f"{where}: role은 {'·'.join(ROLES)} 중 하나, 겹치지 않는다")
        refs = _strs(item, "license_texts", where)
        if not refs or not set(refs) <= text_files:
            raise ManifestError(f"{where}: license_texts는 [[text]]의 file을 가리킨다")
        models.append(
            ModelSpec(
                role=role,
                file=_file(item, where),
                sha256=sha,
                size=size,
                license=_str(item, "license", where),
                source=_str(item, "source", where),
                url=_str(item, "url", where),
                mirrors=_strs(item, "mirrors", where),
                license_texts=refs,
            )
        )
    if sorted(m.role for m in models) != sorted(ROLES):
        raise ManifestError(f"모델 표에 {'·'.join(ROLES)} 모델이 하나씩 있어야 한다")
    return Manifest(tuple(models), tuple(texts))


def load_manifest(path: Path = MANIFEST_PATH) -> Manifest:
    with path.open("rb") as f:
        return parse_manifest(tomllib.load(f))


# ---------------------------------------------------------------- 찾기


def install_root() -> Path:
    """설치본 루트 후보: 동봉 Python 폴더(`<설치>/python`)의 부모."""
    return Path(sys.base_prefix).resolve().parent


def repo_root() -> Path | None:
    """레포에서 실행 중이면 레포 루트 (편집 가능 설치). 아니면 None."""
    root = Path(__file__).resolve().parents[5]
    return root if (root / "python" / "kookabug_platform").is_dir() else None


def candidate_dirs(
    *,
    env: str | None = None,
    install: Path | None = None,
    repo: Path | None = None,
) -> list[Path]:
    """찾는 순서대로 후보 폴더. 환경 변수를 주면 그것 하나."""
    if env:
        return [Path(env)]
    out: list[Path] = []
    if install is not None:
        out.append(install / INSTALL_DIR_NAME)
    if repo is not None:
        out.append(repo / "build" / INSTALL_DIR_NAME)
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_file(path: Path, sha256: str, size: int) -> bool:
    """크기와 SHA256이 표와 같은가."""
    try:
        return path.stat().st_size == size and sha256_file(path) == sha256
    except OSError:
        return False


@dataclass(frozen=True, slots=True)
class OcrModels:
    """확인을 마친 모델 파일."""

    folder: Path
    det: Path
    rec: Path


# 같은 파일(경로·크기·수정 시각)은 프로세스 안에서 한 번만 해시한다
_verified: set[tuple[str, int, int]] = set()
_verified_lock = threading.Lock()


def _check_model(folder: Path, spec: ModelSpec) -> Path:
    path = folder / spec.file
    try:
        st = path.stat()
    except OSError:
        raise PlatformError(
            OCR_MODEL_MISSING, f"OCR 모델 {spec.file}이 {folder}에 없다. {FETCH_HINT}"
        ) from None
    key = (str(path.resolve()), st.st_size, st.st_mtime_ns)
    with _verified_lock:
        if key in _verified:
            return path
    if not verify_file(path, spec.sha256, spec.size):
        raise PlatformError(
            OCR_MODEL_CORRUPT,
            f"OCR 모델 {path}의 크기·SHA256이 모델 표와 다르다 (손상·다른 판). {FETCH_HINT}",
        )
    with _verified_lock:
        _verified.add(key)
    return path


def find_models(
    manifest: Manifest | None = None,
    *,
    dirs: Sequence[Path] | None = None,
) -> OcrModels:
    """모델 폴더를 찾고 두 모델을 확인한다. `dirs`를 주지 않으면 `candidate_dirs`(실제 환경)."""
    manifest = manifest or load_manifest()
    if dirs is None:
        dirs = candidate_dirs(
            env=os.environ.get(ENV, "").strip() or None, install=install_root(), repo=repo_root()
        )
    folder = next((d for d in dirs if d.is_dir()), None)
    if folder is None:
        searched = ", ".join(str(d) for d in dirs) or "(후보 없음)"
        raise PlatformError(
            OCR_MODEL_MISSING, f"OCR 모델 폴더가 없다 (찾은 곳: {searched}). {FETCH_HINT}"
        )
    return OcrModels(
        folder=folder,
        det=_check_model(folder, manifest.model("det")),
        rec=_check_model(folder, manifest.model("rec")),
    )
