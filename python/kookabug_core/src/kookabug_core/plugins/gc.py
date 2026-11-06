"""안 쓰는 환경·보관 wheel 정리 — 사람이 부르는 것만 (M6 계획 3.6, U13).

`busy.lock`을 쥐고, 남길 환경은 `op.lock` 밖에서 고른 뒤(digest 계산) `op.lock` 안에서 잠금
바이트를 다시 보고 사용 표식을 확인하며 지운다:

- 남기는 것: 지금 잠금의 각 환경에 대해 runner·sync와 같은 선택(`envs.select`)이 고르는 폴더와
  읽지 못한 후보 전부(보수적), 살아 있는 사용 표식(`.in-use/<pid>-<생성시각>`)이 있는 환경 폴더,
  잠금이 가리키는 `plugins/wheels/<sha256>/` 폴더
- 지우는 것: 나머지 환경 폴더(미완성·커밋 안 된 거래의 환경·같은 지문 중복·깨짐 기록이 있는 것),
  안 쓰는 보관 wheel 폴더, staging, 폴더가 없어진 깨짐 기록
- 사용 표식은 PID + 생성 시각으로 살아 있는지 본다 (PID 재사용을 가린다). 죽은 프로세스의 표식은
  없는 것으로 본다
- 지우다 실패하면 그 폴더는 `.kb-env.json`부터 지워 "없는 것"으로 만든 뒤 다음 gc에 맡긴다
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from kookabug_core.plugins import envs as envs_mod
from kookabug_core.plugins.errors import PluginError
from kookabug_core.plugins.layout import Layout
from kookabug_core.plugins.lockfile import parse_lock
from kookabug_core.plugins.uv import remove_tree
from kookabug_core.win import ProcessId, is_alive

__all__ = ["collect", "in_use", "keep_envs", "marker_name"]

GC_ATTEMPTS: Final = 3
"""남길 환경을 고르는 동안 잠금이 바뀌면 처음부터 다시 하는 횟수."""


def marker_name(ident: ProcessId) -> str:
    return f"{ident.pid}-{ident.created}"


def in_use(env_dir: Path) -> bool:
    """살아 있는 프로세스의 사용 표식이 있는가."""
    folder = env_dir / envs_mod.IN_USE_DIR
    if not folder.is_dir():
        return False
    for marker in folder.iterdir():
        pid, _, created = marker.name.partition("-")
        try:
            ident = ProcessId(int(pid), int(created))
        except ValueError:
            continue
        if is_alive(ident):
            return True
    return False


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def keep_envs(layout: Layout, lock: Mapping[str, Any] | None) -> set[Path]:
    """지금 잠금에서 남길 환경 폴더 — runner·sync와 **같은 선택**(`envs.select`, digest = 잠금):
    고르는 폴더 + 읽지 못한 후보 전부(보수적, 깨짐 기록 없음). 검증에 실패한 폴더는 그 선택이
    깨짐으로 기록하므로 남기지 않는다. digest를 계산하므로 op.lock 밖에서 부른다."""
    keep: set[Path] = set()
    if lock is None:
        return keep
    for name, env in lock["environments"].items():
        chosen = envs_mod.select(layout.envs, name, env["fingerprint"], env["digest"])
        if chosen.folder is not None:
            keep.add(chosen.folder)
        keep.update(chosen.unreadable)
    return keep


def plan(layout: Layout, lock: Mapping[str, Any] | None, keep: set[Path]) -> dict[str, list[Path]]:
    """지울 것 (op.lock 안에서 부른다 — 사용 표식은 여기서 본다). `keep`은 `keep_envs`."""
    keep_wheels: set[Path] = set()
    if lock is not None:
        for plugin in lock["plugins"]:
            keep_wheels.add(layout.wheel_path(plugin["wheel"]).parent)
    envs = [
        p
        for p in sorted(layout.envs.iterdir() if layout.envs.is_dir() else [])
        if p.is_dir() and p not in keep and not in_use(p)
    ]
    wheels = [
        p
        for p in sorted(layout.wheels.iterdir() if layout.wheels.is_dir() else [])
        if p.is_dir() and p not in keep_wheels
    ]
    staging = sorted(layout.staging.iterdir()) if layout.staging.is_dir() else []
    return {"envs": envs, "wheels": wheels, "staging": staging}


def collect(layout: Layout, confirm: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    """busy.lock을 쥔 호출자가 부른다. 확인에서 취소하면 아무것도 지우지 않는다.

    남길 환경은 op.lock 밖에서 고르고(digest), 지우기 직전 op.lock 안에서 잠금 바이트가 그대로인지
    다시 본다 — 그 사이 설치가 커밋했으면 처음부터. 사용 표식은 op.lock 안에서 본다."""
    for _ in range(GC_ATTEMPTS):
        with layout.op():
            data = _read(layout.lock)
        lock = None if data is None else parse_lock(data, layout.lock.name)
        keep = keep_envs(layout, lock)
        with layout.op():
            if _read(layout.lock) != data:
                continue
            return _remove(layout, plan(layout, lock, keep), confirm)
    raise PluginError(
        "revision_conflict", "gc를 준비하는 동안 kookabug.lock이 계속 바뀌었다", stage="gc"
    )


def _remove(
    layout: Layout, targets: dict[str, list[Path]], confirm: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    """op.lock 안에서 부른다."""
    names = {k: [p.name for p in v] for k, v in targets.items()}
    if not any(targets.values()):
        return {"removed": names, "failed": [], "cancelled": False}
    if not confirm(names):
        return {"removed": {k: [] for k in names}, "failed": [], "cancelled": True}
    failed: list[str] = []
    removed: dict[str, list[str]] = {k: [] for k in targets}
    for kind, paths in targets.items():
        for path in paths:
            try:
                if kind == "envs":
                    # 먼저 "없는 것"으로: 중간에 실패해도 반쯤 지운 폴더를 아무도 쓰지 않는다
                    with contextlib.suppress(FileNotFoundError):
                        (path / envs_mod.MARKER).unlink()
                remove_tree(path)
                removed[kind].append(path.name)
            except OSError:
                failed.append(f"{kind}/{path.name}")
    _drop_orphan_records(layout)
    return {"removed": removed, "failed": failed, "cancelled": False}


def _drop_orphan_records(layout: Layout) -> None:
    """폴더가 없어진 깨짐 기록을 지운다."""
    records = envs_mod.broken_dir(layout.envs)
    if not records.is_dir():
        return
    for record in records.iterdir():
        if not (layout.envs / record.name).exists():
            with contextlib.suppress(OSError):
                record.unlink()
