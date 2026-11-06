"""검사용 PEP 517 빌드 백엔드: `KBFIX_MARKER_DIR`에 `backend` 표식을 쓰고 순수 Python wheel을
만든다.

설치 거래가 신뢰 확인 전에 빌드 백엔드 코드를 돌리지 않는지 본다 (M6 계획 3.11 `build_marker`).
"""

from __future__ import annotations

import base64
import hashlib
import os
import tomllib
import zipfile
from pathlib import Path

_EPOCH = (1980, 1, 1, 0, 0, 0)


def _mark(name: str) -> None:
    folder = os.environ.get("KBFIX_MARKER_DIR")
    if folder:
        Path(folder, name).write_text("ran\n", encoding="utf-8")


def get_requires_for_build_wheel(config_settings: object = None) -> list[str]:
    return []


def build_wheel(
    wheel_directory: str, config_settings: object = None, metadata_directory: object = None
) -> str:
    _mark("backend")
    root = Path.cwd()
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    stem = f"{project['name'].replace('-', '_')}-{project['version']}"
    info = f"{stem}.dist-info"
    files: dict[str, bytes] = {}
    src = root / "src"
    for path in sorted(src.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            files[path.relative_to(src).as_posix()] = path.read_bytes()
    metadata = [
        "Metadata-Version: 2.4",
        f"Name: {project['name']}",
        f"Version: {project['version']}",
        *(f"Requires-Dist: {r}" for r in project.get("dependencies", [])),
    ]
    files[f"{info}/METADATA"] = ("\n".join(metadata) + "\n").encode()
    files[f"{info}/WHEEL"] = b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    record = ""
    for item, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        record += f"{item},sha256={digest},{len(data)}\n"
    files[f"{info}/RECORD"] = (record + f"{info}/RECORD,,\n").encode()
    name = f"{stem}-py3-none-any.whl"
    with zipfile.ZipFile(Path(wheel_directory) / name, "w", zipfile.ZIP_DEFLATED) as zf:
        for item, data in files.items():
            entry = zipfile.ZipInfo(item, date_time=_EPOCH)
            entry.external_attr = 0o644 << 16
            zf.writestr(entry, data)
    return name
