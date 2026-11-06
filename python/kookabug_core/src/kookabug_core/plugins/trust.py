"""신뢰한 잠금 기억 (M6 U2): `.kookabug/local.json`의 `plugin_trust.locks`(정규 잠금 해시 목록).

- 사람이 신뢰 확인을 한 잠금(설치·제거·upgrade·relock으로 커밋한 잠금, sync에서 확인한 잠금)의
  `lock_sha256`을 기억한다. 잠금이 조금이라도 바뀌면(원천·wheel·권한 포함) 해시가 달라 다시 묻는다
- 쓰기는 `plugin_trust` 키만 바꾸고 다른 키·순서는 그대로, 교체 직전 revision 확인(바뀌었으면
  다시 읽어 한 번 더). 파일이 JSON이 아니거나 형식이 틀리면 쓰지 않는다 (기억 못 함 = 다음에 다시
  묻는다, 안전 쪽)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

from kookabug_core.canonical import loads_strict
from kookabug_core.documents import DocumentError, write_atomic
from kookabug_core.schema import check_shape
from kookabug_core.workspace import LOCAL_FILE

__all__ = ["KEEP", "is_trusted", "remember"]

KEEP: Final = 20
"""기억하는 잠금 해시 수 (오래된 것부터 버린다)."""
_LOCAL_FORMAT: Final = "kookabug.local/0"


class _Conflict(Exception):
    pass


def _path(root: Path) -> Path:
    return root.joinpath(*LOCAL_FILE.split("/"))


def _load(raw: bytes | None) -> dict[str, Any] | None:
    if raw is None:
        return {"format": _LOCAL_FORMAT}
    try:
        value = loads_strict(raw.decode("utf-8-sig"))
    except UnicodeDecodeError, ValueError:
        return None
    return value if isinstance(value, dict) else None  # pyright: ignore[reportUnknownVariableType]


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def is_trusted(root: Path, lock_sha256: str) -> bool:
    data = _load(_read(_path(root))) or {}
    locks = (data.get("plugin_trust") or {}).get("locks") or []
    return lock_sha256 in locks


def remember(root: Path, lock_sha256: str) -> bool:
    """기억한다. 쓰지 못하면 False (다음에 다시 묻는다)."""
    path = _path(root)
    for _ in range(3):
        raw = _read(path)
        data = _load(raw)
        if data is None:
            return False
        trust = dict(data.get("plugin_trust") or {})
        locks = [x for x in trust.get("locks") or [] if x != lock_sha256]
        trust["locks"] = [*locks, lock_sha256][-KEEP:]
        data["plugin_trust"] = trust
        if check_shape(data, "local"):
            return False
        body = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        before = None if raw is None else hashlib.sha256(raw).hexdigest()

        def unchanged(before: str | None = before) -> None:
            now = _read(path)
            if (None if now is None else hashlib.sha256(now).hexdigest()) != before:
                raise _Conflict

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(path, body, before_replace=unchanged)
            return True
        except _Conflict:
            continue
        except DocumentError, OSError:
            return False
    return False
