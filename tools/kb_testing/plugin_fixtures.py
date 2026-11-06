"""플러그인 검사 픽스처 (M6 계획 D15): 결정적 wheel 만들기 — 네트워크·빌드 백엔드 없이.

    sdk = sdk_wheel(tmp / "sdk")                              # 레포의 kookabug_sdk 소스 그대로
    wheel = plugin_wheel(PLUGINS / "conflict_a", tmp / "w")   # kookabug-sdk build로 스키마 생성
    dep = dist_wheel(tmp / "idx", "kbfix-dep", "1.0.0", {"kbfix_dep/__init__.py": b"..."})
    broken = plugin_wheel(..., overrides={"kbfix_conflict_a/nodes.py": b"raise ..."})

- 같은 입력이면 같은 바이트: zip 항목 순서·시각(1980-01-01)·권한을 고정한다
- 플러그인 wheel은 프로젝트를 임시 폴더에 복사해 `kookabug_sdk.build.build()`로 스키마를 만든 뒤
  `src/<패키지>/` 아래 파일을 담는다(원본 폴더에 쓰지 않음). `overrides`·`schema_edit`로 빌드 뒤
  파일을 바꿔 깨진 픽스처를 만든다
- `index_files()`: 검사 인덱스에 올릴 의존성 wheel·sdist 묶음 (`plugin_index.IndexServer`)
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import tarfile
import tempfile
import tomllib
import zipfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
PLUGINS: Final = REPO_ROOT / "fixtures" / "plugins"
SAMPLE: Final = REPO_ROOT / "examples" / "plugins" / "kookabug-plugin-sample"
SDK_PROJECT: Final = REPO_ROOT / "python" / "kookabug_sdk"
_EPOCH: Final = (1980, 1, 1, 0, 0, 0)

__all__ = [
    "PLUGINS",
    "SAMPLE",
    "dist_wheel",
    "index_files",
    "normalize",
    "plugin_wheel",
    "sdist",
    "sdk_wheel",
    "sha256_file",
]


def normalize(name: str) -> str:
    """PEP 503 이름 정규화."""
    out = name.lower()
    for ch in "_.":
        out = out.replace(ch, "-")
    while "--" in out:
        out = out.replace("--", "-")
    return out


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_hash(data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"sha256={digest}"


def dist_wheel(
    dest: Path,
    name: str,
    version: str,
    files: Mapping[str, bytes],
    *,
    requires: Iterable[str] = (),
    entry_points: str | None = None,
    summary: str = "Kookabug test fixture",
) -> Path:
    """순수 Python wheel 하나 (`py3-none-any`)를 결정적으로 쓴다."""
    dest.mkdir(parents=True, exist_ok=True)
    stem = f"{name.replace('-', '_')}-{version}"
    info = f"{stem}.dist-info"
    metadata = [
        "Metadata-Version: 2.4",
        f"Name: {name}",
        f"Version: {version}",
        f"Summary: {summary}",
        "Requires-Python: >=3.14",
        *(f"Requires-Dist: {r}" for r in requires),
    ]
    entries: dict[str, bytes] = {path: data for path, data in sorted(files.items())}
    entries[f"{info}/METADATA"] = ("\n".join(metadata) + "\n").encode("utf-8")
    entries[f"{info}/WHEEL"] = (
        b"Wheel-Version: 1.0\nGenerator: kb_testing\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    )
    if entry_points:
        entries[f"{info}/entry_points.txt"] = entry_points.encode("utf-8")
    record = "".join(f"{p},{_record_hash(d)},{len(d)}\n" for p, d in entries.items())
    entries[f"{info}/RECORD"] = (record + f"{info}/RECORD,,\n").encode("utf-8")
    path = dest / f"{stem}-py3-none-any.whl"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for item, data in entries.items():
            zinfo = zipfile.ZipInfo(item, date_time=_EPOCH)
            zinfo.external_attr = 0o644 << 16
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zinfo, data)
    path.write_bytes(buffer.getvalue())
    return path


def sdist(dest: Path, name: str, version: str) -> Path:
    """sdist만 있는 배포판 (빌드하면 안 된다 — 빌드 스크립트가 표식을 남기지 않게 비어 있다)."""
    dest.mkdir(parents=True, exist_ok=True)
    stem = f"{name.replace('-', '_')}-{version}"
    path = dest / f"{stem}.tar.gz"
    pkg_info = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n".encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.PAX_FORMAT) as tf:
        for member, data in ((f"{stem}/PKG-INFO", pkg_info),):
            tar = tarfile.TarInfo(member)
            tar.size = len(data)
            tar.mtime = 0
            tf.addfile(tar, io.BytesIO(data))
    path.write_bytes(buffer.getvalue())
    return path


def _package_files(src: Path, package: str) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    root = src / package
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        out[path.relative_to(src).as_posix()] = path.read_bytes()
    return out


def sdk_wheel(dest: Path) -> Path:
    """레포의 `kookabug_sdk` 소스로 만든 SDK wheel (앱이 동봉하는 것과 같은 모양)."""
    project = tomllib.loads((SDK_PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(project["project"]["version"])
    files = _package_files(SDK_PROJECT / "src", "kookabug_sdk")
    scripts = "[console_scripts]\nkookabug-sdk = kookabug_sdk.cli:main\n"
    return dist_wheel(dest, "kookabug-sdk", version, files, entry_points=scripts)


def plugin_wheel(
    project: Path,
    dest: Path,
    *,
    overrides: Mapping[str, bytes | None] | None = None,
    schema_edit: Callable[[dict[str, Any]], None] | None = None,
    pyproject_edit: Callable[[dict[str, Any]], None] | None = None,
    version: str | None = None,
) -> Path:
    """플러그인 프로젝트 → wheel. 스키마는 `kookabug-sdk build`로 만든다(이 프로세스에서 모듈을
    import한다). `overrides`(패키지 기준 경로 → 바이트, None이면 지움)·`schema_edit`는 빌드 뒤에
    적용한다 — 파일 스키마와 코드가 다른 wheel, 잘못된 머리 같은 깨진 픽스처용."""
    from kookabug_sdk.build import build
    from kookabug_sdk.schema import SCHEMA_FILE

    with tempfile.TemporaryDirectory(prefix="kbplug-") as tmp:
        work = Path(tmp) / project.name
        shutil.copytree(project, work, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        pyproject_path = work / "pyproject.toml"
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        if version is not None or pyproject_edit is not None:
            if version is not None:
                data["project"]["version"] = version
            if pyproject_edit is not None:
                pyproject_edit(data)
            pyproject_path.write_text(_dump_toml(data), encoding="utf-8")
        out = build(work)
        package = out.path.parent.name
        if schema_edit is not None:
            document = json.loads(out.path.read_text(encoding="utf-8"))
            schema_edit(document)
            out.path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        files = _package_files(work / "src", package)
        for rel, value in (overrides or {}).items():
            if value is None:
                files.pop(rel, None)
            else:
                files[rel] = value
        assert f"{package}/{SCHEMA_FILE}" in files
        meta = data["project"]
        return dist_wheel(
            dest,
            str(meta["name"]),
            str(meta["version"]),
            files,
            requires=[str(r) for r in meta.get("dependencies", [])],
        )


def _dump_toml(data: Mapping[str, Any]) -> str:
    """픽스처 pyproject용 아주 작은 TOML 쓰기 (문자열·문자열 목록·표 한 단계)."""
    lines: list[str] = []

    def value(v: Any) -> str:
        if isinstance(v, list):
            return "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in v) + "]"
        return json.dumps(v, ensure_ascii=False)

    def table(name: str, body: Mapping[str, Any]) -> None:
        lines.append(f"[{name}]")
        nested: list[tuple[str, Mapping[str, Any]]] = []
        for key, v in body.items():
            if isinstance(v, Mapping):
                nested.append((f"{name}.{key}", v))
            else:
                lines.append(f"{key} = {value(v)}")
        lines.append("")
        for sub, sub_body in nested:
            table(sub, sub_body)

    for key, body in data.items():
        table(key, body)
    return "\n".join(lines)


def _dep_module(version: str) -> dict[str, bytes]:
    return {"kbfix_dep/__init__.py": f'__version__ = "{version}"\n'.encode()}


def index_files(dest: Path) -> Path:
    """검사 인덱스의 배포판 묶음 (폴더 하나, 이름은 wheel·sdist 파일명 그대로).

    - `kbfix-dep` 1.0.0·2.0.0 (충돌 픽스처)
    - `kbfix-mid` 1.0.0 → `kbfix-sdistonly` (sdist만: 전이 sdist 거부 검사)
    - 전이 SDK 요구: `kbfix-sdk-user` → `kookabug-sdk>=0.1.0.dev0,<0.2`(앱 SDK와 맞음),
      `kbfix-sdk-consumer` → `kookabug-sdk>=0.2`(안 맞음) + 인덱스의 가짜 `kookabug-sdk` 0.2.0
    """
    dest.mkdir(parents=True, exist_ok=True)
    dist_wheel(dest, "kbfix-dep", "1.0.0", _dep_module("1.0.0"))
    dist_wheel(dest, "kbfix-dep", "2.0.0", _dep_module("2.0.0"))
    dist_wheel(
        dest,
        "kbfix-mid",
        "1.0.0",
        {"kbfix_mid/__init__.py": b"VALUE = 1\n"},
        requires=["kbfix-sdistonly>=1"],
    )
    sdist(dest, "kbfix-sdistonly", "1.0.0")
    dist_wheel(dest, "kookabug-sdk", "0.2.0", {"kbfix_future_sdk.py": b""})
    dist_wheel(
        dest,
        "kbfix-sdk-user",
        "1.0.0",
        {"kbfix_sdk_user.py": b""},
        requires=["kookabug-sdk>=0.1.0.dev0,<0.2"],
    )
    dist_wheel(
        dest,
        "kbfix-sdk-consumer",
        "1.0.0",
        {"kbfix_sdk_consumer.py": b""},
        requires=["kookabug-sdk>=0.2"],
    )
    return dest
