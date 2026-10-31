"""연결의 주체 (M2 계획 2.4 "주체"). 연결 하나에 주체 하나다.

- `client.kind: "ui"` → `Principal("user", "ui:<연결 번호>", attended=True)`. 판정하지 않는 사람
- `client.kind: "agent"` → `Principal("agent", client.id, attended=client.attended)`. `id`는 필수,
  `attended`는 생략하면 false (사람 없는 에이전트)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kookabug_core.permissions import Principal

__all__ = ["principal_json", "principal_of"]


def principal_of(client: Mapping[str, Any], connection: int) -> Principal:
    """`session.hello`의 `client`(형식 검사를 지난 값) → 주체."""
    if client["kind"] == "agent":
        return Principal("agent", str(client["id"]), attended=bool(client.get("attended", False)))
    return Principal("user", f"ui:{connection}", attended=True)


def principal_json(principal: Principal) -> dict[str, Any]:
    return {"kind": principal.kind, "id": principal.id, "attended": principal.attended}
