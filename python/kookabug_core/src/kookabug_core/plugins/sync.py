"""`kookabug plugin sync`: 잠금 → 환경 (M6 계획 3.7, D4·D10). 잠금 파일을 쓰지 않는다.

- 조건(Python 소판·플랫폼·SDK 판·SDK wheel sha256)이 앱과 다르면 아무것도 바꾸지 않고
  `plugin_env_stale` (앱에 맞추려면 사람이 `relock`)
- 빌드 없음: 커밋된 wheel만, 잠금의 `plugins/wheels/<sha256>/<원래 이름>` 경로를 그대로 uv에 넘기고
  넘기기 전에 바이트 sha256을 대조한다. 의존성은 잠금의 판·해시(`--require-hashes`)
- 환경마다 3.5 ⑦: 같은 지문의 완성 환경이 있으면 읽기 검증만(digest = 잠금), 없으면 새 확정 경로에
  만들고 digest가 잠금과 같을 때만 완성 표식. 틀리면 `verify_failed` (기존 폴더는 손대지 않는다)
- 새 환경을 만들면 플러그인 코드가 돈다(검증 import) → 신뢰 확인. 이 PC에서 신뢰한 잠금(정규 잠금
  해시)이면 다시 묻지 않는다. `expected_sha256`(사람이 확인한 잠금)이 지금 잠금과 다르면
  `revision_conflict`
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from kookabug_core.plugins import envs as envs_mod
from kookabug_core.plugins import trust
from kookabug_core.plugins.errors import PluginError
from kookabug_core.plugins.lockfile import lock_sha256, read_lock
from kookabug_core.plugins.resolve import Package

if TYPE_CHECKING:
    from kookabug_core.plugins.ops import PluginOps

__all__ = ["check_conditions", "sync"]


def check_conditions(ops: PluginOps, lock: dict[str, Any]) -> None:
    """조건(D10)이 앱과 다르면 `plugin_env_stale` (아무것도 바꾸기 전에 부른다)."""
    stale = ops.app.stale_reason(lock)
    if stale is not None:
        raise PluginError(
            "plugin_env_stale",
            f"{stale}. 이 앱으로 쓰려면 kookabug plugin relock (사람이 확인)",
            stage="check",
        )


def sync(
    ops: PluginOps,
    *,
    confirm: Callable[[dict[str, Any]], bool],
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    from kookabug_core.plugins.ops import _EnvPlan  # pyright: ignore[reportPrivateUsage]

    with ops._transaction() as (op_id, staging, runner):  # pyright: ignore[reportPrivateUsage]
        with ops.layout.op():
            lock, _ = read_lock(ops.layout.lock)
        if lock is None:
            if expected_sha256 is not None:
                raise PluginError("revision_conflict", "잠금이 없다", stage="check")
            return {"op_id": op_id, "lock_sha256": None, "created": [], "ready": []}
        current = lock_sha256(lock)
        if expected_sha256 is not None and expected_sha256 != current:
            raise PluginError(
                "revision_conflict", "확인한 뒤 kookabug.lock이 바뀌었다", stage="check"
            )
        check_conditions(ops, lock)
        app = ops.app
        ready: list[str] = []
        missing: list[str] = []
        for name, env in sorted(lock["environments"].items()):
            members = [p for p in lock["plugins"] if p["env"] == name]
            fp = envs_mod.fingerprint(
                python=app.python,
                platform=app.platform,
                sdk=app.sdk(),
                packages=env["packages"],
                plugin_wheels=[str(p["wheel_sha256"]) for p in members],
            )
            if fp != env["fingerprint"] or sorted(p["id"] for p in members) != env["plugins"]:
                raise PluginError(
                    "verify_failed",
                    f"잠금의 환경 {name} 지문이 내용과 맞지 않는다 (잠금이 바뀌었다)",
                    stage="check",
                    env=name,
                )
            folder = envs_mod.find_env(ops.layout.envs, name, fp)
            if folder is None:
                missing.append(name)
                continue
            # (가) 읽기 검증만
            problem = envs_mod.verify_env(folder, fp, env["digest"])
            if problem is not None:
                raise PluginError(
                    "verify_failed", f"{folder.name}: {problem}", stage="verify", env=name
                )
            ready.append(name)
        if not missing:
            return {"op_id": op_id, "lock_sha256": current, "created": [], "ready": ready}
        plans = []
        for name in missing:
            members = [p for p in lock["plugins"] if p["env"] == name]
            # 커밋된 wheel: 잠금 경로 그대로, 바이트 대조 (코드 실행 전)
            wheels = {str(m["id"]): ops._archived_wheel(m) for m in members}  # pyright: ignore[reportPrivateUsage]
            packages = [Package.from_json(p) for p in lock["environments"][name]["packages"]]
            plans.append(_EnvPlan(name, members, packages, wheels))
        if not trust.is_trusted(ops.root, current):
            asked = {
                "op_id": op_id,
                "lock_sha256": current,
                "environments": missing,
                "plugins": [
                    {
                        "id": p["id"],
                        "version": p["version"],
                        "source": p["source"],
                        "permissions": p["manifest"].get("permissions", []),
                        "env": p["env"],
                    }
                    for p in lock["plugins"]
                    if p["env"] in missing
                ],
            }
            if not confirm(asked):
                raise PluginError("cancelled", "신뢰 확인에서 취소했다", stage="confirm")
        ops._point("confirmed")  # pyright: ignore[reportPrivateUsage]
        index = ops.index()
        for plan in plans:
            env = lock["environments"][plan.name]
            folder = ops.layout.envs / envs_mod.folder_name(plan.name, env["fingerprint"], op_id)
            ops._create_env(  # pyright: ignore[reportPrivateUsage]
                runner,
                staging,
                folder,
                plan,
                env["fingerprint"],
                index,
                expect_digest=env["digest"],
            )
        trust.remember(ops.root, current)
        return {"op_id": op_id, "lock_sha256": current, "created": missing, "ready": ready}
