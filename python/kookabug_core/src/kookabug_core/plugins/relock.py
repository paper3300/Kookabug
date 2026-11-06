"""`kookabug plugin relock`: 앱 Python 소판·SDK로 다시 잠근다 (M6 계획 3.7, D10). 사람이 승인하는
별도 거래다 (sync·실행은 조건이 다르면 아무것도 바꾸지 않는다).

    busy.lock → 각 플러그인 `requires`의 SDK 범위·min_core 검사 (어긋나면 그 ID와 함께 거부,
    아무것도 안 바뀜) → 커밋된 wheel 바이트 대조 → 신뢰 확인 → 환경마다 기존 판을 제약으로 다시
    해석 → 3.5 ⑦(가)/(나) → ⑨ 잠금 바꿔 넣기

- 빌드 없음 (커밋된 wheel 그대로). 플러그인 항목(wheel·스키마·원천)은 그대로, 머리 조건과 환경만
  바뀐다
- 조건이 이미 같으면 아무것도 하지 않는다 (`changed: false`)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from kookabug_core.plugins.errors import PluginError
from kookabug_core.plugins.lockfile import UNCHECKED, Unchecked, lock_sha256, read_lock
from kookabug_core.plugins.manifest import SDK_DIST, min_core_satisfied, requirement_name
from kookabug_core.plugins.resolve import Package, ResolveFailure, resolve_with_app_sdk
from kookabug_core.plugins.uv import find_uv, mask

if TYPE_CHECKING:
    from kookabug_core.plugins.ops import PluginOps

__all__ = ["relock"]


def relock(
    ops: PluginOps,
    *,
    confirm: Callable[[dict[str, Any]], bool],
    expected_sha256: str | Unchecked | None = UNCHECKED,
) -> dict[str, Any]:
    """`expected_sha256`: 사람이 확인 카드에서 본 잠금의 정규 해시 (잠금이 없었으면 명시적 None).
    거래 안(busy.lock·op.lock 아래)에서 읽은 잠금과 None까지 비교해 다르면 `revision_conflict` —
    확인한 목록과 확인 실행할 목록이 같을 때만 진행한다. 생략(`UNCHECKED`, CLI)만 비교하지 않는다
    (CLI는 거래 안에서 묻는다)."""
    from kookabug_core.plugins.ops import (
        _EnvPlan,  # pyright: ignore[reportPrivateUsage]
        _last_line,  # pyright: ignore[reportPrivateUsage]
        _resolve_error,  # pyright: ignore[reportPrivateUsage]
    )

    with ops._transaction() as (op_id, staging, runner):  # pyright: ignore[reportPrivateUsage]
        with ops.layout.op():
            lock, revision = read_lock(ops.layout.lock)
        current = None if lock is None else lock_sha256(lock)
        if expected_sha256 is not UNCHECKED and expected_sha256 != current:
            raise PluginError(
                "revision_conflict", "확인한 뒤 kookabug.lock이 바뀌었다", stage="check"
            )
        app = ops.app
        if lock is None or app.stale_reason(lock) is None:
            return {"op_id": op_id, "changed": False, "revision": revision}
        work = staging / "resolve"
        for plugin in lock["plugins"]:
            sdk_requires = [r for r in plugin["requires"] if requirement_name(r) == SDK_DIST]
            ops._check_sdk(runner, work, plugin["id"], sdk_requires)  # pyright: ignore[reportPrivateUsage]
            min_core = plugin["manifest"].get("min_core")
            if min_core and not min_core_satisfied(app.core_version, str(min_core)):
                raise PluginError(
                    "core_too_old",
                    f"{plugin['id']}은(는) 앱 {min_core} 이상이 필요하다 (지금 {app.core_version})",
                    stage="manifest",
                    plugin=plugin["id"],
                )
        wheels = {str(p["id"]): ops._archived_wheel(p) for p in lock["plugins"]}  # pyright: ignore[reportPrivateUsage]
        asked = {
            "op_id": op_id,
            "from": {"python": lock["python"], "sdk": lock["sdk"]["version"]},
            "to": {"python": app.python, "sdk": app.sdk_version},
            "plugins": [
                {
                    "id": p["id"],
                    "version": p["version"],
                    "permissions": p["manifest"].get("permissions", []),
                }
                for p in lock["plugins"]
            ],
            # 신뢰 확인 안 한 잠금이면 전체 플러그인 (위 목록과 같다 — 새 환경에서 모두 import된다)
            "untrusted": ops._untrusted(lock, lock["plugins"]),  # pyright: ignore[reportPrivateUsage]
        }
        if not confirm(asked):
            raise PluginError("cancelled", "신뢰 확인에서 취소했다", stage="confirm")
        ops._point("confirmed")  # pyright: ignore[reportPrivateUsage]
        index = ops.index()
        uv = find_uv(ops.environ)
        new_lock = dict(lock)
        new_lock.update(
            python=app.python,
            python_full=app.python_full,
            platform=app.platform,
            sdk=app.sdk(),
            index=mask(index.url),
            environments={},
        )
        sdk_wheel = ops._app_sdk_wheel(work)  # pyright: ignore[reportPrivateUsage]
        for name, env in sorted(lock["environments"].items()):
            members = [p for p in lock["plugins"] if p["env"] == name]
            requirements = sorted(
                {r for p in members for r in p["requires"] if requirement_name(r) != SDK_DIST}
            )
            pins = [f"{p['name']}=={p['version']}" for p in env["packages"]]
            try:
                packages: list[Package] = resolve_with_app_sdk(
                    runner,
                    uv,
                    work,
                    requirements,
                    python=app.python,
                    index=index,
                    sdk_wheel=sdk_wheel,
                    constraints=pins,
                )
            except ResolveFailure as exc:
                if exc.kind == "unsatisfiable" and SDK_DIST in exc.message:
                    raise PluginError(
                        "sdk_incompatible",
                        f"환경 {name}의 의존성이 앱 SDK {app.sdk_version}과(와) 맞지 않는다: "
                        f"{mask(_last_line(exc.message))}",
                        stage="resolve",
                        env=name,
                    ) from exc
                raise _resolve_error(exc) from exc
            plan = _EnvPlan(
                name, members, packages, {str(m["id"]): wheels[m["id"]] for m in members}
            )
            ops._prepare_env(runner, op_id, staging, plan, new_lock, index)  # pyright: ignore[reportPrivateUsage]
        new_revision = ops._commit(new_lock, revision)  # pyright: ignore[reportPrivateUsage]
        ops._point("committed")  # pyright: ignore[reportPrivateUsage]
        shown = [str(p["id"]) for p in lock["plugins"]]  # 확인에 전부 나왔다
        ops._remember(lock, new_lock, shown)  # pyright: ignore[reportPrivateUsage]
        return {"op_id": op_id, "changed": True, "revision": new_revision}
