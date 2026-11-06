"""실행 환경 폴더: 지문·찾기·digest·완성 표식 (M6 계획 D6, 3.3·3.4).

- 폴더 `envs/<환경>-<지문12>-<작업8>/`. 쓰는 쪽은 `envs/` 안에서 완성 표식(`.kb-env.json`
  `{fingerprint, digest, complete: true, link_mode: "copy"}`)의 지문이 맞는 폴더를 찾는다 (여럿이면
  이름 순 첫째). 표식이 없거나 `complete`가 아니거나 복사 설치가 아니면 그 폴더는 없는 것이다
- `fingerprint` = sha256(정규 JSON `{python, platform, sdk, packages, plugin_wheels}`)
- `digest` = `Lib/site-packages` 아래 모든 파일(정규 상대 경로 '/', 대소문자 그대로)의 **실제
  바이트** sha256을 경로 순으로 이은 것의 sha256. 제외: `__pycache__/`·`*.pyc`, 각 `*.dist-info/`의
  `RECORD`·`INSTALLER`·`REQUESTED`·`direct_url.json`·`uv_cache.json`, `site-packages` 밖 전부
- 재사용 검증은 읽기만 한다 (표식 지문 일치·digest 재계산 = 표식 값)
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from kookabug_core.documents import write_atomic
from kookabug_core.plugins.uv import LINK_MODE

__all__ = [
    "MARKER",
    "env_digest",
    "env_python",
    "find_env",
    "fingerprint",
    "folder_name",
    "read_marker",
    "verify_env",
    "write_marker",
]

MARKER: Final = ".kb-env.json"
IN_USE_DIR: Final = ".in-use"
_DIST_INFO_SKIP: Final = frozenset(
    {"RECORD", "INSTALLER", "REQUESTED", "direct_url.json", "uv_cache.json"}
)


def canonical_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(
    *,
    python: str,
    platform: str,
    sdk: Mapping[str, str],
    packages: Sequence[Mapping[str, Any]],
    plugin_wheels: Iterable[str],
) -> str:
    return canonical_hash(
        {
            "python": python,
            "platform": platform,
            "sdk": dict(sdk),
            "packages": sorted(packages, key=lambda p: str(p["name"])),
            "plugin_wheels": sorted(plugin_wheels),
        }
    )


def folder_name(env: str, fp: str, op_id: str) -> str:
    return f"{env}-{fp[:12]}-{op_id[:8]}"


def env_python(env_dir: Path) -> Path:
    return env_dir / "Scripts" / "python.exe"


def site_packages(env_dir: Path) -> Path:
    return env_dir / "Lib" / "site-packages"


def _counted(rel: Sequence[str]) -> bool:
    if "__pycache__" in rel or rel[-1].endswith(".pyc"):
        return False
    return not (len(rel) == 2 and rel[0].endswith(".dist-info") and rel[1] in _DIST_INFO_SKIP)


def env_digest(env_dir: Path) -> str:
    """실제 파일 바이트 digest (RECORD를 믿지 않는다)."""
    base = site_packages(env_dir)
    lines: list[str] = []
    for folder, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            path = Path(folder) / name
            rel = path.relative_to(base).parts
            if not _counted(rel):
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{'/'.join(rel)}\0{digest}\n")
    return hashlib.sha256("".join(sorted(lines)).encode("utf-8")).hexdigest()


def read_marker(env_dir: Path) -> dict[str, Any] | None:
    """완성 표식. 없거나 깨졌거나 `complete`가 아니거나 복사 설치(`link_mode: copy`)가 아니면
    None (그 폴더는 없는 것 — 실행·재사용에 안 쓰고 gc가 치운다). 하드 링크 환경은 uv 캐시·다른
    환경과 파일을 나눠 쓰므로 재사용하지 않는다."""
    try:
        data = json.loads((env_dir / MARKER).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    if not isinstance(data, dict) or data.get("complete") is not True:
        return None
    if data.get("link_mode") != LINK_MODE:  # pyright: ignore[reportUnknownMemberType]
        return None
    return data  # pyright: ignore[reportUnknownVariableType]


def write_marker(env_dir: Path, *, env: str, fp: str, digest: str) -> None:
    """완성 표식 (거래 ⑦(나)의 마지막)."""
    body = {
        "complete": True,
        "digest": digest,
        "env": env,
        "fingerprint": fp,
        "link_mode": LINK_MODE,
    }
    write_atomic(env_dir / MARKER, (json.dumps(body, sort_keys=True, indent=2) + "\n").encode())


def find_env(envs: Path, env: str, fp: str) -> Path | None:
    """그 지문의 완성 환경 (이름 순 첫째). 없으면 None."""
    if not envs.is_dir():
        return None
    prefix = f"{env}-{fp[:12]}-"
    for folder in sorted(p for p in envs.iterdir() if p.is_dir() and p.name.startswith(prefix)):
        marker = read_marker(folder)
        if marker is not None and marker.get("fingerprint") == fp:
            return folder
    return None


def verify_env(env_dir: Path, fp: str, digest: str | None = None) -> str | None:
    """읽기 전용 검증. 문제가 없으면 None, 있으면 이유. `digest`를 주면 그 값과도 대조한다."""
    marker = read_marker(env_dir)
    if marker is None:
        return "완성 표식이 없다"
    if marker.get("fingerprint") != fp:
        return "완성 표식의 지문이 다르다"
    actual = env_digest(env_dir)
    if actual != marker.get("digest"):
        return "환경 파일이 완성 표식과 다르다 (digest)"
    if digest is not None and actual != digest:
        return "환경 파일이 잠금과 다르다 (digest)"
    return None
