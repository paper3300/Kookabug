"""`kookabug.lock` 읽기·쓰기 (M6 계획 3.3).

- 형식 `kookabug.lock/0`, 모양은 `plugin-lock.schema.json`. 파일은 정해진 JSON(canonical) 출력
- `revision` = 디스크 바이트 sha256 (없으면 None). 바꿔 넣기는 `write_atomic` + 교체 직전 revision
  재확인 → 다르면 `revision_conflict` (대상 파일 그대로)
- `lock_sha256` = 잠금 전체의 정규 JSON 해시 (신뢰 승인 캐시의 키, U2)
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from kookabug_core.canonical import canonical_dumps, loads_strict
from kookabug_core.documents import DocumentError, write_atomic
from kookabug_core.plugins.envs import canonical_hash
from kookabug_core.plugins.errors import PluginError
from kookabug_core.schema import check_shape

__all__ = [
    "LOCK_FORMAT",
    "dumps_lock",
    "lock_sha256",
    "parse_lock",
    "read_lock",
    "revision_of",
    "write_lock",
]

LOCK_FORMAT: Final = "kookabug.lock/0"


def revision_of(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def read_lock(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """(잠금, revision). 파일이 없으면 (None, None). 형식이 틀리면 `lock_invalid`."""
    data = _read_bytes(path)
    if data is None:
        return None, None
    return parse_lock(data, path.name), revision_of(data)


def parse_lock(data: bytes, name: str = "kookabug.lock") -> dict[str, Any]:
    """잠금 바이트 → 잠금. 형식이 틀리면 `lock_invalid`."""
    try:
        value = loads_strict(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PluginError("lock_invalid", f"{name}을(를) 읽을 수 없다: {exc}") from exc
    if not isinstance(value, dict) or value.get("format") != LOCK_FORMAT:
        raise PluginError("lock_invalid", f"{name}의 format이 {LOCK_FORMAT}이(가) 아니다")
    if problems := check_shape(value, "plugin-lock"):
        first = problems[0]
        raise PluginError("lock_invalid", f"{name}{first.pointer or ''}: {first.message}")
    lock: dict[str, Any] = value
    return lock


def normalized(lock: dict[str, Any]) -> dict[str, Any]:
    out = dict(lock)
    out["plugins"] = sorted(lock["plugins"], key=lambda p: str(p["id"]))
    envs = {}
    for name, env in sorted(lock["environments"].items()):
        env = dict(env)
        env["plugins"] = sorted(env["plugins"])
        env["packages"] = sorted(env["packages"], key=lambda p: str(p["name"]))
        envs[name] = env
    out["environments"] = envs
    return out


def dumps_lock(lock: dict[str, Any]) -> bytes:
    return canonical_dumps(normalized(lock)).encode("utf-8")


def lock_sha256(lock: dict[str, Any]) -> str:
    return canonical_hash(normalized(lock))


def write_lock(
    path: Path,
    lock: dict[str, Any],
    expected_revision: str | None,
    *,
    before_replace: Callable[[], None] | None = None,
) -> str:
    """잠금을 바꿔 넣는다 (커밋 지점). 교체 직전 디스크 revision이 `expected_revision`과 다르면
    `revision_conflict`이고 파일은 그대로다. 새 revision을 돌려준다."""
    if problems := check_shape(lock, "plugin-lock"):
        raise PluginError("lock_invalid", f"잠금 모양이 틀렸다: {problems[0].message}")
    data = dumps_lock(lock)

    def check() -> None:
        current = revision_of(_read_bytes(path))
        if current != expected_revision:
            raise PluginError(
                "revision_conflict", f"{path.name}이(가) 작업 중에 바뀌었다", stage="commit"
            )
        if before_replace is not None:
            before_replace()

    try:
        write_atomic(path, data, before_replace=check)
    except DocumentError as exc:
        raise PluginError("env_create_failed", str(exc), stage="commit") from exc
    return revision_of(data) or ""
