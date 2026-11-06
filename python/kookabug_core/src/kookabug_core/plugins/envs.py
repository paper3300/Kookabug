"""실행 환경 폴더: 지문·찾기·digest·완성 표식 (M6 계획 D6, 3.3·3.4).

- 폴더 `envs/<환경>-<지문12>-<작업8>/`. 쓰는 쪽은 `envs/` 안에서 완성 표식(`.kb-env.json`
  `{fingerprint, digest, complete: true, link_mode: "copy"}`)의 지문이 맞는 폴더를 찾는다 (여럿이면
  이름 순 첫째). 표식이 없거나 `complete`가 아니거나 복사 설치가 아니면 그 폴더는 없는 것이다
- `fingerprint` = sha256(정규 JSON `{python, platform, sdk, packages, plugin_wheels}`)
- `digest` = `Lib/site-packages` 아래 모든 파일(정규 상대 경로 '/', 대소문자 그대로)의 **실제
  바이트** sha256을 경로 순으로 이은 것의 sha256. 제외: `__pycache__/`·`*.pyc`, 각 `*.dist-info/`의
  `RECORD`·`INSTALLER`·`REQUESTED`·`direct_url.json`·`uv_cache.json`, `site-packages` 밖 전부
- 재사용 검증은 읽기만 한다 (표식 지문 일치·digest 재계산 = 표식 값)
- 검증에 실패한 완성 환경은 고치지 않고 `broken/<폴더 이름>` 기록(환경 폴더 밖)으로 "깨짐"을
  남긴다. 찾기·실행·sync·설치는 깨진 폴더를 건너뛰고 다음 후보를 쓰거나 새로 만든다. 그 폴더는
  gc가 지운다 (`select_env`)
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from kookabug_core.documents import write_atomic
from kookabug_core.plugins.uv import LINK_MODE

__all__ = [
    "MARKER",
    "Selection",
    "broken_of",
    "candidates",
    "env_digest",
    "env_python",
    "find_env",
    "fingerprint",
    "folder_name",
    "is_broken",
    "mark_broken",
    "read_marker",
    "select",
    "select_env",
    "state_signature",
    "still_complete",
    "verify_env",
    "write_marker",
]

MARKER: Final = ".kb-env.json"
IN_USE_DIR: Final = ".in-use"
BROKEN_DIR: Final = "broken"
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


def broken_dir(envs: Path) -> Path:
    """깨진 환경 기록 폴더 (`.kookabug/plugins/broken/`, 환경 폴더 밖)."""
    return envs.parent / BROKEN_DIR


def is_broken(env_dir: Path) -> bool:
    return (broken_dir(env_dir.parent) / env_dir.name).is_file()


def state_signature(envs: Path, environments: Mapping[str, Mapping[str, Any]]) -> str:
    """잠금 환경들의 지금 상태 표지: 환경마다 runner가 고를 폴더(깨지지 않은 완성 환경)와 깨짐 기록.
    잠금은 그대로인데 환경이 깨짐·없음으로 바뀐 것을 알아채는 데 쓴다 (daemon `plugins.changed`,
    M6 B6). 잠금 밖 환경(설치 중 새 폴더 등)은 보지 않는다. 읽기만 한다."""
    parts: list[str] = []
    for name in sorted(environments):
        fp = str(environments[name].get("fingerprint", ""))
        folder = find_env(envs, name, fp)
        broken = ",".join(broken_of(envs, name, fp))
        parts.append(f"{name}:{folder.name if folder else '-'}:{broken}")
    return "\n".join(parts)


def mark_broken(env_dir: Path, reason: str) -> None:
    """그 환경을 깨짐으로 기록한다 (폴더는 손대지 않는다 — gc가 지운다)."""
    record = broken_dir(env_dir.parent) / env_dir.name
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(reason + "\n", encoding="utf-8")


def candidates(envs: Path, env: str, fp: str) -> list[Path]:
    """그 지문의 깨지지 않은 완성 환경들 (이름 순)."""
    if not envs.is_dir():
        return []
    prefix = f"{env}-{fp[:12]}-"
    found: list[Path] = []
    for folder in sorted(p for p in envs.iterdir() if p.is_dir() and p.name.startswith(prefix)):
        marker = read_marker(folder)
        if marker is not None and marker.get("fingerprint") == fp and not is_broken(folder):
            found.append(folder)
    return found


def find_env(envs: Path, env: str, fp: str) -> Path | None:
    """그 지문의 깨지지 않은 완성 환경 (이름 순 첫째). 없으면 None. 검증하지 않는다."""
    found = candidates(envs, env, fp)
    return found[0] if found else None


@dataclass(frozen=True, slots=True)
class Selection:
    """`select` 결과. `folder`: 검증을 통과한 첫째 (없으면 None). `unreadable`: 읽다 실패했거나
    검증 중 사라진(gc가 지우는 중인) 후보 — 깨짐으로 기록하지 않았다. 호출자가 잠금·폴더를 다시
    보고 재시도할지 정한다."""

    folder: Path | None
    unreadable: tuple[Path, ...] = ()


def _same_marker(folder: Path, before: Mapping[str, Any]) -> bool:
    return read_marker(folder) == before


def select(envs: Path, env: str, fp: str, digest: str | None = None) -> Selection:
    """그 지문의 완성 환경 중 읽기 검증(`verify_env`)을 통과한 첫째.

    - 검증이 틀렸고(digest 다름) 그 뒤에도 폴더·완성 표식이 그대로면 깨짐으로 기록(폴더는
      그대로)하고 다음 후보
    - 파일 읽기가 실패했거나(`OSError`) 검증 중 완성 표식이 사라지거나 바뀌었으면(gc는 표식부터
      지운다) 깨짐으로 기록하지 않고 `unreadable`에 넣고 다음 후보 — 일시적 실패·합법적 삭제를
      영구 깨짐으로 남기지 않는다"""
    unreadable: list[Path] = []
    for folder in candidates(envs, env, fp):
        before = read_marker(folder)
        if before is None:
            unreadable.append(folder)
            continue
        try:
            problem = verify_env(folder, fp, digest)
        except OSError:
            unreadable.append(folder)
            continue
        if problem is None:
            return Selection(folder, tuple(unreadable))
        if not _same_marker(folder, before):
            unreadable.append(folder)  # 지우는 중이었다: 파일 목록이 줄어 digest가 달랐을 수 있다
            continue
        mark_broken(folder, problem)
    return Selection(None, tuple(unreadable))


def select_env(envs: Path, env: str, fp: str, digest: str | None = None) -> Path | None:
    """`select`의 폴더만 (읽을 수 없는 후보는 건너뛴다 — 호출자는 새로 만들거나 없음으로)."""
    return select(envs, env, fp, digest).folder


def still_complete(folder: Path) -> bool:
    """완성 표식이 있고 깨짐 기록이 없다 (op.lock 안 재확인용)."""
    return read_marker(folder) is not None and not is_broken(folder)


def broken_of(envs: Path, env: str, fp: str) -> list[str]:
    """그 지문의 깨짐 기록이 있는 폴더 이름들 (`verify` 보고용)."""
    folder = broken_dir(envs)
    if not folder.is_dir():
        return []
    prefix = f"{env}-{fp[:12]}-"
    return sorted(p.name for p in folder.iterdir() if p.name.startswith(prefix))


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
