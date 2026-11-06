"""플러그인 작업 오류 (M6 계획 3.5). 응답·화면은 요약(`code`·`stage`·`message`), 원문은
작업 로그."""

from __future__ import annotations

from typing import Any, Final

__all__ = ["CODES", "PluginError"]

CODES: Final = frozenset(
    {
        "source_unavailable",
        "source_refused",
        "manifest_invalid",
        "plugin_id_taken",
        "plugin_not_found",
        "sdk_incompatible",
        "core_too_old",
        "sdist_only_dependency",
        "build_failed",
        "plugin_conflict",
        "resolve_failed",
        "env_create_failed",
        "verify_failed",
        "plugin_busy",
        "revision_conflict",
        "lock_invalid",
        "app_incomplete",
        "cancelled",
    }
)


class PluginError(Exception):
    """플러그인 작업이 실패했다. `stage`는 실패한 거래 단계 (모르면 None)."""

    def __init__(self, code: str, message: str, *, stage: str | None = None, **fields: Any) -> None:
        if code not in CODES:
            raise ValueError(f"모르는 플러그인 오류 {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.fields = fields

    def to_json(self) -> dict[str, Any]:
        return {"code": self.code, "stage": self.stage, "message": self.message, **self.fields}
