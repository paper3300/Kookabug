"""팔레트 내보내기 (M2 계획 2.7): 레지스트리를 노드 스키마 문서 형식 그대로 낸다.

플러그인마다 문서 하나(`kookabug.nodes/0`, `kookabug-sdk build` 산출물과 같은 모양)이고, 노드는 타입
순이다. 분류(`category`)를 화면 분류·색으로 묶는 것은 에디터가 한다 (`palette/categories.ts`).
"""

from __future__ import annotations

import copy
from typing import Any

from kookabug_core.registry import Registry
from kookabug_sdk.schema import FORMAT

__all__ = ["export"]


def export(registry: Registry) -> list[dict[str, Any]]:
    """플러그인 ID 순 노드 스키마 문서 목록 (복사본)."""
    nodes: dict[str, list[dict[str, Any]]] = {plugin: [] for plugin in registry.plugins}
    for node_type in sorted(registry.types()):
        nodedef = registry.get(node_type)
        assert nodedef is not None
        nodes[nodedef.plugin].append(copy.deepcopy(dict(nodedef.decl)))
    return [
        {"format": FORMAT, "nodes": nodes[plugin], "plugin": registry.plugin_info(plugin)}
        for plugin in sorted(nodes)
    ]
