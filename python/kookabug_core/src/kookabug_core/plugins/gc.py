"""안 쓰는 환경·보관 wheel 정리 — 사람이 부르는 것만 (M6 계획 3.6, U13).

`busy.lock` + `op.lock`을 쥐고 판단·삭제한다:

- 남기는 것: 지금 잠금의 각 환경에 대해 runner가 고를 완성 폴더(지문이 맞는 이름 순 첫째),
  살아 있는 사용 표식(`.in-use/<pid>-<생성시각>`)이 있는 환경 폴더, 잠금이 가리키는
  `plugins/wheels/<sha256>/` 폴더
- 지우는 것: 나머지 환경 폴더(미완성·커밋 안 된 거래의 환경·같은 지문 중복), 안 쓰는 보관 wheel
  폴더, staging
- 사용 표식은 PID + 생성 시각으로 살아 있는지 본다 (PID 재사용을 가린다). 죽은 프로세스의 표식은
  없는 것으로 본다
- 지우다 실패하면 그 폴더는 `.kb-env.json`부터 지워 "없는 것"으로 만든 뒤 다음 gc에 맡긴다
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kookabug_core.plugins import envs as envs_mod
from kookabug_core.plugins.layout import Layout
from kookabug_core.plugins.lockfile import read_lock
from kookabug_core.plugins.uv import remove_tree
from kookabug_core.win import ProcessId, is_alive

__all__ = ["collect", "in_use", "marker_name"]


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


def plan(layout: Layout) -> dict[str, list[Path]]:
    """지울 것 (op.lock 안에서 부른다)."""
    lock, _ = read_lock(layout.lock)
    keep_envs: set[Path] = set()
    keep_wheels: set[Path] = set()
    if lock is not None:
        for name, env in lock["environments"].items():
            found = envs_mod.find_env(layout.envs, name, env["fingerprint"])
            if found is not None:
                keep_envs.add(found)
        for plugin in lock["plugins"]:
            keep_wheels.add(layout.wheel_path(plugin["wheel"]).parent)
    envs = [
        p
        for p in sorted(layout.envs.iterdir() if layout.envs.is_dir() else [])
        if p.is_dir() and p not in keep_envs and not in_use(p)
    ]
    wheels = [
        p
        for p in sorted(layout.wheels.iterdir() if layout.wheels.is_dir() else [])
        if p.is_dir() and p not in keep_wheels
    ]
    staging = sorted(layout.staging.iterdir()) if layout.staging.is_dir() else []
    return {"envs": envs, "wheels": wheels, "staging": staging}


def collect(layout: Layout, confirm: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    """busy.lock을 쥔 호출자가 부른다. 확인에서 취소하면 아무것도 지우지 않는다."""
    with layout.op():
        targets = plan(layout)
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
        return {"removed": removed, "failed": failed, "cancelled": False}
