"""인증 정보 가림 (M6 계획 3.2·3.5a — 엄격: 비밀값). 다른 플러그인 모듈에 기대지 않는다.

가리는 것: URL의 사용자 정보(`scheme://user:token@` → `scheme://***@`)와 비밀 쿼리 값
(`?token=…` → `?token=***`). `PluginError`가 메시지·필드를 만들 때 늘 적용하고(오류가 밖으로 나가는
경계 하나), 작업 로그 쓰기에도 적용한다.

작업 로그 원문 정책: 로그(`.kookabug/plugins/logs`, 이 PC 전용·Git 제외)에는 명령·출력이 그대로
남는다 — 로컬 경로(staging·앱 SDK wheel의 file URI)도. 가리는 것은 인증 정보뿐이다. 잠금·응답에는
로컬 작업 경로를 넣지 않는다.
"""

from __future__ import annotations

import re
from typing import Any, Final

__all__ = ["SECRET_QUERY", "mask", "mask_value"]

_USERINFO: Final = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/@\s'\"]+@")
SECRET_QUERY: Final = re.compile(
    r"(?i)([?&](?:access_token|token|api_key|apikey|key|secret|password|passwd|pwd|auth|"
    r"signature|sig|credential|x-amz-signature|x-amz-credential|x-amz-security-token)=)"
    r"[^&#\s'\"]+"
)


def mask(text: str) -> str:
    """URL 사용자 정보와 비밀 쿼리 값을 가린다."""
    return SECRET_QUERY.sub(r"\1***", _USERINFO.sub(r"\1***@", text))


def mask_value(value: Any) -> Any:
    """JSON 모양 값 안의 모든 문자열을 `mask` (dict·list·tuple 재귀)."""
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, dict):
        return {k: mask_value(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, (list, tuple)):
        return [mask_value(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return value
