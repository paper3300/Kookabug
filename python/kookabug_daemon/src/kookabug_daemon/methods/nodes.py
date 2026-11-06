"""`nodes.list` (M2 계획 2.4·2.7): 팔레트 = 레지스트리의 노드 스키마 문서 그대로.

M6 B4: 설치 플러그인의 요약(`plugins`: ID·판·권한·환경 상태)을 함께 준다 — `kb_node_search`가
노드마다 그 플러그인의 권한·환경 상태를 보인다 (같은 도구로 판정되는 메서드만 부른다).
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

from kookabug_core import palette
from kookabug_core.plugins import PluginError
from kookabug_core.plugins.redact import mask_value
from kookabug_daemon.methods import Call, MethodSpec

__all__ = ["METHODS"]


def _installed(call: Call) -> list[dict[str, Any]]:
    try:
        status = call.daemon.plugin_jobs.reader().status()
    except PluginError:
        return []  # 잠금이 깨졌다: 요약 없이 (plugins.list가 오류를 보인다)
    out: list[dict[str, Any]] = []
    for plugin in status["plugins"]:
        manifest = plugin.get("manifest", {})
        item: dict[str, Any] = {
            "id": plugin["id"],
            "version": plugin["version"],
            "permissions": list(manifest.get("permissions", [])),
            "env": plugin["env"],
            "env_status": plugin["env_status"],
        }
        if manifest.get("title"):
            item["title"] = manifest["title"]
        out.append(item)
    return mask_value(out)


async def _list(call: Call) -> dict[str, Any]:
    plugins = await asyncio.to_thread(_installed, call)
    return {"schemas": palette.export(call.daemon.checker.registry), "plugins": plugins}


METHODS: Final = {"nodes.list": MethodSpec(_list)}
