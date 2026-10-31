"""`nodes.list` (M2 계획 2.4·2.7): 팔레트 = 레지스트리의 노드 스키마 문서 그대로."""

from __future__ import annotations

from typing import Any, Final

from kookabug_core import palette
from kookabug_daemon.methods import Call, MethodSpec

__all__ = ["METHODS"]


async def _list(call: Call) -> dict[str, Any]:
    return {"schemas": palette.export(call.daemon.checker.registry)}


METHODS: Final = {"nodes.list": MethodSpec(_list)}
