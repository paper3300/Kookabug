"""연결의 주체 (M2 계획 2.4 "주체"). 연결 하나에 주체 하나다.

- `client.kind: "ui"` → `Principal("user", "ui:<연결 번호>", attended=True)`. 판정하지 않는 사람
- `client.kind: "agent"` → `Principal("agent", client.id, attended=client.attended)`. `id`는 필수,
  `attended`는 생략하면 false (사람 없는 에이전트). `client.job_token`이 살아 있는 작업의 토큰이면
  `job`이 붙는다 (M8 R7)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kookabug_core.permissions import Principal

__all__ = ["principal_json", "principal_of"]


def principal_of(client: Mapping[str, Any], connection: int, job: str | None = None) -> Principal:
    """`session.hello`의 `client`(형식 검사를 지난 값) → 주체. `job`은 작업 토큰을 확인한 작업
    (M8 R7 — 자기 신고가 아니라 `jobs.JobRegistry.bind`가 정한 값)."""
    if client["kind"] == "agent":
        return Principal(
            "agent", str(client["id"]), attended=bool(client.get("attended", False)), job=job
        )
    return Principal("user", f"ui:{connection}", attended=True)


def principal_json(principal: Principal) -> dict[str, Any]:
    out: dict[str, Any] = {
        "kind": principal.kind,
        "id": principal.id,
        "attended": principal.attended,
    }
    if principal.job is not None:
        out["job"] = principal.job
    return out
