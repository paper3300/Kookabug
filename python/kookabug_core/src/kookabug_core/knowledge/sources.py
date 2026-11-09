"""원본 위치와 상태 (M8 계획 3.4), `source` 근거 검증 (계획 9장 R5).

- 원본은 복사하지 않고 위치만 둔다. `path`(절대 또는 워크스페이스 기준), `url`, `local: true`(경로는
  `.kookabug/local.json#sources.<id>.path` — PC마다 다름)
- `check_sources`: `{id, state: ok|missing|unreadable|unchecked_url, hash, at}` → 캐시
  `.kookabug/cache/knowledge/sources.json`. 파일은 sha256, 폴더는 목록 해시(상대 경로·크기·수정
  시각, 링크·정션과 워크스페이스 파생 폴더 제외). URL은 받지 않는다(`unchecked_url`)
- `verify_basis`: Agent가 준 `source` 근거를 서비스가 확인한다. 실경로로 정규화(정션·심볼릭 해석)한
  뒤 워크스페이스 파생 경로면 `basis_derived`, 서비스가 계산한 hash와 다르면 `basis_hash_mismatch`,
  없는 원본·위치는 `basis_unknown`. URL·확인 못 한 원본은 `verified: false`
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, cast

from kookabug_core.documents import write_atomic
from kookabug_core.knowledge.formats import KnowledgeError, now
from kookabug_core.workspace import Workspace

__all__ = [
    "CACHE_FILE",
    "DERIVED_DIRS",
    "check_sources",
    "read_cache",
    "source_path",
    "sources_of",
    "verify_basis",
]

CACHE_FILE: Final = ".kookabug/cache/knowledge/sources.json"
DERIVED_DIRS: Final = (
    "knowledge",
    "wiki",
    ".kookabug",
    "runs",
    "tests",
    "subgraphs",
    "targets",
    "screens",
)
"""워크스페이스의 파생 경로 (R5): 원본 폴더 안이라도 근거로 쓰지 않는다. `AGENTS.md`도 제품 몫이라
뺀다."""
DERIVED_FILES: Final = ("agents.md",)
_REF: Final = re.compile(r"^sources:([A-Za-z0-9_.-]{1,64})(?:#(.+))?$")
_CHUNK: Final = 1 << 20


def sources_of(workspace: Workspace) -> list[dict[str, Any]]:
    raw = workspace.config.get("sources")
    return (
        [cast(dict[str, Any], s) for s in raw if isinstance(s, dict)]
        if isinstance(raw, list)
        else []
    )


def _find(workspace: Workspace, source_id: str) -> dict[str, Any] | None:
    return next((s for s in sources_of(workspace) if s.get("id") == source_id), None)


def source_path(workspace: Workspace, source: Mapping[str, Any]) -> Path | None:
    """파일·폴더 원본의 경로 (실경로 아님). URL·로컬 경로가 없는 원본은 None."""
    if source.get("local"):
        local = workspace.local or {}
        entry = (local.get("sources") or {}).get(source.get("id"))
        raw = entry.get("path") if isinstance(entry, dict) else None
    else:
        raw = source.get("path")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else workspace.root / path


def _rel_parts(base: Path, path: Path) -> list[str] | None:
    """`path`가 `base` 아래면 그 아래 조각들(대소문자 무시 비교), 아니면 None."""
    b = [p.casefold() for p in base.parts]
    p = list(path.parts)
    if len(p) < len(b) or [x.casefold() for x in p[: len(b)]] != b:
        return None
    return p[len(b) :]


def _derived(workspace: Workspace, path: Path) -> bool:
    """`path`가 워크스페이스(지정 경로·실경로 둘 다로 본다)의 파생 경로인가."""
    for root in (Path(os.path.abspath(workspace.root)), Path(os.path.realpath(workspace.root))):
        parts = _rel_parts(root, path)
        if not parts:
            continue
        first = parts[0].casefold()
        if any(first == d.casefold() for d in DERIVED_DIRS):
            return True
        if len(parts) == 1 and first in DERIVED_FILES:
            return True
    return False


def _link_target(path: Path) -> Path | None:
    """링크·정션이 바로 가리키는 곳 (한 단계). 링크가 아니거나 못 읽으면 None."""
    if not (path.is_symlink() or path.is_junction()):
        return None
    try:
        raw = os.readlink(path)
    except OSError:
        return None
    raw = raw.removeprefix("\\\\?\\")
    target = Path(raw)
    return Path(os.path.abspath(target if target.is_absolute() else path.parent / target))


def _derived_route(workspace: Workspace, path: Path, depth: int = 0) -> bool:
    """정규화 **전** 경로를 조각마다 따라가며 파생 경로를 지나는지 본다 (R5 — 정션 우회 차단).

    조각마다: 글자 그대로의 경로, 그 조각까지의 실경로(8.3 짧은 이름·대소문자·링크 해석), 그
    조각이 놓인 자리(부모 실경로 + 이름 — 파생 폴더 안의 링크·정션), 링크·정션이면 그것이 한
    단계씩 가리키는 곳(사슬 중간에 파생 경로를 지나는 경우) 중 하나라도 파생 경로면 True. 파생 경로
    안의 링크·정션이 바깥을 가리켜도, 바깥 별칭이 안쪽 파생 경로를 가리켜도 걸린다. 사슬이 너무
    길면 안전 쪽(True)."""
    if depth > 16:
        return True
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if _derived(workspace, current):
            return True
        if not (current.exists() or current.is_symlink()):
            continue
        placed = Path(os.path.realpath(current.parent)) / current.name
        if _derived(workspace, placed) or _derived(workspace, Path(os.path.realpath(current))):
            return True
        target = _link_target(current)
        if target is not None and _derived_route(workspace, target, depth + 1):
            return True
    return False


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _folder_hash(workspace: Workspace, folder: Path) -> str:
    """목록 해시: (상대 경로, 크기, 수정 시각 ns) 정렬. 링크·정션·워크스페이스 파생 폴더는 뺀다."""
    lines: list[str] = []
    for dirpath, dirnames, filenames in os.walk(folder):
        here = Path(dirpath)
        keep: list[str] = []
        for name in sorted(dirnames):
            entry = here / name
            if entry.is_symlink() or entry.is_junction():
                continue
            if _derived(workspace, Path(os.path.realpath(entry))):
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in sorted(filenames):
            entry = here / name
            if entry.is_symlink() or _derived(workspace, Path(os.path.realpath(entry))):
                continue
            st = entry.stat()
            rel = entry.relative_to(folder).as_posix()
            lines.append(f"{rel}\t{st.st_size}\t{st.st_mtime_ns}")
    return "sha256:" + hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def _hash_of(workspace: Workspace, real: Path) -> str:
    return _folder_hash(workspace, real) if real.is_dir() else _file_hash(real)


def check_sources(workspace: Workspace, *, write_cache: bool = True) -> list[dict[str, Any]]:
    """원본마다 상태 (3.4 `sources.check`). `write_cache`면 캐시 파일에도 쓴다."""
    out: list[dict[str, Any]] = []
    at = now()
    for source in sources_of(workspace):
        entry: dict[str, Any] = {"id": source.get("id"), "state": "ok", "hash": None, "at": at}
        if (
            isinstance(source.get("url"), str)
            and not source.get("path")
            and not source.get("local")
        ):
            entry["state"] = "unchecked_url"
            out.append(entry)
            continue
        path = source_path(workspace, source)
        if path is None:
            entry["state"] = "missing"
            out.append(entry)
            continue
        try:
            real = Path(os.path.realpath(path))
            if not real.exists():
                entry["state"] = "missing"
            else:
                entry["hash"] = _hash_of(workspace, real)
        except OSError:
            entry["state"] = "unreadable"
        out.append(entry)
    if write_cache:
        cache = workspace.root.joinpath(*CACHE_FILE.split("/"))
        cache.parent.mkdir(parents=True, exist_ok=True)
        body = {"format": "kookabug.sources-state/0", "sources": out}
        write_atomic(cache, (json.dumps(body, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return out


def read_cache(workspace: Workspace) -> list[dict[str, Any]]:
    """마지막 `check_sources` 결과 (없거나 깨졌으면 빈 목록)."""
    try:
        data = json.loads(
            workspace.root.joinpath(*CACHE_FILE.split("/")).read_text(encoding="utf-8")
        )
        return list(data["sources"])
    except OSError, ValueError, KeyError, TypeError:
        return []


def verify_basis(workspace: Workspace, basis: Mapping[str, Any]) -> dict[str, Any]:
    """`source` 근거 하나를 확인해 서비스가 채운 근거(`hash`·`verified`·`seen_at`)를 돌려준다.

    위치(`#` 뒤)는 폴더 원본이면 그 안의 상대 경로로 보고(파일이면 그 파일 hash), 파일 원본이면
    파일 안 위치 표시라 파일 hash를 쓴다."""
    ref = str(basis.get("ref", ""))
    match = _REF.fullmatch(ref)
    if match is None:
        raise KnowledgeError("basis_unknown", "source 근거 ref는 sources:<원본 ID>#<위치> 꼴이다")
    source = _find(workspace, match.group(1))
    if source is None:
        raise KnowledgeError("basis_unknown", "kookabug.json sources에 없는 원본이다")
    out = {k: v for k, v in basis.items() if k not in ("verified",)}
    out["seen_at"] = now()  # 서비스가 확인한 때 (Agent가 준 값은 쓰지 않는다)
    path = source_path(workspace, source)
    if path is None:
        # URL 등: Kookabug가 받지 않는다. 근거로 쓰되 확인 안 됨으로 남긴다 (R5)
        out["verified"] = False
        return out
    path = Path(os.path.abspath(path))
    real = Path(os.path.realpath(path))
    loc = match.group(2)
    if loc is not None and real.is_dir():
        parts = loc.replace("\\", "/").split("/")
        if loc.startswith("/") or any(p in ("", ".", "..") or ":" in p for p in parts):
            raise KnowledgeError("basis_unknown", "원본 위치가 원본 폴더 안 상대 경로가 아니다")
        lexical = path.joinpath(*parts)
        target = Path(os.path.realpath(real.joinpath(*parts)))
    else:
        lexical = path
        target = real
    # 파생 판정이 먼저다: 정규화 전 경로가 파생 경로를 지나거나(안→밖 정션), 실경로가 파생
    # 경로면(밖→안 별칭) basis_derived로 드러낸다
    if _derived_route(workspace, lexical) or _derived(workspace, target):
        raise KnowledgeError(
            "basis_derived",
            "워크스페이스의 파생 경로(knowledge·wiki·runs·tests 등)는 원본 근거로 쓸 수 없다",
        )
    if not target.is_relative_to(real):
        raise KnowledgeError("basis_unknown", "원본 위치의 실경로가 원본 폴더 밖이다")
    if not target.exists():
        raise KnowledgeError("basis_unknown", "원본 파일이 없다")
    try:
        computed = _hash_of(workspace, target)
    except OSError as exc:
        raise KnowledgeError("basis_unknown", f"원본을 읽을 수 없다: {exc.strerror}") from exc
    given = basis.get("hash")
    if isinstance(given, str) and given and given != computed:
        raise KnowledgeError(
            "basis_hash_mismatch", "근거 hash가 서비스가 계산한 원본 hash와 다르다", hash=computed
        )
    out["hash"] = computed
    out["verified"] = True
    return out
